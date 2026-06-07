"""
Probe script: explore what DFHack exposes about world items.
Prints a type-count summary, then dumps a sample of individual items.
"""

import asyncio
from dfhack.client import DFHackClient


async def main():
    async with DFHackClient() as client:
        print("=== Item type summary (stack-adjusted counts) ===")
        rows = await client.run_lua("rpc.items", "summary")
        for row in sorted(rows):
            print(" ", row)

        print()
        print("=== Sample items (first 80) ===")
        print("  type | material | description | stack | quality | pos | loc")
        samples = await client.run_lua("rpc.items", "sample", "80")
        for s in samples:
            parts = s.split("|")
            type_name = parts[0]
            mat       = parts[1]
            desc      = parts[2]
            stack     = parts[3]
            quality   = parts[4]
            pos       = parts[5]
            loc       = parts[6] if len(parts) > 6 else "?"
            print(f"  [{type_name}] {mat!r} / {desc!r}  stack={stack} q={quality} @{pos} {loc}")


asyncio.run(main())
