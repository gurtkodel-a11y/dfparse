# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project vision

Dwarf Fortress has a very steep learning curve because its interface requires memorizing menus, hotkeys, and game-specific concepts before a player can express intent. The goal of this project is to remove that barrier by building an agent that accepts plain English and translates it into in-game actions — "start brewing some ale", "assign the miners to dig out the eastern hall", "build a trade depot near the entrance" — without requiring the player to know where those options live in the UI.

The project has four loosely-ordered phases:

**Phase 1 — Game state reading (complete)**  
Connect to a live DF session via DFHack's remote server and reliably read game state: world info, units, jobs, stockpiles, buildings, nobles, stocks, map tiles. Map tile reading (GetBlockList, tiletype resolution, water/magma overlays) is fully implemented via Spyglass; tile data is cached to `snapshot_tiles.json` and viewable offline via `snapshot_view.py`.

**Phase 2 — Targeted writes (active)**  
Issue commands that are legitimately available to the player: job queue modifications, workshop orders, labor assignments, zone designations, construction blueprints. Dig commands (staircase, rectangle, slope, hillside shear) are implemented. All writes should be equivalent to something the player could do manually — no save-scumming or memory hacks.

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
- `anthropic` — installed globally; required only for `SpyglassEvaluator` (self-evaluation loop). Spyglass itself works without it.
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
4. Prints `"Reading game state..."`, opens a fresh DFHack connection, and reads world info, date, units, map tiles, work details, unmet needs, creature raws, and buildings.
5. Writes `snapshot.json` in the project root and prints a summary line like `[14:35:12] saved + snapshot — y100 summer — 43 units — 1204 tile blocks — 87 buildings`.

`python snapshot.py --watch`:
- Polls `DF_SAVE_ROOT` every 5 seconds. When a mtime change is detected (autosave happened), dumps state and archives it as a seasonal snapshot if that season isn't already captured.

### Snapshot history format

Archives live under `snapshots/{save_dir}/`:
- **Seasonal autosaves**: `y{year}-{n}-{season}.json` where n=1 (spring), 2 (summer), 3 (autumn), 4 (winter). The numeric prefix ensures alphabetical = chronological ordering.
- **Manual snapshots**: `y{year}-{n}-{season}-manual-T{hhmmss}.json` — the `-manual-T...` suffix means they sort immediately after the corresponding autosave.

`Snapshot.list_history("region16")` returns all snapshots for a region sorted by `(year, season_num, is_manual)`.

### Running the connection test

```
python archive/test_connection.py
```

## Architecture

### `dfhack/` package

**`proto_defs.py`** — All protobuf message classes, built at import time using `google.protobuf.descriptor_pb2` + `message_factory.GetMessageClass`. This avoids needing `protoc`. Build functions must be called in dependency order at the bottom of the file. Currently defined:

