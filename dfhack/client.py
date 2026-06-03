"""
Async DFHack remote client.
Implements the DFHack RPC wire protocol: handshake + protobuf messages over TCP.
"""

import asyncio
import struct
from enum import IntEnum
from functools import wraps
from inspect import signature

from . import proto_defs as pb


class ReplyCode(IntEnum):
    RESULT      = -1
    FAIL        = -2
    TEXT        = -3
    QUIT        = -4


_HANDSHAKE_MAGIC_REQ  = b"DFHack?\n"
_HANDSHAKE_MAGIC_RESP = b"DFHack!\n"
_PROTO_VERSION = 1


def _encode_header(id_: int, size: int) -> bytes:
    return struct.pack("<hhi", id_, 0, size)


def _decode_header(data: bytes) -> tuple[int, int]:
    id_, _pad, size = struct.unpack("<hhi", data)
    return id_, size


class DFHackError(Exception):
    pass


class DFHackClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._method_cache: dict[str, int] = {}

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        # Send handshake
        req = _HANDSHAKE_MAGIC_REQ + struct.pack("<I", _PROTO_VERSION)
        self._writer.write(req)
        await self._writer.drain()
        # Read handshake response (12 bytes)
        resp = await self._reader.readexactly(12)
        magic = resp[:8]
        version = struct.unpack("<I", resp[8:12])[0]
        if magic != _HANDSHAKE_MAGIC_RESP or version != _PROTO_VERSION:
            raise DFHackError(f"Bad handshake: magic={magic!r}, version={version}")

    async def disconnect(self):
        if self._writer:
            try:
                self._writer.write(_encode_header(ReplyCode.QUIT, 0))
                await self._writer.drain()
            except Exception:
                pass
            self._writer.close()
            try:
                # wait_closed() can hang indefinitely on Windows ProactorEventLoop
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
            self._reader = None
            self._writer = None

    async def _drain(self) -> None:
        try:
            await asyncio.wait_for(self._writer.drain(), timeout=5.0)
        except asyncio.TimeoutError:
            raise DFHackError("Timed out flushing write buffer")

    async def _send(self, method_id: int, msg) -> None:
        payload = msg.SerializeToString()
        self._writer.write(_encode_header(method_id, len(payload)) + payload)
        await self._drain()

    async def _recv(self, response_class, timeout: float = 20.0):
        """Read one RPC reply, handling TEXT notifications along the way."""
        while True:
            try:
                header = await asyncio.wait_for(self._reader.readexactly(8), timeout=timeout)
            except asyncio.TimeoutError:
                raise DFHackError(f"Timed out waiting for {response_class.__name__} reply")
            id_, size = _decode_header(header)
            payload = await self._reader.readexactly(size) if size > 0 else b""

            if id_ == ReplyCode.TEXT:
                notif = pb.CoreTextNotification()
                notif.ParseFromString(payload)
                text = "".join(f.text for f in notif.fragments)
                print(f"[DFHack] {text}", end="")
                continue

            if id_ == ReplyCode.FAIL:
                if payload:
                    err = pb.CoreErrorNotification()
                    err.ParseFromString(payload)
                    raise DFHackError(f"RPC error: {err.code}")
                raise DFHackError("RPC call failed (no error detail)")

            if id_ == ReplyCode.RESULT:
                obj = response_class()
                if payload:
                    obj.ParseFromString(payload)
                return obj

            raise DFHackError(f"Unexpected reply id: {id_}")

    async def bind_method(self, method: str, input_class, output_class, plugin: str = "") -> int:
        cache_key = f"{plugin}::{method}"
        if cache_key in self._method_cache:
            return self._method_cache[cache_key]

        req = pb.CoreBindRequest()
        req.method = method
        req.input_msg = input_class.DESCRIPTOR.full_name
        req.output_msg = output_class.DESCRIPTOR.full_name
        if plugin:
            req.plugin = plugin

        payload = req.SerializeToString()
        self._writer.write(_encode_header(0, len(payload)) + payload)
        await self._drain()
        reply = await self._recv(pb.CoreBindReply)
        method_id = reply.assigned_id
        self._method_cache[cache_key] = method_id
        return method_id

    async def call(self, method: str, input_msg=None, output_class=None, plugin: str = ""):
        """Generic RPC call. input_msg defaults to EmptyMessage."""
        if input_msg is None:
            input_msg = pb.EmptyMessage()
        if output_class is None:
            output_class = pb.EmptyMessage

        method_id = await self.bind_method(
            method,
            type(input_msg),
            output_class,
            plugin=plugin,
        )
        await self._send(method_id, input_msg)
        return await self._recv(output_class)

    async def get_version(self) -> str:
        """Return the DFHack version string."""
        result = await self.call("GetVersion", output_class=pb.StringMessage)
        return result.value

    async def get_df_version(self) -> str:
        """Return the Dwarf Fortress version string."""
        result = await self.call("GetDFVersion", output_class=pb.StringMessage)
        return result.value

    async def run_command(self, command: str, *args: str) -> None:
        """Run a DFHack console command."""
        req = pb.CoreRunCommandRequest()
        req.command = command
        req.arguments.extend(args)
        await self.call("RunCommand", req, pb.EmptyMessage)

    async def run_lua(self, module: str, function: str, *args: str) -> list[str]:
        """Call a Lua function by module and name. Returns list of string results."""
        req = pb.CoreRunLuaRequest()
        req.module = module
        req.function = function
        req.args.extend(args)
        result = await self.call("RunLua", req, pb.StringListMessage)
        return list(result.value)

    async def get_game_date(self) -> tuple[int, str, int]:
        """Return (year, season, tick_within_year) for the current in-game date.

        season is one of: "spring", "summer", "autumn", "winter".
        Requires rpc/date.lua installed in hack/lua/rpc/.
        """
        results = await self.run_lua("rpc.date", "get")
        return int(results[0]), results[1], int(results[2])

    async def get_world_info(self):
        """Return basic world/fort information. Requires an active game."""
        return await self.call("GetWorldInfo", output_class=pb.GetWorldInfoOut)

    async def list_units(self, *, civ_id=None, race=None,
                         skills=False, labors=False, profession=False):
        """Return a list of BasicUnitInfo for all units.

        Server-side filters (sane/alive/dead) cause hangs in DFHack 53.14-r2,
        so we always fetch with scan_all=True and filter client-side.
        """
        req = pb.ListUnitsIn()
        req.scan_all = True
        if skills or labors or profession:
            req.mask.skills     = skills
            req.mask.labors     = labors
            req.mask.profession = profession
        result = await self.call("ListUnits", req, pb.ListUnitsOut)
        units = list(result.value)
        if civ_id is not None:
            units = [u for u in units if u.civ_id == civ_id]
        if race is not None:
            units = [u for u in units if u.race == race]
        return units

    async def get_work_details(self) -> list[str]:
        """Return raw work-detail strings from the Lua rpc.workdetails module.

        Each string has the format:
            "name|mode|labor_id,...|unit_id,..."
        where mode is: 0=Default 1=EverybodyDoesThis 2=NobodyDoesThis 3=OnlySelectedDoesThis
        Parse with gamestate.work_details.WorkDetail.from_raw().
        """
        return await self.run_lua("rpc.workdetails", "all")

    async def get_unmet_needs(self) -> list[tuple[str, int, int]]:
        """Return unmet needs across all citizens as (need_name, dwarf_count, total_focus).

        total_focus is the sum of focus_levels for that need (all negative);
        more negative = more urgently felt across the fort.
        Calls the needs-rpc Lua script installed in dfhack-config/scripts/.
        """
        raw = await self.run_lua("rpc.needs", "get_unmet")
        results = []
        for entry in raw:
            parts = entry.split(":")
            if len(parts) == 3:
                name, count, total = parts
                results.append((name, int(count), int(total)))
        return results

    async def get_creature_raws(self) -> dict[int, str]:
        """Return race_id -> creature_id (e.g. {572: 'DWARF'}) for all creature raws.

        Requires rpc/creatures.lua installed in hack/lua/rpc/.
        """
        raw = await self.run_lua("rpc.creatures", "all")
        result = {}
        for entry in raw:
            idx, _, name = entry.partition(":")
            if idx:
                result[int(idx)] = name
        return result

    async def list_squads(self):
        """Return a list of BasicSquadInfo for all active squads."""
        result = await self.call("ListSquads", pb.ListSquadsIn(), pb.ListSquadsOut)
        return list(result.value)

    async def send_dig_command(
        self,
        designation: int,
        locations: list[tuple[int, int, int]],
    ) -> None:
        """Designate tiles for digging. designation is a TileDigDesignation value.

        locations is a list of (x, y, z) tile coordinates. DF must not be paused.
        """
        req = pb.DigCommand()
        req.designation = int(designation)
        for x, y, z in locations:
            c = req.locations.add()
            c.x = x
            c.y = y
            c.z = z
        await self.call("SendDigCommand", req, pb.EmptyMessage, plugin="RemoteFortressReader")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.disconnect()
