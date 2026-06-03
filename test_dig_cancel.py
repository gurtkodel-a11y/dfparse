"""
Cancel the dig designations placed by test_dig.py:
  - DEFAULT_DIG at (98, 125, 166)
  - CHANNEL at (100, 136, 169)
Requires DF + DFHack running with a world loaded and game unpaused.
"""

import asyncio
from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation


async def main():
    async with DFHackClient() as client:
        print("Cancelling designations...")
        await client.send_dig_command(
            TileDigDesignation.NO_DIG,
            [(98, 125, 166), (100, 136, 169)],
        )
        print("Done.")


asyncio.run(main())
