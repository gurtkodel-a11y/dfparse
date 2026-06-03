"""
Print a formatted unit roster from the current snapshot.json.

Usage:
    python roster.py
"""

from collections import Counter, defaultdict

from gamestate.snapshot import Snapshot
from gamestate.units import Unit, UnitKind


def _fmt_name(u: Unit) -> str:
    return u.name.display()


def _top_skills(u: Unit, n: int = 2) -> str:
    skills = u.decoded_skills()[:n]
    if not skills:
        return ""
    return ", ".join(f"{s.name} ({s.title})" for s in skills)


def _role(u: Unit, work_details) -> str:
    return u.role_label(work_details)


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _subsection(title: str) -> None:
    print(f"\n  --- {title} ---")


def _species_counts(units, creature_raws) -> list[tuple[str, int]]:
    """Return (species_name, count) pairs sorted by count desc."""
    counts = Counter(creature_raws.name(u.race) for u in units)
    return sorted(counts.items(), key=lambda x: -x[1])


def main() -> None:
    s = Snapshot.load()
    cr = s.creature_raws
    civ_id = s.world.civ_id
    race_id = s.world.race_id
    wds = s.work_details

    print(f"Snapshot: {s.game_date}  ({s.snapshot_time[:19]})")
    print(f"Fort: {s.world.world_name}  |  civ {civ_id}  |  {len(s.units)} total units")

    # ------------------------------------------------------------------ #
    # Classify every unit                                                  #
    # ------------------------------------------------------------------ #
    citizens      = []
    fort_animals  = []   # CIV_ANIMAL (no histfig) + named CIV_OTHER (pets)
    visitor_animals = [] # unnamed CIV_OTHER (caravan pack animals)
    merchants     = []
    diplomats     = []
    visitors      = []   # foreign-civ sentients, not merchant/diplomat/invader
    invaders      = []
    wild          = []   # WILD_CREATURE + NOTABLE_CREATURE
    dead          = []
    misc          = []   # GHOST, OFFMAP

    for u in s.units:
        kind = u.kind(civ_id, race_id)
        if kind == UnitKind.CITIZEN:
            citizens.append(u)
        elif kind == UnitKind.CIV_ANIMAL:
            fort_animals.append(u)
        elif kind == UnitKind.CIV_OTHER:
            # Named = a fort pet; unnamed = caravan pack animal
            if u.name.first or u.name.english:
                fort_animals.append(u)
            else:
                visitor_animals.append(u)
        elif kind == UnitKind.MERCHANT:
            merchants.append(u)
        elif kind == UnitKind.DIPLOMAT:
            diplomats.append(u)
        elif kind == UnitKind.VISITOR:
            visitors.append(u)
        elif kind == UnitKind.INVADER:
            invaders.append(u)
        elif kind in (UnitKind.WILD_CREATURE, UnitKind.NOTABLE_CREATURE):
            wild.append(u)
        elif kind == UnitKind.DEAD:
            dead.append(u)
        else:
            misc.append(u)

    # ------------------------------------------------------------------ #
    # 1. Fort Dwarves                                                      #
    # ------------------------------------------------------------------ #
    _section(f"Fort Dwarves ({len(citizens)})")
    if not citizens:
        print("  (none)")
    for u in sorted(citizens, key=lambda u: u.name.first):
        role  = _role(u, wds)
        skills = _top_skills(u, 2)
        line = f"  {_fmt_name(u):<38}  {role:<18}"
        if skills:
            line += f"  {skills}"
        print(line)

    # ------------------------------------------------------------------ #
    # 2. Fort Animals                                                      #
    # ------------------------------------------------------------------ #
    _section(f"Fort Animals ({len(fort_animals)})")
    if not fort_animals:
        print("  (none)")

    # Named pets get their own line; unnamed are grouped by species
    named_pets   = [u for u in fort_animals if u.name.first or u.name.english]
    unnamed_pets = [u for u in fort_animals if not (u.name.first or u.name.english)]

    if named_pets:
        _subsection("Named pets")
        for u in named_pets:
            species = cr.name(u.race)
            print(f"    {_fmt_name(u):<38}  {species}")

    if unnamed_pets:
        _subsection("Livestock & unnamed pets")
        for species, count in _species_counts(unnamed_pets, cr):
            print(f"    {species} x{count}")

    # ------------------------------------------------------------------ #
    # 3. Enemies & their animals                                           #
    # ------------------------------------------------------------------ #
    _section(f"Enemies ({len(invaders)})")
    if not invaders:
        print("  (none confirmed on map)")
    else:
        by_race = defaultdict(list)
        for u in invaders:
            by_race[u.race].append(u)
        for race, units in sorted(by_race.items()):
            species = cr.name(race)
            named = [u for u in units if u.name.first or u.name.english]
            unnamed_count = len(units) - len(named)
            if named:
                for u in named:
                    print(f"  {_fmt_name(u):<38}  {species}  civ {u.civ_id}")
            if unnamed_count:
                print(f"  {species} x{unnamed_count}  (civ {units[0].civ_id})")

    # ------------------------------------------------------------------ #
    # 4. Friendly Visitors & their animals                                 #
    # ------------------------------------------------------------------ #
    all_visitors = diplomats + merchants + visitors
    _section(f"Friendly Visitors ({len(all_visitors)} sentients)")

    if not all_visitors and not visitor_animals:
        print("  (none)")

    if diplomats:
        _subsection("Diplomats")
        for u in diplomats:
            species = cr.name(u.race)
            print(f"    {_fmt_name(u):<38}  {species}  civ {u.civ_id}")

    if merchants:
        merchant_dwarves  = [u for u in merchants if u.race == race_id]
        merchant_animals  = [u for u in merchants if u.race != race_id]

        if merchant_dwarves:
            _subsection("Merchants")
            for u in merchant_dwarves:
                skills = _top_skills(u, 1)
                line = f"    {_fmt_name(u):<38}  Dwarf  civ {u.civ_id}"
                if skills:
                    line += f"  |  {skills}"
                print(line)

        if merchant_animals:
            _subsection("Caravan animals")
            for species, count in _species_counts(merchant_animals, cr):
                print(f"    {species} x{count}")

    if visitors:
        _subsection("Other visitors")
        by_race = defaultdict(list)
        for u in visitors:
            by_race[(u.race, u.civ_id)].append(u)
        for (race, civ), units in sorted(by_race.items()):
            species = cr.name(race)
            named = [u for u in units if u.name.first or u.name.english]
            unnamed_count = len(units) - len(named)
            for u in named:
                print(f"    {_fmt_name(u):<38}  {species}  civ {civ}")
            if unnamed_count:
                print(f"    {species} x{unnamed_count}  (civ {civ})")


    # ------------------------------------------------------------------ #
    # 5. Wild & Miscellaneous                                              #
    # ------------------------------------------------------------------ #
    _section(f"Wild & Miscellaneous ({len(wild)} alive, {len(dead)} dead)")

    if wild:
        # Bin by broad elevation band; store as (min_z, label) so sorting is easy
        bands: dict[int, tuple[str, list]] = {}
        for u in wild:
            z = u.pos.z
            if z >= 160:
                key, label = 160, "surface (z>=160)"
            else:
                lo = (z // 20) * 20
                region = "mid-depth" if z >= 100 else "deep"
                key, label = lo, f"{region} (z={lo}-{lo+19})"
            if key not in bands:
                bands[key] = (label, [])
            bands[key][1].append(u)

        for key in sorted(bands, reverse=True):
            label, units = bands[key]
            _subsection(label)
            for species, count in _species_counts(units, cr):
                print(f"    {species} x{count}")

    if dead:
        _subsection("Dead")
        for species, count in _species_counts(dead, cr):
            print(f"    {species} x{count}")

    if misc:
        _subsection("Other (off-map / ghost)")
        for species, count in _species_counts(misc, cr):
            print(f"    {species} x{count}")


if __name__ == "__main__":
    main()
