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

## Snapshot workflow (dual-monitor gameplay)

The primary interaction pattern: DF runs on one monitor, a terminal runs on the other. `snapshot.py` is the entry point for reading and archiving game state.

### Running snapshot.py

Requires DF + DFHack running with a world loaded. **DF must not be paused** — DFHack's RPC server is unresponsive during most pause states.

```
python snapshot.py              # trigger quicksave, then dump current state
python snapshot.py --keep       # same, also archive to snapshots/ history
python snapshot.py --no-save    # dump without triggering a quicksave
python snapshot.py --watch      # poll save directory; archive each new season
```

### What snapshot.py does

`python snapshot.py` (one-shot with quicksave):
1. Prints `"Triggering quicksave..."` and issues `quicksave` via DFHack, then **closes the connection** so DF can write freely.
2. Polls `DF_SAVE_ROOT` mtime every second (up to 30s) until a newer file appears, printing `"Save detected, waiting for DF to finish cleanup..."`.
3. Sleeps 3 seconds to let DF finish post-save internal work.
4. Prints `"Reading game state..."`, opens a fresh DFHack connection, and reads world info, date, units, work details, and unmet needs.
5. Writes `snapshot.json` in the project root and prints a summary line like `[14:35:12] saved + snapshot — y100 summer — 43 units`.

`python snapshot.py --watch`:
- Polls `DF_SAVE_ROOT` every 5 seconds. When a mtime change is detected (autosave happened), dumps state and archives it as a seasonal snapshot if that season isn't already captured.

### Snapshot history format

Archives live under `snapshots/{save_dir}/`:
- **Seasonal autosaves**: `y{year}-{n}-{season}.json` where n=1 (spring), 2 (summer), 3 (autumn), 4 (winter). The numeric prefix ensures alphabetical = chronological ordering.
- **Manual snapshots**: `y{year}-{n}-{season}-manual-T{hhmmss}.json` — the `-manual-T...` suffix means they sort immediately after the corresponding autosave.

`Snapshot.list_history("region16")` returns all snapshots for a region sorted by `(year, season_num, is_manual)`.

### Running the connection test

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
- `_recv()` loops past `TEXT` notifications and has a **20-second** default timeout on `readexactly` (increased from 8s because the first RPC after a large save can be slow)
- `_drain()` wraps `writer.drain()` with a 5-second timeout (plain `drain()` can hang on Windows when a connection drops mid-flight)
- `disconnect()` uses `asyncio.wait_for(..., timeout=2.0)` on `wait_closed()` — needed because Windows `ProactorEventLoop` can block indefinitely otherwise
- Use as async context manager: `async with DFHackClient() as client:`

High-level methods on `DFHackClient`:

| Method | Returns | Notes |
|---|---|---|
| `get_version()` | `str` | DFHack version string |
| `get_df_version()` | `str` | DF version string |
| `run_command(cmd, *args)` | `None` | Runs a DFHack console command; returns `EmptyMessage` |
| `run_lua(module, fn, *args)` | `list[str]` | Calls `rpc.*` Lua function; results as strings |
| `get_game_date()` | `(year, season, tick)` | Via `rpc.date.get()`; season = "spring"/"summer"/"autumn"/"winter" |
| `get_world_info()` | proto | Raw `GetWorldInfoOut`; wrap with `WorldInfo.from_proto()` |
| `list_units(skills, labors)` | `list[proto]` | Always `scan_all=True`; filters client-side |
| `get_work_details()` | `list[str]` | Raw pipe-delimited strings; parse with `WorkDetail.from_raw()` |
| `get_unmet_needs()` | `list[(str,int,int)]` | `(need_name, dwarf_count, total_focus)` |
| `get_creature_raws()` | `dict[int, str]` | `{race_id: "CREATURE_ID"}` for all creature raws; via `rpc.creatures.all()` |
| `list_squads()` | `list[proto]` | Active squads |
| `send_dig_command(designation, locations)` | `None` | Set dig designations; `designation` is a `TileDigDesignation` int; `locations` is `list[(x,y,z)]`; plugin `RemoteFortressReader` |

