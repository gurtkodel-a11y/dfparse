"""
Test: dig a staircase from z=169 down to z=165 at (95, 123),
and designate a ramp at (95, 119, 168).
Requires DF + DFHack running with a world loaded and game unpaused.
"""

import asyncio
from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation

X, Y = 95, 123
TOP_Z, BOT_Z = 169, 165


async def main():
    async with DFHackClient() as client:

        # --- staircase ---
        # top: down staircase only (entry point)
        print(f"DOWN_STAIR at ({X}, {Y}, {TOP_Z})...")
        await client.send_dig_command(TileDigDesignation.DOWN_STAIR, [(X, Y, TOP_Z)])

        # middle floors: up/down so dwarves can pass through
        mid = [(X, Y, z) for z in range(TOP_Z - 1, BOT_Z, -1)]
        print(f"UP_DOWN_STAIR at z={TOP_Z-1} to z={BOT_Z+1} ({len(mid)} tiles)...")
        await client.send_dig_command(TileDigDesignation.UP_DOWN_STAIR, mid)

        # bottom: up staircase only (exit point)
        print(f"UP_STAIR at ({X}, {Y}, {BOT_Z})...")
        await client.send_dig_command(TileDigDesignation.UP_STAIR, [(X, Y, BOT_Z)])

        # --- ramp ---
        print("RAMP at (95, 119, 168)...")
        await client.send_dig_command(TileDigDesignation.RAMP, [(95, 119, 168)])
        print("  done.")

    print("All orders sent.")


asyncio.run(main())
