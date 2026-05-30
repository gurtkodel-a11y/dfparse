# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project vision

Dwarf Fortress has a very steep learning curve because its interface requires memorizing menus, hotkeys, and game-specific concepts before a player can express intent. The goal of this project is to remove that barrier by building an agent that accepts plain English and translates it into in-game actions — "start brewing some ale", "assign the miners to dig out the eastern hall", "build a trade depot near the entrance" — without requiring the player to know where those options live in the UI.

The project has four loosely-ordered phases:

**Phase 1 — Game state reading (current)**  
Connect to a live DF session via DFHack's remote server and reliably read game state: world info, units, jobs, stockpiles, buildings, map tiles. Validate results against the running game. No writes yet.

**Phase 2 — Targeted writes**  
Issue commands that are legitimately available to the player: job queue modifications, workshop orders, labor assignments, zone designations, construction blueprints. All writes should be equivalent to something the player could do manually — no save-scumming or memory hacks.

**Phase 3 — Natural language agent**  
Build an LLM-backed agent layer that accepts ordinary language, maps it to game-state queries and Phase 2 write commands, and confirms results. The agent needs enough game-state context to reason about feasibility (e.g., "you don't have any brewable plants right now").

**Phase 4 — Multiplayer and narrative**  
Allow multiple human players to collaborate on a fort through the same agent interface. Separately, use the game's rich output of unit thoughts, moods, and actions as raw material for a narrative-interpretation layer.

Each phase builds on the previous one; Phase 1 output (game-state reading) is a direct dependency of every later phase.

## Environment

- Python 3.13, Windows 11
- The venv (`.venv/`) was created with `--system-site-packages` because pip has SSL/connectivity issues on this machine. **Do not try to `pip install` inside a Claude Code session** — flag missing packages to the user instead, and they will install via a workaround.
- Run scripts with: `python <script>.py` (uses global Python which has the packages)
- The venv Python is at `.venv/Scripts/python.exe` and inherits global site-packages

## Key dependencies

- `google-protobuf` (7.35.0) — installed globally
- No `protoc` or `grpcio-tools` available; proto messages are defined programmatically (see below)

## Running the connection test

Requires DF + DFHack running with a world loaded. DFHack's remote server listens on `localhost:5000` by default.

```
python test_connection.py
```

## Architecture

### `dfhack/` package

**`proto_defs.py`** — All protobuf message classes, built at import time using `google.protobuf.descriptor_pb2` + `message_factory.GetMessageClass`. This avoids needing `protoc`. Build functions must be called in dependency order at the bottom of the file. Currently defined:

- `_build_basic()` — `Basic.proto` shared types: `NameInfo`, `SkillInfo`, `BasicUnitInfo`, `BasicUnitInfoMask`, `BasicSquadInfo`, `UnitLaborState`, and supporting types. Must be called before `_build_basic_api()`.
- `_build_core_protocol()` — `CoreProtocol.proto`: bind/reply, run-command, run-lua, text/error notifications.
- `_build_basic_api()` — `BasicApi.proto`: `GetWorldInfoOut`, `ListUnitsIn/Out`, `ListSquadsIn/Out`.

Each DFHack API addition requires defining a new `FileDescriptorProto` block and calling `_pool.Add(fp)`. Messages live in the `dfproto` package namespace. Always verify enum field numbers against the actual proto source on GitHub (`library/proto/` for core, `plugins/remotefortressreader/proto/` for RFR) — guessed orderings have been wrong before (e.g. `GetWorldInfoOut.Mode`: `DWARF=1`, `ADVENTURE=2`, `LEGENDS=3`).

**`enums.py`** — Static ID→name mappings for DF enumerated types used in `BasicUnitInfo`:
- `SKILL_NAMES: dict[int, str]` — 137 entries (IDs 0–136), captions sourced directly from `df-structures/df.skill_enum.xml`. Do not guess these; fetch from the XML if adding entries. Notable: ALCHEMY does not exist in DF 50.x; the enum is denser than pre-Steam versions.
- `skill_title(level) -> str` — maps level 0→"Dabbling" through 15→"Legendary" and beyond.
- `LABOR_NAMES: dict[int, str]` — 94 entries (IDs 0–93). Best-effort; validate with `rpc.enums.all_labors()` against the live game.

