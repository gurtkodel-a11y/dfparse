"""
Creature raw ID resolution: race_id (int) -> species name (str).

Race IDs are world-specific integer indices into the creature raws array.
They are not stable across worlds or saves.
"""


class CreatureRaws:
    def __init__(self, raws: dict[int, str]):
        self._raws = raws  # race_id -> "CREATURE_ID" (all-caps raw name)

    @classmethod
    def from_dict(cls, d: dict) -> "CreatureRaws":
        """Parse from snapshot JSON (keys are strings; convert to ints)."""
        return cls({int(k): v for k, v in d.items()})

    def to_dict(self) -> dict[str, str]:
        """Serialise for snapshot JSON (int keys become strings)."""
        return {str(k): v for k, v in self._raws.items()}

    # Category prefixes that DF uses in raw IDs but that clutter display names.
    _STRIP_PREFIXES = ("BIRD_", "FISH_", "REPTILE_", "AMPHIBIAN_", "VERMIN_")

    def name(self, race_id: int) -> str:
        """Return a display name for a race ID (e.g. 572 -> 'Dwarf').

        Strips common DF category prefixes (BIRD_, FISH_, etc.), converts the
        remaining all-caps raw ID to title case, and replaces underscores.
        Returns 'Unknown(N)' for unrecognised IDs.
        """
        raw = self._raws.get(race_id)
        if raw is None:
            return f"Unknown({race_id})"
        for prefix in self._STRIP_PREFIXES:
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return raw.replace("_", " ").title()

    def raw_id(self, race_id: int) -> str | None:
        """Return the raw creature ID string (e.g. 'DWARF'), or None."""
        return self._raws.get(race_id)

    def __len__(self) -> int:
        return len(self._raws)

    def __contains__(self, race_id: int) -> bool:
        return race_id in self._raws

    def __repr__(self) -> str:
        return f"CreatureRaws({len(self._raws)} entries)"
