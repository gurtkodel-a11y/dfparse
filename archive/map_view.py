"""
ASCII map viewer — renders a z-level cross-section of the current DF map.

Usage:
    python map_view.py                     # z-level of median citizen, full map
    python map_view.py --focus             # crop to 64×32 window around median citizen
    python map_view.py --z 167 --focus     # specific z, auto-centred crop
    python map_view.py --z 167 --range 3  # z-167 ± 3 stacked slices
    python map_view.py --cx 139 --cy 157 --cw 60 --ch 30  # explicit crop
"""

import argparse
import asyncio
import sys

from dfhack.client import DFHackClient
from dfhack.proto_defs import TiletypeShape
from gamestate.snapshot import Snapshot

# ASCII glyphs for each tiletype shape
_SHAPE_GLYPH: dict[int, str] = {
    TiletypeShape.EMPTY:        " ",
    TiletypeShape.FLOOR:        ".",
    TiletypeShape.BOULDER:      "o",
    TiletypeShape.PEBBLES:      ",",
    TiletypeShape.WALL:         "#",
    TiletypeShape.FORTIFICATION:"=",
    TiletypeShape.STAIR_UP:     "<",
    TiletypeShape.STAIR_DOWN:   ">",
    TiletypeShape.STAIR_UPDOWN: "X",
    TiletypeShape.RAMP:         "/",
    TiletypeShape.RAMP_TOP:     "'",
    TiletypeShape.BROOK_BED:    "~",
    TiletypeShape.BROOK_TOP:    "~",
    TiletypeShape.TREE_SHAPE:   "T",
    TiletypeShape.SAPLING:      "t",
    TiletypeShape.SHRUB:        "s",
    TiletypeShape.ENDLESS_PIT:  "V",
    TiletypeShape.BRANCH:       "b",
    TiletypeShape.TRUNK_BRANCH: "B",
    TiletypeShape.TWIG:         "w",
    TiletypeShape.NO_SHAPE:     "!",  # should not appear
}

_LEGEND = (
    "Legend: # wall  = fortif  . floor  o boulder  , pebbles\n"
    "        < up-stair  > dn-stair  X ud-stair  / ramp  ' ramp-top\n"
    "        ~ water  * magma  T tree-trunk  t sapling  s shrub  B trunk-branch  b branch  w twig\n"
    "        V endless-pit  (space) empty/sky  ? hidden/unexplored  ! unrecognised\n"
    "        (brook-bed/top show as ~ only if dry; water depth overrides all shape glyphs)\n"
    "Units:  d dwarf  D other-dwarf  a animal/other"
)


def _build_tiletype_map(tiletype_list) -> dict[int, TiletypeShape]:
    result: dict[int, TiletypeShape] = {}
    for tt in tiletype_list:
        shape_val = tt.shape if tt.HasField("shape") else TiletypeShape.NO_SHAPE
        try:
            shape = TiletypeShape(shape_val)
        except ValueError:
            shape = TiletypeShape.NO_SHAPE
        result[tt.id] = shape
    return result


def _render_z_level(
    z: int,
    blocks: list,
    tiletype_map: dict[int, TiletypeShape],
    unit_positions: dict[tuple[int, int], str],
    x_min: int, x_max: int,   # tile crop bounds (inclusive)
    y_min: int, y_max: int,
) -> list[str]:
    """Render one z-level crop as a list of text rows."""
    w = x_max - x_min + 1
    h = y_max - y_min + 1

    # Default: ? for tiles not covered by any returned block
    grid: list[list[str]] = [["?" for _ in range(w)] for _ in range(h)]

    for block in blocks:
        if block.map_z != z:
            continue
        bx = block.map_x  # map_x/map_y are tile coords, not block coords
        by = block.map_y

        for i, tile_id in enumerate(block.tiles):
            lx = i % 16
            ly = i // 16
            tx = bx + lx
            ty = by + ly
            if tx < x_min or tx > x_max or ty < y_min or ty > y_max:
                continue

            hidden = block.hidden[i] if i < len(block.hidden) else False
            if hidden:
                grid[ty - y_min][tx - x_min] = "?"
            else:
                shape = tiletype_map.get(tile_id, TiletypeShape.NO_SHAPE)
                glyph = _SHAPE_GLYPH.get(int(shape), "!")
                # Fluid overlays take priority over tile shape
                if i < len(block.magma) and block.magma[i] > 0:
                    glyph = "*"
                elif i < len(block.water) and block.water[i] > 0:
                    glyph = "~"
                grid[ty - y_min][tx - x_min] = glyph

    # Overlay unit glyphs
    for (ux, uy), glyph in unit_positions.items():
        if x_min <= ux <= x_max and y_min <= uy <= y_max:
            grid[uy - y_min][ux - x_min] = glyph

    # Axis labels (every 16 tiles, aligned to block boundaries)
    label_width = max(len(str(y_min)), len(str(y_max)))
    rows: list[str] = []
    for gy, row in enumerate(grid):
        abs_y = y_min + gy
        label = str(abs_y).rjust(label_width) if abs_y % 16 == 0 else " " * label_width
        rows.append(f"{label} |{''.join(row)}|")

    ruler_parts = [" " * (label_width + 2)]
    for x in range(x_min - (x_min % 16), x_max + 1, 16):
        if x < x_min:
            ruler_parts.append(" " * (16 - (x_min % 16)))
        else:
            segment = str(x).ljust(16)[:16]
            ruler_parts.append(segment)
    ruler = "".join(ruler_parts)[:label_width + 2 + w + 2]

    return [ruler] + rows + [ruler]


