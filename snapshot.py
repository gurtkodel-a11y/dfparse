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

from agent.spyglass import Spyglass
from dfhack import DFHackClient
from gamestate.buildings import Building
from gamestate.units import Unit, UnitKind
from gamestate.world import WorldInfo

DF_SAVE_ROOT  = Path(r"C:\Users\kkado\AppData\Roaming\Bay 12 Games\Dwarf Fortress\save")
SNAPSHOT_PATH = Path(__file__).parent / "snapshot.json"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
REGION_PATH   = Path(__file__).parent / "snapshot_region.json"
TILES_PATH    = Path(__file__).parent / "snapshot_tiles.json"
POLL_SECONDS  = 5

_TILE_PADDING_XY = 32   # tiles of margin around citizen bounding box (2 blocks)
_TILE_PADDING_Z  = 10   # z-levels above/below citizen z-range


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
# Region helpers
# ---------------------------------------------------------------------------

def _citizen_bbox(units: list, world: WorldInfo) -> tuple | None:
    """Tile bounding box of all living, on-map citizens. Returns None if none found."""
    citizens = [
        u for u in units
        if u.kind(world.civ_id, world.race_id) == UnitKind.CITIZEN
        and u.pos.x >= 0 and u.pos.y >= 0
    ]
    if not citizens:
        return None
    xs = [u.pos.x for u in citizens]
    ys = [u.pos.y for u in citizens]
    zs = [u.pos.z for u in citizens]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _load_region() -> dict | None:
    if REGION_PATH.exists():
        try:
            return json.loads(REGION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_region(region: dict) -> None:
    REGION_PATH.write_text(json.dumps(region, indent=2), encoding="utf-8")


def _union_regions(a: dict, b: dict) -> dict:
    """Return the smallest region enclosing both a and b (regions only grow)."""
    return {
        "x1": min(a["x1"], b["x1"]),
        "y1": min(a["y1"], b["y1"]),
        "z1": min(a["z1"], b["z1"]),
        "x2": max(a["x2"], b["x2"]),
        "y2": max(a["y2"], b["y2"]),
        "z2": max(a["z2"], b["z2"]),
    }


def _compute_region(units: list, world: WorldInfo, glass: Spyglass) -> dict | None:
    """Citizen bbox + padding, unioned with the previous persisted region."""
    bbox = _citizen_bbox(units, world)
    if bbox is None:
        return _load_region()

    x1, y1, z1, x2, y2, z2 = bbox
    region = {
        "x1": max(0, x1 - _TILE_PADDING_XY),
        "y1": max(0, y1 - _TILE_PADDING_XY),
        "z1": max(0, z1 - _TILE_PADDING_Z),
        "x2": x2 + _TILE_PADDING_XY,
        "y2": y2 + _TILE_PADDING_XY,
        "z2": z2 + _TILE_PADDING_Z,
    }
    prev = _load_region()
    return _union_regions(region, prev) if prev else region


def _full_region(glass: Spyglass) -> dict:
    bx_max, by_max, z_max = glass.map_bounds
    return {
        "x1": 0, "y1": 0, "z1": 0,
        "x2": (bx_max + 1) * 16 - 1,
        "y2": (by_max + 1) * 16 - 1,
        "z2": z_max,
    }


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
    full_map: bool = False,
    z_min_override: int | None = None,
    z_max_override: int | None = None,
) -> None:
    """Connect to DFHack, collect game state, write snapshot.json + snapshot_tiles.json.

    trigger_save  — issue a quicksave before reading (default for one-shot use).
                    The connection is closed while the save writes, then reopened
                    so DF isn't busy when we issue the read RPCs.
    archive       — archive to snapshots/{region}/y{year}-{season}.json if the
                    season isn't already captured (used by watch mode).
    keep          — archive as a manual snapshot regardless of season coverage
                    (used by one-shot --keep).
    full_map      — fetch the entire map instead of the citizen-bounding-box region.
                    May be slow for large maps; uses one RPC call covering all z-levels.
    z_min_override / z_max_override — clamp the captured z range to at least these values,
                    overriding the citizen-bbox heuristic. Useful when dwarves are traveling
                    and happen not to be at their work levels when tiles are fetched.
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

        # Initialise Spyglass (map metadata) before reading units so the only
        # delay between unit positions and tile fetch is the chunk RPCs themselves.
        glass = await Spyglass.create(client)

        # Unit positions — read immediately before tile fetch so dwarves are
        # still where they were when we calculate the region and start fetching.
        raw_units = await client.list_units(skills=True, labors=True)
        units = [Unit.from_proto(u) for u in raw_units]

        # Map tiles — fetch immediately after unit read, citizen z-levels first.
        region = _full_region(glass) if full_map else _compute_region(units, world, glass)
        if region is not None and (z_min_override is not None or z_max_override is not None):
            if z_min_override is not None:
                region["z1"] = min(region["z1"], z_min_override)
            if z_max_override is not None:
                region["z2"] = max(region["z2"], z_max_override)

        tile_block_count = 0
        if region is not None:
            ts2 = datetime.datetime.now().strftime("%H:%M:%S")
            span = (
                f"x[{region['x1']}..{region['x2']}] "
                f"y[{region['y1']}..{region['y2']}] "
                f"z[{region['z1']}..{region['z2']}]"
            )
            print(f"[{ts2}] Fetching tiles ({span})...")
            # Pass the citizen median z so prefetch_region starts chunks there.
            cit_zs = [u.pos.z for u in units
                      if u.kind(world.civ_id, world.race_id) == UnitKind.CITIZEN
                      and u.pos.x >= 0]
            # Prioritise the LOWEST citizen z: underground blocks are only
            # loaded while dwarves are present and unload quickly when they leave.
            # Fetching that chunk first minimises the gap from unit-read to query.
            priority_z = min(cit_zs) if cit_zs else None
            # Expand the Spyglass LRU cache for the bulk prefetch so that
            # underground blocks fetched in early chunks aren't evicted by
            # later surface chunks before export_blocks can read them.
            # The default (500) is sized for incremental queries; a full
            # region fetch can exceed 2000 blocks.
            _orig_cache_max = glass.settings.cache_max_blocks
            glass.settings.cache_max_blocks = 10_000
            await glass.prefetch_region(
                region["x1"], region["y1"], region["z1"],
                region["x2"], region["y2"], region["z2"],
                priority_z=priority_z,
            )
            glass.settings.cache_max_blocks = _orig_cache_max
            _save_region(region)
            blocks = glass.export_blocks(
                region["x1"], region["y1"], region["z1"],
                region["x2"], region["y2"], region["z2"],
            )
            TILES_PATH.write_text(
                json.dumps({"region": region, "blocks": blocks}, ensure_ascii=False),
                encoding="utf-8",
            )
            tile_block_count = len(blocks)
        else:
            ts2 = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{ts2}] No citizens found and no prior region; skipping tile fetch")

        # Read remaining snapshot data after tiles are safely captured.
        year, season, tick = await client.get_game_date()
        raw_wds = await client.get_work_details()
        raw_needs = await client.get_unmet_needs()
        creature_raws = await client.get_creature_raws()
        raw_buildings = await client.get_buildings()

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
        "map_region": region,
        "buildings": [Building.from_raw(r).to_dict() for r in raw_buildings],
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
    tile_note = f" — {tile_block_count} tile blocks" if tile_block_count else ""
    bldg_note = f" — {len(raw_buildings)} buildings" if raw_buildings else ""
    print(f"[{ts}] {prefix}snapshot — y{year} {season} — {len(units)} units{tile_note}{bldg_note}{archive_note}")


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
    parser.add_argument("--full", action="store_true",
                        help="Fetch the entire map instead of the fort region only")
    parser.add_argument("--z-min", type=int, default=None, metavar="Z",
                        help="Ensure tile capture extends at least down to this z-level")
    parser.add_argument("--z-max", type=int, default=None, metavar="Z",
                        help="Ensure tile capture extends at least up to this z-level")
    args = parser.parse_args()

    if args.watch:
        asyncio.run(watch())
    else:
        asyncio.run(dump(
            trigger_save=not args.no_save,
            keep=args.keep,
            full_map=args.full,
            z_min_override=args.z_min,
            z_max_override=args.z_max,
        ))


if __name__ == "__main__":
    main()