- `_build_basic()` — `Basic.proto` shared types: `NameInfo`, `SkillInfo`, `BasicUnitInfo`, `BasicUnitInfoMask`, `BasicSquadInfo`, `UnitLaborState`, and supporting types. Must be called before `_build_basic_api()`.
- `_build_core_protocol()` — `CoreProtocol.proto`: bind/reply, run-command, run-lua, text/error notifications.
- `_build_basic_api()` — `BasicApi.proto`: `GetWorldInfoOut`, `ListUnitsIn/Out`, `ListSquadsIn/Out`.
- `_build_rfr_dig()` — `RFRDig.proto` (package `RemoteFortressReader`): `TileDigDesignation` enum, `Coord`, `DigCommand`. Used by `SendDigCommand`.
- `_build_rfr_map()` — `RFRMap.proto` (package `RemoteFortressReader`): `TiletypeShape/Special/Material/Variant` enums, `Tiletype`, `TiletypeList`, `BlockRequest`, `MapBlock`, `BlockList`, `MapInfo`. Used by `GetTiletypeList`, `GetBlockList`, `GetMapInfo`.

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
| `get_buildings()` | `list[str]` | Raw pipe-delimited strings for all non-construction buildings; parse with `Building.from_raw()`. Via `rpc.buildings.all()`. |
| `get_nobles()` | `list[str]` | Noble assignments + bookkeeper/manager state; parse with `NoblesReport.from_raw()`. Via `rpc.nobles.all()`. |
| `get_noble_positions()` | `list[str]` | All defined noble position slots including vacant ones (`"pos\|CODE\|name\|id"`). Via `rpc.nobles.positions()`. |
| `get_stocks()` | `list[str]` | Item counts + bookkeeper precision metadata; parse with `StockReport.from_raw()`. Via `rpc.stocks.all()`. |
| `list_squads()` | `list[proto]` | Active squads |
| `send_dig_command(designation, locations)` | `None` | Set dig designations; `designation` is a `TileDigDesignation` int; `locations` is `list[(x,y,z)]`; plugin `RemoteFortressReader` |
| `reset_map_hashes()` | `None` | Force RFR to mark all blocks dirty; call before `get_block_list` (done automatically by the wrapper) |
| `get_map_info()` | proto | `MapInfo`: `block_size_x/y/z` (block counts), `block_pos_x/y/z` (world region origin); plugin `RemoteFortressReader` |
| `get_tiletype_list()` | `list[proto]` | All `Tiletype` descriptors: `id`, `shape` (TiletypeShape), `material`, `special`, `name`. Used to resolve tile IDs in MapBlock.tiles. |
| `get_block_list(min_x,max_x,min_y,max_y,min_z,max_z)` | `list[proto]` | `MapBlock` objects for the region. x/y in block coords (inclusive); z in tile z-level (inclusive). Calls `reset_map_hashes` first. |

### Known DFHack 53.14-r2 quirks

- **`RunLua` is restricted**: only modules matching `rpc.*`, `*.rpc`, or `*-rpc` may be called remotely. The `rpc.*` pattern (`hack\lua\rpc\name.lua`) is the only one that works reliably in practice — `*-rpc` is accepted by docs but rejected at runtime.
- **Server-side `ListUnits` filters hang**: passing `sane=True`, `alive=True`, or `dead=True` to `ListUnitsIn` causes DFHack's handler to never return. Always use `scan_all=True` and filter client-side. The `list_units()` wrapper handles this automatically.
- **RunLua error notifications cause a timeout hang**: if the Lua call fails (module not found, runtime error), DFHack sends a TEXT notification then never sends RESULT or FAIL, so `_recv` blocks until its timeout. Errors appear as `[DFHack] ...` lines. Wrap per-element enum access in `pcall` so a bad index never propagates as a Lua error.
- **`df.profession` enum iteration is unreliable**: `df.profession[i]` may error rather than return nil, triggering the hang above. Keep `rpc.enums.all_professions()` out of the critical path.
- **`RunCommand` output is `EmptyMessage`**: do not declare it with `IntMessage` or any other type — that causes a "Requested wrong signature for RPC method: ::RunCommand" error.
- **Post-quicksave reconnect needs a buffer**: after `quicksave` returns, DF writes a large save (~12 MB `world.sav`) asynchronously. Even after the save file mtime updates, DF may still be doing internal cleanup. `snapshot.py` waits for mtime change then sleeps an additional 3 seconds before reopening a connection. Skipping this buffer causes `GetWorldInfoOut` timeouts.
- **`GetBlockList` uses exclusive upper bounds on all axes**: the plugin iterates `for (x = min_x; x < max_x; ...)` — passing `min_x = max_x = N` yields zero blocks. The `get_block_list()` wrapper adds +1 to all max parameters so callers can use natural inclusive ranges. Requesting a single z-level as `min_z=max_z=167` is valid from the Python side; the wire message will have `max_z=168`.
- **`MapBlock.map_x`/`map_y` are tile coordinates, not block coordinates**: the server returns the tile-level origin of each block (e.g. block (8,9) → `map_x=128, map_y=144`). Do NOT multiply by 16 when computing tile positions within the block. `BlockRequest` min/max x/y fields, by contrast, use block coordinates.
- **`GetBlockList` block hash caching persists across connections**: the RFR plugin tracks per-block SHA256 hashes and skips blocks whose content hasn't changed since the last client call. Hash state survives client disconnects. `get_block_list()` calls `ResetMapHashes` before every fetch to force all blocks dirty. Some z-levels near the top and bottom of the map are absent entirely — they are legitimately unloaded (sky void or deep underground not near any activity).

