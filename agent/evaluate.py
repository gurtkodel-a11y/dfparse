"""
Spyglass self-evaluation system.

SpyglassEvaluator reads recent usage log entries, asks a Claude model to reason
about whether the current settings are appropriate, and optionally applies the
recommended changes.  The full reasoning text is saved to spyglass_evals.jsonl
so the human operator can review the agent's inner monologue and tune the rubric.

Dependency: the `anthropic` Python SDK must be installed.
  Install via your site-packages workaround, then this module becomes active.

Standalone use:
    python -m agent.evaluate              # evaluate now against recent log
    python -m agent.evaluate --dry-run    # print recommendation without applying
    python -m agent.evaluate --last 5     # show last 5 saved evaluations
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spyglass import Spyglass

_DIR       = Path(__file__).parent
LOG_PATH   = _DIR / "spyglass_log.jsonl"
EVALS_PATH = _DIR / "spyglass_evals.jsonl"

# ── Evaluation rubric ─────────────────────────────────────────────────────────
#
# This is the guided procedure the model follows.  It is deliberately structured
# so that reasoning steps appear BEFORE the recommendation, making the inner
# monologue visible and the final answer parseable.
#
# The human operator reads EVALS_PATH to assess quality and can edit this prompt
# to improve the evaluation procedure over time.

_RUBRIC = """\
You are reviewing your own recent usage of the Spyglass map query tool to decide \
whether the current settings are well-tuned for the work you have been doing.

## Current settings
{settings}

## Recent usage log ({n} entries, most recent last)
Each entry is one Spyglass call.  Key fields:
  call            – which method was called
  blocks_fetched  – blocks pulled fresh from DFHack this call (RPC cost)
  blocks_cached   – blocks served from the Python cache (free)
  blocks_extra    – extra blocks fetched beyond the minimum due to prefetch_padding
  tiles_returned  – tiles in the final result (after any filters)
  fetch_ms        – wall-clock time of the call

{log_entries}

## Diagnostic questions — work through each before recommending

### 1. Cache hit rate
Compute (blocks_cached) / (blocks_cached + blocks_fetched) across all entries.
A rate below 0.4 means the cache is cold for your access pattern.
  → If hit rate is low AND blocks_extra is also low: prefetch_padding may be too small,
    or fetch_region() should be called more proactively before query bursts.
  → If hit rate is low AND blocks_extra is large: cache is being warmed but blocks are
    expiring — consider increasing cache_ttl.

### 2. Padding overhead
Compute blocks_extra / max(1, blocks_fetched) per fetch call.
Overhead above 1.0 means more than half the fetched blocks came from padding.
  → High overhead with high hit rate: padding is working but over-aggressively;
    consider reducing prefetch_padding by 1.
  → High overhead with low hit rate: padding is wasteful and still not warming
    the right blocks — consider a targeted fetch_region() instead of padding.

### 3. Query granularity
Count how many calls used tile_at() vs tiles_in_volume/tiles_where.
Many tile_at() calls with low cache hit rate indicates repeated single-block fetches
that would be cheaper as one tiles_in_volume() call with fetch_region() beforehand.
  → Consider setting lazy=False to surface these hidden costs.

### 4. Query precision
For tiles_in_volume and tiles_where calls, estimate what fraction of the fetched
block space (volume_tiles = (x2-x1+1)*(y2-y1+1)*(z2-z1+1)) was actually returned
as results (tiles_returned).  Low precision (<0.1) means large volumes are being
queried but most tiles are filtered out — consider narrowing the requested volume
or pre-filtering with a smaller fetch_region() call.

### 5. Fetch latency
If fetch_ms is consistently high (>500 ms per call with blocks_fetched > 0), the
RPC round-trips are expensive.  Increasing cache_ttl or prefetch_padding reduces
call frequency at the cost of potentially stale data.

## Your recommendation

After working through the above, write:

DIAGNOSIS: (2–4 sentences describing the dominant patterns you observed)

RECOMMENDATION: (one sentence describing what to change and why, or "no change needed")