### Known DFHack 53.14-r2 quirks

- **`RunLua` is restricted**: only modules matching `rpc.*`, `*.rpc`, or `*-rpc` may be called remotely. The `rpc.*` pattern (`hack\lua\rpc\name.lua`) is the only one that works reliably in practice — `*-rpc` is accepted by docs but rejected at runtime.
- **Server-side `ListUnits` filters hang**: passing `sane=True`, `alive=True`, or `dead=True` to `ListUnitsIn` causes DFHack's handler to never return. Always use `scan_all=True` and filter client-side. The `list_units()` wrapper handles this automatically.
- **RunLua error notifications cause a timeout hang**: if the Lua call fails (module not found, runtime error), DFHack sends a TEXT notification then never sends RESULT or FAIL, so `_recv` blocks until its timeout. Errors appear as `[DFHack] ...` lines. Wrap per-element enum access in `pcall` so a bad index never propagates as a Lua error.
- **`df.profession` enum iteration is unreliable**: `df.profession[i]` may error rather than return nil, triggering the hang above. Keep `rpc.enums.all_professions()` out of the critical path.
- **`RunCommand` output is `EmptyMessage`**: do not declare it with `IntMessage` or any other type — that causes a "Requested wrong signature for RPC method: ::RunCommand" error.
- **Post-quicksave reconnect needs a buffer**: after `quicksave` returns, DF writes a large save (~12 MB `world.sav`) asynchronously. Even after the save file mtime updates, DF may still be doing internal cleanup. `snapshot.py` waits for mtime change then sleeps an additional 3 seconds before reopening a connection. Skipping this buffer causes `GetWorldInfoOut` timeouts.

### Dig designations (Phase 2)

`send_dig_command(designation, locations)` sends `DigCommand` (package `RemoteFortressReader`) to the `SendDigCommand` RPC. Key behaviours confirmed by live testing:

- **Proto package matters**: `DigCommand` and `Coord` must be defined under `package = "RemoteFortressReader"`, not `dfproto`. The bind request sends the full type name; `dfproto.DigCommand` causes "Requested wrong signature for RPC method: RemoteFortressReader::SendDigCommand".
- **DF does not validate on receipt**: sending a designation to an already-open or otherwise invalid tile succeeds at the RPC level. DF places the designation briefly, then removes it with a cancellation notification as soon as a dwarf attempts to fulfil the job. No crash, no hang, no broken state — this is the game's normal job-cancellation path.
- **No pre-validation in the client**: pre-checking tile validity would require fetching map blocks via `GetBlockList` (one RPC per 16×16 block touched), which is expensive for large blueprints and redundant with what DF already does for free. The `commands/` layer should not add this check. The agent layer (Phase 3) can filter impossible targets using snapshot data already in memory before issuing commands.
- **`NO_DIG = 0` cancels a designation**: sending `NO_DIG` to a tile clears any existing dig order on it.
- **Multiple tiles, one call**: `locations` is a repeated field — batch all tiles of the same designation type into a single `send_dig_command` call rather than one call per tile.
- **Staircase convention**: for a vertical staircase from z_top down to z_bot, designate `DOWN_STAIR` at z_top, `UP_DOWN_STAIR` at each intermediate level, and `UP_STAIR` at z_bot. This creates a fully traversable connected stair.

`TileDigDesignation` IntEnum (in `proto_defs.py`): `NO_DIG=0`, `DEFAULT_DIG=1`, `UP_DOWN_STAIR=2`, `CHANNEL=3`, `RAMP=4`, `DOWN_STAIR=5`, `UP_STAIR=6`.

### `commands/` package (Phase 2)

High-level write operations built on `DFHackClient.send_dig_command`. All functions are `async` and accept a connected `DFHackClient` as their first argument. Callers are responsible for passing diggable coordinates; DF silently cancels invalid designations without crashing (see "Dig designations" above).

**`dig.py`** — Shape-level dig designations:

