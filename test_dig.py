"""
Quick test: send dig and channel orders to two specific tiles.
Requires DF + DFHack running with a world loaded and game unpaused.
"""

import asyncio
from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation


async def main():
    async with DFHackClient() as client:
        print("Sending DEFAULT_DIG at (98, 125, 166)...")
        await client.send_dig_command(TileDigDesignation.DEFAULT_DIG, [(98, 125, 166)])
        print("  done.")

        print("Sending CHANNEL at (100, 136, 169)...")
        await client.send_dig_command(TileDigDesignation.CHANNEL, [(100, 136, 169)])
        print("  done.")

    print("All orders sent. Check the map for dig designations.")


asyncio.run(main())
