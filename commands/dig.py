"""
High-level dig designation commands built on top of DFHackClient.send_dig_command.

Callers are responsible for passing diggable coordinates; DF will silently cancel
any designation it cannot fulfil (already-open tiles, etc.) without crashing.
"""

from dfhack.client import DFHackClient
from dfhack.proto_defs import TileDigDesignation


def _z_sequence(z1: int, z2: int, n: int) -> list[int]:
    """Return a z value for each of n tiles, rising/descending from z1 to z2.

    Rises (or descents) are spaced every floor((n-1)/dz) tiles so that all
    inter-rise gaps are equal.  Any leftover tile is absorbed into the final
    flat segment rather than stretching an internal gap.
    """
    dz = abs(z2 - z1)
    if dz == 0 or n <= 1:
        return [z1] * n

    sign = 1 if z2 > z1 else -1
    step = (n - 1) // dz       # tiles between consecutive z-changes
    z = z1
    result: list[int] = []
    count = 0                   # tiles spent at current z-level

    for _ in range(n):
        result.append(z)
        count += 1
        if count >= step and z != z2:
            z += sign
            count = 0

    return result


def _bresenham(x1: int, y1: int, x2: int, y2: int) -> list[tuple[int, int]]:
    """Return a 1-tile-wide grid path from (x1,y1) to (x2,y2), inclusive."""
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    sx = 1 if x2 > x1 else -1
    sy = 1 if y2 > y1 else -1
    x, y = x1, y1
    points: list[tuple[int, int]] = []
    if dx >= dy:
        err = dx // 2
        while x != x2:
            points.append((x, y))
            err -= dy
            if err < 0:
                y += sy
                err += dx
            x += sx
    else:
        err = dy // 2
        while y != y2:
            points.append((x, y))
            err -= dx
            if err < 0:
                x += sx
                err += dy
            y += sy
    points.append((x2, y2))
    return points


async def dig_staircase(client: DFHackClient, x: int, y: int, z1: int, z2: int) -> None:
    """Designate a vertical staircase at (x, y) from z1 to z2 (inclusive, either order).

    Uses the standard DF stair convention:
      top z    → DOWN_STAIR
      middle z → UP_DOWN_STAIR (one call, all tiles batched)
      bottom z → UP_STAIR

    A single-tile staircase (z1 == z2) is designated UP_DOWN_STAIR so it can
    connect to levels above and below if they are later dug out.
    """
    top, bot = max(z1, z2), min(z1, z2)

    if top == bot:
        await client.send_dig_command(TileDigDesignation.UP_DOWN_STAIR, [(x, y, top)])
        return

    await client.send_dig_command(TileDigDesignation.DOWN_STAIR, [(x, y, top)])

    mid = [(x, y, z) for z in range(top - 1, bot, -1)]
    if mid:
        await client.send_dig_command(TileDigDesignation.UP_DOWN_STAIR, mid)

    await client.send_dig_command(TileDigDesignation.UP_STAIR, [(x, y, bot)])


async def dig_rectangle(
    client: DFHackClient,
    designation: int,
    x1: int, y1: int,
    x2: int, y2: int,
    z: int,
) -> None:
    """Designate a filled rectangle of tiles at elevation z.

    Corner order and direction do not matter; the bounding box is normalised.
    All tiles share the same designation and are sent in a single RPC call.

    Args:
        client:      Connected DFHackClient.
        designation: A TileDigDesignation value (e.g. TileDigDesignation.DEFAULT_DIG).
        x1, y1:      One corner of the rectangle.
        x2, y2:      Opposite corner of the rectangle.
        z:           Elevation of the rectangle.
    """
    xs = range(min(x1, x2), max(x1, x2) + 1)
    ys = range(min(y1, y2), max(y1, y2) + 1)
    tiles = [(x, y, z) for x in xs for y in ys]
    await client.send_dig_command(designation, tiles)


async def dig_slope(
    client: DFHackClient,
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
) -> None:
    """Designate a 1-tile-wide sloped path from (x1,y1,z1) to (x2,y2,z2).

    The XY path follows Bresenham's line. Z changes by at most 1 per step,
    distributed as evenly as possible. Raises ValueError if |Δz| exceeds the
    number of XY steps (slope too steep for a ramp; use dig_staircase instead).

    Descent steps use CHANNEL_DIG (removes floor at the upper z, auto-creates
    ramp at the lower z). Ascent steps use RAMP_DIG at the lower z plus
    DEFAULT_DIG at the upper z to open the headroom above the ramp.
    Flat steps use DEFAULT_DIG. All tiles of each designation type are batched
    into a single RPC call.
    """
    path = _bresenham(x1, y1, x2, y2)
    n = len(path)
    dz = abs(z2 - z1)
    if dz > n - 1:
        raise ValueError(
            f"Slope too steep: {dz} z-levels over {n - 1} horizontal step(s). "
            f"Need at least {dz + 1} tiles of XY distance, or use dig_staircase."
        )

    z_seq = _z_sequence(z1, z2, n)

    default_tiles: list[tuple[int, int, int]] = []
    channel_tiles: list[tuple[int, int, int]] = []
    ramp_tiles:    list[tuple[int, int, int]] = []

    for i, (x, y) in enumerate(path):
        z      = z_seq[i]
        z_prev = z_seq[i - 1] if i > 0 else z

        if z == z_prev:
            default_tiles.append((x, y, z))
        elif z < z_prev:                        # descending
            channel_tiles.append((x, y, z_prev))   # channel from above; ramp auto-created at z
        else:                                   # ascending
            ramp_tiles.append((x, y, z_prev))       # ramp carved at lower level
            default_tiles.append((x, y, z))          # open the headroom above the ramp

    if default_tiles:
        await client.send_dig_command(TileDigDesignation.DEFAULT_DIG, default_tiles)
    if channel_tiles:
        await client.send_dig_command(TileDigDesignation.CHANNEL, channel_tiles)
    if ramp_tiles:
        await client.send_dig_command(TileDigDesignation.RAMP, ramp_tiles)