| Function | Signature | Notes |
|---|---|---|
| `dig_staircase` | `(client, x, y, z1, z2)` | Vertical staircase at (x,y). DOWN_STAIR at top, UP_DOWN_STAIR through middle, UP_STAIR at bottom. Single-tile case → UP_DOWN_STAIR. |
| `dig_rectangle` | `(client, designation, x1, y1, x2, y2, z)` | Filled rectangle at elevation z. Corner order normalised. All tiles sent in one RPC call. |
| `dig_slope` | `(client, x1, y1, z1, x2, y2, z2)` | 1-tile-wide sloped path. XY follows Bresenham; z changes are evenly distributed (see below). Raises `ValueError` if `|Δz| > max(|Δx|,|Δy|)`. |

**`dig_slope` internals:**
- `_bresenham(x1,y1,x2,y2)` — returns 1-tile-wide grid path; length = `max(|Δx|,|Δy|) + 1`.
- `_z_sequence(z1,z2,n)` — distributes `dz` z-changes across `n` tiles using a step-counter (`step = (n-1)//dz`). Fires every `step` tiles so all inter-rise gaps are equal; any leftover tile is absorbed into the trailing flat segment. Do **not** replace this with `round()`-based interpolation — Python's banker's rounding creates an oversized middle gap when the midpoint z falls exactly on a 0.5 boundary.
- Descent steps → `CHANNEL_DIG` at the upper z (DF auto-creates the ramp below).
- Ascent steps → `RAMP_DIG` at the lower z + `DEFAULT_DIG` at the upper z (headroom above the ramp must be explicitly dug).
- Flat steps → `DEFAULT_DIG`.
- All tiles of each designation type are batched into a single RPC call (at most 3 calls total).

### Adding a new RPC method

1. In `proto_defs.py`: add the request/response messages to the appropriate `_build_*()` function and export the classes at the bottom.
2. In `client.py`: add a typed wrapper method that calls `self.call(method_name, req, ResponseClass, plugin="PluginName")`.

### Adding a Lua RPC script

For game data not exposed by the protobuf API (e.g. unit personality needs, thoughts), write a Lua module and call it via `client.run_lua(module, function, *args)`.

**Rules learned from practice:**

- Place the script at `hack\lua\rpc\<name>.lua` and call it as module `rpc.<name>`.
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

### `gamestate/` package

Typed Python facade over raw DFHack RPC responses. The agent layer should never touch proto objects directly.

**`world.py`** — `WorldInfo` dataclass:
- Fields: `mode` (str: "DWARF"/"ADVENTURE"/"LEGENDS"), `world_name`, `save_dir`, `civ_id`, `site_id`, `group_id`, `race_id`
- `WorldInfo.from_proto(w)` — converts `GetWorldInfoOut` proto

**`units.py`** — `Unit` and related types:
- `UnitName(first, last, nickname, english)` — `.display()` → `"Firstname Lastname \"Nickname\" [English Translation]"`
- `Pos(x, y, z)` — X east, Y south (north = negative Y), Z = elevation up
- `UnitSkill(id, name, level, title, experience)`
- `UnitKind` enum — classification categories (see below)
- `Unit` dataclass — wraps all `BasicUnitInfo` fields plus:
  - `.kind(civ_id, race_id) -> UnitKind` — classify the unit
  - `.role_label(work_details, profession_names=None) -> str` — display-ready job label
  - `.decoded_skills() -> list[UnitSkill]` — sorted by level descending
  - `.decoded_labors() -> list[str]` — human-readable enabled labor names
  - `.from_proto(u)` — construct from `BasicUnitInfo` proto
  - Boolean properties: `is_ghost`, `is_killed`, `is_inactive`, `has_left_map`, `is_incoming`, `is_merchant`, `is_diplomat`, `is_active_invader`, `is_invader_origin`, `is_resident`, `is_on_ground`, `marked_for_slaughter`, `is_underworld`, `has_histfig`

`UnitKind` values: `CITIZEN`, `CIV_ANIMAL`, `CIV_OTHER`, `MERCHANT`, `DIPLOMAT`, `VISITOR`, `INVADER`, `WILD_CREATURE`, `NOTABLE_CREATURE`, `GHOST`, `DEAD`, `OFFMAP`

