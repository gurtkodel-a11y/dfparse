"""
Safety check: send a dig order to an open-air tile (88, 129, 169).
Expected: command succeeds at the RPC level but DF ignores it (no designation placed,
no crash, no hang). Confirms DFHack defers validity checks to the game engine.
"""

import asyncio
from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation


async def main():
    async with DFHackClient() as client:
        print("Sending DEFAULT_DIG to open-air tile (88, 129, 169)...")
        await client.send_dig_command(TileDigDesignation.DEFAULT_DIG, [(88, 129, 169)])
        print("RPC returned without error.")
        print("Check the map: no designation should appear at (88, 129, 169).")


asyncio.run(main())