### Map tile reading (Phase 1)

`get_map_info()` → `get_tiletype_list()` → `get_block_list(...)` is the standard sequence for reading terrain. All three share a single `DFHackClient` connection; do not split them across connections (hash state would be reset again mid-flight).

**Coordinate systems:**
- `BlockRequest` min/max x/y: block coordinates (1 block = 16 tiles). `get_block_list()` wrapper accepts inclusive bounds and adds +1 internally for DFHack's exclusive loop.
- `MapBlock.map_x/map_y`: tile coordinates of the block's origin (e.g. block 8 → map_x=128). Do NOT multiply by 16.
- `MapBlock.map_z`: tile z-level (same as unit `pos_z`).
- Tile index within a block: `i = lx + ly * 16` where lx = i%16 (x offset), ly = i//16 (y offset).

**MapBlock fields decoded:**
- `tiles` (repeated int32, 256): tiletype IDs — look up in `{tt.id: shape}` dict built from `get_tiletype_list()`.
- `water` (repeated int32, 256): water depth per tile (0 = dry, 1–7 = depth). Overlay `~` wherever > 0.
- `magma` (repeated int32, 256): magma depth per tile. Overlay `*` wherever > 0.
- `hidden` (repeated bool, 256): True = tile not yet explored by the player (fog of war). Fields beyond the list length default to False.
- Fields 5–8 (material arrays) are omitted from the proto definition; protobuf skips unknown fields silently.

**TiletypeShape values used for rendering** (Python IntEnum `TiletypeShape` in `proto_defs.py`):
`EMPTY=0` (sky/open air), `FLOOR=1`, `WALL=4`, `STAIR_UP=6`, `STAIR_DOWN=7`, `STAIR_UPDOWN=8`, `RAMP=9`, `RAMP_TOP=10`, `BROOK_BED=11`, `BROOK_TOP=12`, `TREE_SHAPE=13`. Water/magma depth fields override shape glyphs.

**Performance:** a single z-level of a 12×12-block map is ~144 blocks. Full-map scans across all z-levels can hit protobuf reply-size limits; fetch one or a few z-levels at a time. The `blocks_needed` parameter caps how many blocks DFHack returns per call (default 50000, safe for single-z scans).

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

**`terrain.py`** — Terrain-aware dig commands (require a live Spyglass query to determine what to dig):

| Function | Signature | Notes |
|---|---|---|
| `dig_shear_hillside` | `(client, x1, y1, x2, y2, z_min, z_max, *, glass, dry_run=False)` | CHANNEL every surface tile in the rectangle; see below |

**`dig_shear_hillside` details:**
- Queries all tiles in `[x1..x2, y1..y2, z_min..z_max]` via Spyglass, then for each `(x, y)` column scans downward from `z_max` to find the topmost non-air tile (skipping `EMPTY`, `RAMP_TOP`, floating branch/twig shapes).
- Issues a single `CHANNEL` batch RPC covering all found surface tiles. CHANNEL lowers a floor by one z-level (creates a ramp below, opens the tile above), so applying it across an irregular hillside drops the whole surface by one level regardless of current elevation variation.
- Skips columns where the surface tile is: `hidden` (unexplored), has `water`/`magma` depth > 0, or is a tree/shrub shape. Reports skip counts in the return dict.
- Returns `{"designated", "skipped_hidden", "skipped_fluid", "skipped_veg", "skipped_empty", "by_z", "plan"}`. `by_z` is a `{z: count}` breakdown; `plan` is the full coordinate list (set even in `dry_run` mode for inspection).
- Set `z_min` safely below the hill base and `z_max` above the hilltop — the scan handles uneven terrain automatically. Call `glass.invalidate(x1,y1,z_min, x2,y2,z_max)` after issuing to clear stale cache.

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

