"""
Load snapshot.json (or an archived snapshot) into gamestate objects.

Typical use:
    from gamestate.snapshot import Snapshot

    # Current state
    s = Snapshot.load()

    # A specific archived season
    s = Snapshot.load_season("region16", 125, "spring")

    # Everything available for a region, oldest first
    for entry in Snapshot.list_history("region16"):
        print(entry.label, entry.path)
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from gamestate.buildings import Building
from gamestate.creatures import CreatureRaws
from gamestate.units import Unit, UnitKind, UnitName, Pos
from gamestate.work_details import WorkDetail
from gamestate.world import WorldInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _REPO_ROOT / "snapshot.json"
SNAPSHOTS_DIR = _REPO_ROOT / "snapshots"

_SEASON_NUM = {"spring": 1, "summer": 2, "autumn": 3, "winter": 4}


class HistoryEntry(NamedTuple):
    year: int
    season: str
    label: str       # e.g. "y125-spring"
    path: Path
    is_manual: bool


@dataclass
class GameDate:
    year: int
    season: str
    tick: int

    def __str__(self) -> str:
        return f"y{self.year}-{self.season} (tick {self.tick})"


@dataclass
class Snapshot:
    snapshot_time: str
    game_date: GameDate | None
    world: WorldInfo
    units: list[Unit]
    work_details: list[WorkDetail]
    unmet_needs: list[tuple[str, int, int]]
    creature_raws: CreatureRaws = None
    map_region: dict | None = None  # tile bounds captured in snapshot_tiles.json
    buildings: list[Building] = None

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "Snapshot":
        """Load snapshot.json (or any snapshot file) from path."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls._from_dict(data)

    @classmethod
    def load_season(cls, region: str, year: int, season: str) -> "Snapshot":
        """Load the archived seasonal snapshot for a specific region and season."""
        n = _SEASON_NUM[season]
        path = SNAPSHOTS_DIR / region / f"y{year}-{n}-{season}.json"
        if not path.exists():
            raise FileNotFoundError(f"No archived snapshot at {path}")
        return cls.load(path)

    @classmethod
    def list_history(cls, region: str) -> list[HistoryEntry]:
        """Return all archived snapshots for a region, sorted by game date."""
        region_dir = SNAPSHOTS_DIR / region
        if not region_dir.exists():
            return []

        entries = []
        for p in region_dir.glob("*.json"):
            stem = p.stem
            if stem.startswith("y"):
                # y125-2-summer.json  or  y125-2-summer-manual-T143013.json
                parts = stem.split("-")
                if len(parts) >= 3:
                    try:
                        year = int(parts[0][1:])
                        season = parts[2]
                        is_manual = len(parts) > 3 and parts[3] == "manual"
                        entries.append(HistoryEntry(year, season, stem, p, is_manual=is_manual))
                    except (ValueError, IndexError):
                        pass

        return sorted(
            entries,
            key=lambda e: (e.year, _SEASON_NUM.get(e.season, 99), e.is_manual),
        )

    # ------------------------------------------------------------------
    # Internal construction
    # ------------------------------------------------------------------

    @classmethod
    def _from_dict(cls, data: dict) -> "Snapshot":
        w = data["world"]
        world = WorldInfo(
            mode=w["mode"],
            world_name=w["world_name"],
            save_dir=w["save_dir"],
            civ_id=w["civ_id"],
            site_id=w["site_id"],
            group_id=w["group_id"],
            race_id=w["race_id"],
        )

        gd = data.get("game_date")
        game_date = GameDate(gd["year"], gd["season"], gd["tick"]) if gd else None

        units = []
        for u in data["units"]:
            n = u["name"]
            units.append(Unit(
                unit_id=u["unit_id"],
                name=UnitName(
                    first=n["first"],
                    last=n["last"],
                    nickname=n["nickname"],
                    english=n["english"],
                ),
                race=u["race"],
                caste=u["caste"],
                gender=u["gender"],
                civ_id=u["civ_id"],
                histfig_id=u["histfig_id"],
                flags1=u["flags1"],
                flags2=u["flags2"],
                flags3=u["flags3"],
                pos=Pos(u["pos"]["x"], u["pos"]["y"], u["pos"]["z"]),
                profession=u["profession"],
                custom_profession=u["custom_profession"],
                squad_id=u["squad_id"],
                squad_position=u["squad_position"],
                death_id=u["death_id"],
                labors=u["labors"],
                skills=[tuple(s) for s in u["skills"]],
            ))

        work_details = [WorkDetail.from_raw(r) for r in data["work_details"]]
        unmet_needs = [(e[0], e[1], e[2]) for e in data["unmet_needs"]]
        cr_raw = data.get("creature_raws")
        creature_raws = CreatureRaws.from_dict(cr_raw) if cr_raw else CreatureRaws({})

        raw_buildings = data.get("buildings", [])
        buildings = [Building.from_dict(b) for b in raw_buildings]

        return cls(
            snapshot_time=data["snapshot_time"],
            game_date=game_date,
            world=world,
            units=units,
            work_details=work_details,
            unmet_needs=unmet_needs,
            creature_raws=creature_raws,
            map_region=data.get("map_region"),
            buildings=buildings,
        )

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def citizens(self) -> list[Unit]:
        """Dwarven citizens only (alive, on-map, player civ and race)."""
        return [
            u for u in self.units
            if u.kind(self.world.civ_id, self.world.race_id) == UnitKind.CITIZEN
        ]

    def _buildings(self) -> list[Building]:
        return self.buildings or []

    def workshops(self) -> list[Building]:
        """Completed workshops."""
        return [b for b in self._buildings() if b.type_name == "Workshop" and b.is_complete]

    def furnaces(self) -> list[Building]:
        """Completed furnaces."""
        return [b for b in self._buildings() if b.type_name == "Furnace" and b.is_complete]

    def stockpiles(self) -> list[Building]:
        """All stockpile zones."""
        return [b for b in self._buildings() if b.type_name == "Stockpile"]

    def zones(self) -> list[Building]:
        """All activity zones (meeting halls, bedrooms, hospitals, barracks, etc.)."""
        return [b for b in self._buildings() if b.type_name == "Civzone"]

    def buildings_by_type(self, type_name: str) -> list[Building]:
        """All buildings with the given type_name (e.g. 'Door', 'TradeDepot')."""
        return [b for b in self._buildings() if b.type_name == type_name]
