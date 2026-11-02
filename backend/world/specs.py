"""Immutable data specifications shared by world-engine components."""

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Literal, Mapping


LocalizedText = Mapping[str, str]
RolloverPolicy = Literal["clamp", "next_day"]
MapPoint = tuple[float, float]
VisualSlotType = Literal[
    "map_image",
    "actor_map_thumbnail",
    "location_map_thumbnail",
    "actor_dialogue_portrait",
    "location_scene_image",
]


class WorldSpecValidationError(ValueError):
    """Raised when a world definition has invalid or dangling content."""


def _freeze(value: Any) -> Any:
    """Copy common content containers into recursively read-only values."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _point(value: tuple[float, float], *, label: str) -> MapPoint:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise WorldSpecValidationError(f"{label} must be a pair of numbers.")
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(item) for item in point):
        raise WorldSpecValidationError(f"{label} must contain finite numbers.")
    return point


@dataclass(frozen=True)
class MapPathSpec:
    path_id: str
    from_location_id: str
    to_location_id: str
    points: tuple[MapPoint, ...]

    def __post_init__(self) -> None:
        if not self.path_id or not self.from_location_id or not self.to_location_id:
            raise WorldSpecValidationError("Map paths require non-empty ids and endpoints.")
        normalized = tuple(
            _point(item, label=f"map path {self.path_id} point")
            for item in self.points
        )
        if len(normalized) < 2:
            raise WorldSpecValidationError(
                f"Map path {self.path_id} requires at least two points."
            )
        object.__setattr__(self, "points", normalized)


@dataclass(frozen=True)
class MapLocationNodeSpec:
    location_id: str
    x: float
    y: float
    click_radius: float
    icon_key: str
    label_offset: MapPoint = (0.0, 0.0)

    def __post_init__(self) -> None:
        if not self.location_id or not self.icon_key:
            raise WorldSpecValidationError("Map location nodes require ids and icon keys.")
        position = _point((self.x, self.y), label=f"map node {self.location_id}")
        if isinstance(self.click_radius, bool) or not isinstance(
            self.click_radius, (int, float)
        ):
            raise WorldSpecValidationError(
                f"Map node {self.location_id} click_radius must be a number."
            )
        radius = float(self.click_radius)
        if not math.isfinite(radius) or radius <= 0:
            raise WorldSpecValidationError(
                f"Map node {self.location_id} click_radius must be positive."
            )
        object.__setattr__(self, "x", position[0])
        object.__setattr__(self, "y", position[1])
        object.__setattr__(self, "click_radius", radius)
        object.__setattr__(
            self,
            "label_offset",
            _point(self.label_offset, label=f"map node {self.location_id} label_offset"),
        )


@dataclass(frozen=True)
class SceneHotspotSpec:
    hotspot_id: str
    shape: str
    target_object_id: str
    x: float
    y: float
    width: float | None = None
    height: float | None = None
    radius: float | None = None
    label: LocalizedText = field(default_factory=dict)
    log_code: str = "hotspot_select"

    def __post_init__(self) -> None:
        if self.shape not in {"circle", "rectangle"}:
            raise WorldSpecValidationError("Scene hotspot shape must be circle or rectangle.")
        object.__setattr__(self, "label", _freeze(self.label))


@dataclass(frozen=True)
class SceneLayoutSpec:
    location_id: str
    width: float
    height: float
    participant_spawn: MapPoint
    resident_slots: tuple[MapPoint, ...]
    interaction_point_positions: Mapping[str, MapPoint]
    hotspots: tuple[SceneHotspotSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.location_id:
            raise WorldSpecValidationError("Scene layouts require a location_id.")
        for label, value in (("width", self.width), ("height", self.height)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise WorldSpecValidationError(
                    f"Scene {self.location_id} {label} must be positive."
                )
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "height", float(self.height))
        object.__setattr__(
            self,
            "participant_spawn",
            _point(
                self.participant_spawn,
                label=f"scene {self.location_id} participant_spawn",
            ),
        )
        object.__setattr__(
            self,
            "resident_slots",
            tuple(
                _point(item, label=f"scene {self.location_id} resident slot")
                for item in self.resident_slots
            ),
        )
        object.__setattr__(
            self,
            "interaction_point_positions",
            _freeze(
                {
                    key: _point(
                        value,
                        label=f"scene {self.location_id} object {key}",
                    )
                    for key, value in self.interaction_point_positions.items()
                }
            ),
        )
        object.__setattr__(self, "hotspots", tuple(self.hotspots))


@dataclass(frozen=True)
class MapSpec:
    map_id: str
    version: str
    width: float
    height: float
    background: Mapping[str, str]
    land_polygon: tuple[MapPoint, ...]
    paths: Mapping[str, MapPathSpec]
    location_nodes: Mapping[str, MapLocationNodeSpec]
    scene_layouts: Mapping[str, SceneLayoutSpec]

    def __post_init__(self) -> None:
        if not self.map_id or not self.version:
            raise WorldSpecValidationError("MapSpec requires map_id and version.")
        for label, value in (("width", self.width), ("height", self.height)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise WorldSpecValidationError(f"Map {label} must be positive.")
        polygon = tuple(
            _point(item, label=f"map {self.map_id} land polygon")
            for item in self.land_polygon
        )
        if len(polygon) < 3:
            raise WorldSpecValidationError("Map land_polygon requires at least 3 points.")
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "height", float(self.height))
        object.__setattr__(self, "background", _freeze(self.background))
        object.__setattr__(self, "land_polygon", polygon)
        object.__setattr__(self, "paths", _freeze(self.paths))
        object.__setattr__(self, "location_nodes", _freeze(self.location_nodes))
        object.__setattr__(self, "scene_layouts", _freeze(self.scene_layouts))


@dataclass(frozen=True)
class VisualAssetSpec:
    """Immutable metadata for one pack-owned raster asset."""

    asset_key: str
    file_name: str
    mime_type: str
    width: int
    height: int
    sha256: str
    source: str
    license: str

    def __post_init__(self) -> None:
        if not self.asset_key or not self.file_name:
            raise WorldSpecValidationError("Visual assets require a key and filename.")
        if self.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise WorldSpecValidationError("Visual asset MIME type is unsupported.")
        if self.width < 1 or self.height < 1:
            raise WorldSpecValidationError("Visual asset dimensions must be positive.")
        if len(self.sha256) != 64:
            raise WorldSpecValidationError("Visual asset sha256 must contain 64 hex characters.")
        if not self.source.strip() or not self.license.strip():
            raise WorldSpecValidationError("Visual assets require source and license metadata.")


@dataclass(frozen=True)
class VisualSlotSpec:
    """A semantic visual slot. ``asset_key=None`` intentionally uses a fallback."""

    slot_id: str
    slot_type: VisualSlotType
    target_id: str
    asset_key: str | None
    fallback_palette_key: str
    fallback_title: LocalizedText
    fallback_description: LocalizedText

    def __post_init__(self) -> None:
        if not self.slot_id or not self.target_id or not self.fallback_palette_key:
            raise WorldSpecValidationError("Visual slots require ids and fallback metadata.")
        object.__setattr__(self, "fallback_title", _freeze(self.fallback_title))
        object.__setattr__(self, "fallback_description", _freeze(self.fallback_description))


@dataclass(frozen=True)
class VisualSpec:
    visual_version: str
    visual_assets: Mapping[str, VisualAssetSpec]
    visual_slots: Mapping[str, VisualSlotSpec]

    def __post_init__(self) -> None:
        if not self.visual_version:
            raise WorldSpecValidationError("VisualSpec requires visual_version.")
        object.__setattr__(self, "visual_assets", _freeze(self.visual_assets))
        object.__setattr__(self, "visual_slots", _freeze(self.visual_slots))


@dataclass(frozen=True)
class EventActionContentSpec:
    action_id: str
    label: LocalizedText
    requires_text: bool
    outcome_key: str
    follow_up_event_id: str | None = None
    memory_text: LocalizedText | None = None
    memory_owner_agent_id: int | None = None
    relationship_effect: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not self.outcome_key:
            raise WorldSpecValidationError("Event actions require ids and outcome keys.")
        if not isinstance(self.requires_text, bool):
            raise WorldSpecValidationError("Event action requires_text must be boolean.")
        object.__setattr__(self, "label", _freeze(self.label))
        if self.memory_text is not None:
            object.__setattr__(self, "memory_text", _freeze(self.memory_text))
        if self.relationship_effect is not None:
            object.__setattr__(
                self,
                "relationship_effect",
                _freeze(self.relationship_effect),
            )


@dataclass(frozen=True)
class BehavioralEventActionContentSpec:
    """One data-owned action in a multi-stage behavioral event.

    The fields are deliberately descriptive.  Content can select a next stage,
    annotate the raw action, request a bounded goal update, and provide a static
    NPC line, but it cannot execute code or issue database writes.
    """

    action_id: str
    label: LocalizedText
    requires_text: bool
    action_type: str
    next_stage_id: str | None
    terminal: bool
    outcome_code: str
    action_minutes: int = 5
    target_type: str | None = None
    target_id: str | None = None
    target_agent_id: int | None = None
    target_location_id: str | None = None
    state_updates: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    npc_response: Mapping[str, Any] | None = None
    goal_effect: Mapping[str, Any] | None = None
    effects: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id or not self.action_type or not self.outcome_code:
            raise WorldSpecValidationError(
                "Behavioral event actions require ids, action types, and outcomes."
            )
        if not isinstance(self.requires_text, bool) or not isinstance(self.terminal, bool):
            raise WorldSpecValidationError(
                "Behavioral event action flags must be boolean."
            )
        if self.action_minutes < 0:
            raise WorldSpecValidationError(
                "Behavioral event action_minutes cannot be negative."
            )
        object.__setattr__(self, "label", _freeze(self.label))
        object.__setattr__(self, "state_updates", _freeze(self.state_updates))
        object.__setattr__(self, "metadata", _freeze(self.metadata))
        if self.npc_response is not None:
            object.__setattr__(self, "npc_response", _freeze(self.npc_response))
        if self.goal_effect is not None:
            object.__setattr__(self, "goal_effect", _freeze(self.goal_effect))
        object.__setattr__(
            self,
            "effects",
            tuple(_freeze(effect) for effect in self.effects),
        )


@dataclass(frozen=True)
class BehavioralEventStageContentSpec:
    """One participant-visible stage in a config-driven event."""

    stage_id: str
    title: LocalizedText
    stimulus: LocalizedText
    actions: tuple[BehavioralEventActionContentSpec, ...]

    def __post_init__(self) -> None:
        if not self.stage_id or not self.actions:
            raise WorldSpecValidationError(
                "Behavioral event stages require an id and at least one action."
            )
        object.__setattr__(self, "title", _freeze(self.title))
        object.__setattr__(self, "stimulus", _freeze(self.stimulus))
        object.__setattr__(self, "actions", tuple(self.actions))


@dataclass(frozen=True)
class EventContentSpec:
    event_id: str
    event_type: str
    version: str
    title: LocalizedText
    stimulus: LocalizedText
    location_ids: tuple[str, ...]
    event_pool_ids: tuple[str, ...]
    trigger_type: str
    time_window: tuple[int, int] | None
    weight: float
    cooldown_minutes: int
    max_occurrences: int
    prerequisites: Mapping[str, Any]
    exclusion_flags: Mapping[str, Any]
    actions: tuple[EventActionContentSpec, ...]
    renderer_key: str = "declarative_event"
    initial_stage_id: str | None = None
    stages: tuple[BehavioralEventStageContentSpec, ...] = ()
    logging_config: Mapping[str, Any] = field(default_factory=dict)
    llm_context: Mapping[str, Any] = field(default_factory=dict)
    trigger_conditions: Mapping[str, Any] = field(default_factory=dict)
    social_publications: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type or not self.version:
            raise WorldSpecValidationError("Event content requires id, type, and version.")
        object.__setattr__(self, "title", _freeze(self.title))
        object.__setattr__(self, "stimulus", _freeze(self.stimulus))
        object.__setattr__(self, "location_ids", tuple(self.location_ids))
        object.__setattr__(self, "event_pool_ids", tuple(self.event_pool_ids))
        object.__setattr__(self, "prerequisites", _freeze(self.prerequisites))
        object.__setattr__(self, "exclusion_flags", _freeze(self.exclusion_flags))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "logging_config", _freeze(self.logging_config))
        object.__setattr__(self, "llm_context", _freeze(self.llm_context))
        object.__setattr__(self, "trigger_conditions", _freeze(self.trigger_conditions))
        object.__setattr__(
            self,
            "social_publications",
            tuple(_freeze(item) for item in self.social_publications),
        )


@dataclass(frozen=True)
class CalendarSpec:
    total_days: int
    day_start_minute: int
    day_end_minute: int
    rollover: RolloverPolicy = "clamp"

    def __post_init__(self) -> None:
        if isinstance(self.total_days, bool) or self.total_days < 1:
            raise WorldSpecValidationError("calendar.total_days must be at least 1.")
        if not 0 <= self.day_start_minute <= 1439:
            raise WorldSpecValidationError(
                "calendar.day_start_minute must be between 0 and 1439."
            )
        if not 0 <= self.day_end_minute <= 1439:
            raise WorldSpecValidationError(
                "calendar.day_end_minute must be between 0 and 1439."
            )
        if self.day_start_minute >= self.day_end_minute:
            raise WorldSpecValidationError(
                "calendar.day_start_minute must be before day_end_minute."
            )
        if self.rollover not in {"clamp", "next_day"}:
            raise WorldSpecValidationError(
                "calendar.rollover must be clamp or next_day."
            )
        if self.rollover == "clamp" and self.total_days != 1:
            raise WorldSpecValidationError(
                "calendar.rollover=clamp is only valid for a one-day world."
            )


@dataclass(frozen=True)
class LocationSpec:
    location_id: str
    name: LocalizedText
    description: LocalizedText
    scene_type: str
    connected_location_ids: tuple[str, ...]
    interaction_points: tuple[Mapping[str, Any], ...]
    version: str
    opening_hours: Mapping[str, Any] = field(
        default_factory=lambda: {"always_open": True}
    )
    allowed_actions: tuple[str, ...] = ()
    event_pool_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.location_id:
            raise WorldSpecValidationError("location_id cannot be empty.")
        if not self.name.get("en"):
            raise WorldSpecValidationError(
                f"Location {self.location_id} requires an English name."
            )
        if not self.description.get("en"):
            raise WorldSpecValidationError(
                f"Location {self.location_id} requires an English description."
            )
        object.__setattr__(self, "name", _freeze(self.name))
        object.__setattr__(self, "description", _freeze(self.description))
        object.__setattr__(
            self,
            "connected_location_ids",
            tuple(self.connected_location_ids),
        )
        object.__setattr__(
            self,
            "interaction_points",
            tuple(_freeze(item) for item in self.interaction_points),
        )
        object.__setattr__(self, "opening_hours", _freeze(self.opening_hours))
        object.__setattr__(self, "allowed_actions", tuple(self.allowed_actions))
        object.__setattr__(self, "event_pool_ids", tuple(self.event_pool_ids))


@dataclass(frozen=True)
class ScheduleBlock:
    state_id: str
    start_minute: int
    end_minute: int
    location_id: str
    activity: LocalizedText
    goal: LocalizedText
    days: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if not self.state_id:
            raise WorldSpecValidationError("schedule state_id cannot be empty.")
        if not 0 <= self.start_minute <= self.end_minute <= 1439:
            raise WorldSpecValidationError(
                f"Schedule {self.state_id} must stay within minutes 0..1439."
            )
        if not self.location_id:
            raise WorldSpecValidationError(
                f"Schedule {self.state_id} requires a location_id."
            )
        if not self.activity.get("en") or not self.goal.get("en"):
            raise WorldSpecValidationError(
                f"Schedule {self.state_id} requires English activity and goal text."
            )
        if self.days is not None:
            normalized_days = frozenset(self.days)
            if not normalized_days or any(
                isinstance(day, bool) or day < 1 for day in normalized_days
            ):
                raise WorldSpecValidationError(
                    f"Schedule {self.state_id} has invalid days."
                )
            object.__setattr__(self, "days", normalized_days)
        object.__setattr__(self, "activity", _freeze(self.activity))
        object.__setattr__(self, "goal", _freeze(self.goal))


AUTONOMY_INTENT_TYPES = frozenset(
    {
        "idle",
        "inspect_object",
        "socialize_resident",
        "greet_participant",
        "visit_adjacent_location",
    }
)


@dataclass(frozen=True)
class AutonomySpec:
    """Bounded, data-owned defaults for ordinary resident activity."""

    enabled: bool = False
    allowed_intents: tuple[str, ...] = tuple(sorted(AUTONOMY_INTENT_TYPES))
    preferred_location_ids: tuple[str, ...] = ()
    free_time_state_ids: tuple[str, ...] = ()
    action_cooldown_minutes: int = 10
    idle_weight: int = 8
    inspect_weight: int = 24
    socialize_weight: int = 22
    greet_weight: int = 16
    travel_weight: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise WorldSpecValidationError("autonomy.enabled must be a boolean.")
        intents = tuple(self.allowed_intents)
        if len(set(intents)) != len(intents):
            raise WorldSpecValidationError("autonomy.allowed_intents must be unique.")
        unsupported = sorted(set(intents) - AUTONOMY_INTENT_TYPES)
        if unsupported:
            raise WorldSpecValidationError(
                f"Unsupported autonomy intent(s): {', '.join(unsupported)}."
            )
        if isinstance(self.action_cooldown_minutes, bool) or not 0 <= self.action_cooldown_minutes <= 240:
            raise WorldSpecValidationError(
                "autonomy.action_cooldown_minutes must be between 0 and 240."
            )
        for field_name in (
            "idle_weight",
            "inspect_weight",
            "socialize_weight",
            "greet_weight",
            "travel_weight",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not 0 <= value <= 100:
                raise WorldSpecValidationError(
                    f"autonomy.{field_name} must be between 0 and 100."
                )
        object.__setattr__(self, "allowed_intents", intents)
        object.__setattr__(
            self, "preferred_location_ids", tuple(self.preferred_location_ids)
        )
        object.__setattr__(self, "free_time_state_ids", tuple(self.free_time_state_ids))


@dataclass(frozen=True)
class ResidentSpec:
    agent_id: int
    name: str
    role: LocalizedText
    background: LocalizedText
    schedule: tuple[ScheduleBlock, ...]
    adult_age_range: str = "adult"
    home_location_id: str | None = None
    public_summary: LocalizedText = field(default_factory=dict)
    avatar_key: str = "resident_default"
    marker_color_key: str = "resident_teal"
    profile: Mapping[str, Any] = field(default_factory=dict)
    profile_version: str = "legacy-profile-v1"
    prompt_version: str = "legacy-prompt-v1"
    autonomy: AutonomySpec = field(default_factory=AutonomySpec)

    def __post_init__(self) -> None:
        if isinstance(self.agent_id, bool) or self.agent_id < 1:
            raise WorldSpecValidationError("resident agent_id must be positive.")
        if not self.name:
            raise WorldSpecValidationError(
                f"Resident {self.agent_id} requires a name."
            )
        if not self.role.get("en") or not self.background.get("en"):
            raise WorldSpecValidationError(
                f"Resident {self.agent_id} requires English role and background text."
            )
        if not self.schedule:
            raise WorldSpecValidationError(
                f"Resident {self.agent_id} requires at least one schedule block."
            )
        object.__setattr__(self, "role", _freeze(self.role))
        object.__setattr__(self, "background", _freeze(self.background))
        object.__setattr__(self, "schedule", tuple(self.schedule))
        object.__setattr__(self, "public_summary", _freeze(self.public_summary))
        object.__setattr__(self, "profile", _freeze(self.profile))


@dataclass(frozen=True)
class WorldSpec:
    world_version: str
    scenario_pack_version: str
    start_location_id: str
    calendar: CalendarSpec
    locations: Mapping[str, LocationSpec]
    residents: Mapping[int, ResidentSpec]
    action_minutes: Mapping[str, int]
    content_pack_version: str | None = None
    event_pack_version: str | None = None
    map_spec: MapSpec | None = None
    event_specs: Mapping[str, EventContentSpec] = field(default_factory=dict)
    visual_spec: VisualSpec | None = None
    content_schema_version: str = "content-pack-v1"
    experience: Mapping[str, Any] = field(default_factory=dict)
    systems: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.world_version:
            raise WorldSpecValidationError("world_version cannot be empty.")
        if not self.scenario_pack_version:
            raise WorldSpecValidationError("scenario_pack_version cannot be empty.")
        if not self.locations:
            raise WorldSpecValidationError("A world requires at least one location.")
        if not self.residents:
            raise WorldSpecValidationError("A world requires at least one resident.")
        for action_type, minutes in self.action_minutes.items():
            if not action_type or isinstance(minutes, bool) or minutes < 0:
                raise WorldSpecValidationError(
                    "action_minutes must map non-empty actions to non-negative integers."
                )
        object.__setattr__(self, "locations", _freeze(self.locations))
        object.__setattr__(self, "residents", _freeze(self.residents))
        object.__setattr__(self, "action_minutes", _freeze(self.action_minutes))
        object.__setattr__(self, "event_specs", _freeze(self.event_specs))
        object.__setattr__(self, "experience", _freeze(self.experience))
        object.__setattr__(self, "systems", _freeze(self.systems))


def world_spec_from_legacy(
    *,
    world_version: str,
    scenario_pack_version: str,
    start_location_id: str,
    calendar: CalendarSpec,
    locations: Mapping[str, Mapping[str, Any]],
    residents: Mapping[int, Mapping[str, Any]],
    action_minutes: Mapping[str, int],
) -> WorldSpec:
    """Adapt the existing v0.3 dictionary content without changing it."""

    location_specs: dict[str, LocationSpec] = {}
    for location_key, raw_location in locations.items():
        location_id = str(raw_location["location_id"])
        location_specs[str(location_key)] = LocationSpec(
            location_id=location_id,
            name=dict(raw_location["name"]),
            description=dict(raw_location["description"]),
            scene_type=str(raw_location["scene_type"]),
            connected_location_ids=tuple(raw_location["connected_location_ids"]),
            interaction_points=tuple(
                dict(item) for item in raw_location["interaction_points"]
            ),
            version=str(raw_location.get("version", world_version)),
        )

    resident_specs: dict[int, ResidentSpec] = {}
    for resident_key, raw_resident in residents.items():
        blocks: list[ScheduleBlock] = []
        for raw_block in raw_resident["schedule"]:
            if len(raw_block) != 6:
                raise WorldSpecValidationError(
                    f"Resident {resident_key} has a malformed legacy schedule block."
                )
            start, end, location_id, activity, goal, state_id = raw_block
            blocks.append(
                ScheduleBlock(
                    state_id=str(state_id),
                    start_minute=int(start),
                    end_minute=int(end),
                    location_id=str(location_id),
                    activity=dict(activity),
                    goal=dict(goal),
                )
            )
        agent_id = int(raw_resident["agent_id"])
        resident_specs[int(resident_key)] = ResidentSpec(
            agent_id=agent_id,
            name=str(raw_resident["name"]),
            role=dict(raw_resident["role"]),
            background=dict(raw_resident["background"]),
            schedule=tuple(blocks),
        )

    return WorldSpec(
        world_version=world_version,
        scenario_pack_version=scenario_pack_version,
        start_location_id=start_location_id,
        calendar=calendar,
        locations=location_specs,
        residents=resident_specs,
        action_minutes=dict(action_minutes),
    )