Note on `VISITOR`: currently catches foreign-civ sentients that aren't merchants/diplomats/invaders. Observed units with `is_resident=True` in this bucket appear to be underground-civ members at home (race 624, z=9–14). True surface visitors probably lack the resident flag — defer further classification until a confirmed surface visitor is observed.

**`creatures.py`** — `CreatureRaws` class for race ID → display name resolution:
- `CreatureRaws(raws: dict[int, str])` — wraps `{race_id: "CREATURE_ID"}` dict
- `.name(race_id) -> str` — returns display name (e.g. `572 → "Dwarf"`). Strips common DF category prefixes (`BIRD_`, `FISH_`, `REPTILE_`, `AMPHIBIAN_`, `VERMIN_`) before title-casing, so `BIRD_RAVEN → "Raven"`. Returns `"Unknown(N)"` for unrecognised IDs.
- `.raw_id(race_id) -> str | None` — returns the all-caps raw string (e.g. `"DWARF"`)
- `.from_dict(d)` / `.to_dict()` — round-trip through snapshot JSON (string keys ↔ int keys)
- Race IDs are world-specific and not stable across saves. `CreatureRaws` is populated once per snapshot via `get_creature_raws()`.

**`work_details.py`** — Work Details labor-group system:
- `WorkDetailMode` — `Default=0`, `EverybodyDoesThis=1`, `NobodyDoesThis=2`, `OnlySelectedDoesThis=3`
- `WorkDetail(name, mode, labor_ids, assigned_unit_ids)` — `.from_raw(pipe_string)` parses raw strings from `rpc.workdetails.all()`
- `effective_labors(unit_id, allowlist, work_details) -> list[int]` — computes actual effective labor set accounting for both layers

**`snapshot.py`** — Loads snapshot files into structured objects:
- `GameDate(year, season, tick)` — `__str__` → `"y100 summer (tick 153042)"`
- `HistoryEntry(year, season, label, path, is_manual)` — one archived snapshot
- `Snapshot` dataclass — top-level object:
  - `.snapshot_time: str`
  - `.game_date: GameDate | None`
  - `.world: WorldInfo`
  - `.units: list[Unit]`
  - `.work_details: list[WorkDetail]`
  - `.unmet_needs: list[tuple[str, int, int]]` — `(need_name, dwarf_count, total_focus)`
  - `.creature_raws: CreatureRaws` — race ID → species name; empty `CreatureRaws({})` for snapshots predating this field
  - `Snapshot.load(path=DEFAULT_PATH)` — load from `snapshot.json` or any path
  - `Snapshot.load_season(region, year, season)` — load archived `y{year}-{n}-{season}.json`
  - `Snapshot.list_history(region) -> list[HistoryEntry]` — all archives for a region, sorted chronologically
  - `.citizens() -> list[Unit]` — dwarven citizens only (alive, on-map, player civ and race)

`__init__.py` exports: `WorldInfo`, `Unit`, `UnitKind`, `UnitName`, `Pos`, `UnitSkill`, `WorkDetail`, `WorkDetailMode`, `effective_labors`, `CreatureRaws`, `Snapshot`, `GameDate`, `HistoryEntry`

### DF data conventions