**`buildings.py`** — `Building` dataclass for placed buildings:
- Fields: `id`, `type_id`, `type_name` (e.g. `"Workshop"`, `"Furnace"`, `"Stockpile"`, `"Civzone"`, `"Door"`), `subtype_id`, `subtype_name` (e.g. `"Craftsdwarf"`, `"Smelter"`, `"Bedroom"`), `x1/y1/z/x2/y2`, `build_stage`, `max_stage`
- Properties: `is_complete` (true when `build_stage >= max_stage` or `max_stage == 0`), `cx/cy` (centre tile), `width/height`
- `display_name()` → `"Workshop (Craftsdwarf)"` or `"Door"` (type alone when no subtype)
- `Building.from_raw(s)` — parse pipe-delimited string from `rpc.buildings.all()`
- `Building.to_dict()` / `Building.from_dict(d)` — round-trip through snapshot JSON
- **Wire format** (12 pipe-delimited fields): `id|btype_int|btype_str|subtype_int|subtype_str|x1|y1|z|x2|y2|build_stage|max_stage`
- Player-built constructions (walls, floors, stairs) are **excluded** — they are already captured as tile data with `TiletypeMaterial.CONSTRUCTION`.

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

**`stocks.py`** — Live item inventory with bookkeeper precision simulation:
- `BookkeeperState(precision, cooldown)` — raw values from `df.global.plotinfo.current.nobles`; `precision` is 0–4 (verified range TBD), `cooldown` is 0–1008 ticks. `.label()` returns a human-readable description.
- `StockEntry(item_type, count)` — aggregate count for one item type; `.fuzzy(precision)` rounds to the nearest bucket.
- `StockDetail(item_type, material, count)` — per-material breakdown for consumable types (FOOD, DRINK, PLANT, SEEDS, MEAT, FISH, CHEESE, EGG).
- `StockReport(bookkeeper, entries, details)` — top-level container:
  - `.by_type(item_type) -> int` — exact total
  - `.fuzzy_by_type(item_type) -> int` — precision-rounded total (simulates game UI)
  - `.material_breakdown(item_type, fuzzy=False) -> dict[str, int]` — per-material counts, sorted descending
  - `.summary(fuzzy=False) -> dict[str, int]` — all types → count, sorted descending
  - `.from_raw(lines)` — parse output of `get_stocks()`
- **Precision fuzz buckets** (in `_BUCKET`, tune after live testing): 0→100, 1→50, 2→20, 3→10, 4→5, 5→1 (exact). These are estimates; verify against the in-game Stocks screen once DF is running.
- Items with `flags.garbage_collect` or `flags.forbid` are excluded. Caravan goods are **not** filtered separately — a visiting caravan's items will appear in counts; callers should be aware of this when a caravan is present.

**`nobles.py`** — Fort noble assignments and administrator state:
- `NoblePosition(code, name, position_id, histfig_id, unit_id, unit_name)` — one filled noble slot:
  - `code` — raw token, e.g. `"BOOKKEEPER"`, `"MAYOR"`, `"MANAGER"`, `"CHIEF_MEDICAL_DWARF"`, `"SHERIFF"`
  - `name` — display name from the position definition, e.g. `"Bookkeeper"`
  - `histfig_id` — -1 if vacant; `unit_id` — -1 if off-map or vacant
  - `.is_filled()`, `.is_on_map()`, `.display()` — convenience properties/method
- `NoblesReport(positions, bookkeeper_precision, bookkeeper_cooldown, bookkeeper_settings, manager_cooldown)`:
  - `.by_code(code) -> NoblePosition | None` — find by position token
  - `.bookkeeper()`, `.manager()`, `.mayor()`, `.chief_medical_dwarf()`, `.sheriff()` — typed lookups
  - `.bookkeeper_precision_label() -> str` — human-readable precision description
  - `.summary() -> str` — one line per filled position
  - `.from_raw(lines)` — parse output of `get_nobles()`
  - `.errors` — list of error strings from Lua (useful when field paths fail during development)
