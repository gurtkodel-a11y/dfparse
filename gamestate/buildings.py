"""
Building dataclass — typed wrapper for one placed building from rpc.buildings.all().

Raw wire format (pipe-delimited, from buildings.lua):
    "id|btype_int|btype_str|subtype_int|subtype_str|x1|y1|z|x2|y2|build_stage|max_stage"
"""

from dataclasses import dataclass


@dataclass
class Building:
    id: int
    type_id: int
    type_name: str      # e.g. "Workshop", "Furnace", "Stockpile", "Civzone", "Door"
    subtype_id: int     # -1 when not applicable
    subtype_name: str   # e.g. "Craftsdwarf", "Smelter", "Bedroom", ""
    x1: int
    y1: int
    z: int
    x2: int
    y2: int
    build_stage: int
    max_stage: int

    @property
    def is_complete(self) -> bool:
        """True if fully constructed (or a building type with no staged construction)."""
        return self.max_stage == 0 or self.build_stage >= self.max_stage

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2

    @property
    def width(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def height(self) -> int:
        return self.y2 - self.y1 + 1

    def display_name(self) -> str:
        """Human-readable label, e.g. 'Workshop (Craftsdwarf)' or 'Door'."""
        if self.subtype_name:
            return f"{self.type_name} ({self.subtype_name})"
        return self.type_name

    @staticmethod
    def from_raw(s: str) -> "Building":
        p = s.split("|")
        return Building(
            id=int(p[0]),
            type_id=int(p[1]),
            type_name=p[2],
            subtype_id=int(p[3]),
            subtype_name=p[4],
            x1=int(p[5]), y1=int(p[6]), z=int(p[7]),
            x2=int(p[8]), y2=int(p[9]),
            build_stage=int(p[10]),
            max_stage=int(p[11]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type_id": self.type_id,
            "type_name": self.type_name,
            "subtype_id": self.subtype_id,
            "subtype_name": self.subtype_name,
            "x1": self.x1, "y1": self.y1, "z": self.z,
            "x2": self.x2, "y2": self.y2,
            "build_stage": self.build_stage,
            "max_stage": self.max_stage,
        }

    @staticmethod
    def from_dict(d: dict) -> "Building":
        return Building(
            id=d["id"],
            type_id=d["type_id"],
            type_name=d["type_name"],
            subtype_id=d["subtype_id"],
            subtype_name=d["subtype_name"],
            x1=d["x1"], y1=d["y1"], z=d["z"],
            x2=d["x2"], y2=d["y2"],
            build_stage=d["build_stage"],
            max_stage=d["max_stage"],
        )
