"""Diagnostic: probe which blocks/z-levels actually have data."""
import asyncio
from dfhack.client import DFHackClient
from gamestate.snapshot import Snapshot

async def main():
    snap = Snapshot.load()
    citizens = snap.citizens()

    # Find the block coordinates that contain an actual dwarf
    if citizens:
        u = citizens[0]
        bx_unit = u.pos.x // 16
        by_unit = u.pos.y // 16
        z_unit  = u.pos.z
        print(f"First citizen '{u.name.first}' at tile ({u.pos.x},{u.pos.y},{u.pos.z})"
              f" → block ({bx_unit},{by_unit}), z={z_unit}")
    else:
        bx_unit, by_unit, z_unit = 0, 0, 167
        print("No citizens in snapshot, using defaults")

    async with DFHackClient() as client:
        map_info = await client.get_map_info()
        bsx = map_info.block_size_x
        bsy = map_info.block_size_y
        bsz = map_info.block_size_z
        print(f"\nMapInfo: {bsx}×{bsy}×{bsz} blocks ({bsx*16}×{bsy*16} tiles, {bsz} z-levels)")

        # ── Test 1: one block containing a known dwarf at the right z ──
        print(f"\n[Test 1] Single block ({bx_unit},{by_unit}) at z={z_unit}")
        blocks = await client.get_block_list(bx_unit, bx_unit, by_unit, by_unit, z_unit, z_unit)
        print(f"  → {len(blocks)} block(s) returned")
        for b in blocks:
            tiles = list(b.tiles)
            hidden = list(b.hidden)
            print(f"     block ({b.map_x},{b.map_y},{b.map_z})")
            print(f"     tiles:  len={len(tiles)}  first 16={tiles[:16]}")
            print(f"     hidden: len={len(hidden)}  first 16={hidden[:16]}")
            true_count = sum(1 for h in hidden if h)
            false_count = sum(1 for h in hidden if not h)
            print(f"     hidden True={true_count}  False={false_count}  (absent={256-len(hidden)})")

        # ── Test 2: 3×3 neighbourhood around the dwarf block ──
        x0, x1 = max(0, bx_unit-1), min(bsx-1, bx_unit+1)
        y0, y1 = max(0, by_unit-1), min(bsy-1, by_unit+1)
        print(f"\n[Test 2] 3×3 neighbourhood bx {x0}-{x1}, by {y0}-{y1} at z={z_unit}")
        blocks2 = await client.get_block_list(x0, x1, y0, y1, z_unit, z_unit)
        print(f"  → {len(blocks2)} block(s) returned")

        # ── Test 3: full map XY but just 5 z-levels around z_unit ──
        z0, z1 = max(0, z_unit-2), min(bsz-1, z_unit+2)
        print(f"\n[Test 3] Full XY (bx 0-{bsx-1}, by 0-{bsy-1}) at z={z0}..{z1}")
        blocks3 = await client.get_block_list(0, bsx-1, 0, bsy-1, z0, z1)
        print(f"  → {len(blocks3)} block(s) returned")
        z_counts: dict[int, int] = {}
        for b in blocks3:
            z_counts[b.map_z] = z_counts.get(b.map_z, 0) + 1
        for z, cnt in sorted(z_counts.items()):
            print(f"     z={z}: {cnt} block(s)")

        # ── Test 4: single block at dwarf, all z-levels ──
        print(f"\n[Test 4] Single block ({bx_unit},{by_unit}) across all z (0..{bsz-1})")
        blocks4 = await client.get_block_list(bx_unit, bx_unit, by_unit, by_unit, 0, bsz-1)
        print(f"  → {len(blocks4)} block(s) returned")
        for b in blocks4:
            print(f"     z={b.map_z}: tiles[0:4]={list(b.tiles[:4])}")

        # ── Test 5: for each unique citizen z-level, full-XY sweep ──
        print(f"\n[Test 5] Per citizen z-level — full XY sweep (fresh reset each time)")
        unique_z = sorted({u.pos.z for u in citizens})
        for z in unique_z:
            at_z = [u for u in citizens if u.pos.z == z]
            print(f"\n  z={z}  ({len(at_z)} citizen(s): "
                  + ", ".join(u.name.first.capitalize() for u in at_z) + ")")
            # Full reset then full-XY query for just this z
            blocks5 = await client.get_block_list(0, bsx-1, 0, bsy-1, z, z)
            if blocks5:
                print(f"    → {len(blocks5)} block(s) returned  "
                      f"map_z values: {sorted({b.map_z for b in blocks5})}")
                # Check the specific block each citizen is in
                for u in at_z:
                    bx = u.pos.x // 16
                    by = u.pos.y // 16
                    match = [b for b in blocks5 if b.map_x // 16 == bx and b.map_y // 16 == by]
                    if match:
                        h = list(match[0].hidden)
                        tile_idx = (u.pos.x % 16) + (u.pos.y % 16) * 16
                        hidden_at = h[tile_idx] if tile_idx < len(h) else "(absent)"
                        print(f"    {u.name.first.capitalize():20} block ({bx},{by}) found  "
                              f"hidden@dwarf={hidden_at}")
                    else:
                        print(f"    {u.name.first.capitalize():20} block ({bx},{by}) NOT in response")
            else:
                print(f"    → 0 blocks returned for z={z}  "
                      f"(DF has no loaded blocks at this z-level)")

        # ── Test 6: single-block exact query for each underground citizen ──
        underground = [u for u in citizens if u.pos.z < 152]
        print(f"\n[Test 6] Single-block exact query for each underground citizen")
        if not underground:
            print("  (no underground citizens in snapshot)")
        for u in underground:
            bx = u.pos.x // 16
            by = u.pos.y // 16
            z  = u.pos.z
            blks = await client.get_block_list(bx, bx, by, by, z, z)
            tag = f"block({bx},{by}) z={z}"
            if blks:
                h = list(blks[0].hidden)
                idx = (u.pos.x % 16) + (u.pos.y % 16) * 16
                print(f"  {u.name.first.capitalize():20} {tag} → {len(blks)} block(s)  hidden@dwarf={h[idx] if idx < len(h) else '?'}")
            else:
                print(f"  {u.name.first.capitalize():20} {tag} → 0 blocks  ← MISSING")

        # ── Test 7: narrow XY (our prefetch range) vs full XY, per underground z ──
        print(f"\n[Test 7] Narrow XY (capture region) vs full XY for each underground z-level")
        # Reconstruct the prefetch XY range the same way snapshot.py does.
        if underground:
            import json
            try:
                region = json.loads(open("snapshot_region.json").read())
                pbx_min = max(0, region["x1"] // 16 - 1)
                pbx_max = min(bsx - 1, region["x2"] // 16 + 1)
                pby_min = max(0, region["y1"] // 16 - 1)
                pby_max = min(bsy - 1, region["y2"] // 16 + 1)
                print(f"  prefetch XY: bx=[{pbx_min}..{pbx_max}] by=[{pby_min}..{pby_max}]  "
                      f"(full map: bx=[0..{bsx-1}] by=[0..{bsy-1}])")
            except Exception as e:
                pbx_min, pbx_max, pby_min, pby_max = 0, bsx-1, 0, bsy-1
                print(f"  (could not load snapshot_region.json: {e}; using full XY)")

            for z in sorted({u.pos.z for u in underground}):
                blks_narrow = await client.get_block_list(pbx_min, pbx_max, pby_min, pby_max, z, z)
                blks_full   = await client.get_block_list(0, bsx-1, 0, bsy-1, z, z)
                print(f"  z={z}: narrow={len(blks_narrow)} blocks  full={len(blks_full)} blocks")
                if blks_full and not blks_narrow:
                    # Show where the full-XY blocks are
                    coords = sorted({(b.map_x // 16, b.map_y // 16) for b in blks_full})
                    print(f"         full-XY blocks at: {coords[:10]}"
                          + (" ..." if len(coords) > 10 else ""))
                    in_range = [(bx, by) for bx, by in coords
                                if pbx_min <= bx <= pbx_max and pby_min <= by <= pby_max]
                    print(f"         of those, {len(in_range)} are within narrow range: {in_range[:5]}")

asyncio.run(main())
