from __future__ import annotations
from dataclasses import dataclass, field


# bookkeeper_precision appears to be 0-4 in the internal data (displayed as 1-5 in-game).
# bookkeeper_settings is the player-chosen target (the enum record_precision_level_type,
# also probably 0-4 internally).
# These labels need verification against the live game; see stocks.py for the rounding table.
_PRECISION_LABEL: dict[int, str] = {
    0: "none (no records)",
    1: "rough",
    2: "fair",
    3: "good",
    4: "excellent",
    5: "perfect",
}


@dataclass
class NoblePosition:
    code: str           # raw token, e.g. "BOOKKEEPER", "MAYOR", "MANAGER"
    name: str           # display name from position definition, e.g. "Bookkeeper"
    position_id: int    # internal id linking definition to assignment
    histfig_id: int     # -1 if vacant
    unit_id: int        # live unit id; -1 if off-map or vacant
    unit_name: str      # first name; empty string if vacant

    def is_filled(self) -> bool:
        return self.histfig_id >= 0

    def is_on_map(self) -> bool:
        return self.unit_id >= 0

    def display(self) -> str:
        title = self.name or self.code
        if not self.is_filled():
            return f"{title}: (vacant)"
        if self.unit_name:
            label = self.unit_name
        elif self.is_on_map():
            label = f"unit#{self.unit_id}"
        else:
            label = f"hf#{self.histfig_id} (off-map)"
        return f"{title}: {label}"


@dataclass
class NoblesReport:
    positions: list[NoblePosition]

    # Bookkeeper state (mirrors what stocks.py also reads, included here for convenience)
    bookkeeper_precision: int   # current achieved precision (0-4, or -1 unreadable)
    bookkeeper_cooldown: int    # ticks until next record update
    bookkeeper_settings: int    # player's target precision setting
    manager_cooldown: int       # ticks until manager processes next batch of orders

    # Unrecognised / error lines returned from Lua (useful for debugging bad field paths)
    errors: list[str] = field(default_factory=list)
    # Position definitions from nobles.positions() call (populated separately if requested)
    all_positions: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ queries

    def by_code(self, code: str) -> NoblePosition | None:
        """Return the first filled assignment matching the position code."""
        for p in self.positions:
            if p.code == code:
                return p
        return None

    def bookkeeper(self) -> NoblePosition | None:
        return self.by_code("BOOKKEEPER")

    def manager(self) -> NoblePosition | None:
        return self.by_code("MANAGER")

    def mayor(self) -> NoblePosition | None:
        return self.by_code("MAYOR")

    def chief_medical_dwarf(self) -> NoblePosition | None:
        return self.by_code("CHIEF_MEDICAL_DWARF")

    def sheriff(self) -> NoblePosition | None:
        return self.by_code("SHERIFF")

    def bookkeeper_precision_label(self) -> str:
        return _PRECISION_LABEL.get(self.bookkeeper_precision, f"level {self.bookkeeper_precision}")

    def summary(self) -> str:
        lines = []
        for p in self.positions:
            lines.append(p.display())
        if not lines:
            return "(no nobles assigned)"
        return "\n".join(lines)

    # ------------------------------------------------------------------ parsing

    @classmethod
    def from_raw(cls, lines: list[str]) -> "NoblesReport":
        positions: list[NoblePosition] = []
        errors: list[str] = []
        bk_prec = bk_cool = bk_set = mgr_cool = -1

        for line in lines:
            tag, _, rest = line.partition("|")

            if tag == "meta":
                for kv in rest.split("|"):
                    k, _, v = kv.partition("=")
                    try:
                        iv = int(v)
                        if k == "bookkeeper_precision":
                            bk_prec = iv
                        elif k == "bookkeeper_cooldown":
                            bk_cool = iv
                        elif k == "bookkeeper_settings":
                            bk_set = iv
                        elif k == "manager_cooldown":
                            mgr_cool = iv
                    except ValueError:
                        pass

            elif tag == "noble":
                # format: code|display_name|position_id|histfig_id|unit_id|first_name
                parts = rest.split("|", 5)
                if len(parts) == 6:
                    try:
                        positions.append(NoblePosition(
                            code=parts[0],
                            name=parts[1],
                            position_id=int(parts[2]),
                            histfig_id=int(parts[3]),
                            unit_id=int(parts[4]),
                            unit_name=parts[5],
                        ))
                    except ValueError:
                        errors.append(f"bad noble line: {line}")

            elif tag == "error":
                errors.append(rest)

        return cls(
            positions=positions,
            bookkeeper_precision=bk_prec,
            bookkeeper_cooldown=bk_cool,
            bookkeeper_settings=bk_set,
            manager_cooldown=mgr_cool,
            errors=errors,
        )
