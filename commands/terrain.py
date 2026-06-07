"""
Higher-level terrain modification commands.

These differ from dig.py in that they must first query the live map to determine
what designations are needed — the correct dig orders depend on the actual terrain
shape, not just a geometric specification.

All functions require a Spyglass instance for tile queries and a DFHackClient for
issuing dig commands.  DF must not be paused.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation, TiletypeShape

if TYPE_CHECKING:
    from agent.spyglass import Spyglass, TileData

# Tile shapes that are open air — not the terrain surface
_AIR = frozenset({
    TiletypeShape.EMPTY,
    TiletypeShape.RAMP_TOP,
    TiletypeShape.NO_SHAPE,
    TiletypeShape.BRANCH,
    TiletypeShape.TRUNK_BRANCH,
    TiletypeShape.TWIG,
})

# Tree trunks and plants that block surface access — flag separately so the
# caller can decide whether to clear them first
_VEGETATION = frozenset({
    TiletypeShape.TREE_SHAPE,
    TiletypeShape.SAPLING,
    TiletypeShape.SHRUB,
})


def _find_surface(
    by_xyz: dict[tuple[int, int, int], "TileData"],
    x: int, y: int,
    z_min: int, z_max: int,
) -> "TileData | None":
    """Return the topmost non-air tile at (x, y) within [z_min..z_max].

    Scans downward from z_max.  Returns None if the column is entirely air/unloaded.
    """
    for z in range(z_max, z_min - 1, -1):
        tile = by_xyz.get((x, y, z))
        if tile is not None and tile.shape not in _AIR:
            return tile
    return None


async def dig_shear_hillside(
    client: DFHackClient,
    x1: int, y1: int, x2: int, y2: int,
    z_min: int, z_max: int,
    *,
    glass: "Spyglass",
    dry_run: bool = False,
) -> dict:
    """Channel the topmost surface tile at every (x, y) position in the area.

    Scans each column in [x1..x2, y1..y2] downward from z_max to find the
    first non-air tile, then issues a CHANNEL designation on it.  Since
    channeling lowers a floor by one z-level (creating a ramp below and open
    space above), applying this across an irregular hillside drops the whole
    surface by one level, regardless of how uneven the current terrain is.

    Args:
        client:   Live DFHackClient.  DF must not be paused.
        x1..y2:   Tile-coordinate bounding rectangle of the hillside to shear.
        z_min:    Lowest z-level to search for the surface.
        z_max:    Highest z-level to search for the surface.  Set this above
                  the highest visible terrain in the area.
        glass:    Spyglass instance used for tile queries.
        dry_run:  If True, compute the plan but do NOT send any dig commands.
                  Useful for previewing before committing.

    Returns a summary dict:
        designated      int   tiles issued CHANNEL orders (0 if dry_run)
        skipped_hidden  int   columns where the surface tile was unexplored
        skipped_fluid   int   columns where the surface had water or magma
        skipped_veg     int   columns where the surface was a tree/shrub
        skipped_empty   int   columns with no surface found in [z_min..z_max]
        by_z            dict  {z: tile_count} — where the orders were placed
        plan            list  [(x, y, z), ...] — full coordinate list (always set,
                              even in dry_run, so callers can inspect or display)

    Typical call:
        result = await dig_shear_hillside(
            client, 100, 140, 160, 180, z_min=163, z_max=175, glass=glass
        )
        print(f"Channelled {result['designated']} tiles across z={result['by_z']}")
    """
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    z_min, z_max = min(z_min, z_max), max(z_min, z_max)

    # Pull all tiles in the search volume via Spyglass (cached)
    all_tiles = await glass.tiles_in_volume(x1, y1, z_min, x2, y2, z_max)
    by_xyz: dict[tuple[int, int, int], "TileData"] = {
        (t.x, t.y, t.z): t for t in all_tiles
    }

    plan: list[tuple[int, int, int]] = []
    skipped_hidden = 0
    skipped_fluid  = 0
    skipped_veg    = 0
    skipped_empty  = 0
    by_z: dict[int, int] = {}

    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            tile = _find_surface(by_xyz, x, y, z_min, z_max)

            if tile is None:
                skipped_empty += 1
                continue

            if tile.hidden:
                skipped_hidden += 1
                continue

            if tile.has_fluid:
                skipped_fluid += 1
                continue

            if tile.shape in _VEGETATION:
                skipped_veg += 1
                continue

            plan.append((tile.x, tile.y, tile.z))
            by_z[tile.z] = by_z.get(tile.z, 0) + 1

    designated = 0
    if plan and not dry_run:
        await client.send_dig_command(TileDigDesignation.CHANNEL, plan)
        designated = len(plan)

    return {
        "designated":     designated,
        "skipped_hidden": skipped_hidden,
        "skipped_fluid":  skipped_fluid,
        "skipped_veg":    skipped_veg,
        "skipped_empty":  skipped_empty,
        "by_z":           dict(sorted(by_z.items())),
        "plan":           plan,
    }
