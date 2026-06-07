"""
Diagnostic: probe the nobles system and print raw + parsed output.

Usage:
    python diag_nobles.py
"""

import asyncio
from dfhack.client import DFHackClient
from gamestate.nobles import NoblesReport


async def main():
    async with DFHackClient() as client:
        print("=== raw lines from rpc.nobles.all() ===")
        raw = await client.get_nobles()
        for line in raw:
            print(" ", repr(line))

        print()
        print("=== raw lines from rpc.nobles.positions() ===")
        pos_lines = await client.get_noble_positions()
        for line in pos_lines:
            print(" ", repr(line))

        print()
        report = NoblesReport.from_raw(raw)
        if report.errors:
            print("=== ERRORS ===")
            for e in report.errors:
                print(" ", e)
            print()

        print("=== Parsed nobles report ===")
        print(f"Bookkeeper precision : {report.bookkeeper_precision}  ({report.bookkeeper_precision_label()})")
        print(f"Bookkeeper cooldown  : {report.bookkeeper_cooldown} / 1008 ticks")
        print(f"Bookkeeper settings  : {report.bookkeeper_settings}  (target precision)")
        print(f"Manager cooldown     : {report.manager_cooldown} / 1008 ticks")
        print()
        print("Noble assignments:")
        if report.positions:
            for p in report.positions:
                print(f"  {p.display()}  (code={p.code!r}, pid={p.position_id}, hfid={p.histfig_id}, uid={p.unit_id})")
        else:
            print("  (none)")

        print()
        print("Quick lookups:")
        for label, fn in [
            ("Bookkeeper",         report.bookkeeper),
            ("Manager",            report.manager),
            ("Mayor",              report.mayor),
            ("Chief Medical Dwarf", report.chief_medical_dwarf),
            ("Sheriff",            report.sheriff),
        ]:
            p = fn()
            if p:
                print(f"  {label}: {p.unit_name or '(on-map)'} uid={p.unit_id}")
            else:
                print(f"  {label}: (vacant / not assigned)")


asyncio.run(main())
