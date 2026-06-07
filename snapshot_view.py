"""
ASCII map viewer that reads from snapshot_tiles.json (no live DFHack connection needed).

Usage:
    python snapshot_view.py                # median citizen z, focused crop
    python snapshot_view.py --z 167        # specific z-level
    python snapshot_view.py --range 2      # z ± 2 stacked slices
    python snapshot_view.py --list-z       # show which z-levels were captured
    python snapshot_view.py --cw 100 --ch 50  # wider crop window
"""

import argparse
import json
import sys
from pathlib import Path

from dfhack.proto_defs import TiletypeShape
from gamestate.snapshot import Snapshot

TILES_PATH = Path(__file__).parent / "snapshot_tiles.json"

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
    TiletypeShape.NO_SHAPE:     "!",
}

_LEGEND = (
    "Legend: # wall  = fortif  . floor  o boulder  , pebbles\n"
    "        < up-stair  > dn-stair  X ud-stair  / ramp  ' ramp-top\n"
    "        ~ water  * magma  T tree  t sapling  s shrub  B trunk-branch  b branch  w twig\n"
    "        (space) empty/sky  ? hidden/unexplored\n"
    "Units:  d dwarf  D other-dwarf  a animal/other"
)


def _render_z_level(
    z: int,
    blocks: list[dict],
    unit_positions: dict[tuple[int, int], str],
    x_min: int, x_max: int,
    y_min: int, y_max: int,
) -> list[str]:
    w = x_max - x_min + 1
    h = y_max - y_min + 1
    grid: list[list[str]] = [["?" for _ in range(w)] for _ in range(h)]

    for block in blocks:
        if block["z"] != z:
            continue
        bx = block["bx"] * 16   # block coords → tile coords
        by = block["by"] * 16
        shapes = block["shapes"]
        water  = block.get("water", [])
        magma  = block.get("magma", [])
        hidden = block.get("hidden", [])

        for i, shape_int in enumerate(shapes):
            lx = i % 16
            ly = i // 16
            tx = bx + lx
            ty = by + ly
            if tx < x_min or tx > x_max or ty < y_min or ty > y_max:
                continue

            is_hidden = hidden[i] if i < len(hidden) else False
            if is_hidden:
                grid[ty - y_min][tx - x_min] = "?"
            else:
                try:
                    shape = TiletypeShape(shape_int)
                except ValueError:
                    shape = TiletypeShape.NO_SHAPE
                glyph = _SHAPE_GLYPH.get(int(shape), "!")
                if i < len(magma) and magma[i] > 0:
                    glyph = "*"
                elif i < len(water) and water[i] > 0:
                    glyph = "~"
                grid[ty - y_min][tx - x_min] = glyph

    for (ux, uy), glyph in unit_positions.items():
        if x_min <= ux <= x_max and y_min <= uy <= y_max:
            grid[uy - y_min][ux - x_min] = glyph

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
            ruler_parts.append(str(x).ljust(16)[:16])
    ruler = "".join(ruler_parts)[:label_width + 2 + w + 2]

    return [ruler] + rows + [ruler]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--z",     type=int, default=None, help="Z-level to render")
    parser.add_argument("--range", type=int, default=0, dest="z_range",
                        help="Show target_z ± N slices (default 0)")
    parser.add_argument("--list-z", action="store_true",
                        help="Print captured z-levels and exit")
    parser.add_argument("--cw", type=int, default=80,  help="Crop width in tiles (default 80)")
    parser.add_argument("--ch", type=int, default=40,  help="Crop height in tiles (default 40)")
    parser.add_argument("--cx", type=int, default=None, help="Crop centre x (default: median citizen)")
    parser.add_argument("--cy", type=int, default=None, help="Crop centre y (default: median citizen)")
    args = parser.parse_args()

    if not TILES_PATH.exists():
        print("snapshot_tiles.json not found — run `python snapshot.py` first.", file=sys.stderr)
        sys.exit(1)

    tiles_data = json.loads(TILES_PATH.read_text(encoding="utf-8"))
    blocks: list[dict] = tiles_data["blocks"]
    region: dict = tiles_data["region"]

    snap = Snapshot.load()
    citizens = snap.citizens()

    captured_z = sorted({b["z"] for b in blocks})

    if args.list_z:
        print(f"Captured region: {region}")
        print(f"Z-levels with blocks: {captured_z}")
        return

    # Pick target z
    if args.z is not None:
        target_z = args.z
    else:
        z_vals = [u.pos.z for u in citizens if u.pos.z > 0]
        if not z_vals:
            print("No citizens in snapshot; use --z to specify a z-level.", file=sys.stderr)
            sys.exit(1)
        target_z = sorted(z_vals)[len(z_vals) // 2]

    z_min = target_z - args.z_range
    z_max = target_z + args.z_range

    # Pick crop centre
    cx = args.cx
    cy = args.cy
    if cx is None:
        xs = sorted(u.pos.x for u in citizens if u.pos.z == target_z) or \
             sorted(u.pos.x for u in citizens)
        cx = xs[len(xs) // 2] if xs else (region["x1"] + region["x2"]) // 2
    if cy is None:
        ys = sorted(u.pos.y for u in citizens if u.pos.z == target_z) or \
             sorted(u.pos.y for u in citizens)
        cy = ys[len(ys) // 2] if ys else (region["y1"] + region["y2"]) // 2

    x_min = max(region["x1"], cx - args.cw // 2)
    x_max = min(region["x2"], cx + args.cw // 2)
    y_min = max(region["y1"], cy - args.ch // 2)
    y_max = min(region["y2"], cy + args.ch // 2)

    def _unit_glyphs(z: int) -> dict[tuple[int, int], str]:
        glyphs: dict[tuple[int, int], str] = {}
        for u in snap.units:
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

    snap_time = snap.game_date or snap.snapshot_time
    print(f"Snapshot: {snap_time}  |  Captured z-levels: {captured_z[0]}..{captured_z[-1]}"
          f"  |  Showing z={z_min}..{z_max}, crop x={x_min}..{x_max} y={y_min}..{y_max}",
          file=sys.stderr)

    for z in range(z_min, z_max + 1):
        unit_glyphs = _unit_glyphs(z)
        rows = _render_z_level(z, blocks, unit_glyphs, x_min, x_max, y_min, y_max)
        dwarf_count = sum(1 for g in unit_glyphs.values() if g == "d")
        print(f"\n=== z={z} ({dwarf_count} dwarves) ===")
        print("\n".join(rows))

    print(f"\n{_LEGEND}")


if __name__ == "__main__":
    main()
