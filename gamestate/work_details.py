"""
Work Details — the DF 50.x labor-group system that sits on top of the
per-dwarf labor allowlist stored in BasicUnitInfo.labors.

A Work Detail names a set of labors and specifies which dwarves may perform
them, overriding whatever the per-dwarf allowlist says for those labors.
"""

from dataclasses import dataclass, field
from enum import IntEnum


class WorkDetailMode(IntEnum):
    Default             = 0  # per-dwarf allowlist governs (normal DF behavior)
    EverybodyDoesThis   = 1  # all dwarves may do these labors
    NobodyDoesThis      = 2  # no dwarf may do these labors
    OnlySelectedDoesThis = 3 # only assigned_unit_ids may do these labors


@dataclass(frozen=True)
class WorkDetail:
    name: str
    mode: WorkDetailMode
    labor_ids: frozenset[int]       # which labor IDs this detail governs
    assigned_unit_ids: frozenset[int]

    @classmethod
    def from_raw(cls, raw: str) -> "WorkDetail":
        """Parse a pipe-delimited string from rpc.workdetails.all()."""
        parts = raw.split("|")
        name = parts[0]
        mode = WorkDetailMode(int(parts[1]))
        labor_ids = frozenset(int(x) for x in parts[2].split(",") if x)
        unit_ids  = frozenset(int(x) for x in parts[3].split(",") if x)
        return cls(name, mode, labor_ids, unit_ids)


def effective_labors(
    unit_id: int,
    allowlist: list[int],
    work_details: list[WorkDetail],
) -> list[int]:
    """Return the labor IDs a unit may actually perform.

    Rules (applied per labor ID):
    - If a Work Detail covers the labor:
        - EverybodyDoesThis   → allowed for all units
        - NobodyDoesThis      → denied for all units
        - OnlySelectedDoesThis → allowed only if unit is in assigned_unit_ids
        - Default             → fall through to per-dwarf allowlist
    - If no Work Detail covers the labor → use per-dwarf allowlist.
    """
    allowlist_set = set(allowlist)

    # Build a lookup: labor_id → the work detail that governs it (if any).
    # DF does not enforce uniqueness here, but in practice each labor belongs
    # to at most one Work Detail. Last one wins if there are duplicates.
    governing: dict[int, WorkDetail] = {}
    for wd in work_details:
        for lid in wd.labor_ids:
            governing[lid] = wd

    result = []
    # Iterate over the union of labors that could possibly apply to this unit.
    all_candidates = allowlist_set | {lid for wd in work_details for lid in wd.labor_ids}
    for lid in sorted(all_candidates):
        wd = governing.get(lid)
        if wd is None:
            if lid in allowlist_set:
                result.append(lid)
        elif wd.mode == WorkDetailMode.EverybodyDoesThis:
            result.append(lid)
        elif wd.mode == WorkDetailMode.NobodyDoesThis:
            pass
        elif wd.mode == WorkDetailMode.OnlySelectedDoesThis:
            if unit_id in wd.assigned_unit_ids:
                result.append(lid)
        else:  # Default
            if lid in allowlist_set:
                result.append(lid)

    return result