- **Unit names** — `NameInfo` fields: `first_name` + `last_name` are Dwarvish stored lowercase; capitalize for display. `english_name` is the English translation of the full name. `nickname` is player-assigned.
- **Coordinates** — `(pos_x, pos_y, pos_z)`: X increases east, Y increases south (north is negative Y), Z = elevation (higher = closer to surface, lower = deeper underground).
- **Race IDs** — integer indices into the world's creature raws; not stable across worlds. Resolved via `Snapshot.creature_raws.name(race_id)` (populated by `rpc.creatures.all()` and stored in every snapshot). DF often prefixes raw IDs with a category (`BIRD_RAVEN`, `FISH_DARTER`); `CreatureRaws.name()` strips known prefixes automatically.
- **DF time** — 1 year = 403,200 ticks; 1 season = 100,800 ticks. Seasons by `cur_year_tick`: spring [0, 100800), summer [100800, 201600), autumn [201600, 302400), winter [302400, 403200).
- **Unit needs** — stored at `unit.status.current_soul.personality.needs[]`, not in `BasicUnitInfo`. Each need has `id` (maps to `df.need_type` enum string), `need_level` (how strongly the dwarf values it), and `focus_level` (satisfaction: positive = content, negative = unmet, more negative = more severe). Severity thresholds: ≥100 satisfied, <0 unmet, <-999 serious, <-9999 bad, <-99999 critical. Access via `rpc.needs`.
- **Unit skills** — `BasicUnitInfo.skills` is a repeated `SkillInfo` (id, level, experience). Request via `list_units(skills=True)`. Skill IDs map to names via `dfhack/enums.py SKILL_NAMES` (sourced from `df-structures/df.skill_enum.xml`).
- **Unit labors — two-layer system (DF 50.x)**:
  - Layer 1: `BasicUnitInfo.labors` — repeated int32 list of enabled labor IDs for that dwarf.
  - Layer 2: Work Details — group system that overrides the allowlist for covered labor IDs. Mode governs whether all/none/selected dwarves may do the labor.
  - Use `effective_labors(unit_id, allowlist, work_details)` to compute the true effective labor set.
  - Work Detail names default to plural in DF's UI ("Miners", "Woodcutters"). `_singularize()` in `gamestate/units.py` strips the trailing -s for role labels.
- **Unit role label** — `Unit.role_label(work_details, profession_names=None)`: priority is custom_profession → OnlySelectedDoesThis Work Details → DF profession name → "Generalist".
- **DF enum sources** — fetch from `https://github.com/DFHack/df-structures` using Python `httpx`. Key files: `df.skill_enum.xml` (job skills with captions), `df.plotinfo.xml` (Work Detail structures), `df.unit.xml`, `df.d_basics.xml` (large; may time out at 30s). Parse with `xml.etree.ElementTree`.

## Repository structure

```
dfparse/
├── dfhack/                   # Phase 1 — DFHack RPC client
│   ├── client.py             #   async TCP client
│   ├── proto_defs.py         #   protobuf message definitions (no protoc)
│   └── enums.py              #   skill/labor ID→name mappings (from df-structures)
│
├── gamestate/                # Phase 1 — structured game-state models
│   ├── __init__.py           #   re-exports all public types
│   ├── world.py              #   WorldInfo: world/fort info, civ, site
│   ├── units.py              #   Unit, UnitKind, UnitSkill, role_label()
│   ├── work_details.py       #   WorkDetail, WorkDetailMode, effective_labors()
│   ├── creatures.py          #   CreatureRaws: race_id → display name
│   └── snapshot.py           #   Snapshot, GameDate, HistoryEntry — load/query snapshots
│
├── commands/                 # Phase 2 — write-side dig operations
│   ├── __init__.py           #   re-exports all public functions
│   └── dig.py                #   dig_staircase, dig_rectangle, dig_slope
│
├── agent/                    # Phase 3 — LLM agent layer (planned)
│
├── narrative/                # Phase 4 — narrative interpretation (planned)
│
├── snapshot.py               # top-level: dump game state; --watch mode for auto-archiving
├── roster.py                 # human-readable unit roster from current snapshot (see below)
├── test_connection.py        # smoke-test: connect and print versions
├── check_census.py           # diagnostic: show sample units per UnitKind
├── inspect_visitors.py       # diagnostic: dump raw flags for all VISITOR units
└── query_needs.py            # diagnostic: print unmet needs sorted by severity
```

### `roster.py` — Human-readable unit roster

`python roster.py` loads the current `snapshot.json` and prints a structured summary. Sections:

1. **Fort Dwarves** — citizens sorted by first name; columns: display name, role label, top 2 skills with titles.
2. **Fort Animals** — named pets listed individually (species + name); unnamed animals grouped by species with counts.
3. **Enemies** — active/origin invaders. Currently always empty because no invasion has been validated against; the classification logic exists but is untested in practice.
4. **Friendly Visitors** — split into: Diplomats, Merchants (with top skill), Caravan animals (MERCHANT-flagged non-dwarves), Other visitors. Caravan guards (player-race, player-civ, no histfig) land here too.
5. **Wild & Miscellaneous** — alive wild creatures binned by elevation band (surface z≥160, mid-depth, deep), then Dead, then Other (off-map/ghost).

