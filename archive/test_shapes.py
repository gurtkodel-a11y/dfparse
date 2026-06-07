"""
Test: staircase and rectangle dig commands.
Requires DF + DFHack running with a world loaded and game unpaused.
"""

import asyncio
from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation
from commands import dig_staircase, dig_rectangle


async def main():
    async with DFHackClient() as client:
        print("Staircase at (104, 130), z=169 down to z=160...")
        await dig_staircase(client, 104, 130, 169, 160)
        print("  done.")

        print("Rectangle (81,130)→(85,140) at z=167, DEFAULT_DIG...")
        await dig_rectangle(client, TileDigDesignation.DEFAULT_DIG, 81, 130, 85, 140, 167)
        print("  done.")

    print("All orders sent.")


asyncio.run(main())
