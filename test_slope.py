"""
Test: sloped path from (81, 132, 160) to (97, 132, 165).
Ascending 5 z-levels over 16 horizontal tiles — ramps + floor openings.
Requires DF + DFHack running with a world loaded and game unpaused.
"""

import asyncio
from dfhack.client import DFHackClient
from commands import dig_slope


async def main():
    async with DFHackClient() as client:
        print("Digging slope (81,132,160) -> (97,132,165)...")
        await dig_slope(client, 81, 132, 160, 97, 132, 165)
        print("Done.")


asyncio.run(main())