- **Nobles data paths** (confirmed from `df.entity.xml` and `df.plotinfo.xml`):
  - Bookkeeper state: `df.global.plotinfo.current.nobles.bookkeeper_precision / bookkeeper_cooldown / bookkeeper_settings`; manager: `current.nobles.manager_cooldown` (range 0–1008 ticks for both cooldowns).
  - Fortress entity: `df.global.plotinfo.current.fortress_entity` (direct pointer to `historical_entity`).
  - Position definitions: `entity.positions.own[]` — each has `.code` (token) and `.name[0]` (singular display name, static-array[2]).
  - Assignments: `entity.positions.assignments[]` — each has `.position_id` (links to definition `.id`), `.histfig` (holder histfig ID, -1 if vacant).
  - Unit resolution: `df.histfig.find(hfid)` → `.unit_id` → `df.unit.find(uid)`.
- **Pending live verification**: position field names (`positions.own`, `positions.assignments`), whether `pos.name[0]` is the right index for the display name, and whether `histfig == -1` is the correct sentinel for a vacant slot. Run `python diag/diag_nobles.py` with DF live to confirm or correct.

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
  - `.buildings: list[Building]` — all placed non-construction buildings; `[]` for snapshots predating this field
  - `Snapshot.load(path=DEFAULT_PATH)` — load from `snapshot.json` or any path
  - `Snapshot.load_season(region, year, season)` — load archived `y{year}-{n}-{season}.json`
  - `Snapshot.list_history(region) -> list[HistoryEntry]` — all archives for a region, sorted chronologically
  - `.citizens() -> list[Unit]` — dwarven citizens only (alive, on-map, player civ and race)
  - `.workshops() -> list[Building]` — completed workshops (type_name == "Workshop")
  - `.furnaces() -> list[Building]` — completed furnaces (type_name == "Furnace")
  - `.stockpiles() -> list[Building]` — all stockpile zones (type_name == "Stockpile")
  - `.zones() -> list[Building]` — all activity zones (type_name == "Civzone")
  - `.buildings_by_type(type_name) -> list[Building]` — filter by any type string

