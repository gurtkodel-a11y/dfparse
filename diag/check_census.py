"""Quick check: show a few units from each UnitKind category with positions."""

import asyncio
from collections import defaultdict

from dfhack import DFHackClient
from gamestate import WorldInfo, Unit, UnitKind


async def main():
    async with DFHackClient() as client:
        world = WorldInfo.from_proto(await client.get_world_info())
        raw_units = await client.list_units()
        units = [Unit.from_proto(u) for u in raw_units]

    by_kind = defaultdict(list)
    for u in units:
        by_kind[u.kind(world.civ_id, world.race_id)].append(u)

    for kind in UnitKind:
        group = by_kind.get(kind, [])
        if not group:
            continue
        print(f"\n{kind.name} ({len(group)} total) — sample:")
        for u in group[:4]:
            print(f"  [{u.unit_id:4d}] {str(u.name):<45} race={u.race}  pos={u.pos}"
                  f"  civ={u.civ_id}  histfig={'yes' if u.has_histfig else 'no'}")


if __name__ == "__main__":
    asyncio.run(main())
