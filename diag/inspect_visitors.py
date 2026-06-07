"""Dump flag details for all VISITOR-classified units."""

import asyncio
from dfhack import DFHackClient
from gamestate import WorldInfo, Unit, UnitKind
from gamestate.units import (
    _F1_INACTIVE, _F1_MERCHANT, _F1_FOREST, _F1_LEFT, _F1_INCOMING,
    _F1_DIPLOMAT, _F1_ON_GROUND, _F1_ACTIVE_INVADER, _F1_INVADER_ORIGIN,
    _F2_KILLED, _F2_SLAUGHTER, _F2_UNDERWORLD, _F2_RESIDENT,
    _F3_GHOSTLY,
)

_F1_NAMES = {
    _F1_INACTIVE:       "inactive",
    _F1_MERCHANT:       "merchant",
    _F1_FOREST:         "forest",
    _F1_LEFT:           "left",
    _F1_INCOMING:       "incoming",
    _F1_DIPLOMAT:       "diplomat",
    _F1_ON_GROUND:      "on_ground",
    _F1_ACTIVE_INVADER: "active_invader",
    _F1_INVADER_ORIGIN: "invader_origin",
}
_F2_NAMES = {
    _F2_KILLED:     "killed",
    _F2_SLAUGHTER:  "slaughter",
    _F2_UNDERWORLD: "underworld",
    _F2_RESIDENT:   "resident",
}
_F3_NAMES = {_F3_GHOSTLY: "ghostly"}


def active_flags(val, mapping):
    return [name for mask, name in mapping.items() if val & mask] or ["(none)"]


async def main():
    async with DFHackClient() as client:
        world = WorldInfo.from_proto(await client.get_world_info())
        raw_units = await client.list_units()

    units = [Unit.from_proto(u) for u in raw_units]
    visitors = [u for u in units if u.kind(world.civ_id, world.race_id) == UnitKind.VISITOR]

    print(f"VISITOR units ({len(visitors)})  player_civ={world.civ_id}  player_race={world.race_id}\n")
    for u in visitors:
        print(f"  id={u.unit_id}  name={u.name.display()!r}  race={u.race}"
              f"  civ={u.civ_id}  histfig={'yes' if u.has_histfig else 'no'}  pos={u.pos}")
        print(f"    flags1: {u.flags1:#010x}  set={active_flags(u.flags1, _F1_NAMES)}")
        print(f"    flags2: {u.flags2:#010x}  set={active_flags(u.flags2, _F2_NAMES)}")
        print(f"    flags3: {u.flags3:#010x}  set={active_flags(u.flags3, _F3_NAMES)}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