async def main(
    target_z: int | None,
    z_range: int,
    focus: bool,
    cx: int | None, cy: int | None,
    cw: int, ch: int,
) -> None:
    snap = Snapshot.load()
    citizens = snap.citizens()
    all_units = snap.units

    async with DFHackClient() as client:
        map_info = await client.get_map_info()
        tiletype_list = await client.get_tiletype_list()

        tiletype_map = _build_tiletype_map(tiletype_list)

        map_w = map_info.block_size_x * 16
        map_h = map_info.block_size_y * 16

        print(f"Map: {map_w}×{map_h} tiles, {map_info.block_size_z} z-levels", file=sys.stderr)

        # Determine z-level
        if target_z is None:
            z_vals = [u.pos.z for u in citizens if u.pos.z > 0]
            if not z_vals:
                print("No citizens in snapshot; specify --z explicitly.", file=sys.stderr)
                return
            target_z = sorted(z_vals)[len(z_vals) // 2]

        z_min = target_z - z_range
        z_max = target_z + z_range

        # Determine crop centre
        if focus or (cx is not None or cy is not None):
            if cx is None or cy is None:
                # Auto-centre on median citizen position
                xs = sorted(u.pos.x for u in citizens if u.pos.z == target_z) or \
                     sorted(u.pos.x for u in citizens)
                ys = sorted(u.pos.y for u in citizens if u.pos.z == target_z) or \
                     sorted(u.pos.y for u in citizens)
                cx = cx if cx is not None else xs[len(xs) // 2]
                cy = cy if cy is not None else ys[len(ys) // 2]
            x_min = max(0, cx - cw // 2)
            x_max = min(map_w - 1, cx + cw // 2)
            y_min = max(0, cy - ch // 2)
            y_max = min(map_h - 1, cy + ch // 2)
        else:
            x_min, x_max = 0, map_w - 1
            y_min, y_max = 0, map_h - 1

        # Only fetch the blocks that overlap the crop window
        bx_min = x_min // 16
        bx_max = x_max // 16
        by_min = y_min // 16
        by_max = y_max // 16

        print(f"Fetching blocks bx={bx_min}..{bx_max} by={by_min}..{by_max} z={z_min}..{z_max}…",
              file=sys.stderr)

        blocks = await client.get_block_list(
            min_x=bx_min, max_x=bx_max,
            min_y=by_min, max_y=by_max,
            min_z=z_min, max_z=z_max,
        )

    print(f"Received {len(blocks)} block(s). Crop: x={x_min}..{x_max}, y={y_min}..{y_max}",
          file=sys.stderr)

    def _unit_glyphs(z: int) -> dict[tuple[int, int], str]:
        glyphs: dict[tuple[int, int], str] = {}
        for u in all_units:
            if u.pos.z != z:
                continue
            if u.civ_id == snap.world.civ_id and u.race == snap.world.race_id:
                g = "d"
            elif u.race == snap.world.race_id:
                g = "D"
            else:
                g = "a"
            glyphs[(u.pos.x, u.pos.y)] = g
        return glyphs

    for z in range(z_min, z_max + 1):
        unit_glyphs = _unit_glyphs(z)
        rows = _render_z_level(z, blocks, tiletype_map, unit_glyphs, x_min, x_max, y_min, y_max)
        dwarf_count = sum(1 for g in unit_glyphs.values() if g == "d")
        print(f"\n=== z={z} ({dwarf_count} dwarves) ===")
        print("\n".join(rows))

    print(f"\n{_LEGEND}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASCII DF map viewer")
    parser.add_argument("--z", type=int, default=None, help="Z-level to display")
    parser.add_argument("--range", type=int, default=0, dest="z_range",
                        help="Show target_z ± N slices (default 0)")
    parser.add_argument("--focus", action="store_true",
                        help="Crop to a window centred on the median citizen position")
    parser.add_argument("--cx", type=int, default=None, help="Crop centre x tile")
    parser.add_argument("--cy", type=int, default=None, help="Crop centre y tile")
    parser.add_argument("--cw", type=int, default=64, help="Crop width in tiles (default 64)")
    parser.add_argument("--ch", type=int, default=32, help="Crop height in tiles (default 32)")
    args = parser.parse_args()
    asyncio.run(main(args.z, args.z_range, args.focus, args.cx, args.cy, args.cw, args.ch))
