# Archive

This folder holds diagnostic and exploratory scripts that were used during active
development but whose findings have been incorporated into the codebase (implementation,
CLAUDE.md analysis, or both). They are not part of the normal workflow.

They are preserved here because they may be useful for:

- Re-running against a new DFHack version to validate that API behaviour has not changed
- Regression-checking after a protocol or gamestate refactor
- Reconstructing the reasoning behind specific design decisions in `dfhack/` or `commands/`

## Scripts

| File | Purpose | Findings captured in |
|---|---|---|
| `test_connection.py` | Smoke-test + live enum cross-check (skill/labor/profession IDs) | `dfhack/enums.py`, CLAUDE.md §Known quirks |
| `test_dig.py` | First live `send_dig_command` call — DEFAULT_DIG + CHANNEL at hardcoded tiles | CLAUDE.md §Dig designations |
| `test_dig2.py` | Staircase designation at hardcoded coords | CLAUDE.md §Dig designations |
| `test_dig_cancel.py` | Cancel orders placed by test_dig.py (NO_DIG = 0) | CLAUDE.md §Dig designations |
| `test_dig_invalid.py` | Dig order sent to open-air tile — confirms DF defers validity to game engine, no crash | CLAUDE.md §"DF does not validate on receipt" |
| `test_items.py` | Exploratory probe of the DFHack items API | Not yet exposed (items API not pursued) |
| `test_shapes.py` | `dig_staircase` + `dig_rectangle` via `commands/` layer | `commands/dig.py` |
| `test_slope.py` | `dig_slope` ascending path | `commands/dig.py`, CLAUDE.md §dig_slope internals |
| `map_view.py` | Live ASCII terrain viewer (requires DFHack connection) | Superseded by `snapshot_view.py` |