**`client.py`** — `DFHackClient`: async TCP client over `asyncio`. Wire protocol:
- Handshake: `DFHack?\n` + little-endian int32 version → expect `DFHack!\n` + version
- Each message: 8-byte header (`int16 id`, `int16 pad=0`, `int32 payload_size`) + protobuf payload
- Special reply IDs: `RESULT=-1`, `FAIL=-2`, `TEXT=-3`, `QUIT=-4`
- Method binding (ID=0) must precede any call; bound IDs are cached in `_method_cache`
- `_recv()` loops past `TEXT` notifications and has an 8-second timeout on `readexactly`
- `_drain()` wraps `writer.drain()` with a 5-second timeout (plain `drain()` can hang on Windows when a connection drops mid-flight)
- `disconnect()` uses `asyncio.wait_for(..., timeout=2.0)` on `wait_closed()` — needed because Windows `ProactorEventLoop` can block indefinitely otherwise
- Use as async context manager: `async with DFHackClient() as client:`

### Known DFHack 53.14-r2 quirks

- **`RunLua` is restricted**: only modules matching `rpc.*`, `*.rpc`, or `*-rpc` may be called remotely. Use `GetVersion`/`GetDFVersion` (BasicApi) for version info instead.
- **Server-side `ListUnits` filters hang**: passing `sane=True`, `alive=True`, or `dead=True` to `ListUnitsIn` causes DFHack's handler to never return. Always use `scan_all=True` and filter client-side. The `list_units()` wrapper in `client.py` handles this automatically — callers just pass `civ_id=` or `race=` and filtering is done in Python after the response arrives.
- **RunLua error notifications cause an 8-second hang**: if the Lua call fails (module not found, runtime error), DFHack sends a TEXT notification with the error then never sends RESULT or FAIL, so `_recv` blocks until its timeout. Errors appear as `[DFHack] ...` lines in output. Wrap per-element enum access in `pcall` (see `rpc/enums.lua`) so a bad index never propagates as a Lua error.
- **`df.profession` enum iteration is unreliable**: `df.profession[i]` may error rather than return nil for some indices, causing the 8-second hang above. Keep `rpc.enums.all_professions()` out of the critical path; role labels work fine from `custom_profession` + Work Details alone.

### Adding a new RPC method

1. In `proto_defs.py`: add the request/response messages to the appropriate `_build_*()` function and export the classes at the bottom.
2. In `client.py`: add a typed wrapper method that calls `self.call(method_name, req, ResponseClass, plugin="PluginName")`.

### Adding a Lua RPC script

For game data not exposed by the protobuf API (e.g. unit personality needs, thoughts), write a Lua module and call it via `client.run_lua(module, function, *args)`.

**Rules learned from practice:**

- Use the `rpc.*` pattern — place the script at `hack\lua\rpc\<name>.lua` and call it as module `rpc.<name>`. The `*-rpc` pattern (e.g. `needs-rpc`) is accepted by the docs but rejected at runtime in 53.14-r2; `rpc.*` works reliably.
- The script **must be a Lua module** (returns a table of functions), not a bare script. DFHack calls a named function within it.
- Return values come back as a `StringListMessage` (list of strings). Encode structured data as delimited strings (e.g. `"NeedName:count:total_focus"`) and parse in Python.
- `dfhack-config\scripts\` is **not** on Lua's module search path; `hack\lua\` is. Put modules in `hack\lua\`.
- **Wrap enum iteration in `pcall`**: iterating `df.some_enum[i]` can throw instead of returning nil. Always guard per-element access: `local ok, name = pcall(function() return e[i] end)`. See `rpc/enums.lua` for the pattern.

Example skeleton (`hack\lua\rpc\myquery.lua`):
```lua
local M = {}
function M.run()
    local result = {}
    -- ... populate result ...
    return table.unpack(result)