`__init__.py` exports: `Building`, `WorldInfo`, `Unit`, `UnitKind`, `UnitName`, `Pos`, `UnitSkill`, `WorkDetail`, `WorkDetailMode`, `effective_labors`, `CreatureRaws`, `Snapshot`, `GameDate`, `HistoryEntry`, `StockReport`, `StockEntry`, `StockDetail`, `BookkeeperState`, `NoblesReport`, `NoblePosition`

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
- **Bookkeeper precision** — `df.global.plotinfo.current.nobles.bookkeeper_precision` is an int (0–4 probable range; not yet verified against live game) representing the currently-achieved record-keeping quality. `bookkeeper_settings` is the player's target precision (the enum `record_precision_level_type`). `bookkeeper_cooldown` (0–1008 ticks) counts down as the bookkeeper works; when it reaches 0 the precision is refreshed. The game's Stocks screen rounds displayed counts based on `bookkeeper_precision` — `StockReport.summary(fuzzy=True)` simulates this using the `_BUCKET` table in `gamestate/stocks.py`. **Fuzz bucket values have not yet been validated against the live game UI; calibrate by comparing `fuzzy=True` output with what the in-game Stocks screen shows.**
- **Nobles mechanic** — Noble positions are part of the fortress entity (`df.global.plotinfo.current.fortress_entity`, a `historical_entity`). Each entity has `positions.own[]` (position definitions, with `.code` token and `.name[0]` display name) and `positions.assignments[]` (who holds each position, linking via `position_id` and holder `histfig`). The manager's job-processing frequency is governed by `current.nobles.manager_cooldown` (0–1008 ticks). Noble positions at a 7-dwarf embark-scale fort typically include: Mayor, Manager, Bookkeeper, Chief Medical Dwarf. Positions exist as definitions even when vacant — use `get_noble_positions()` to see all defined slots.
- **DF enum sources** — fetch from `https://github.com/DFHack/df-structures` using Python `httpx`. Key files: `df.skill_enum.xml` (job skills with captions), `df.plotinfo.xml` (Work Detail structures, bookkeeper/nobles fields), `df.entity.xml` (noble position structures), `df.unit.xml`, `df.d_basics.xml` (large; may time out at 30s). Parse with `xml.etree.ElementTree`.

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
│   ├── buildings.py          #   Building: placed buildings (workshops, stockpiles, zones, etc.)
│   ├── stocks.py             #   StockReport: live item inventory with bookkeeper precision fuzz
│   ├── nobles.py             #   NoblesReport: noble assignments, bookkeeper/manager state
│   └── snapshot.py           #   Snapshot, GameDate, HistoryEntry — load/query snapshots
│
├── commands/                 # Phase 2 — write-side dig operations
│   ├── __init__.py           #   re-exports all public functions
│   ├── dig.py                #   dig_staircase, dig_rectangle, dig_slope
│   └── terrain.py            #   dig_shear_hillside (terrain-aware; requires Spyglass)
│
├── agent/                    # Phase 3 — LLM agent layer
│   ├── __init__.py           #   re-exports Spyglass + evaluator public API
│   ├── spyglass.py           #   Spyglass: tunable live map query tool (see below)
│   ├── evaluate.py           #   SpyglassEvaluator: self-evaluation loop (see below)
│   ├── spyglass_settings.json  # persisted SpyglassSettings (auto-created on first save)
│   ├── spyglass_log.jsonl    #   append-only usage log (one JSON line per call)
│   └── spyglass_evals.jsonl  #   append-only evaluation records (inner monologue + settings changes)
│
├── narrative/                # Phase 4 — narrative interpretation (planned)
│
├── diag/                     # diagnostic scripts (run against a live game to probe subsystems)
│   ├── diag_map.py           #   probe block/tiletype/hidden data from GetBlockList
│   ├── diag_nobles.py        #   dump raw + parsed noble assignments from rpc.nobles
│   ├── check_census.py       #   show sample units per UnitKind
│   ├── inspect_visitors.py   #   dump raw flags for all VISITOR units
│   └── query_needs.py        #   print unmet needs sorted by severity
│
├── archive/                  # historical exploratory scripts (see archive/INDEX.md)
│   └── INDEX.md              #   table of contents + what each script proved
│
├── snapshots/                # seasonal game-state archives (gitignored contents; dir tracked)
│   └── .gitkeep
│
├── snapshot.py               # top-level: dump game state; --watch mode for auto-archiving
├── snapshot_view.py          # offline ASCII terrain viewer: reads snapshot_tiles.json (see below)
├── roster.py                 # human-readable unit roster from current snapshot (see below)
└── shear.py                  # CLI driver for dig_shear_hillside (see below)
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

### `agent/spyglass.py` — Spyglass map query tool

Spyglass is the agent's primary interface to live tile data. It wraps `get_block_list` with a Python-side LRU block cache, configurable prefetch padding, and structured usage logging intended for agent self-evaluation.

**Creating an instance** (async factory; loads map metadata on construction):
```python
async with DFHackClient() as client:
    glass = await Spyglass.create(client)
```

**Query methods** (all async):

| Method | Returns | Notes |
|---|---|---|
| `fetch_region(x1,y1,z1,x2,y2,z2)` | `None` | Explicitly warm cache for a tile volume |
| `tile_at(x,y,z)` | `TileData \| None` | Single tile; lazy-fetches block if needed (when `lazy=True`) |
| `tiles_in_volume(x1,y1,z1,x2,y2,z2)` | `list[TileData]` | All tiles in bounding box |
| `tiles_where(x1,y1,z1,x2,y2,z2, *, shapes, min_water, min_magma, hidden)` | `list[TileData]` | Filtered subset; all filtering is Python-side after one block fetch |

**TileData fields:** `x, y, z, shape` (TiletypeShape), `water` (0–7), `magma` (0–7), `hidden` (bool). Properties: `is_solid`, `is_open`, `has_fluid`.

