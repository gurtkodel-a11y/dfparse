"""
Quick smoke-test for the DFHack remote client + gamestate layer.
Run while DF + DFHack are active and a world is loaded.
"""

import asyncio
from collections import Counter

from dfhack import DFHackClient
from dfhack import enums
from gamestate import WorldInfo, Unit, UnitKind, WorkDetail, WorkDetailMode, effective_labors


async def validate_enums(client: DFHackClient) -> None:
    """Cross-check dfhack/enums.py against live df.job_skill / df.unit_labor."""
    skill_raw = await client.run_lua("rpc.enums", "all_skills")
    labor_raw = await client.run_lua("rpc.enums", "all_labors")
    prof_raw  = await client.run_lua("rpc.enums", "all_professions")

    skill_mismatches = []
    for entry in skill_raw:
        id_str, name = entry.split(":", 1)
        sid = int(id_str)
        py_name = enums.SKILL_NAMES.get(sid)
        if py_name is None:
            skill_mismatches.append(f"  MISSING  skill {sid}: {name}")

    labor_mismatches = []
    for entry in labor_raw:
        id_str, name = entry.split(":", 1)
        lid = int(id_str)
        py_name = enums.LABOR_NAMES.get(lid)
        if py_name is None:
            labor_mismatches.append(f"  MISSING  labor {lid}: {name}")

    total_skills = len(skill_raw)
    total_labors = len(labor_raw)
    total_profs  = len(prof_raw)
    print(f"\nEnum validation — skills: {total_skills} live, {len(enums.SKILL_NAMES)} mapped"
          f"  |  labors: {total_labors} live, {len(enums.LABOR_NAMES)} mapped"
          f"  |  professions: {total_profs} live")
    for m in skill_mismatches:
        print(m)
    for m in labor_mismatches:
        print(m)
    if not skill_mismatches and not labor_mismatches:
        print("  All live enum IDs are covered.")


async def main():
    print("Connecting to DFHack on localhost:5000 ...")
    async with DFHackClient() as client:
        print("Handshake OK")
        print(f"DFHack: {await client.get_version()}  |  DF: {await client.get_df_version()}")

        world = WorldInfo.from_proto(await client.get_world_info())
        print(f"\nWorld:    {world.world_name}  [{world.mode}]")
        print(f"Save dir: {world.save_dir}")
        print(f"Civ ID:   {world.civ_id}   Site ID: {world.site_id}   Race ID: {world.race_id}")

        # Census (no skill/labor data needed)
        raw_units = await client.list_units()
        units = [Unit.from_proto(u) for u in raw_units]

        counts = Counter(u.kind(world.civ_id, world.race_id) for u in units)
        print(f"\nUnit census ({len(units)} total):")
        for kind, n in sorted(counts.items(), key=lambda x: x[0].name):
            print(f"  {kind.name:<20} {n}")

        # Citizen roster (basic)
        citizens = [u for u in units if u.kind(world.civ_id, world.race_id) == UnitKind.CITIZEN]
        print(f"\nCitizens ({len(citizens)}):")
        for u in citizens:
            sqd = f"  squad={u.squad_id}" if u.squad_id != -1 else ""
            print(f"  [{u.unit_id:4d}] {str(u.name):<50} {u.pos}{sqd}")

        raw_wds = await client.get_work_details()
        work_details = [WorkDetail.from_raw(r) for r in raw_wds]
        print(f"\nWork Details ({len(work_details)}):")
        for wd in work_details:
            print(f"  {wd.name!r:30s}  mode={wd.mode.name}  "
                  f"labors={len(wd.labor_ids)}  units={len(wd.assigned_unit_ids)}")

        # Skills and labors — fetch with mask flags set
        raw_units_detail = await client.list_units(
            skills=True, labors=True, profession=True
        )
        detail_by_id = {u.unit_id: u for u in raw_units_detail}

        print(f"\nCitizen skills & effective labors:")
        for u_basic in citizens:
            raw = detail_by_id.get(u_basic.unit_id)
            if raw is None:
                continue
            u = Unit.from_proto(raw)
            role = u.role_label(work_details)
            top_skills = u.decoded_skills()[:5]  # top 5 by level
            skill_str = ", ".join(
                f"{s.title} {s.name}" for s in top_skills
            ) or "(none)"

            print(f"\n  {str(u.name)}  [{role}]")
            print(f"    Skills:  {skill_str}")

        # Any non-citizen notables
        for kind in (UnitKind.MERCHANT, UnitKind.DIPLOMAT, UnitKind.INVADER,
                     UnitKind.NOTABLE_CREATURE, UnitKind.GHOST):
            group = [u for u in units if u.kind(world.civ_id, world.race_id) == kind]
            if group:
                print(f"\n{kind.name} ({len(group)}):")
                for u in group:
                    print(f"  [{u.unit_id:4d}] {str(u.name):<50} race={u.race}  {u.pos}")

        await validate_enums(client)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
