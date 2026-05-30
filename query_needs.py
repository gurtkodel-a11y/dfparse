"""
List unmet needs across all citizens, sorted by number of affected dwarves.
"""

import asyncio
from dfhack import DFHackClient


async def main():
    async with DFHackClient() as client:
        needs = await client.get_unmet_needs()

    if not needs:
        print("No unmet needs — your dwarves are content!")
        return

    # Sort by dwarf count descending, then by urgency (total_focus ascending = more negative first)
    needs.sort(key=lambda x: (-x[1], x[2]))

    print(f"{'Unmet need':<30} {'Dwarves':>7}  {'Avg focus':>10}")
    print(f"{'-'*30} {'-'*7}  {'-'*10}")
    for name, count, total in needs:
        avg = total // count
        print(f"{name:<30} {count:>7}  {avg:>10}")


if __name__ == "__main__":
    asyncio.run(main())
