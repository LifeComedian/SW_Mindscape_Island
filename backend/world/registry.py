"""Small registry for versioned world specifications."""

from dataclasses import replace

from data.island import ISLAND_V03_SPEC
from data.island_v04 import ISLAND_V04_SPEC
from content.loader import load_all_builtin_content_packs
from world.graph import validate_location_graph
from world.schedules import validate_resident_schedules
from world.specs import CalendarSpec, WorldSpec


_WORLD_SPECS: dict[str, WorldSpec] = {}
_DEFAULT_WORLD_VERSION: str | None = None


def register_world_spec(
    spec: WorldSpec,
    *,
    default: bool = False,
) -> None:
    global _DEFAULT_WORLD_VERSION

    validate_location_graph(spec)
    validate_resident_schedules(spec)
    if spec.world_version in _WORLD_SPECS:
        raise ValueError(f"World version already registered: {spec.world_version}")
    _WORLD_SPECS[spec.world_version] = spec
    if default or _DEFAULT_WORLD_VERSION is None:
        _DEFAULT_WORLD_VERSION = spec.world_version


def get_world_spec(world_version: str | None = None) -> WorldSpec:
    resolved_version = world_version or _DEFAULT_WORLD_VERSION
    if resolved_version is None or resolved_version not in _WORLD_SPECS:
        raise KeyError(f"Unknown world version: {resolved_version}")
    return _WORLD_SPECS[resolved_version]


def list_world_versions() -> tuple[str, ...]:
    return tuple(
        sorted(
            version
            for version, spec in _WORLD_SPECS.items()
            if spec.experience.get("fixture_only") is not True
        )
    )


register_world_spec(ISLAND_V03_SPEC, default=True)
register_world_spec(ISLAND_V04_SPEC)
for installed_content_pack in load_all_builtin_content_packs():
    register_world_spec(installed_content_pack.world_spec)

# The seven-day fixture is available only through the guarded test bridge.
if "island-v0.6" in _WORLD_SPECS:
    _fixture_base = _WORLD_SPECS["island-v0.6"]
    register_world_spec(
        replace(
            _fixture_base,
            world_version="study-m6-fixture-v1",
            scenario_pack_version="study-m6-fixture-scenarios-v1",
            content_pack_version="study-m6-fixture-content-v1",
            event_pack_version="study-m6-fixture-events-v1",
            calendar=CalendarSpec(
                total_days=7,
                day_start_minute=_fixture_base.calendar.day_start_minute,
                day_end_minute=_fixture_base.calendar.day_end_minute,
                rollover="next_day",
            ),
            experience={
                **dict(_fixture_base.experience),
                "final_day_departure_required": True,
                "fixture_only": True,
            },
        )
    )