end
return M
```
Called from Python as: `await client.run_lua("rpc.myquery", "run")`

### DFHack plugin namespacing

Methods from the core (`GetWorldInfo`, `GetVersion`, `RunCommand`, `RunLua`) use `plugin=""`. Methods from `RemoteFortressReader` use `plugin="RemoteFortressReader"`. The plugin name goes into `CoreBindRequest.plugin`.

### DF data conventions

- **Unit names** — `NameInfo` fields: `first_name` + `last_name` are the in-language (Dwarvish) name stored in lowercase; capitalize for display. `english_name` is the English translation of the full name. `nickname` is an optional player-assigned nickname. Display order: `Firstname Lastname "Nickname" [English Translation]`.
- **Coordinates** — `(pos_x, pos_y, pos_z)`: X increases east, Y increases south (north is negative Y), Z = elevation (higher = closer to surface, lower = deeper underground).
- **Race IDs** — integer indices into the world's creature raws; not stable across worlds. Must resolve via creature raw lookup to get a name like "DWARF".
- **Unit needs** — stored at `unit.status.current_soul.personality.needs[]`, not in `BasicUnitInfo`. Each need has `id` (maps to `df.need_type` enum string), `need_level` (how strongly the dwarf values it), and `focus_level` (satisfaction: positive = content, negative = unmet, more negative = more severe). Severity thresholds from DFHack's `allneeds.lua`: ≥100 satisfied, <0 unmet, <-999 serious, <-9999 bad, <-99999 critical. Access via the `rpc.needs` Lua module (`hack\lua\rpc\needs.lua`).
- **Unit skills** — `BasicUnitInfo.skills` is a repeated `SkillInfo` (id, level, experience). Request via `list_units(skills=True)`. Decode with `Unit.decoded_skills()` → `list[UnitSkill]` sorted by level descending. Skill IDs map to names via `dfhack/enums.py SKILL_NAMES` (sourced from `df-structures/df.skill_enum.xml`).
- **Unit labors — two-layer system (DF 50.x)**:
  - Layer 1: `BasicUnitInfo.labors` — repeated int32 list of enabled labor IDs for that dwarf (the old per-dwarf allowlist). Request via `list_units(labors=True)`.
  - Layer 2: Work Details — `df.global.plotinfo.labor_info.work_details[]`, a DF 50.x group system that overrides the allowlist. Each Work Detail has a `name`, `flags.mode` (Default=0, EverybodyDoesThis=1, NobodyDoesThis=2, OnlySelectedDoesThis=3), `allowed_labors[94]` (bool array indexed by labor ID), and `assigned_units[]` (unit IDs). Read via `rpc.workdetails.all()` → `gamestate.work_details.WorkDetail`.
  - Use `gamestate.work_details.effective_labors(unit_id, allowlist, work_details)` to compute the true effective labor set that accounts for both layers.
  - Work Detail names default to plural in DF's UI ("Miners", "Woodcutters"). Use `_singularize()` in `gamestate/units.py` when displaying them as individual role labels.
- **Unit role label** — `Unit.role_label(work_details, profession_names=None)`: priority is custom_profession → OnlySelectedDoesThis Work Details the unit is assigned to → DF profession name → "Generalist".
- **DF enum sources** — fetch from `https://github.com/DFHack/df-structures` using Python `httpx`. Key files: `df.skill_enum.xml` (job skills with captions), `df.plotinfo.xml` (Work Detail structures), `df.unit.xml`, `df.d_basics.xml` (large; may time out at 30s). Parse with `xml.etree.ElementTree`.

## Repository structure

```
fortexpl/
├── dfhack/                   # Phase 1 — DFHack RPC client
│   ├── client.py             #   async TCP client
│   ├── proto_defs.py         #   protobuf message definitions (no protoc)
│   └── enums.py              #   skill/labor ID→name mappings (from df-structures)
│
├── gamestate/                # Phase 1 — structured game-state models
│   ├── world.py              #   WorldInfo: world/fort info, civ, site
│   ├── units.py              #   Unit, UnitKind, UnitSkill, role_label()
│   ├── work_details.py       #   WorkDetail, WorkDetailMode, effective_labors()
│   ├── jobs.py               #   (planned) job queues, workshop orders
│   ├── map.py                #   (planned) tiles, zones, designations
│   └── buildings.py          #   (planned) workshops, stockpiles, constructions
│
├── commands/                 # Phase 2 — write-side operations (planned)
│   ├── labor.py
│   ├── jobs.py
│   ├── designations.py
│   └── build.py
│
├── agent/                    # Phase 3 — LLM agent layer (planned)
│   ├── agent.py
│   ├── tools.py
│   ├── context.py
│   └── prompts.py
│
├── narrative/                # Phase 4 — narrative interpretation (planned)
│   └── interpreter.py
│
└── test_connection.py        # Phase 1 smoke-test
```

### Lua scripts installed in DF

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\hack\lua\rpc\`

| Script | Functions | Purpose |
|---|---|---|
| `needs.lua` | `get_unmet()` | Unmet needs across all citizens |
| `enums.lua` | `all_skills()`, `all_labors()`, `all_professions()` | Validate/generate enum ID→name mappings |
| `workdetails.lua` | `all()` | Read Work Details labor-group system |

The `gamestate/` layer acts as a typed Python facade over raw DFHack RPC responses, so that the agent layer never touches proto objects directly. The `commands/` layer is the only place that issues writes to the game. The agent in `agent/` reads from `gamestate/` and writes through `commands/` only.

## DFHack installation

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\`  
DFHack files are under the `hack/` subdirectory. The `RemoteFortressReader.plug.dll` plugin provides the bulk of the game-state reading API.

## Proto message reference

Official source: `https://github.com/DFHack/dfhack` — proto files are in `library/proto/` (core) and `plugins/remotefortressreader/proto/` (RFR). The proto files are not distributed as text in the Steam install; they must be fetched from GitHub or reconstructed from the DFHack docs. When adding new messages, fetch the raw file content via Python `httpx` (installed globally) rather than `curl` (SSL issues on this machine) or `WebFetch` (summarises rather than returning raw text).