**Cache management:**
- `invalidate(x1,y1,z1,x2,y2,z2)` — drop cached blocks overlapping a volume; call after `send_dig_command` so the next query sees post-dig state.
- `cache_stats()` — dict of `cached_blocks`, `fresh_blocks`, `stale_blocks`, `session_log_entries`.
- **Bulk prefetch caveat**: DF loads every block in the embark (including solid rock) at all z-levels, so a full-region `prefetch_region` can easily fetch 2000+ blocks. The default `cache_max_blocks=500` will evict early chunks before `export_blocks` can read them. `snapshot.py` temporarily sets `glass.settings.cache_max_blocks = 10_000` before calling `prefetch_region` and restores it afterward — do the same in any code that bulk-prefetches a large volume.

**Settings (tunable by the agent):**

| Parameter | Default | Effect |
|---|---|---|
| `prefetch_padding` | 1 | Extra blocks fetched around every request (block units). 0 = exact fetch only. |
| `cache_max_blocks` | 500 | LRU eviction threshold. |
| `cache_ttl` | 120.0 | Seconds before a cached block expires. 0 = never expire. |
| `lazy` | True | False = raise `OutOfRegion` if block not pre-loaded; enforces explicit-region pattern. |
| `eval_every` | 20 | Fire self-evaluation every N calls (0 = disabled). Requires evaluator attached. |

`update_settings(**kwargs)` changes parameters and persists them to `spyglass_settings.json`.

**Usage logging:** every call appends one JSON line to `spyglass_log.jsonl` with fields: `call`, `volume`, `blocks_fetched`, `blocks_cached`, `blocks_extra` (padding overhead), `tiles_returned`, `fetch_ms`, `settings`. The agent self-evaluation procedure reads `recent_log(n)` to reason about whether current settings are appropriate and call `update_settings()` to retune.

**Self-evaluation:** attach a `SpyglassEvaluator` to enable automatic periodic retuning:
```python
evaluator = SpyglassEvaluator(apply=True)   # requires `anthropic` SDK
glass.attach_evaluator(evaluator)
# evaluation fires automatically every eval_every calls (default 20)
```
Requires `anthropic` package. Run manually: `python -m agent.evaluate` (or `--dry-run` to preview without applying, `--last N` to review saved evaluations).

### `agent/evaluate.py` — Spyglass self-evaluation

`SpyglassEvaluator` reads recent `spyglass_log.jsonl` entries, sends them to a Claude model with a structured rubric, parses the response for recommended settings changes, and saves the full reasoning (inner monologue) to `spyglass_evals.jsonl`.

**Rubric structure** (in `_RUBRIC` constant — edit to tune the procedure):
1. Cache hit rate — `blocks_cached / (blocks_cached + blocks_fetched)`; low rate → adjust padding or TTL
2. Padding overhead — `blocks_extra / blocks_fetched`; high overhead → reduce prefetch_padding
3. Query granularity — many `tile_at()` calls vs. volume queries; suggests switching to `tiles_in_volume()`
4. Query precision — `tiles_returned / volume_size`; low precision → narrow the requested volume
5. Fetch latency — high `fetch_ms` → increase TTL or padding to reduce fetch frequency

The model outputs a `DIAGNOSIS:`, `RECOMMENDATION:`, and `SETTINGS_UPDATE: {...}` (or `none`) block. The evaluator parses `SETTINGS_UPDATE` and calls `glass.update_settings()` if `apply=True`. The full raw response is saved to `spyglass_evals.jsonl` for human review.

**Viewing evaluations:**
```
python -m agent.evaluate --last 5    # print last 5 evaluation inner monologues
python -m agent.evaluate --dry-run   # run now, print recommendation, don't apply
```

**Dependency:** requires the `anthropic` SDK. The evaluator raises a clear `RuntimeError` (not an import error) if it's missing, so Spyglass itself can still be imported and used without it.

### `shear.py` — Hillside shear CLI

```
python shear.py X1 Y1 X2 Y2 Z_MIN Z_MAX [--dry-run]
```

Queries the terrain in the rectangle, finds each column's surface tile, and issues CHANNEL orders to lower the whole area by one z-level. `--dry-run` prints the plan (tile count, z-level distribution, skip reasons) without sending any dig commands. Always run `--dry-run` first to verify the z range covers the actual surface.

Example:
```
python shear.py 100 140 160 180 163 175 --dry-run
python shear.py 100 140 160 180 163 175
```

