"""
Dump the current DFHack game state to snapshot.json.

Usage:
    python snapshot.py              # quicksave, then dump current state
    python snapshot.py --keep       # same, plus archive to snapshots/ history
    python snapshot.py --no-save    # dump without triggering a quicksave
    python snapshot.py --watch      # poll save directory; archive each new season
"""

import argparse
import asyncio
import datetime
import json
from pathlib import Path

from dfhack import DFHackClient
from gamestate.units import Unit
from gamestate.world import WorldInfo

DF_SAVE_ROOT = Path(r"C:\Users\kkado\AppData\Roaming\Bay 12 Games\Dwarf Fortress\save")
SNAPSHOT_PATH = Path(__file__).parent / "snapshot.json"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
POLL_SECONDS = 5


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_SEASON_NUM = {"spring": 1, "summer": 2, "autumn": 3, "winter": 4}


def _seasonal_path(save_dir: str, year: int, season: str) -> Path:
    n = _SEASON_NUM[season]
    return SNAPSHOTS_DIR / save_dir / f"y{year}-{n}-{season}.json"


def _manual_path(save_dir: str, year: int, season: str) -> Path:
    n = _SEASON_NUM[season]
    ts = datetime.datetime.now().strftime("%H%M%S")
    return SNAPSHOTS_DIR / save_dir / f"y{year}-{n}-{season}-manual-T{ts}.json"


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _unit_to_dict(u: Unit) -> dict:
    return {
        "unit_id": u.unit_id,
        "name": {
            "first": u.name.first,
            "last": u.name.last,
            "nickname": u.name.nickname,
            "english": u.name.english,
        },
        "race": u.race,
        "caste": u.caste,
        "gender": u.gender,
        "civ_id": u.civ_id,
        "histfig_id": u.histfig_id,
        "flags1": u.flags1,
        "flags2": u.flags2,
        "flags3": u.flags3,
        "pos": {"x": u.pos.x, "y": u.pos.y, "z": u.pos.z},
        "profession": u.profession,
        "custom_profession": u.custom_profession,
        "squad_id": u.squad_id,
        "squad_position": u.squad_position,
        "death_id": u.death_id,
        "labors": u.labors,
        "skills": u.skills,
    }


# ---------------------------------------------------------------------------
# Core dump
# ---------------------------------------------------------------------------

async def _wait_for_save(baseline: float, timeout: float = 30.0) -> None:
    """Poll until the save directory mtime advances past baseline, or timeout."""
    for _ in range(int(timeout)):
        await asyncio.sleep(1)
        if _latest_save_mtime() > baseline:
            return
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] Warning: save did not appear within {timeout}s, reading anyway")


async def dump(
    trigger_save: bool = True,
    archive: bool = False,
    keep: bool = False,
) -> None:
    """Connect to DFHack, collect game state, write snapshot.json.

    trigger_save  — issue a quicksave before reading (default for one-shot use).
                    The connection is closed while the save writes, then reopened
                    so DF isn't busy when we issue the read RPCs.
    archive       — archive to snapshots/{region}/y{year}-{season}.json if the
                    season isn't already captured (used by watch mode).
    keep          — archive as a manual snapshot regardless of season coverage
                    (used by one-shot --keep).
    """
    if trigger_save:
        baseline = _latest_save_mtime()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] Triggering quicksave...")
        async with DFHackClient() as client:
            await client.run_command("quicksave")
        # Connection closed; DF can write without serving RPCs.
        await _wait_for_save(baseline)
        # Give DF a moment to finish post-save cleanup before reconnecting.
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] Save detected, waiting for DF to finish cleanup...")
        await asyncio.sleep(3)

    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] Reading game state...")
    async with DFHackClient() as client:
        world = WorldInfo.from_proto(await client.get_world_info())
        year, season, tick = await client.get_game_date()
        raw_units = await client.list_units(skills=True, labors=True)
        raw_wds = await client.get_work_details()
        raw_needs = await client.get_unmet_needs()
        creature_raws = await client.get_creature_raws()

    units = [Unit.from_proto(u) for u in raw_units]
    snapshot = {
        "snapshot_time": datetime.datetime.now().isoformat(),
        "game_date": {"year": year, "season": season, "tick": tick},
        "world": {
            "mode": world.mode,
            "world_name": world.world_name,
            "save_dir": world.save_dir,
            "civ_id": world.civ_id,
            "site_id": world.site_id,
            "group_id": world.group_id,
            "race_id": world.race_id,
        },
        "units": [_unit_to_dict(u) for u in units],
        "work_details": raw_wds,
        "unmet_needs": [[n, c, t] for n, c, t in raw_needs],
        "creature_raws": {str(k): v for k, v in creature_raws.items()},
    }
    text = json.dumps(snapshot, indent=2, ensure_ascii=False)

    # Always update the current snapshot
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")

    # Archiving
    archive_note = ""
    if archive:
        dest = _seasonal_path(world.save_dir, year, season)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_text(text, encoding="utf-8")
            archive_note = f" → {dest.relative_to(Path(__file__).parent)}"
        else:
            archive_note = f" (y{year}-{season} already archived)"
    elif keep:
        dest = _manual_path(world.save_dir, year, season)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        archive_note = f" → {dest.relative_to(Path(__file__).parent)}"

    ts = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = "saved + " if trigger_save else ""
    print(f"[{ts}] {prefix}snapshot — y{year} {season} — {len(units)} units{archive_note}")


# ---------------------------------------------------------------------------
# File-change watcher
# ---------------------------------------------------------------------------

def _latest_save_mtime() -> float:
    """Return the most recent mtime of any file inside any region save folder."""
    best = 0.0
    try:
        for region_dir in DF_SAVE_ROOT.iterdir():
            if not region_dir.is_dir():
                continue
            for f in region_dir.rglob("*"):
                if f.is_file():
                    m = f.stat().st_mtime
                    if m > best:
                        best = m
    except PermissionError:
        pass
    return best


async def watch() -> None:
    print(f"Watching {DF_SAVE_ROOT} every {POLL_SECONDS}s (Ctrl+C to stop)...")
    last = _latest_save_mtime()
    while True:
        await asyncio.sleep(POLL_SECONDS)
        current = _latest_save_mtime()
        if current > last:
            last = current
            await asyncio.sleep(1)  # let DF finish writing before connecting
            try:
                await dump(trigger_save=False, archive=True)
            except Exception as e:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] Dump failed: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--watch", action="store_true",
                        help="Watch the save directory; archive each new season automatically")
    parser.add_argument("--keep", action="store_true",
                        help="Also archive this snapshot to snapshots/ history")
    parser.add_argument("--no-save", action="store_true",
                        help="Skip the quicksave trigger")
    args = parser.parse_args()

    if args.watch:
        asyncio.run(watch())
    else:
        asyncio.run(dump(trigger_save=not args.no_save, keep=args.keep))


if __name__ == "__main__":
    main()
