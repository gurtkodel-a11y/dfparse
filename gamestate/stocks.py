from __future__ import annotations
from dataclasses import dataclass

# Rounding bucket per bookkeeper_precision level (estimated from DF mechanics).
# Precision -1 (unreadable) is treated like 0.  Precision 5+ = exact.
# Tune these after live comparison with the in-game Stocks screen.
_BUCKET: dict[int, int] = {
    0: 100,   # no bookkeeper assigned (or not started yet)
    1: 50,
    2: 20,
    3: 10,
    4: 5,
    5: 1,     # exact
}


def _fuzz(count: int, precision: int) -> int:
    """Round count to the nearest bucket for the given bookkeeper precision level."""
    bucket = _BUCKET.get(max(0, precision), 100)
    if bucket <= 1:
        return count
    return max(0, round(count / bucket) * bucket)


@dataclass
class BookkeeperState:
    precision: int    # raw value from df.global.plotinfo; -1 if unreadable
    cooldown: int     # ticks until next record refresh; -1 if unreadable

    def label(self) -> str:
        labels = {
            -1: "unknown (plotinfo unreadable)",
            0:  "none (no bookkeeper assigned)",
            1:  "rough (nearest ~50)",
            2:  "fair (nearest ~20)",
            3:  "good (nearest ~10)",
            4:  "excellent (nearest ~5)",
            5:  "perfect (exact)",
        }
        return labels.get(self.precision, f"level {self.precision}")

    def is_exact(self) -> bool:
        return self.precision >= 5


@dataclass
class StockEntry:
    item_type: str
    count: int          # exact raw count from game data

    def fuzzy(self, precision: int) -> int:
        return _fuzz(self.count, precision)


@dataclass
class StockDetail:
    item_type: str
    material: str
    count: int          # exact raw count from game data

    def fuzzy(self, precision: int) -> int:
        return _fuzz(self.count, precision)


@dataclass
class StockReport:
    bookkeeper: BookkeeperState
    entries: list[StockEntry]
    details: list[StockDetail]

    # ------------------------------------------------------------------ queries

    def by_type(self, item_type: str) -> int:
        """Exact total count for an item type."""
        for e in self.entries:
            if e.item_type == item_type:
                return e.count
        return 0

    def fuzzy_by_type(self, item_type: str) -> int:
        """Precision-fuzzed count (as the game UI would show)."""
        return _fuzz(self.by_type(item_type), self.bookkeeper.precision)

    def material_breakdown(self, item_type: str, *, fuzzy: bool = False) -> dict[str, int]:
        """Per-material counts for a consumable type (FOOD, DRINK, PLANT, …).

        Returns {material_name: count} sorted by count descending.
        Pass fuzzy=True to apply bookkeeper precision rounding.
        """
        prec = self.bookkeeper.precision
        result: dict[str, int] = {}
        for d in self.details:
            if d.item_type == item_type:
                c = _fuzz(d.count, prec) if fuzzy else d.count
                if c > 0:
                    result[d.material] = c
        return dict(sorted(result.items(), key=lambda kv: -kv[1]))

    def summary(self, *, fuzzy: bool = False) -> dict[str, int]:
        """All item types -> count, sorted by count descending.

        Pass fuzzy=True to apply bookkeeper precision rounding (simulates game UI).
        """
        prec = self.bookkeeper.precision
        result: dict[str, int] = {}
        for e in self.entries:
            c = _fuzz(e.count, prec) if fuzzy else e.count
            if c > 0:
                result[e.item_type] = c
        return dict(sorted(result.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------------ parsing

    @classmethod
    def from_raw(cls, lines: list[str]) -> "StockReport":
        bookkeeper = BookkeeperState(precision=-1, cooldown=-1)
        entries: list[StockEntry] = []
        details: list[StockDetail] = []

        for line in lines:
            tag, _, rest = line.partition("|")

            if tag == "meta":
                for kv in rest.split("|"):
                    k, _, v = kv.partition("=")
                    try:
                        if k == "precision":
                            bookkeeper.precision = int(v)
                        elif k == "cooldown":
                            bookkeeper.cooldown = int(v)
                    except ValueError:
                        pass

            elif tag == "type":
                item_type, _, count_s = rest.partition("|")
                try:
                    entries.append(StockEntry(item_type=item_type, count=int(count_s)))
                except ValueError:
                    pass

            elif tag == "detail":
                # format after tag: "ITEM_TYPE|material name|count"
                parts = rest.split("|", 2)
                if len(parts) == 3:
                    try:
                        details.append(StockDetail(
                            item_type=parts[0],
                            material=parts[1],
                            count=int(parts[2]),
                        ))
                    except ValueError:
                        pass

        return cls(bookkeeper=bookkeeper, entries=entries, details=details)
