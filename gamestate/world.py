from dataclasses import dataclass


@dataclass(frozen=True)
class WorldInfo:
    mode: str       # "DWARF", "ADVENTURE", or "LEGENDS"
    world_name: str
    save_dir: str
    civ_id: int
    site_id: int
    group_id: int
    race_id: int    # player civ's race (e.g. dwarf race index)

    @classmethod
    def from_proto(cls, w) -> "WorldInfo":
        mode_name = (
            w.DESCRIPTOR.fields_by_name["mode"]
            .enum_type.values_by_number[w.mode].name
        )
        return cls(
            mode=mode_name,
            world_name=w.world_name,
            save_dir=w.save_dir,
            civ_id=w.civ_id,
            site_id=w.site_id,
            group_id=w.group_id,
            race_id=w.race_id,
        )