SETTINGS_UPDATE: {"key": value, ...}
(Use valid JSON with only keys from: prefetch_padding, cache_max_blocks, cache_ttl, \
lazy, eval_every.  Write the literal string  none  if no change is needed.)
"""

# ── Evaluation record ─────────────────────────────────────────────────────────

@dataclass
class EvalRecord:
    timestamp:        float
    timestamp_iso:    str
    log_entries:      list[dict]   # entries shown to the model
    settings_before:  dict
    settings_after:   dict | None  # None if no change or dry_run
    raw_response:     str          # full model output (the inner monologue)
    diagnosis:        str
    recommendation:   str
    applied:          bool
    model:            str

    def to_dict(self) -> dict:
        return asdict(self)


# ── Evaluator ─────────────────────────────────────────────────────────────────

class SpyglassEvaluator:
    """Runs periodic self-evaluations of Spyglass usage and optionally retunes settings.

    Attach to a Spyglass instance with glass.attach_evaluator(evaluator).
    Evaluations then fire automatically whenever len(glass._log) % eval_every == 0.

    Args:
        model:       Claude model ID to use for evaluation.
        log_entries: Number of recent log entries to include in each evaluation.
        apply:       If True, automatically apply recommended settings changes.
        log_path:    Path to spyglass_log.jsonl (default: agent/spyglass_log.jsonl).
        evals_path:  Path to evaluation output file.
    """

    def __init__(
        self,
        model:       str  = "claude-haiku-4-5-20251001",
        log_entries: int  = 15,
        apply:       bool = True,
        log_path:    Path = LOG_PATH,
        evals_path:  Path = EVALS_PATH,
    ):
        self.model       = model
        self.log_entries = log_entries
        self.apply       = apply
        self.log_path    = log_path
        self.evals_path  = evals_path
        self._client     = None  # lazy-init anthropic client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
            self._client = anthropic.Anthropic()
            return self._client
        except ImportError:
            raise RuntimeError(
                "The 'anthropic' package is required for Spyglass self-evaluation. "
                "Install it via your site-packages workaround and restart."
            )

    def load_recent_log(self, n: int | None = None) -> list[dict]:
        """Read the last n entries from spyglass_log.jsonl."""
        n = n or self.log_entries
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text().strip().splitlines()
        recent = lines[-n:] if len(lines) > n else lines
        entries = []
        for line in recent:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries

    def _format_log(self, entries: list[dict]) -> str:
        """Compact, readable log display for the prompt."""
        rows = []
        for i, e in enumerate(entries, 1):
            rows.append(
                f"{i:>2}. [{e.get('timestamp_iso','?')}] {e['call']:<18} "
                f"fetched={e['blocks_fetched']:>3}  cached={e['blocks_cached']:>3}  "
                f"extra={e['blocks_extra']:>3}  tiles={e['tiles_returned']:>5}  "
                f"{e['fetch_ms']:>7.1f}ms"
            )
        return "\n".join(rows)

    def _parse_response(self, text: str) -> tuple[str, str, dict | None]:
        """Extract DIAGNOSIS, RECOMMENDATION, and SETTINGS_UPDATE from model output."""
        diagnosis      = ""
        recommendation = ""
        settings_delta = None

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("DIAGNOSIS:"):
                diagnosis = stripped[len("DIAGNOSIS:"):].strip()
            elif stripped.startswith("RECOMMENDATION:"):
                recommendation = stripped[len("RECOMMENDATION:"):].strip()
            elif stripped.startswith("SETTINGS_UPDATE:"):
                raw = stripped[len("SETTINGS_UPDATE:"):].strip()
                if raw.lower() == "none":
                    settings_delta = None
                else:
                    try:
                        settings_delta = json.loads(raw)
                    except json.JSONDecodeError:
                        pass

        return diagnosis, recommendation, settings_delta

    async def evaluate(self, glass: "Spyglass", dry_run: bool = False) -> EvalRecord:
        """Run one self-evaluation against recent log entries.

        Saves the full reasoning to spyglass_evals.jsonl.
        If apply=True (and dry_run=False), applies any recommended settings changes.
        Returns the EvalRecord for inspection.
        """
        from dataclasses import asdict as _asdict

        entries = self.load_recent_log()
        if not entries:
            raise ValueError("No log entries found — run some Spyglass queries first.")

        settings_before = _asdict(glass.settings)

        prompt = _RUBRIC.format(
            settings    = json.dumps(settings_before, indent=2),
            n           = len(entries),
            log_entries = self._format_log(entries),
        )

        client = self._get_client()

        # Prompt caching: the rubric is static and benefits from caching on long sessions
        response = client.messages.create(
            model      = self.model,
            max_tokens = 1024,
            messages   = [{"role": "user", "content": prompt}],
            system     = (
                "You are reasoning about your own tool usage to improve your performance. "
                "Be specific, analytical, and concise. Follow the rubric exactly."
            ),
        )
        raw = response.content[0].text

        diagnosis, recommendation, settings_delta = self._parse_response(raw)

        # Apply changes
        settings_after = None
        applied = False
        if settings_delta and self.apply and not dry_run:
            try:
                glass.update_settings(**settings_delta)
                settings_after = _asdict(glass.settings)
                applied = True
            except (ValueError, TypeError) as exc:
                recommendation += f" [settings update failed: {exc}]"

        now = time.time()
        record = EvalRecord(
            timestamp       = now,
            timestamp_iso   = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            log_entries     = entries,
            settings_before = settings_before,
            settings_after  = settings_after,
            raw_response    = raw,
            diagnosis       = diagnosis,
            recommendation  = recommendation,
            applied         = applied,
            model           = self.model,
        )

        with self.evals_path.open("a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

        # Print a brief summary so the operator can see evaluations as they fire
        print(
            f"\n[Spyglass eval @ {record.timestamp_iso}]\n"
            f"  Diagnosis:      {diagnosis}\n"
            f"  Recommendation: {recommendation}\n"
            f"  Applied:        {applied}"
            + (f" → {settings_delta}" if applied else "")
        )

        return record


# ── CLI ───────────────────────────────────────────────────────────────────────

def _show_recent_evals(n: int) -> None:
    if not EVALS_PATH.exists():
        print("No evaluations recorded yet.")
        return
    lines = EVALS_PATH.read_text().strip().splitlines()
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(f"\n{'='*70}")
        print(f"  {rec['timestamp_iso']}  model={rec['model']}")
        print(f"  Settings before: {rec['settings_before']}")
        print(f"  Settings after:  {rec.get('settings_after')}")
        print(f"\n--- Inner monologue ---\n{rec['raw_response']}")


async def _run_cli(dry_run: bool) -> None:
    """Manual evaluation against the current log without a live Spyglass instance."""
    from .spyglass import Spyglass, SpyglassSettings

    evaluator = SpyglassEvaluator(apply=not dry_run)
    entries   = evaluator.load_recent_log()
    if not entries:
        print("No log entries in spyglass_log.jsonl — run some queries first.")
        return

    # Build a minimal stub with current persisted settings (no DFHack connection needed)
    settings     = SpyglassSettings.load()
    settings_str = json.dumps(asdict(settings) if False else {
        k: getattr(settings, k)
        for k in ("prefetch_padding", "cache_max_blocks", "cache_ttl", "lazy", "eval_every")
    }, indent=2)

    prompt = _RUBRIC.format(
        settings    = settings_str,
        n           = len(entries),
        log_entries = evaluator._format_log(entries),
    )

    client = evaluator._get_client()
    response = client.messages.create(
        model      = evaluator.model,
        max_tokens = 1024,
        messages   = [{"role": "user", "content": prompt}],
        system     = (
            "You are reasoning about your own tool usage to improve your performance. "
            "Be specific, analytical, and concise. Follow the rubric exactly."
        ),
    )
    raw = response.content[0].text
    print("\n--- Spyglass self-evaluation (inner monologue) ---\n")
    print(raw)

    _, _, delta = evaluator._parse_response(raw)
    if delta and not dry_run:
        print(f"\nApplying: {delta}")
        for k, v in delta.items():
            setattr(settings, k, v)
        settings.save()
        print("Settings saved.")
    elif delta:
        print(f"\n(dry-run) Would apply: {delta}")
    else:
        print("\nNo settings change recommended.")


if __name__ == "__main__":
    import argparse, asyncio
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description="Spyglass self-evaluation CLI")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print recommendation without applying settings changes")
    parser.add_argument("--last", type=int, default=0, metavar="N",
                        help="Show last N saved evaluations instead of running a new one")
    args = parser.parse_args()

    if args.last:
        _show_recent_evals(args.last)
    else:
        asyncio.run(_run_cli(args.dry_run))
