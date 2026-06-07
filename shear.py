"""
CLI driver for dig_shear_hillside.

Usage:
    python shear.py X1 Y1 X2 Y2 Z_MIN Z_MAX [--dry-run]

Queries the terrain in the given rectangle and z range, then issues CHANNEL
orders on every surface tile.  Use --dry-run to preview the plan without
sending any dig commands.

Example:
    python shear.py 100 140 160 180 163 175
    python shear.py 100 140 160 180 163 175 --dry-run
"""

import argparse
import asyncio

from dfhack.client import DFHackClient
from agent.spyglass import Spyglass
from commands.terrain import dig_shear_hillside


def _summary(result: dict) -> None:
    print(f"\nShear plan: {len(result['plan'])} surface tiles found")
    if result["by_z"]:
        z_min = min(result["by_z"])
        z_max = max(result["by_z"])
        print(f"  z range: {z_min}..{z_max}")
        for z in range(z_min, z_max + 1):
            count = result["by_z"].get(z, 0)
            bar   = "#" * min(count, 60)
            print(f"  z={z:3d}  {bar} {count}")
    skips = [
        ("hidden",  result["skipped_hidden"]),
        ("fluid",   result["skipped_fluid"]),
        ("veg",     result["skipped_veg"]),
        ("no surf", result["skipped_empty"]),
    ]
    skip_parts = [f"{n} {label}" for label, n in skips if n > 0]
    if skip_parts:
        print(f"  skipped: {', '.join(skip_parts)}")
    if result["designated"]:
        print(f"\n  → {result['designated']} CHANNEL orders issued.")
    else:
        print("\n  → dry-run: no orders sent.")


async def main(x1, y1, x2, y2, z_min, z_max, dry_run):
    async with DFHackClient() as client:
        glass = await Spyglass.create(client)
        result = await dig_shear_hillside(
            client, x1, y1, x2, y2, z_min, z_max,
            glass=glass, dry_run=dry_run,
        )
    _summary(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Shear a hillside down one z-level")
    p.add_argument("x1",    type=int)
    p.add_argument("y1",    type=int)
    p.add_argument("x2",    type=int)
    p.add_argument("y2",    type=int)
    p.add_argument("z_min", type=int, help="lowest z to search for the surface")
    p.add_argument("z_max", type=int, help="highest z to search (set above the hilltop)")
    p.add_argument("--dry-run", action="store_true",
                   help="preview the plan without sending dig commands")
    args = p.parse_args()
    asyncio.run(main(args.x1, args.y1, args.x2, args.y2,
                     args.z_min, args.z_max, args.dry_run))