### `snapshot_view.py` — Offline ASCII terrain viewer

Renders a z-level cross-section from `snapshot_tiles.json`, which `snapshot.py` writes alongside `snapshot.json`. Does **not** require a live DFHack connection — useful for reviewing terrain between play sessions or on a second machine.

```
python snapshot_view.py                   # median citizen z, focused crop
python snapshot_view.py --z 167           # specific z-level
python snapshot_view.py --range 2         # z ± 2 stacked slices
python snapshot_view.py --list-z          # show which z-levels were captured
python snapshot_view.py --cw 100 --ch 50  # wider crop window
```

Glyph reference: `#` wall, `=` fortification, `.` floor, `/` ramp, `'` ramp-top, `<`/`>` stairs, `X` up-down stair, `~` water, `*` magma, `T` tree trunk, `b`/`B`/`w` branch/trunk-branch/twig, `t` sapling, `s` shrub, ` ` open sky, `?` hidden/unexplored. Units: `d` player dwarf, `D` other dwarf, `a` animal/other.

Water and magma depth override shape glyphs. Most underground tiles show as `?` (hidden) until explored by dwarves. The previous live viewer (`map_view.py`) is preserved in `archive/` if a real-time DFHack-connected view is needed again.

### Lua scripts installed in DF

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\hack\lua\rpc\`

| Script | Functions | Purpose |
|---|---|---|
| `needs.lua` | `get_unmet()` | Unmet needs across all citizens |
| `enums.lua` | `all_skills()`, `all_labors()`, `all_professions()` | Validate/generate enum ID→name mappings |
| `workdetails.lua` | `all()` | Read Work Details labor-group system |
| `date.lua` | `get()` | Current in-game year, season name, and tick-within-year |
| `creatures.lua` | `all()` | All creature raws as `"idx:CREATURE_ID"` strings; used to populate `CreatureRaws` |
| `buildings.lua` | `all()` | All placed buildings (excluding player constructions) as pipe-delimited strings; used to populate `Snapshot.buildings` |
| `stocks.lua` | `all()` | Item counts by type + per-material breakdown for consumables + bookkeeper state. Returns `"meta\|precision=N\|cooldown=M\|settings=S"`, `"type\|ITEM_TYPE\|count"`, `"detail\|ITEM_TYPE\|material\|count"` lines. Bookkeeper fields from `df.global.plotinfo.current.nobles`. |
| `nobles.lua` | `all()`, `positions()` | `all()`: noble assignment lines + bookkeeper/manager cooldown header. `positions()`: all defined position slots including vacant ones. Accesses `df.global.plotinfo.current.fortress_entity` for entity positions. Field paths need live verification — run `diag/diag_nobles.py` after first use. |

The `gamestate/` layer acts as a typed Python facade over raw DFHack RPC responses. The `commands/` layer is the only place that issues writes to the game. The agent in `agent/` reads from `gamestate/` and writes through `commands/` only.

## DFHack installation

`C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress\`  
DFHack files are under the `hack/` subdirectory. The `RemoteFortressReader.plug.dll` plugin provides the bulk of the game-state reading API.

## Save file location

Steam version (50.x) saves go to `C:\Users\kkado\AppData\Roaming\Bay 12 Games\Dwarf Fortress\save\`, **not** the game install directory (which has empty placeholder folders). The main save file is `world.sav` (~12 MB), accompanied by `unit-N.dat` files. The `current/` subdirectory is the live in-progress state; `autosave N/` and `regionN/` directories are autosave/backup snapshots. `snapshot.py` watches this directory for mtime changes to detect autosaves.

## Proto message reference

Official source: `https://github.com/DFHack/dfhack` — proto files are in `library/proto/` (core) and `plugins/remotefortressreader/proto/` (RFR). The proto files are not distributed as text in the Steam install; they must be fetched from GitHub or reconstructed from the DFHack docs. When adding new messages, fetch the raw file content via Python `httpx` (installed globally) rather than `curl` (SSL issues on this machine) or `WebFetch` (summarises rather than returning raw text).