**Known gaps and TODO items:**

- **Per-dwarf needs** — The roster shows nothing about dwarf happiness. Unmet needs are captured in the snapshot as aggregate `(need_name, count, total_focus)` but not per-unit. Surfacing which specific dwarves have critical needs requires either splitting the Lua `rpc.needs` output per-unit or adding a new Lua query. This is high value for the agent.
- **Caravan guard label** — Guards (player-race, player-civ, `histfig_id=-1`) currently fall under "Other visitors" alongside foreign-civ entities like Olm Men. They should have a dedicated "Caravan guards" subsection.
- **Enemy validation** — The `INVADER` classification (`is_active_invader` / `is_invader_origin` flags) has not been tested against a real invasion. The section will show "none confirmed on map" until then.
- **Pet ownership** — We know pets belong to individual dwarves (e.g. Lokum owns the turkey) but that relationship is not in `BasicUnitInfo`. Exposing it would need a Lua RPC walking `df.global.world.items.all` or `unit.relationship_ids`. Currently named pets are identified heuristically (CIV_OTHER with a name).
- **Age display** — Puppies, calves, and poults all share their parent species' race ID. The roster can't distinguish ages without a Lua RPC comparing `unit.birth_year` to the current year. All dogs show as "Dog" regardless of age.
- **Species name adjective order** — DF raw names like `BIRD_PEAFOWL_BLUE` become "Peafowl Blue" after prefix-stripping and title-casing, but English convention would be "Blue Peafowl". Fixing this generally is hard; a small overrides dict for known species could handle the common cases.
- **Foreign-civ classification** — The 9 Olm Men (civ 182, z=114) fall under `UnitKind.VISITOR`. Whether they are neutral underground-civ residents or a threat is not yet determined. See the VISITOR note in `units.py`.

### Lua scripts installed in DF

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\hack\lua\rpc\`

| Script | Functions | Purpose |
|---|---|---|
| `needs.lua` | `get_unmet()` | Unmet needs across all citizens |
| `enums.lua` | `all_skills()`, `all_labors()`, `all_professions()` | Validate/generate enum ID→name mappings |
| `workdetails.lua` | `all()` | Read Work Details labor-group system |
| `date.lua` | `get()` | Current in-game year, season name, and tick-within-year |
| `creatures.lua` | `all()` | All creature raws as `"idx:CREATURE_ID"` strings; used to populate `CreatureRaws` |

The `gamestate/` layer acts as a typed Python facade over raw DFHack RPC responses. The `commands/` layer is the only place that issues writes to the game. The agent in `agent/` reads from `gamestate/` and writes through `commands/` only.

## DFHack installation

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\`  
DFHack files are under the `hack/` subdirectory. The `RemoteFortressReader.plug.dll` plugin provides the bulk of the game-state reading API.

## Save file location

Steam version (50.x) saves go to `C:\Users\kkado\AppData\Roaming\Bay 12 Games\Dwarf Fortress\save\`, **not** the game install directory (which has empty placeholder folders). The main save file is `world.sav` (~12 MB), accompanied by `unit-N.dat` files. The `current/` subdirectory is the live in-progress state; `autosave N/` and `regionN/` directories are autosave/backup snapshots. `snapshot.py` watches this directory for mtime changes to detect autosaves.

## Proto message reference

Official source: `https://github.com/DFHack/dfhack` — proto files are in `library/proto/` (core) and `plugins/remotefortressreader/proto/` (RFR). The proto files are not distributed as text in the Steam install; they must be fetched from GitHub or reconstructed from the DFHack docs. When adding new messages, fetch the raw file content via Python `httpx` (installed globally) rather than `curl` (SSL issues on this machine) or `WebFetch` (summarises rather than returning raw text).
