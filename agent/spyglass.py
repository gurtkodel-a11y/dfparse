"""
Spyglass — tunable live map query tool for the DF agent.

Wraps DFHackClient block-fetching with:
  - A Python-side LRU block cache with configurable TTL and size
  - Prefetch padding (fetch a neighbourhood beyond the requested volume)
  - Lazy vs. explicit-region fetch modes
  - Structured per-call usage logging for agent self-evaluation

Quick start:
    async with DFHackClient() as client:
        glass = await Spyglass.create(client)
        walls = await glass.tiles_where(
            x1, y1, z, x2, y2, z,
            shapes={TiletypeShape.WALL},
        )

Settings are persisted to agent/spyglass_settings.json between sessions.
Every call appends a JSON line to agent/spyglass_log.jsonl for evaluation.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path

from dfhack.client import DFHackClient
from dfhack.proto_defs import TiletypeShape

_DIR = Path(__file__).parent
SETTINGS_PATH = _DIR / "spyglass_settings.json"
LOG_PATH      = _DIR / "spyglass_log.jsonl"


# ── Settings ──────────────────────────────────────────────────────────────────

@dataclass
class SpyglassSettings:
    """Tunable parameters. The agent may update these via Spyglass.update_settings().

    prefetch_padding:
        Extra blocks to fetch around each requested volume (block units; 1 block = 16 tiles).
        0 = fetch only what was asked for.
        Higher values warm the cache proactively at the cost of more wasted fetches.

    cache_max_blocks:
        LRU eviction threshold. When the cache exceeds this, the least-recently-used
        block is dropped. Tune down to reduce memory use; up to survive larger regions.

    cache_ttl:
        Seconds before a cached block is considered stale and re-fetched on next access.
        0 = blocks never expire within a session (manual invalidate() required after writes).

    lazy:
        True  — tile_at() fetches the block on demand if it is not cached.
        False — tile_at() raises OutOfRegion if the block is not already loaded.
                Use False to enforce the explicit-region pattern and make RPC costs visible.
    """
    prefetch_padding: int   = 1
    cache_max_blocks: int   = 500
    cache_ttl:        float = 120.0
    lazy:             bool  = True
    eval_every:       int   = 20
    # Run a self-evaluation every N Spyglass calls (0 = disabled).
    # The evaluator must be attached via Spyglass.attach_evaluator() for this to fire.

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> SpyglassSettings:
        if path.exists():
            try:
                return cls(**json.loads(path.read_text()))
            except Exception:
                pass
        return cls()


# ── Public data types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TileData:
    """Immutable snapshot of one map tile, ready for agent consumption."""
    x:      int
    y:      int
    z:      int
    shape:  TiletypeShape
    water:  int   # 0 = dry, 1–7 = depth
    magma:  int   # 0 = none, 1–7 = depth
    hidden: bool  # True = player has not explored this tile

    # Convenience predicates used by planning code

    @property
    def is_solid(self) -> bool:
        """True for tiles that can be designated for digging."""
        return self.shape in (TiletypeShape.WALL, TiletypeShape.FORTIFICATION)

    @property
    def is_open(self) -> bool:
        """True for revealed, walkable, non-fluid tiles."""
        return not self.hidden and not self.has_fluid and self.shape in (
            TiletypeShape.FLOOR,
            TiletypeShape.EMPTY,
            TiletypeShape.RAMP_TOP,
            TiletypeShape.STAIR_UP,
            TiletypeShape.STAIR_DOWN,
            TiletypeShape.STAIR_UPDOWN,
        )

    @property
    def has_fluid(self) -> bool:
        return self.water > 0 or self.magma > 0


class OutOfRegion(Exception):
    """Raised by tile_at() when lazy=False and the requested block is not cached."""


@dataclass
class SpyglassLogEntry:
    """One structured record of a Spyglass call.  Written to spyglass_log.jsonl.

    The agent self-evaluation procedure reads recent entries from that file and
    reasons about whether the current settings are serving it well.
    """
    timestamp:       float      # Unix time
    call:            str        # "fetch_region"|"tile_at"|"tiles_in_volume"|"tiles_where"
    volume:          list[int]  # [x1, y1, z1, x2, y2, z2]
    blocks_fetched:  int        # blocks pulled fresh from DFHack this call
    blocks_cached:   int        # blocks served entirely from the Python cache
    blocks_extra:    int        # extra blocks fetched beyond the minimum (padding overhead)
    tiles_returned:  int        # size of the final result set
    fetch_ms:        float      # wall-clock time of the call in milliseconds
    settings:        dict       # SpyglassSettings snapshot at call time

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)
        )
        return d


# ── Internal cache entry ──────────────────────────────────────────────────────

@dataclass
class _Block:
    tiles:         list[int]
    water:         list[int]
    magma:         list[int]
    hidden:        list[bool]
    fetched_at:    float        # time.monotonic()
    last_accessed: float


# ── Spyglass ──────────────────────────────────────────────────────────────────

class Spyglass:
    """Tunable live map query tool.  See module docstring for overview."""

    def __init__(self, client: DFHackClient, settings: SpyglassSettings | None = None):
        self._client        = client
        self.settings       = settings or SpyglassSettings.load()
        self._cache: OrderedDict[tuple[int, int, int], _Block] = OrderedDict()
        self._tiletype_map: dict[int, TiletypeShape] | None = None
        self._map_bx_max    = 0
        self._map_by_max    = 0
        self._map_z_max     = 0
        self._log: list[SpyglassLogEntry] = []
        self._evaluator = None   # set via attach_evaluator()

    @classmethod
    async def create(
        cls,
        client: DFHackClient,
        settings: SpyglassSettings | None = None,
    ) -> Spyglass:
        """Async factory.  Loads map metadata before returning."""
        glass = cls(client, settings)
        await glass._init_metadata()
        return glass

    @property
    def map_bounds(self) -> tuple[int, int, int]:
        """(max_block_x, max_block_y, max_z_level) as set during initialisation."""
        return self._map_bx_max, self._map_by_max, self._map_z_max

    async def _init_metadata(self) -> None:
        info = await self._client.get_map_info()
        self._map_bx_max = info.block_size_x - 1
        self._map_by_max = info.block_size_y - 1
        self._map_z_max  = info.block_size_z - 1

        tt_list = await self._client.get_tiletype_list()
        self._tiletype_map = {}
        for tt in tt_list:
            try:
                shape = TiletypeShape(tt.shape if tt.HasField("shape") else -1)
            except ValueError:
                shape = TiletypeShape.NO_SHAPE
            self._tiletype_map[tt.id] = shape

    # ── cache helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _key(bx: int, by: int, z: int) -> tuple[int, int, int]:
        return (bx, by, z)

    def _fresh(self, block: _Block) -> bool:
        if self.settings.cache_ttl <= 0:
            return True
        return (time.monotonic() - block.fetched_at) < self.settings.cache_ttl

    def _evict(self) -> None:
        while len(self._cache) > self.settings.cache_max_blocks:
            self._cache.popitem(last=False)   # drop oldest

    def _read_tile(self, x: int, y: int, z: int) -> TileData | None:
        key = self._key(x // 16, y // 16, z)
        block = self._cache.get(key)
        if block is None:
            return None
        i = (x % 16) + (y % 16) * 16
        if i >= len(block.tiles):
            return None
        block.last_accessed = time.monotonic()
        self._cache.move_to_end(key)
        return TileData(
            x=x, y=y, z=z,
            shape   = self._tiletype_map.get(block.tiles[i], TiletypeShape.NO_SHAPE),
            water   = block.water[i]  if i < len(block.water)  else 0,
            magma   = block.magma[i]  if i < len(block.magma)  else 0,
            hidden  = block.hidden[i] if i < len(block.hidden) else False,
        )

    # ── fetch logic ───────────────────────────────────────────────────────

    async def _fetch(
        self,
        bx_min: int, bx_max: int,
        by_min: int, by_max: int,
        z_min:  int, z_max:  int,
        *,
        reset_hashes: bool = True,
    ) -> tuple[int, int, int]:
        """Ensure the requested block range is in cache, applying prefetch padding.

        Returns (blocks_fetched, blocks_cached, blocks_extra) where:
          blocks_fetched  = blocks returned by the RPC call (0 if cache was fully warm)
          blocks_cached   = blocks in the REQUESTED range already fresh in cache
          blocks_extra    = blocks fetched beyond the requested range due to padding
        """
        pad = self.settings.prefetch_padding
        pbx_min = max(0, bx_min - pad)
        pbx_max = min(self._map_bx_max, bx_max + pad)
        pby_min = max(0, by_min - pad)
        pby_max = min(self._map_by_max, by_max + pad)
        pz_min  = max(0, z_min)
        pz_max  = min(self._map_z_max, z_max)

        # Count which blocks in the REQUESTED range are already fresh
        cached_count = sum(
            1
            for bx in range(bx_min, bx_max + 1)
            for by in range(by_min, by_max + 1)
            for z  in range(z_min,  z_max  + 1)
            if (b := self._cache.get(self._key(bx, by, z))) and self._fresh(b)
        )

        # Skip the RPC entirely if the full PADDED range is warm
        padded_total = (
            (pbx_max - pbx_min + 1) *
            (pby_max - pby_min + 1) *
            (pz_max  - pz_min  + 1)
        )
        padded_fresh = sum(
            1
            for bx in range(pbx_min, pbx_max + 1)
            for by in range(pby_min, pby_max + 1)
            for z  in range(pz_min,  pz_max  + 1)
            if (b := self._cache.get(self._key(bx, by, z))) and self._fresh(b)
        )
        if padded_fresh == padded_total:
            return 0, cached_count, 0

        # Fetch the full padded range
        now = time.monotonic()
        blocks = await self._client.get_block_list(
            pbx_min, pbx_max, pby_min, pby_max, pz_min, pz_max,
            reset_hashes=reset_hashes,
        )
        for b in blocks:
            key = self._key(b.map_x // 16, b.map_y // 16, b.map_z)
            self._cache[key] = _Block(
                tiles=list(b.tiles),
                water=list(b.water),
                magma=list(b.magma),
                hidden=list(b.hidden),
                fetched_at=now,
                last_accessed=now,
            )
            self._cache.move_to_end(key)
        self._evict()

        requested_total = (bx_max-bx_min+1) * (by_max-by_min+1) * (z_max-z_min+1)
        extra = max(0, len(blocks) - requested_total)
        return len(blocks), 0, extra   # fetched = fresh for all; old cached count irrelevant

    # ── logging ───────────────────────────────────────────────────────────

    def attach_evaluator(self, evaluator) -> None:
        """Attach a SpyglassEvaluator.  Evaluations fire automatically per eval_every."""
        self._evaluator = evaluator

    def _log_call(
        self,
        call: str,
        volume: tuple[int, ...],
        fetched: int,
        cached: int,
        extra: int,
        tiles_returned: int,
        fetch_ms: float,
    ) -> None:
        entry = SpyglassLogEntry(
            timestamp      = time.time(),
            call           = call,
            volume         = list(volume),
            blocks_fetched = fetched,
            blocks_cached  = cached,
            blocks_extra   = extra,
            tiles_returned = tiles_returned,
            fetch_ms       = round(fetch_ms, 2),
            settings       = asdict(self.settings),
        )
        self._log.append(entry)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    async def _maybe_evaluate(self) -> None:
        """Fire self-evaluation if the call threshold has been reached."""
        n = self.settings.eval_every
        if n <= 0 or self._evaluator is None:
            return
        if len(self._log) % n == 0:
            try:
                await self._evaluator.evaluate(self)
            except Exception as exc:
                print(f"[Spyglass] Evaluation skipped: {exc}")

    # ── public API ────────────────────────────────────────────────────────

    async def fetch_region(
        self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
    ) -> None:
        """Explicitly warm the cache for a tile volume.

        Call this before a series of tile_at() queries when lazy=False, or to
        pre-load a planning area at the start of a session.
        """
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)
        t0 = time.monotonic()
        fetched, cached, extra = await self._fetch(
            x1//16, x2//16, y1//16, y2//16, z1, z2
        )
        self._log_call("fetch_region", (x1,y1,z1,x2,y2,z2),
                       fetched, cached, extra, 0, (time.monotonic()-t0)*1000)
        await self._maybe_evaluate()

    async def prefetch_region(
        self,
        x1: int, y1: int, z1: int,
        x2: int, y2: int, z2: int,
        *,
        z_chunk: int = 5,
        priority_z: int | None = None,
    ) -> int:
        """Warm the cache for a large tile volume by chunking across z-levels.

        Splits the z range into slices of z_chunk to stay within DFHack's
        protobuf reply-size limit (~64 MB). Resets DFHack block hashes ONCE
        before the first chunk so all subsequent chunks share a single clean
        slate — resetting per-chunk would cause later chunks to clear the hash
        state established by earlier ones, which can cause blocks to be skipped.

        priority_z: if given, the chunk containing this z-level is fetched
        first. Use the current citizen median z so that the most important
        z-levels are captured while dwarves are still there, before other
        chunks give them time to walk away.

        Logs a single entry for the whole operation. Returns total blocks fetched.
        """
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)

        # Build ordered list of (zs, ze) chunk pairs, priority chunk first.
        chunks = [(zs, min(zs + z_chunk - 1, z2)) for zs in range(z1, z2 + 1, z_chunk)]
        if priority_z is not None:
            priority_z = max(z1, min(z2, priority_z))
            chunks.sort(key=lambda c: (0 if c[0] <= priority_z <= c[1] else 1, c[0]))

        t0 = time.monotonic()
        total_fetched = total_cached = total_extra = 0
        first_chunk = True
        for zs, ze in chunks:
            f, c, e = await self._fetch(
                x1 // 16, x2 // 16, y1 // 16, y2 // 16, zs, ze,
                reset_hashes=first_chunk,
            )
            first_chunk = False
            total_fetched += f
            total_cached  += c
            total_extra   += e
        elapsed = (time.monotonic() - t0) * 1000
        self._log_call(
            "prefetch_region", (x1, y1, z1, x2, y2, z2),
            total_fetched, total_cached, total_extra, 0, elapsed,
        )
        await self._maybe_evaluate()
        return total_fetched

    async def tile_at(self, x: int, y: int, z: int) -> TileData | None:
        """Single tile lookup.  Fetches the block on demand when lazy=True.

        Returns None if the block exists but contains no data at (x,y,z)
        (e.g. an unloaded z-level at the map extremes).
        Raises OutOfRegion if the block is not cached and lazy=False.
        """
        key = self._key(x // 16, y // 16, z)
        t0 = time.monotonic()
        fetched = cached = extra = 0

        block = self._cache.get(key)
        if block is None or not self._fresh(block):
            if not self.settings.lazy:
                raise OutOfRegion(
                    f"Block {key} not in cache and lazy=False. "
                    "Call fetch_region() first."
                )
            fetched, cached, extra = await self._fetch(
                x//16, x//16, y//16, y//16, z, z
            )
        else:
            cached = 1

        tile = self._read_tile(x, y, z)
        self._log_call("tile_at", (x,y,z,x,y,z),
                       fetched, cached, extra, 1 if tile else 0,
                       (time.monotonic()-t0)*1000)
        await self._maybe_evaluate()
        return tile

    async def tiles_in_volume(
        self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
    ) -> list[TileData]:
        """All tiles in [x1..x2, y1..y2, z1..z2], unfiltered."""
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)
        t0 = time.monotonic()
        fetched, cached, extra = await self._fetch(
            x1//16, x2//16, y1//16, y2//16, z1, z2
        )
        results = [
            tile
            for z in range(z1, z2 + 1)
            for y in range(y1, y2 + 1)
            for x in range(x1, x2 + 1)
            if (tile := self._read_tile(x, y, z)) is not None
        ]
        self._log_call("tiles_in_volume", (x1,y1,z1,x2,y2,z2),
                       fetched, cached, extra, len(results),
                       (time.monotonic()-t0)*1000)
        await self._maybe_evaluate()
        return results

    async def tiles_where(
        self,
        x1: int, y1: int, z1: int,
        x2: int, y2: int, z2: int,
        *,
        shapes:    set[TiletypeShape] | None = None,
        min_water: int  = 0,
        min_magma: int  = 0,
        hidden:    bool | None = None,
    ) -> list[TileData]:
        """Tiles in volume matching all supplied filters.

        shapes=None  → accept any tile shape.
        hidden=None  → accept both explored and unexplored tiles.
        min_water/min_magma → minimum fluid depth (1 = any fluid present).

        All filtering is Python-side after a single block fetch; no extra RPC calls.
        """
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)
        t0 = time.monotonic()
        fetched, cached, extra = await self._fetch(
            x1//16, x2//16, y1//16, y2//16, z1, z2
        )
        results = [
            tile
            for z in range(z1, z2 + 1)
            for y in range(y1, y2 + 1)
            for x in range(x1, x2 + 1)
            if (tile := self._read_tile(x, y, z)) is not None
            and (shapes    is None or tile.shape  in shapes)
            and tile.water >= min_water
            and tile.magma >= min_magma
            and (hidden    is None or tile.hidden == hidden)
        ]
        self._log_call("tiles_where", (x1,y1,z1,x2,y2,z2),
                       fetched, cached, extra, len(results),
                       (time.monotonic()-t0)*1000)
        await self._maybe_evaluate()
        return results

    def invalidate(
        self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
    ) -> int:
        """Drop cached blocks overlapping a tile volume.

        Call after send_dig_command() so the next query fetches fresh data
        rather than serving pre-dig tile states.  Returns number of blocks evicted.
        """
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)
        evicted = 0
        for bx in range(x1 // 16, x2 // 16 + 1):
            for by in range(y1 // 16, y2 // 16 + 1):
                for z in range(z1, z2 + 1):
                    if self._cache.pop(self._key(bx, by, z), None) is not None:
                        evicted += 1
        return evicted

    def update_settings(self, **kwargs) -> None:
        """Change one or more settings and persist to disk.

        The agent self-evaluation procedure calls this after deciding to retune.
        Example:
            glass.update_settings(prefetch_padding=2, cache_ttl=60.0)
        """
        for k, v in kwargs.items():
            if not hasattr(self.settings, k):
                raise ValueError(f"Unknown Spyglass setting: {k!r}")
            setattr(self.settings, k, v)
        self.settings.save()

    def export_blocks(
        self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
    ) -> list[dict]:
        """Return cached block data for the given tile volume as serialisable dicts.

        Keys per block: bx, by, z, shapes, water, magma, hidden.
        Tile IDs are resolved to TiletypeShape int values so the file is
        self-contained (no tiletype list needed to interpret it later).
        Only blocks already in the cache are included; call fetch_region() first.
        """
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        z1, z2 = min(z1, z2), max(z1, z2)
        result = []
        for bx in range(x1 // 16, x2 // 16 + 1):
            for by in range(y1 // 16, y2 // 16 + 1):
                for z in range(z1, z2 + 1):
                    block = self._cache.get(self._key(bx, by, z))
                    if block is not None:
                        shapes = [
                            self._tiletype_map.get(tid, TiletypeShape.NO_SHAPE).value
                            for tid in block.tiles
                        ]
                        result.append({
                            "bx":     bx,
                            "by":     by,
                            "z":      z,
                            "shapes": shapes,
                            "water":  block.water,
                            "magma":  block.magma,
                            "hidden": block.hidden,
                        })
        return result

    def recent_log(self, n: int = 10) -> list[SpyglassLogEntry]:
        """Last n log entries from this session (most recent last)."""
        return self._log[-n:]

    def cache_stats(self) -> dict:
        """Snapshot of current cache state, useful for agent introspection."""
        now = time.monotonic()
        fresh = sum(1 for b in self._cache.values() if self._fresh(b))
        return {
            "cached_blocks":      len(self._cache),
            "fresh_blocks":       fresh,
            "stale_blocks":       len(self._cache) - fresh,
            "max_blocks":         self.settings.cache_max_blocks,
            "session_log_entries": len(self._log),
        }
