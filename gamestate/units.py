"""
Typed Python facade over raw DFHack BasicUnitInfo proto messages.

Flag bit positions verified against df-structures df.unit.xml (unit_flags1/2/3).
Sentience (can_speak/can_learn) is a caste property, not a per-unit flag; it is
not available in BasicUnitInfo. Use civ_id + histfig_id as proxies instead.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from dfhack import enums as _enums


# ---------------------------------------------------------------------------
# Flag bit masks (source: df-structures df.unit.xml)
# ---------------------------------------------------------------------------

# unit_flags1
_F1_INACTIVE       = 1 << 1   # dead OR off-map-alive (original name: DEAD)
_F1_MERCHANT       = 1 << 6
_F1_FOREST         = 1 << 7   # creature no longer tied to merchant/diplomacy; tries to leave
_F1_LEFT           = 1 << 8   # left the map
_F1_INCOMING       = 1 << 10  # not yet arrived
_F1_DIPLOMAT       = 1 << 11
_F1_ON_GROUND      = 1 << 15
_F1_ACTIVE_INVADER = 1 << 17  # organised invader currently active
_F1_INVADER_ORIGIN = 1 << 19  # was an invader; may now be fleeing

# unit_flags2
_F2_KILLED         = 1 << 7   # killed by kill function (reliable death marker)
_F2_SLAUGHTER      = 1 << 17  # marked for slaughter
_F2_UNDERWORLD     = 1 << 18  # underworld / circus creature
_F2_RESIDENT       = 1 << 19  # current resident of the fortress

# unit_flags3
_F3_GHOSTLY        = 1 << 12  # ghost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _singularize(name: str) -> str:
    """Best-effort singularization for DF work detail group names.

    DF's UI defaults group names to plural (Miners, Woodcutters, Farmers).
    Handles -ves (Fisherdwarves->Fisherdwarf), -s, and plain -ers.
    Does not strip -ss endings (Glass, Moss) or words shorter than 4 chars.
    """
    if len(name) >= 5 and name.endswith("ves"):
        return name[:-3] + "f"   # Fisherdwarves -> Fisherdwarf
    if len(name) >= 4 and name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitSkill:
    id: int
    name: str
    level: int
    title: str
    experience: int


@dataclass(frozen=True)
class Pos:
    x: int
    y: int
    z: int

    def __str__(self) -> str:
        return f"({self.x},{self.y},{self.z})"


@dataclass(frozen=True)
class UnitName:
    first: str
    last: str
    nickname: str
    english: str

    def display(self) -> str:
        parts = []
        if self.first or self.last:
            parts.append(f"{self.first.capitalize()} {self.last.capitalize()}".strip())
        if self.nickname:
            parts.append(f'"{self.nickname}"')
        if self.english:
            parts.append(f"[{self.english}]")
        return " ".join(parts) if parts else "(unnamed)"

    def __str__(self) -> str:
        return self.display()


class UnitKind(Enum):
    """Broad behavioural/ownership category for a unit."""
    CITIZEN         = auto()  # your civ, your race, alive, on-map
    CIV_ANIMAL      = auto()  # your civ, no histfig (pets, livestock)
    CIV_OTHER       = auto()  # your civ, different race, has histfig (rare: modded immigrants)
    MERCHANT        = auto()  # visiting merchant party member
    DIPLOMAT        = auto()  # visiting diplomat
    VISITOR         = auto()  # foreign-civ sentient, not merchant/diplomat/invader
    INVADER         = auto()  # active or origin invader
    WILD_CREATURE   = auto()  # no civ, no histfig (mundane wildlife)
    NOTABLE_CREATURE = auto() # no civ, has histfig (forgotten beast, megabeast, named animal…)
    GHOST           = auto()  # ghostly (dead but lingering)
    DEAD            = auto()  # killed and not a ghost
    OFFMAP          = auto()  # left the map or not yet arrived


@dataclass
class Unit:
    unit_id: int
    name: UnitName
    race: int
    caste: int
    gender: int         # -1 = unknown / not applicable
    civ_id: int         # -1 = no civ
    histfig_id: int     # -1 = no historical figure record
    flags1: int
    flags2: int
    flags3: int
    pos: Pos
    profession: int     # -1 = none; raw DF profession enum value
    custom_profession: str
    squad_id: int       # -1 = not in a squad
    squad_position: int
    death_id: int       # -1 = not dead
    labors: list[int] = field(default_factory=list)
    skills: list[tuple[int, int, int]] = field(default_factory=list)  # (id, level, xp)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_proto(cls, u) -> "Unit":
        n = u.name
        return cls(
            unit_id=u.unit_id,
            name=UnitName(
                first=n.first_name,
                last=n.last_name,
                nickname=n.nickname,
                english=n.english_name,
            ),
            race=u.race,
            caste=u.caste,
            gender=u.gender,
            civ_id=u.civ_id,
            histfig_id=u.histfig_id,
            flags1=u.flags1,
            flags2=u.flags2,
            flags3=u.flags3,
            pos=Pos(u.pos_x, u.pos_y, u.pos_z),
            profession=u.profession,
            custom_profession=u.custom_profession,
            squad_id=u.squad_id,
            squad_position=u.squad_position,
            death_id=u.death_id,
            labors=list(u.labors),
            skills=[(s.id, s.level, s.experience) for s in u.skills],
        )

    # ------------------------------------------------------------------
    # Semantic flag properties
    # ------------------------------------------------------------------

    @property
    def is_ghost(self) -> bool:
        return bool(self.flags3 & _F3_GHOSTLY)

    @property
    def is_killed(self) -> bool:
        """Killed by the game's kill function — the reliable dead-unit marker."""
        return bool(self.flags2 & _F2_KILLED)

    @property
    def is_inactive(self) -> bool:
        """Dead OR alive-but-off-map (the raw DEAD flag; use is_killed for true death)."""
        return bool(self.flags1 & _F1_INACTIVE)

    @property
    def has_left_map(self) -> bool:
        return bool(self.flags1 & _F1_LEFT)

    @property
    def is_incoming(self) -> bool:
        return bool(self.flags1 & _F1_INCOMING)

    @property
    def is_merchant(self) -> bool:
        return bool(self.flags1 & _F1_MERCHANT)

    @property
    def is_diplomat(self) -> bool:
        return bool(self.flags1 & _F1_DIPLOMAT)

    @property
    def is_active_invader(self) -> bool:
        return bool(self.flags1 & _F1_ACTIVE_INVADER)

    @property
    def is_invader_origin(self) -> bool:
        return bool(self.flags1 & _F1_INVADER_ORIGIN)

    @property
    def is_resident(self) -> bool:
        """Explicitly flagged as a current fortress resident."""
        return bool(self.flags2 & _F2_RESIDENT)

    @property
    def is_on_ground(self) -> bool:
        return bool(self.flags1 & _F1_ON_GROUND)

    @property
    def marked_for_slaughter(self) -> bool:
        return bool(self.flags2 & _F2_SLAUGHTER)

    @property
    def is_underworld(self) -> bool:
        return bool(self.flags2 & _F2_UNDERWORLD)

    @property
    def has_histfig(self) -> bool:
        """Has a historical figure record — proxy for 'named / significant'."""
        return self.histfig_id != -1

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def kind(self, player_civ_id: int, player_race_id: int) -> UnitKind:
        """Classify this unit given the player civ and race IDs from WorldInfo."""
        if self.is_ghost:
            return UnitKind.GHOST
        if self.is_killed:
            return UnitKind.DEAD
        if self.has_left_map or self.is_incoming:
            return UnitKind.OFFMAP

        # Behavioural flags take priority over civ membership — merchants and
        # diplomats from the player's own civilisation share civ_id but are
        # visitors, not citizens.
        if self.is_merchant:
            return UnitKind.MERCHANT
        if self.is_diplomat:
            return UnitKind.DIPLOMAT
        if self.is_active_invader or self.is_invader_origin:
            return UnitKind.INVADER

        in_player_civ = self.civ_id == player_civ_id
        no_civ = self.civ_id == -1

        if in_player_civ:
            if self.race == player_race_id:
                # Caravan guards are player-race, player-civ, but have no
                # historical figure record. Real citizens always have one.
                if not self.has_histfig:
                    return UnitKind.VISITOR
                return UnitKind.CITIZEN
            elif self.has_histfig:
                return UnitKind.CIV_OTHER
            else:
                return UnitKind.CIV_ANIMAL

        if no_civ:
            return UnitKind.NOTABLE_CREATURE if self.has_histfig else UnitKind.WILD_CREATURE

        # foreign civ, not merchant / diplomat / invader
        # NOTE: units with is_resident=True here are likely underground-civ members
        # at home in their own territory (observed: 10 units, race 624, civ 105,
        # z=9–14, all had resident flag set, body_temp_in_range, no underworld/invader
        # flags). True surface visitors probably lack the resident flag. Revisit once
        # we observe a confirmed surface visitor and can compare flags.
        return UnitKind.VISITOR

    def role_label(
        self,
        work_details: list,
        profession_names: dict[int, str] | None = None,
    ) -> str:
        """Return a concise job-role string for display.

        Priority:
        1. custom_profession — player-assigned name
        2. OnlySelectedDoesThis Work Details this unit is assigned to
        3. DF profession name (from profession_names lookup)
        4. "Generalist" fallback
        """
        from gamestate.work_details import WorkDetailMode

        if self.custom_profession:
            return self.custom_profession

        specific = [
            _singularize(wd.name) for wd in work_details
            if wd.mode == WorkDetailMode.OnlySelectedDoesThis
            and self.unit_id in wd.assigned_unit_ids
        ]
        if specific:
            return ", ".join(specific)

        if profession_names and self.profession >= 0:
            name = profession_names.get(self.profession, "")
            if name and name not in ("NONE", "STANDARD"):
                return name.replace("_", " ").title()

        return "Generalist"

    def decoded_skills(self) -> list[UnitSkill]:
        """Return skills sorted by level descending, with human-readable names."""
        result = []
        for skill_id, level, xp in self.skills:
            name = _enums.SKILL_NAMES.get(skill_id, f"Unknown({skill_id})")
            title = _enums.skill_title(level)
            result.append(UnitSkill(skill_id, name, level, title, xp))
        return sorted(result, key=lambda s: -s.level)

    def decoded_labors(self) -> list[str]:
        """Return enabled labor names, excluding the sentinel 'None' (id=0)."""
        return [
            _enums.LABOR_NAMES.get(lid, f"Unknown({lid})")
            for lid in self.labors
            if lid != 0
        ]

    def __str__(self) -> str:
        return f"Unit({self.unit_id}, {self.name.display()!r})"
