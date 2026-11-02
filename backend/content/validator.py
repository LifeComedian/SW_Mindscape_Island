"""Schema and cross-reference validation for editable island content packs."""

from __future__ import annotations

import argparse
import json
import math
import re
from typing import Any, Mapping, NoReturn, Sequence

from world.graph import can_travel, validate_location_graph
from world.emergence_contracts import (
    ACTIVITY_COMPLEXITIES,
    ATOMIC_EFFECT_TYPES,
    CANDIDATE_SOURCE_TYPES,
    KNOWLEDGE_SOURCE_TYPES,
    KNOWLEDGE_VISIBILITY_LEVELS,
    MAX_CONCURRENT_PLAYER_FACING_EVENTS,
    MAX_DIRECT_AGENT_INVITATIONS_PER_DAY,
    MAX_NEW_MAJOR_EVENTS_PER_DAY,
    MAX_NEW_PLAYER_FACING_EVENTS_PER_DAY,
    MAX_OPEN_COMMITMENTS_PER_ACTOR,
    MAX_PLAYER_CHOICES_PER_STAGE,
    MAX_STAGES_PER_EVENT,
    MODULAR_SYSTEMS_CONTRACT_VERSION,
    PLAN_STATES,
    ActivityRecipeContractSpec,
    AffordanceContractSpec,
    AtomicActionContractSpec,
    AtomicActionInputSpec,
    CandidatePolicySpec,
    EmergenceBudgetSpec,
    KnowledgePolicySpec,
    ModularSystemsContractSpec,
    PlanPolicySpec,
    StageRecipeContractSpec,
)
from world.schedules import resolve_resident_schedule, validate_resident_schedules
from world.specs import (
    AUTONOMY_INTENT_TYPES,
    AutonomySpec,
    BehavioralEventActionContentSpec,
    BehavioralEventStageContentSpec,
    CalendarSpec,
    EventActionContentSpec,
    EventContentSpec,
    LocationSpec,
    MapLocationNodeSpec,
    MapPathSpec,
    MapSpec,
    ResidentSpec,
    SceneHotspotSpec,
    SceneLayoutSpec,
    ScheduleBlock,
    WorldSpec,
    WorldSpecValidationError,
    VisualAssetSpec,
    VisualSlotSpec,
    VisualSpec,
)
from content.visual_assets import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_PIXELS,
    MAX_IMAGE_WIDTH,
    MAX_VISUAL_ASSETS,
    SHA256_RE,
    VisualAssetValidationError,
    validate_asset_file_name,
)


SCHEMA_V1 = "content-pack-v1"
SCHEMA_V2 = "content-pack-v2"
SCHEMA_V3 = "content-pack-v3"
SCHEMA_V4 = "content-pack-v4"
SCHEMA_V5 = "content-pack-v5"
SUPPORTED_SCHEMA_VERSIONS = frozenset(
    {SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5}
)
REQUIRED_CONTENT_FILES_V1 = ("map", "locations", "residents", "events")
REQUIRED_CONTENT_FILES_V2 = (*REQUIRED_CONTENT_FILES_V1, "visuals")
REQUIRED_CONTENT_FILES_V4 = (*REQUIRED_CONTENT_FILES_V2, "systems")
SUPPORTED_LANGUAGES = frozenset({"en", "zh-CN"})
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")

MAP_ICON_KEYS = frozenset(
    {"cottage", "homes", "square", "harbor", "restaurant", "shop", "lighthouse"}
)
AVATAR_KEYS = frozenset(
    {"mira", "leo", "chen", "nova", "kai", "resident_default"}
)
MARKER_COLOR_KEYS = frozenset(
    {"resident_teal", "resident_blue", "resident_amber", "resident_rose", "resident_violet"}
)
VISUAL_PALETTE_KEYS = frozenset(
    {"ocean_teal", "sand_warm", "forest_green", "harbor_blue", "sunset_rose", "neutral_stone"}
)
INTERACTION_RENDERER_KEYS = frozenset(
    {"desk", "notice", "garden", "table", "books", "bench", "railing", "counter", "shelf", "display", "landmark", "seat"}
)
ALLOWED_ACTIONS = frozenset(
    {"move", "observe", "approach", "wait", "end_day", "end_conversation", "event_action"}
)
BACKGROUND_KEYS = {
    "style_key": frozenset({"island_day", "island_sunset", "minimal"}),
    "sea_color_key": frozenset({"sea_blue", "sea_teal"}),
    "land_color_key": frozenset({"land_green", "land_sand"}),
}
TRIGGER_TYPES = frozenset({"on_location_enter", "on_world_tick", "on_time_window", "on_object_interact"})
FLOW_EFFECT_TYPES = frozenset({
    "advance_time", "goto_node", "complete_flow", "start_event",
    "schedule_event", "set_flag", "goal_update", "relationship_delta",
    "add_memory", "move_participant", "show_message",
})
OUTCOME_KEYS = frozenset(
    {"complete", "leave", "remember", "relationship_delta", "schedule_follow_up"}
)
RELATIONSHIP_DELTA_KEYS = frozenset(
    {"familiarity_delta", "trust_delta", "warmth_delta", "tension_delta"}
)
RESERVED_EVENT_HANDLER_KEYS = frozenset(
    {
        ("neutral_greeting", "neutral-greeting-v1"),
        ("restaurant_seating", "restaurant-seating-v03-runtime-v1"),
        ("restaurant_conflict", "restaurant-conflict-v03-runtime-v1"),
        (
            "restaurant_conflict_follow_up",
            "restaurant-followup-v03-runtime-v1",
        ),
    }
)


class ContentPackValidationError(WorldSpecValidationError):
    """A content error with enough context for a non-core editor to fix it."""

    def __init__(self, message: str, *, file: str, json_path: str) -> None:
        self.file = file
        self.json_path = json_path
        self.reason = message
        super().__init__(f"{file}:{json_path}: {message}")


def _fail(message: str, *, file: str, path: str) -> NoReturn:
    raise ContentPackValidationError(message, file=file, json_path=path)


def _object(value: Any, *, file: str, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("must be a JSON object", file=file, path=path)
    return value


def _array(value: Any, *, file: str, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("must be a JSON array", file=file, path=path)
    return value


def _keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    file: str,
    path: str,
) -> None:
    missing = sorted(required - set(value))
    if missing:
        _fail(f"missing required field(s): {', '.join(missing)}", file=file, path=path)
    unknown = sorted(set(value) - required - optional)
    if unknown:
        _fail(f"unknown field(s): {', '.join(unknown)}", file=file, path=path)


def _string(value: Any, *, file: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("must be a non-empty string", file=file, path=path)
    return value


def _identifier(value: Any, *, file: str, path: str) -> str:
    result = _string(value, file=file, path=path)
    if not ID_RE.fullmatch(result):
        _fail(
            "must be URL-safe and contain only letters, digits, dot, underscore, or hyphen",
            file=file,
            path=path,
        )
    return result


def _integer(
    value: Any,
    *,
    file: str,
    path: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("must be an integer", file=file, path=path)
    if minimum is not None and value < minimum:
        _fail(f"must be at least {minimum}", file=file, path=path)
    if maximum is not None and value > maximum:
        _fail(f"must be at most {maximum}", file=file, path=path)
    return value


def _number(
    value: Any,
    *,
    file: str,
    path: str,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("must be a number", file=file, path=path)
    result = float(value)
    if not math.isfinite(result):
        _fail("must be finite", file=file, path=path)
    if minimum is not None and (
        result < minimum or (exclusive_minimum and result == minimum)
    ):
        operator = "greater than" if exclusive_minimum else "at least"
        _fail(f"must be {operator} {minimum}", file=file, path=path)
    if maximum is not None and result > maximum:
        _fail(f"must be at most {maximum}", file=file, path=path)
    return result


def _boolean(value: Any, *, file: str, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("must be a boolean", file=file, path=path)
    return value


def _unique(values: Sequence[Any], *, label: str, file: str, path: str) -> None:
    seen: set[Any] = set()
    duplicate: Any | None = None
    for value in values:
        if value in seen:
            duplicate = value
            break
        seen.add(value)
    if duplicate is not None:
        _fail(f"duplicate {label}: {duplicate!r}", file=file, path=path)


def _identifier_array(
    value: Any,
    *,
    file: str,
    path: str,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    items = _array(value, file=file, path=path)
    if not allow_empty and not items:
        _fail("must not be empty", file=file, path=path)
    result = tuple(
        _identifier(item, file=file, path=f"{path}[{index}]")
        for index, item in enumerate(items)
    )
    _unique(result, label="id", file=file, path=path)
    return result


def _localized(value: Any, *, file: str, path: str) -> dict[str, str]:
    item = _object(value, file=file, path=path)
    unknown = sorted(set(item) - SUPPORTED_LANGUAGES)
    if unknown:
        _fail(
            f"unsupported language key(s): {', '.join(unknown)}",
            file=file,
            path=path,
        )
    missing = sorted(SUPPORTED_LANGUAGES - set(item))
    if missing:
        _fail(
            f"missing language key(s): {', '.join(missing)}",
            file=file,
            path=path,
        )
    return {
        language: _string(item[language], file=file, path=f"{path}.{language}")
        for language in sorted(SUPPORTED_LANGUAGES)
    }


def _localized_array(value: Any, *, file: str, path: str) -> tuple[dict[str, str], ...]:
    items = _array(value, file=file, path=path)
    if not items:
        _fail("must contain at least one item", file=file, path=path)
    return tuple(
        _localized(item, file=file, path=f"{path}[{index}]")
        for index, item in enumerate(items)
    )


def _safe_config_value(
    value: Any,
    *,
    file: str,
    path: str,
    depth: int = 0,
    max_depth: int = 5,
) -> Any:
    """Validate bounded inert JSON used by behavioral event annotations."""

    # Allow five levels for nested action consequences.
    if depth > max_depth:
        _fail("configuration nesting is too deep", file=file, path=path)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("number must be finite", file=file, path=path)
        return value
    if isinstance(value, str):
        if len(value) > 2000:
            _fail("string must not exceed 2000 characters", file=file, path=path)
        return value
    if isinstance(value, list):
        limit = 256 if file == "systems.json" and path in {"$.action_definitions", "$.affordances"} else 40
        if len(value) > limit:
            _fail(f"array must not contain more than {limit} items", file=file, path=path)
        return [
            _safe_config_value(item, file=file, path=f"{path}[{index}]", depth=depth + 1, max_depth=max_depth)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        if len(value) > 50:
            _fail("object must not contain more than 50 fields", file=file, path=path)
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _identifier(key, file=file, path=f"{path}.<key>")
            result[normalized_key] = _safe_config_value(
                item,
                file=file,
                path=f"{path}.{normalized_key}",
                depth=depth + 1,
                max_depth=max_depth,
            )
        return result
    _fail("must contain only inert JSON values", file=file, path=path)


def _point(value: Any, *, file: str, path: str) -> tuple[float, float]:
    items = _array(value, file=file, path=path)
    if len(items) != 2:
        _fail("must contain exactly two coordinates", file=file, path=path)
    return (
        _number(items[0], file=file, path=f"{path}[0]"),
        _number(items[1], file=file, path=f"{path}[1]"),
    )


def _inside(
    point: tuple[float, float],
    *,
    width: float,
    height: float,
    file: str,
    path: str,
) -> None:
    if not 0 <= point[0] <= width or not 0 <= point[1] <= height:
        _fail(
            f"coordinate must stay inside 0..{width} by 0..{height}",
            file=file,
            path=path,
        )


def validate_manifest_for_loading(manifest: Any) -> dict[str, str]:
    file = "manifest.json"
    item = _object(manifest, file=file, path="$")
    _keys(
        item,
        required={
            "content_pack_version",
            "world_version",
            "event_pack_version",
            "schema_version",
            "default_language",
            "supported_languages",
            "start_location_id",
            "calendar",
            "action_minutes",
            "files",
        },
        optional={"authoring_only", "experience"},
        file=file,
        path="$",
    )
    if "authoring_only" in item:
        _boolean(item["authoring_only"], file=file, path="$.authoring_only")
    _identifier(item["content_pack_version"], file=file, path="$.content_pack_version")
    _identifier(item["world_version"], file=file, path="$.world_version")
    _identifier(item["event_pack_version"], file=file, path="$.event_pack_version")
    schema_version = item["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _fail(
            "unsupported schema_version; expected content-pack-v1 through content-pack-v5",
            file=file,
            path="$.schema_version",
        )
    default_language = _string(
        item["default_language"], file=file, path="$.default_language"
    )
    languages = _array(item["supported_languages"], file=file, path="$.supported_languages")
    if any(not isinstance(language, str) for language in languages):
        _fail("must contain language strings", file=file, path="$.supported_languages")
    _unique(languages, label="language", file=file, path="$.supported_languages")
    if set(languages) != SUPPORTED_LANGUAGES:
        _fail(
            f"{schema_version} requires exactly en and zh-CN",
            file=file,
            path="$.supported_languages",
        )
    if default_language not in languages:
        _fail(
            "default_language must appear in supported_languages",
            file=file,
            path="$.default_language",
        )
    _identifier(item["start_location_id"], file=file, path="$.start_location_id")

    calendar = _object(item["calendar"], file=file, path="$.calendar")
    _keys(
        calendar,
        required={"total_days", "day_start_minute", "day_end_minute", "rollover"},
        file=file,
        path="$.calendar",
    )
    _integer(
        calendar["total_days"],
        file=file,
        path="$.calendar.total_days",
        minimum=1,
        maximum=14 if schema_version in {SCHEMA_V4, SCHEMA_V5} else None,
    )
    _integer(calendar["day_start_minute"], file=file, path="$.calendar.day_start_minute", minimum=0, maximum=1439)
    _integer(calendar["day_end_minute"], file=file, path="$.calendar.day_end_minute", minimum=0, maximum=1439)
    if calendar["rollover"] not in {"clamp", "next_day"}:
        _fail("must be clamp or next_day", file=file, path="$.calendar.rollover")

    action_minutes = _object(item["action_minutes"], file=file, path="$.action_minutes")
    if not action_minutes:
        _fail("must not be empty", file=file, path="$.action_minutes")
    for action, minutes in action_minutes.items():
        _identifier(action, file=file, path=f"$.action_minutes.{action}")
        _integer(minutes, file=file, path=f"$.action_minutes.{action}", minimum=0)

    if schema_version in {SCHEMA_V4, SCHEMA_V5}:
        required_files = REQUIRED_CONTENT_FILES_V4
    elif schema_version in {SCHEMA_V2, SCHEMA_V3}:
        required_files = REQUIRED_CONTENT_FILES_V2
    else:
        required_files = REQUIRED_CONTENT_FILES_V1
    files = _object(item["files"], file=file, path="$.files")
    if set(files) != set(required_files):
        _fail(
            "files must contain exactly " + ", ".join(required_files),
            file=file,
            path="$.files",
        )
    resolved: dict[str, str] = {}
    for key in required_files:
        name = _string(files[key], file=file, path=f"$.files.{key}")
        if not FILE_NAME_RE.fullmatch(name) or "/" in name or "\\" in name or ".." in name:
            _fail(
                "must be a plain JSON filename without directories or '..'",
                file=file,
                path=f"$.files.{key}",
            )
        resolved[key] = name
    _unique(tuple(resolved.values()), label="content filename", file=file, path="$.files")
    if schema_version in {SCHEMA_V4, SCHEMA_V5}:
        experience = _object(item.get("experience"), file=file, path="$.experience")
        _keys(
            experience,
            required={
                "mode", "recommended_total_days", "final_day_departure_required",
                "departure_prompt", "behavior_audit_version",
            },
            optional={"rest_location_id"},
            file=file,
            path="$.experience",
        )
        if experience["mode"] != "open_exploration":
            _fail("must be open_exploration", file=file, path="$.experience.mode")
        _integer(experience["recommended_total_days"], file=file, path="$.experience.recommended_total_days", minimum=1, maximum=14)
        _boolean(experience["final_day_departure_required"], file=file, path="$.experience.final_day_departure_required")
        _localized(experience["departure_prompt"], file=file, path="$.experience.departure_prompt")
        _identifier(experience["behavior_audit_version"], file=file, path="$.experience.behavior_audit_version")
        if "rest_location_id" in experience:
            _identifier(experience["rest_location_id"], file=file, path="$.experience.rest_location_id")
    elif "experience" in item:
        _fail("experience requires content-pack-v4 or v5", file=file, path="$.experience")
    return resolved


def _parse_systems(
    document: Any,
    *,
    locations: Mapping[str, LocationSpec],
    schema_version: str = SCHEMA_V4,
) -> dict[str, Any]:
    """Validate reusable actions, affordances, activities, and bounded policy."""
    if schema_version == SCHEMA_V5:
        return _parse_modular_systems(document, locations=locations)
    file = "systems.json"
    root = _object(document, file=file, path="$")
    _keys(
        root,
        required={"action_definitions", "affordances", "activity_recipes", "emergence_policy"},
        file=file,
        path="$",
    )
    object_ids = {
        str(point["object_id"])
        for location in locations.values()
        for point in location.interaction_points
    }
    action_ids: list[str] = []
    for index, raw in enumerate(_array(root["action_definitions"], file=file, path="$.action_definitions")):
        path = f"$.action_definitions[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"action_id", "label", "actor_types", "target_types", "duration_minutes", "consequences"}, file=file, path=path)
        action_ids.append(_identifier(item["action_id"], file=file, path=f"{path}.action_id"))
        _localized(item["label"], file=file, path=f"{path}.label")
        actor_types = _identifier_array(item["actor_types"], file=file, path=f"{path}.actor_types", allow_empty=False)
        if set(actor_types) - {"participant", "resident"}:
            _fail("actor_types may contain only participant or resident", file=file, path=f"{path}.actor_types")
        target_types = _identifier_array(item["target_types"], file=file, path=f"{path}.target_types", allow_empty=False)
        if set(target_types) - {"none", "location", "object", "resident", "participant", "activity"}:
            _fail("contains an unsupported target type", file=file, path=f"{path}.target_types")
        _integer(item["duration_minutes"], file=file, path=f"{path}.duration_minutes", minimum=0, maximum=240)
        _array(item["consequences"], file=file, path=f"{path}.consequences")
    _unique(action_ids, label="action_id", file=file, path="$.action_definitions")

    affordance_ids: list[str] = []
    for index, raw in enumerate(_array(root["affordances"], file=file, path="$.affordances")):
        path = f"$.affordances[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"affordance_id", "action_id", "location_ids", "object_ids", "enabled"}, optional={"conditions"}, file=file, path=path)
        affordance_ids.append(_identifier(item["affordance_id"], file=file, path=f"{path}.affordance_id"))
        action_id = _identifier(item["action_id"], file=file, path=f"{path}.action_id")
        if action_id not in action_ids:
            _fail("references a missing action definition", file=file, path=f"{path}.action_id")
        for location_id in _identifier_array(item["location_ids"], file=file, path=f"{path}.location_ids"):
            if location_id not in locations:
                _fail("references a missing location", file=file, path=f"{path}.location_ids")
        for object_id in _identifier_array(item["object_ids"], file=file, path=f"{path}.object_ids"):
            if object_id not in object_ids:
                _fail("references a missing interaction point", file=file, path=f"{path}.object_ids")
        _boolean(item["enabled"], file=file, path=f"{path}.enabled")
    _unique(affordance_ids, label="affordance_id", file=file, path="$.affordances")

    recipe_ids: list[str] = []
    for index, raw in enumerate(_array(root["activity_recipes"], file=file, path="$.activity_recipes")):
        path = f"$.activity_recipes[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"recipe_id", "label", "location_ids", "action_ids", "min_participants", "max_participants", "duration_minutes"}, optional={"conditions", "board_post_template"}, file=file, path=path)
        recipe_ids.append(_identifier(item["recipe_id"], file=file, path=f"{path}.recipe_id"))
        _localized(item["label"], file=file, path=f"{path}.label")
        for location_id in _identifier_array(item["location_ids"], file=file, path=f"{path}.location_ids", allow_empty=False):
            if location_id not in locations:
                _fail("references a missing location", file=file, path=f"{path}.location_ids")
        for action_id in _identifier_array(item["action_ids"], file=file, path=f"{path}.action_ids", allow_empty=False):
            if action_id not in action_ids:
                _fail("references a missing action definition", file=file, path=f"{path}.action_ids")
        minimum = _integer(item["min_participants"], file=file, path=f"{path}.min_participants", minimum=1, maximum=20)
        maximum = _integer(item["max_participants"], file=file, path=f"{path}.max_participants", minimum=1, maximum=20)
        if minimum > maximum:
            _fail("min_participants must not exceed max_participants", file=file, path=path)
        _integer(item["duration_minutes"], file=file, path=f"{path}.duration_minutes", minimum=0, maximum=480)
        if "board_post_template" in item:
            _localized(item["board_post_template"], file=file, path=f"{path}.board_post_template")
    _unique(recipe_ids, label="recipe_id", file=file, path="$.activity_recipes")

    policy = _object(root["emergence_policy"], file=file, path="$.emergence_policy")
    _keys(policy, required={"policy_id", "policy_version", "max_agent_actions_per_tick", "max_invitations_per_tick", "max_activity_creations_per_tick", "max_event_chain_depth"}, file=file, path="$.emergence_policy")
    _identifier(policy["policy_id"], file=file, path="$.emergence_policy.policy_id")
    _identifier(policy["policy_version"], file=file, path="$.emergence_policy.policy_version")
    for key in ("max_agent_actions_per_tick", "max_invitations_per_tick", "max_activity_creations_per_tick", "max_event_chain_depth"):
        _integer(policy[key], file=file, path=f"$.emergence_policy.{key}", minimum=0, maximum=20)
    return dict(_safe_config_value(root, file=file, path="$"))


def _parse_atomic_conditions(value: Any, *, file: str, path: str) -> dict[str, Any]:
    item = _object(value, file=file, path=path)
    _keys(
        item,
        required=set(),
        optional={"location_open", "object_state_equals", "actor_state_equals", "requires_stage"},
        file=file,
        path=path,
    )
    result: dict[str, Any] = {}
    if "requires_stage" in item:
        result["requires_stage"] = _boolean(item["requires_stage"], file=file, path=f"{path}.requires_stage")
    if "location_open" in item:
        result["location_open"] = _boolean(
            item["location_open"], file=file, path=f"{path}.location_open"
        )
    for key in ("object_state_equals", "actor_state_equals"):
        if key not in item:
            continue
        state = _object(item[key], file=file, path=f"{path}.{key}")
        normalized: dict[str, Any] = {}
        for state_key, expected in state.items():
            normalized_key = _identifier(
                state_key, file=file, path=f"{path}.{key}.<key>"
            )
            if expected is not None and not isinstance(expected, (bool, int, float, str)):
                _fail(
                    "state comparison values must be scalar",
                    file=file,
                    path=f"{path}.{key}.{normalized_key}",
                )
            if isinstance(expected, float) and not math.isfinite(expected):
                _fail(
                    "state comparison number must be finite",
                    file=file,
                    path=f"{path}.{key}.{normalized_key}",
                )
            normalized[normalized_key] = expected
        result[key] = normalized
    return result


def _parse_atomic_inputs(value: Any, *, file: str, path: str) -> tuple[AtomicActionInputSpec, ...]:
    result: list[AtomicActionInputSpec] = []
    for index, raw in enumerate(_array(value, file=file, path=path)):
        input_path = f"{path}[{index}]"
        item = _object(raw, file=file, path=input_path)
        _keys(
            item,
            required={"input_id", "value_type", "required"},
            optional={"allowed_values", "minimum", "maximum", "max_length"},
            file=file,
            path=input_path,
        )
        value_type = _identifier(
            item["value_type"], file=file, path=f"{input_path}.value_type"
        )
        if value_type not in {"boolean", "integer", "identifier", "free_text", "object_command"}:
            _fail(
                "contains an unsupported input value type",
                file=file,
                path=f"{input_path}.value_type",
            )
        try:
            result.append(
                AtomicActionInputSpec(
                    input_id=_identifier(
                        item["input_id"], file=file, path=f"{input_path}.input_id"
                    ),
                    value_type=value_type,  # type: ignore[arg-type]
                    required=_boolean(
                        item["required"], file=file, path=f"{input_path}.required"
                    ),
                    allowed_values=_identifier_array(
                        item.get("allowed_values", []),
                        file=file,
                        path=f"{input_path}.allowed_values",
                    ),
                    minimum=(
                        _integer(
                            item["minimum"],
                            file=file,
                            path=f"{input_path}.minimum",
                        )
                        if "minimum" in item
                        else None
                    ),
                    maximum=(
                        _integer(
                            item["maximum"],
                            file=file,
                            path=f"{input_path}.maximum",
                        )
                        if "maximum" in item
                        else None
                    ),
                    max_length=(
                        _integer(
                            item["max_length"],
                            file=file,
                            path=f"{input_path}.max_length",
                            minimum=1,
                            maximum=180000 if value_type=="object_command" else 2000,
                        )
                        if "max_length" in item
                        else None
                    ),
                )
            )
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path=input_path)
    return tuple(result)


def _parse_atomic_consequences(
    value: Any, *, file: str, path: str
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_array(value, file=file, path=path)):
        effect_path = f"{path}[{index}]"
        item = _object(raw, file=file, path=effect_path)
        effect_type = _identifier(
            item.get("effect_type"), file=file, path=f"{effect_path}.effect_type"
        )
        if effect_type == "set_object_state":
            _keys(
                item,
                required={"effect_type", "state_key", "value"},
                file=file,
                path=effect_path,
            )
            state_key = _identifier(
                item["state_key"], file=file, path=f"{effect_path}.state_key"
            )
            normalized = {
                "effect_type": effect_type,
                "state_key": state_key,
                "value": _safe_config_value(
                    item["value"], file=file, path=f"{effect_path}.value"
                ),
            }
        elif effect_type == "set_world_flag":
            _keys(
                item,
                required={"effect_type", "flag_id", "value"},
                file=file,
                path=effect_path,
            )
            normalized = {
                "effect_type": effect_type,
                "flag_id": _identifier(
                    item["flag_id"], file=file, path=f"{effect_path}.flag_id"
                ),
                "value": _boolean(
                    item["value"], file=file, path=f"{effect_path}.value"
                ),
            }
        else:
            _fail(
                "contains an unsupported atomic effect type",
                file=file,
                path=f"{effect_path}.effect_type",
            )
        result.append(normalized)
    return tuple(result)


def _parse_modular_systems(
    document: Any,
    *,
    locations: Mapping[str, LocationSpec],
) -> dict[str, Any]:
    """Validate the inert M7 authoring contract without enabling runtime behavior."""

    file = "systems.json"
    root = _object(document, file=file, path="$")
    modular_extension_keys = {
        "contract_version",
        "stage_recipes",
        "plan_policy",
        "knowledge_policy",
        "candidate_policy",
    }
    _keys(
        root,
        required={
            "action_definitions",
            "affordances",
            "activity_recipes",
            "emergence_policy",
        },
        optional=modular_extension_keys | {"llm_policy", "interaction_policy", "autonomy_policy", "narrative_arcs"},
        file=file,
        path="$",
    )
    present_extension_keys = set(root) & modular_extension_keys
    if "autonomy_policy" in root:
        from world.autonomy_policy import AutonomyPolicy
        try:
            AutonomyPolicy.parse(root["autonomy_policy"])
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path="$.autonomy_policy")
        if not present_extension_keys or "interaction_policy" not in root:
            _fail("Autonomy requires modular and interaction policies", file=file, path="$.autonomy_policy")
    if "interaction_policy" in root:
        from world.interaction_policy import InteractionPolicy
        try:
            InteractionPolicy.parse(root["interaction_policy"])
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path="$.interaction_policy")
        if not present_extension_keys:
            _fail("Interaction policy requires the modular extension", file=file, path="$.interaction_policy")
    if "llm_policy" in root:
        from world.decision_contracts import DecisionPolicy
        try:
            DecisionPolicy.parse(root["llm_policy"])
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path="$.llm_policy")
        if not present_extension_keys:
            _fail("LLM policy requires the full modular extension", file=file, path="$.llm_policy")
    if not present_extension_keys:
        return _parse_systems(root, locations=locations, schema_version=SCHEMA_V4)
    if present_extension_keys != modular_extension_keys:
        missing = sorted(modular_extension_keys - present_extension_keys)
        _fail(
            "partial modular extension; missing field(s): " + ", ".join(missing),
            file=file,
            path="$",
        )
    contract_version = _identifier(
        root["contract_version"], file=file, path="$.contract_version"
    )
    if contract_version != MODULAR_SYSTEMS_CONTRACT_VERSION:
        _fail(
            f"must be {MODULAR_SYSTEMS_CONTRACT_VERSION!r}",
            file=file,
            path="$.contract_version",
        )

    action_rows = _array(
        root["action_definitions"], file=file, path="$.action_definitions"
    )
    affordance_rows = _array(root["affordances"], file=file, path="$.affordances")
    recipe_rows = _array(
        root["activity_recipes"], file=file, path="$.activity_recipes"
    )

    # Validate shared fields with the V4 schema before checking V5 extensions.
    legacy_policy_keys = {
        "policy_id",
        "policy_version",
        "max_agent_actions_per_tick",
        "max_invitations_per_tick",
        "max_activity_creations_per_tick",
        "max_event_chain_depth",
    }
    legacy_document = {
        "action_definitions": [
            {
                key: item[key]
                for key in (
                    "action_id",
                    "label",
                    "actor_types",
                    "target_types",
                    "duration_minutes",
                    "consequences",
                )
                if key in item
            }
            for item in action_rows
            if isinstance(item, Mapping)
        ],
        "affordances": [
            {
                key: item[key]
                for key in (
                    "affordance_id",
                    "action_id",
                    "location_ids",
                    "object_ids",
                    "enabled",
                    "conditions",
                )
                if key in item
            }
            for item in affordance_rows
            if isinstance(item, Mapping)
        ],
        "activity_recipes": [
            {
                key: item[key]
                for key in (
                    "recipe_id",
                    "label",
                    "location_ids",
                    "action_ids",
                    "min_participants",
                    "max_participants",
                    "duration_minutes",
                    "conditions",
                    "board_post_template",
                )
                if key in item
            }
            for item in recipe_rows
            if isinstance(item, Mapping)
        ],
        "emergence_policy": {
            key: value
            for key, value in _object(
                root["emergence_policy"],
                file=file,
                path="$.emergence_policy",
            ).items()
            if key in legacy_policy_keys
        },
    }
    _parse_systems(legacy_document, locations=locations, schema_version=SCHEMA_V4)

    object_ids = {
        str(point["object_id"])
        for location in locations.values()
        for point in location.interaction_points
    }
    actions: list[AtomicActionContractSpec] = []
    action_ids: set[str] = set()
    for index, raw in enumerate(action_rows):
        path = f"$.action_definitions[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "action_id",
                "label",
                "actor_types",
                "target_types",
                "duration_minutes",
                "consequences",
            },
            optional={
                "inputs",
                "execution_mode",
                "location_scope",
                "min_participants",
                "max_participants",
                "preconditions",
                "effect_allowlist",
                "permission_keys",
                "capability_keys",
                "interruptible",
                "failure_reason_codes",
                "text_record",
            },
            file=file,
            path=path,
        )
        action_id = _identifier(item["action_id"], file=file, path=f"{path}.action_id")
        action_ids.add(action_id)
        consequences = _parse_atomic_consequences(
            item["consequences"], file=file, path=f"{path}.consequences"
        )
        execution_mode = _identifier(
            item.get("execution_mode", "execute"),
            file=file,
            path=f"{path}.execution_mode",
        )
        if execution_mode not in {"execute", "proposal"}:
            _fail(
                "must be execute or proposal",
                file=file,
                path=f"{path}.execution_mode",
            )
        location_scope = _identifier(
            item.get("location_scope", "co_located"),
            file=file,
            path=f"{path}.location_scope",
        )
        if location_scope not in {"actor_location", "co_located"}:
            _fail(
                "must be actor_location or co_located",
                file=file,
                path=f"{path}.location_scope",
            )
        effect_allowlist = _identifier_array(
            item.get(
                "effect_allowlist",
                [effect["effect_type"] for effect in consequences],
            ),
            file=file,
            path=f"{path}.effect_allowlist",
        )
        if set(effect_allowlist) - set(ATOMIC_EFFECT_TYPES):
            _fail(
                "contains an unsupported atomic effect type",
                file=file,
                path=f"{path}.effect_allowlist",
            )
        try:
            actions.append(
                AtomicActionContractSpec(
                    action_id=action_id,
                    text_record=item.get("text_record"),
                    label=_localized(item["label"], file=file, path=f"{path}.label"),
                    actor_types=_identifier_array(
                        item["actor_types"],
                        file=file,
                        path=f"{path}.actor_types",
                        allow_empty=False,
                    ),  # type: ignore[arg-type]
                    target_types=_identifier_array(
                        item["target_types"],
                        file=file,
                        path=f"{path}.target_types",
                        allow_empty=False,
                    ),  # type: ignore[arg-type]
                    duration_minutes=_integer(
                        item["duration_minutes"],
                        file=file,
                        path=f"{path}.duration_minutes",
                        minimum=0,
                        maximum=240,
                    ),
                    consequences=consequences,
                    inputs=_parse_atomic_inputs(
                        item.get("inputs", []),
                        file=file,
                        path=f"{path}.inputs",
                    ),
                    execution_mode=execution_mode,  # type: ignore[arg-type]
                    location_scope=location_scope,  # type: ignore[arg-type]
                    min_participants=_integer(
                        item.get("min_participants", 1),
                        file=file,
                        path=f"{path}.min_participants",
                        minimum=1,
                        maximum=20,
                    ),
                    max_participants=_integer(
                        item.get("max_participants", 20),
                        file=file,
                        path=f"{path}.max_participants",
                        minimum=1,
                        maximum=20,
                    ),
                    preconditions=_parse_atomic_conditions(
                        item.get("preconditions", {}),
                        file=file,
                        path=f"{path}.preconditions",
                    ),
                    effect_allowlist=effect_allowlist,
                    permission_keys=_identifier_array(
                        item.get("permission_keys", []),
                        file=file,
                        path=f"{path}.permission_keys",
                    ),
                    capability_keys=_identifier_array(
                        item.get("capability_keys", []),
                        file=file,
                        path=f"{path}.capability_keys",
                    ),
                    interruptible=_boolean(
                        item.get("interruptible", True),
                        file=file,
                        path=f"{path}.interruptible",
                    ),
                    failure_reason_codes=_identifier_array(
                        item.get("failure_reason_codes", []),
                        file=file,
                        path=f"{path}.failure_reason_codes",
                    ),
                )
            )
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path=path)

    affordances: list[AffordanceContractSpec] = []
    for index, raw in enumerate(affordance_rows):
        path = f"$.affordances[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "affordance_id",
                "action_id",
                "location_ids",
                "object_ids",
                "enabled",
            },
            optional={"conditions", "permission_keys", "capability_keys"},
            file=file,
            path=path,
        )
        action_id = _identifier(item["action_id"], file=file, path=f"{path}.action_id")
        if action_id not in action_ids:
            _fail("references a missing action definition", file=file, path=f"{path}.action_id")
        location_ids = _identifier_array(
            item["location_ids"], file=file, path=f"{path}.location_ids"
        )
        object_id_values = _identifier_array(
            item["object_ids"], file=file, path=f"{path}.object_ids"
        )
        if any(location_id not in locations for location_id in location_ids):
            _fail("references a missing location", file=file, path=f"{path}.location_ids")
        if any(object_id not in object_ids for object_id in object_id_values):
            _fail("references a missing interaction point", file=file, path=f"{path}.object_ids")
        conditions = _parse_atomic_conditions(
            item.get("conditions", {}),
            file=file,
            path=f"{path}.conditions",
        )
        try:
            affordances.append(
                AffordanceContractSpec(
                    affordance_id=_identifier(
                        item["affordance_id"], file=file, path=f"{path}.affordance_id"
                    ),
                    action_id=action_id,
                    location_ids=location_ids,
                    object_ids=object_id_values,
                    enabled=_boolean(item["enabled"], file=file, path=f"{path}.enabled"),
                    conditions=conditions,
                    permission_keys=_identifier_array(
                        item.get("permission_keys", []),
                        file=file,
                        path=f"{path}.permission_keys",
                    ),
                    capability_keys=_identifier_array(
                        item.get("capability_keys", []),
                        file=file,
                        path=f"{path}.capability_keys",
                    ),
                )
            )
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path=path)

    recipes: list[ActivityRecipeContractSpec] = []
    recipe_ids: set[str] = set()
    pending_variants: list[tuple[str, str]] = []
    pending_followups: list[tuple[str, str]] = []
    for index, raw in enumerate(recipe_rows):
        path = f"$.activity_recipes[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "recipe_id",
                "label",
                "location_ids",
                "action_ids",
                "min_participants",
                "max_participants",
                "duration_minutes",
            },
            optional={
                "object_ids",
                "role_slots",
                "variant_recipe_ids",
                "complexity",
                "player_facing",
                "conditions",
                "board_post_template",
            },
            file=file,
            path=path,
        )
        recipe_id = _identifier(item["recipe_id"], file=file, path=f"{path}.recipe_id")
        recipe_ids.add(recipe_id)
        recipe_action_ids = _identifier_array(
            item["action_ids"], file=file, path=f"{path}.action_ids", allow_empty=False
        )
        if any(action_id not in action_ids for action_id in recipe_action_ids):
            _fail("references a missing action definition", file=file, path=f"{path}.action_ids")
        recipe_object_ids = _identifier_array(
            item.get("object_ids", []), file=file, path=f"{path}.object_ids"
        )
        if any(object_id not in object_ids for object_id in recipe_object_ids):
            _fail("references a missing interaction point", file=file, path=f"{path}.object_ids")
        variant_ids = _identifier_array(
            item.get("variant_recipe_ids", []),
            file=file,
            path=f"{path}.variant_recipe_ids",
        )
        pending_variants.extend(
            (variant_id, f"{path}.variant_recipe_ids") for variant_id in variant_ids
        )
        complexity = _identifier(
            item.get("complexity", "ordinary"),
            file=file,
            path=f"{path}.complexity",
        )
        if complexity not in ACTIVITY_COMPLEXITIES:
            _fail("contains an unsupported complexity", file=file, path=f"{path}.complexity")
        board_post_template = (
            _localized(
                item["board_post_template"],
                file=file,
                path=f"{path}.board_post_template",
            )
            if "board_post_template" in item
            else None
        )
        recipe_conditions = dict(
            _safe_config_value(
                _object(
                    item.get("conditions", {}),
                    file=file,
                    path=f"{path}.conditions",
                ),
                file=file,
                path=f"{path}.conditions",
            )
        )
        for boolean_key in (
            "emergence_enabled",
            "followup_only",
            "project_to_board",
            "auto_emergence",
            "invite_all_residents",
            "open_admission_until_end",
            "fixed_stage_timeline",
            "participant_stage_control",
        ):
            if boolean_key in recipe_conditions:
                _boolean(
                    recipe_conditions[boolean_key],
                    file=file,
                    path=f"{path}.conditions.{boolean_key}",
                )
        if "participant_mode" in recipe_conditions:
            participant_mode = _identifier(
                recipe_conditions["participant_mode"],
                file=file,
                path=f"{path}.conditions.participant_mode",
            )
            if participant_mode not in {"required", "optional", "exclude"}:
                _fail(
                    "must be required, optional, or exclude",
                    file=file,
                    path=f"{path}.conditions.participant_mode",
                )
        if "fixed_day" in recipe_conditions or "fixed_start_minute" in recipe_conditions:
            _integer(recipe_conditions.get("fixed_day"), file=file, path=f"{path}.conditions.fixed_day", minimum=1, maximum=7)
            _integer(recipe_conditions.get("fixed_start_minute"), file=file, path=f"{path}.conditions.fixed_start_minute", minimum=0, maximum=1439)
        if recipe_conditions.get("fixed_stage_timeline") and "fixed_day" not in recipe_conditions:
            _fail("fixed stage timelines require an authored day and time", file=file, path=f"{path}.conditions")
        if "required_resident_ids" in recipe_conditions:
            required_ids = _array(recipe_conditions["required_resident_ids"], file=file, path=f"{path}.conditions.required_resident_ids")
            for value in required_ids:
                _integer(value, file=file, path=f"{path}.conditions.required_resident_ids", minimum=1)
            _unique(required_ids, label="required_resident_ids", file=file, path=f"{path}.conditions.required_resident_ids")
        if "invitee_role_ids" in recipe_conditions:
            invitee_roles = _identifier_array(recipe_conditions["invitee_role_ids"], file=file, path=f"{path}.conditions.invitee_role_ids")
            if not set(invitee_roles) <= set(item.get("role_slots", [])):
                _fail("references an unknown invitee role", file=file, path=f"{path}.conditions.invitee_role_ids")
        for minute_key in ("start_delay_minutes", "expires_after_minutes"):
            if minute_key in recipe_conditions:
                _integer(
                    recipe_conditions[minute_key],
                    file=file,
                    path=f"{path}.conditions.{minute_key}",
                    minimum=15,
                    maximum=240,
                )
        if "organizer_agent_ids" in recipe_conditions:
            organizer_ids = [
                _integer(
                    value,
                    file=file,
                    path=f"{path}.conditions.organizer_agent_ids[{item_index}]",
                    minimum=1,
                )
                for item_index, value in enumerate(
                    _array(
                        recipe_conditions["organizer_agent_ids"],
                        file=file,
                        path=f"{path}.conditions.organizer_agent_ids",
                    )
                )
            ]
            _unique(
                organizer_ids,
                label="organizer_agent_ids",
                file=file,
                path=f"{path}.conditions.organizer_agent_ids",
            )
        if "followup_recipe_ids" in recipe_conditions:
            followup_ids = _identifier_array(
                recipe_conditions["followup_recipe_ids"],
                file=file,
                path=f"{path}.conditions.followup_recipe_ids",
            )
            pending_followups.extend(
                (followup_id, f"{path}.conditions.followup_recipe_ids")
                for followup_id in followup_ids
            )
        try:
            recipes.append(
                ActivityRecipeContractSpec(
                    recipe_id=recipe_id,
                    label=_localized(item["label"], file=file, path=f"{path}.label"),
                    location_ids=_identifier_array(
                        item["location_ids"],
                        file=file,
                        path=f"{path}.location_ids",
                        allow_empty=False,
                    ),
                    action_ids=recipe_action_ids,
                    object_ids=recipe_object_ids,
                    role_slots=_identifier_array(
                        item.get("role_slots", []),
                        file=file,
                        path=f"{path}.role_slots",
                    ),
                    variant_recipe_ids=variant_ids,
                    min_participants=_integer(
                        item["min_participants"],
                        file=file,
                        path=f"{path}.min_participants",
                        minimum=1,
                        maximum=20,
                    ),
                    max_participants=_integer(
                        item["max_participants"],
                        file=file,
                        path=f"{path}.max_participants",
                        minimum=1,
                        maximum=20,
                    ),
                    duration_minutes=_integer(
                        item["duration_minutes"],
                        file=file,
                        path=f"{path}.duration_minutes",
                        minimum=0,
                        maximum=480,
                    ),
                    complexity=complexity,  # type: ignore[arg-type]
                    player_facing=_boolean(
                        item.get("player_facing", True),
                        file=file,
                        path=f"{path}.player_facing",
                    ),
                    conditions=recipe_conditions,
                    board_post_template=board_post_template,
                )
            )
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path=path)
    for variant_id, path in pending_variants:
        if variant_id not in recipe_ids:
            _fail("references a missing activity recipe", file=file, path=path)
    for followup_id, path in pending_followups:
        if followup_id not in recipe_ids:
            _fail("references a missing follow-up activity recipe", file=file, path=path)

    stage_recipes: list[StageRecipeContractSpec] = []
    for index, raw in enumerate(
        _array(root["stage_recipes"], file=file, path="$.stage_recipes")
    ):
        path = f"$.stage_recipes[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "stage_recipe_id",
                "label",
                "allowed_action_ids",
                "terminal_outcomes",
                "max_stages",
                "max_player_choices_per_stage",
            },
            optional={"initial_stage_id", "stages"},
            file=file,
            path=path,
        )
        allowed_action_ids = _identifier_array(
            item["allowed_action_ids"],
            file=file,
            path=f"{path}.allowed_action_ids",
            allow_empty=False,
        )
        if any(action_id not in action_ids for action_id in allowed_action_ids):
            _fail("references a missing action definition", file=file, path=f"{path}.allowed_action_ids")
        try:
            from world.stage_recipes import validate_stage_cards

            validate_stage_cards(item, root)
            stage_recipes.append(
                StageRecipeContractSpec(
                    stage_recipe_id=_identifier(
                        item["stage_recipe_id"],
                        file=file,
                        path=f"{path}.stage_recipe_id",
                    ),
                    label=_localized(item["label"], file=file, path=f"{path}.label"),
                    allowed_action_ids=allowed_action_ids,
                    terminal_outcomes=_identifier_array(
                        item["terminal_outcomes"],
                        file=file,
                        path=f"{path}.terminal_outcomes",
                        allow_empty=False,
                    ),
                    max_stages=_integer(
                        item["max_stages"],
                        file=file,
                        path=f"{path}.max_stages",
                        minimum=1,
                        maximum=MAX_STAGES_PER_EVENT,
                    ),
                    max_player_choices_per_stage=_integer(
                        item["max_player_choices_per_stage"],
                        file=file,
                        path=f"{path}.max_player_choices_per_stage",
                        minimum=1,
                        maximum=MAX_PLAYER_CHOICES_PER_STAGE,
                    ),
                    initial_stage_id=item.get("initial_stage_id"),
                    stages=tuple(item.get("stages", ())),
                )
            )
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path=path)

    stage_ids = {item.stage_recipe_id for item in stage_recipes if item.stages}
    for index, recipe in enumerate(recipes):
        stage_id = recipe.conditions.get("stage_recipe_id")
        if stage_id is not None and (not isinstance(stage_id, str) or stage_id not in stage_ids):
            _fail("references a missing executable stage recipe", file=file, path=f"$.activity_recipes[{index}].conditions.stage_recipe_id")

    emergence = _object(
        root["emergence_policy"], file=file, path="$.emergence_policy"
    )
    _keys(
        emergence,
        required=legacy_policy_keys
        | {
            "max_new_player_facing_events_per_day",
            "max_new_major_events_per_day",
            "max_concurrent_player_facing_events",
            "max_direct_agent_invitations_to_player_per_day",
            "max_open_commitments_per_actor",
            "same_recipe_daily_limit",
            "declined_pair_cooldown_minutes",
        },
        file=file,
        path="$.emergence_policy",
    )
    emergence_spec = EmergenceBudgetSpec(
        policy_id=_identifier(
            emergence["policy_id"], file=file, path="$.emergence_policy.policy_id"
        ),
        policy_version=_identifier(
            emergence["policy_version"],
            file=file,
            path="$.emergence_policy.policy_version",
        ),
        max_agent_actions_per_tick=_integer(
            emergence["max_agent_actions_per_tick"],
            file=file,
            path="$.emergence_policy.max_agent_actions_per_tick",
            minimum=0,
            maximum=20,
        ),
        max_invitations_per_tick=_integer(
            emergence["max_invitations_per_tick"],
            file=file,
            path="$.emergence_policy.max_invitations_per_tick",
            minimum=0,
            maximum=20,
        ),
        max_activity_creations_per_tick=_integer(
            emergence["max_activity_creations_per_tick"],
            file=file,
            path="$.emergence_policy.max_activity_creations_per_tick",
            minimum=0,
            maximum=20,
        ),
        max_event_chain_depth=_integer(
            emergence["max_event_chain_depth"],
            file=file,
            path="$.emergence_policy.max_event_chain_depth",
            minimum=0,
            maximum=20,
        ),
        max_new_player_facing_events_per_day=_integer(
            emergence["max_new_player_facing_events_per_day"],
            file=file,
            path="$.emergence_policy.max_new_player_facing_events_per_day",
            minimum=0,
            maximum=MAX_NEW_PLAYER_FACING_EVENTS_PER_DAY,
        ),
        max_new_major_events_per_day=_integer(
            emergence["max_new_major_events_per_day"],
            file=file,
            path="$.emergence_policy.max_new_major_events_per_day",
            minimum=0,
            maximum=MAX_NEW_MAJOR_EVENTS_PER_DAY,
        ),
        max_concurrent_player_facing_events=_integer(
            emergence["max_concurrent_player_facing_events"],
            file=file,
            path="$.emergence_policy.max_concurrent_player_facing_events",
            minimum=0,
            maximum=MAX_CONCURRENT_PLAYER_FACING_EVENTS,
        ),
        max_direct_agent_invitations_to_player_per_day=_integer(
            emergence["max_direct_agent_invitations_to_player_per_day"],
            file=file,
            path="$.emergence_policy.max_direct_agent_invitations_to_player_per_day",
            minimum=0,
            maximum=MAX_DIRECT_AGENT_INVITATIONS_PER_DAY,
        ),
        max_open_commitments_per_actor=_integer(
            emergence["max_open_commitments_per_actor"],
            file=file,
            path="$.emergence_policy.max_open_commitments_per_actor",
            minimum=0,
            maximum=MAX_OPEN_COMMITMENTS_PER_ACTOR,
        ),
        same_recipe_daily_limit=_integer(
            emergence["same_recipe_daily_limit"],
            file=file,
            path="$.emergence_policy.same_recipe_daily_limit",
            minimum=0,
            maximum=1,
        ),
        declined_pair_cooldown_minutes=_integer(
            emergence["declined_pair_cooldown_minutes"],
            file=file,
            path="$.emergence_policy.declined_pair_cooldown_minutes",
            minimum=0,
            maximum=10080,
        ),
    )

    plan = _object(root["plan_policy"], file=file, path="$.plan_policy")
    _keys(
        plan,
        required={
            "policy_id",
            "policy_version",
            "states",
            "actor_availability_checks",
            "conflict_checks",
            "travel_time_required",
            "explicit_change_required",
            "release_reservation_on_terminal",
        },
        file=file,
        path="$.plan_policy",
    )
    try:
        plan_spec = PlanPolicySpec(
            policy_id=_identifier(plan["policy_id"], file=file, path="$.plan_policy.policy_id"),
            policy_version=_identifier(
                plan["policy_version"], file=file, path="$.plan_policy.policy_version"
            ),
            states=_identifier_array(plan["states"], file=file, path="$.plan_policy.states"),
            actor_availability_checks=_identifier_array(
                plan["actor_availability_checks"],
                file=file,
                path="$.plan_policy.actor_availability_checks",
            ),
            conflict_checks=_identifier_array(
                plan["conflict_checks"],
                file=file,
                path="$.plan_policy.conflict_checks",
            ),
            travel_time_required=_boolean(
                plan["travel_time_required"],
                file=file,
                path="$.plan_policy.travel_time_required",
            ),
            explicit_change_required=_boolean(
                plan["explicit_change_required"],
                file=file,
                path="$.plan_policy.explicit_change_required",
            ),
            release_reservation_on_terminal=_boolean(
                plan["release_reservation_on_terminal"],
                file=file,
                path="$.plan_policy.release_reservation_on_terminal",
            ),
        )
    except WorldSpecValidationError as exc:
        _fail(str(exc), file=file, path="$.plan_policy")

    knowledge = _object(
        root["knowledge_policy"], file=file, path="$.knowledge_policy"
    )
    _keys(
        knowledge,
        required={
            "policy_id",
            "policy_version",
            "allowed_source_types",
            "visibility_levels",
            "require_provenance",
            "prevent_omniscient_propagation",
        },
        file=file,
        path="$.knowledge_policy",
    )
    knowledge_sources = _identifier_array(
        knowledge["allowed_source_types"],
        file=file,
        path="$.knowledge_policy.allowed_source_types",
        allow_empty=False,
    )
    if set(knowledge_sources) - set(KNOWLEDGE_SOURCE_TYPES):
        _fail(
            "contains an unsupported knowledge source type",
            file=file,
            path="$.knowledge_policy.allowed_source_types",
        )
    try:
        knowledge_spec = KnowledgePolicySpec(
            policy_id=_identifier(
                knowledge["policy_id"], file=file, path="$.knowledge_policy.policy_id"
            ),
            policy_version=_identifier(
                knowledge["policy_version"],
                file=file,
                path="$.knowledge_policy.policy_version",
            ),
            allowed_source_types=knowledge_sources,
            visibility_levels=_identifier_array(
                knowledge["visibility_levels"],
                file=file,
                path="$.knowledge_policy.visibility_levels",
            ),
            require_provenance=_boolean(
                knowledge["require_provenance"],
                file=file,
                path="$.knowledge_policy.require_provenance",
            ),
            prevent_omniscient_propagation=_boolean(
                knowledge["prevent_omniscient_propagation"],
                file=file,
                path="$.knowledge_policy.prevent_omniscient_propagation",
            ),
        )
    except WorldSpecValidationError as exc:
        _fail(str(exc), file=file, path="$.knowledge_policy")

    candidate = _object(
        root["candidate_policy"], file=file, path="$.candidate_policy"
    )
    _keys(
        candidate,
        required={
            "policy_id",
            "policy_version",
            "allowed_source_types",
            "allowed_complexities",
            "llm_candidate_only",
            "fail_closed_unknown_ids",
            "max_candidates_per_evaluation",
        },
        file=file,
        path="$.candidate_policy",
    )
    candidate_sources = _identifier_array(
        candidate["allowed_source_types"],
        file=file,
        path="$.candidate_policy.allowed_source_types",
        allow_empty=False,
    )
    if set(candidate_sources) - set(CANDIDATE_SOURCE_TYPES):
        _fail(
            "contains an unsupported candidate source type",
            file=file,
            path="$.candidate_policy.allowed_source_types",
        )
    complexities = _identifier_array(
        candidate["allowed_complexities"],
        file=file,
        path="$.candidate_policy.allowed_complexities",
        allow_empty=False,
    )
    if set(complexities) - set(ACTIVITY_COMPLEXITIES):
        _fail(
            "contains an unsupported activity complexity",
            file=file,
            path="$.candidate_policy.allowed_complexities",
        )
    try:
        candidate_spec = CandidatePolicySpec(
            policy_id=_identifier(
                candidate["policy_id"], file=file, path="$.candidate_policy.policy_id"
            ),
            policy_version=_identifier(
                candidate["policy_version"],
                file=file,
                path="$.candidate_policy.policy_version",
            ),
            allowed_source_types=candidate_sources,
            allowed_complexities=complexities,
            llm_candidate_only=_boolean(
                candidate["llm_candidate_only"],
                file=file,
                path="$.candidate_policy.llm_candidate_only",
            ),
            fail_closed_unknown_ids=_boolean(
                candidate["fail_closed_unknown_ids"],
                file=file,
                path="$.candidate_policy.fail_closed_unknown_ids",
            ),
            max_candidates_per_evaluation=_integer(
                candidate["max_candidates_per_evaluation"],
                file=file,
                path="$.candidate_policy.max_candidates_per_evaluation",
                minimum=1,
                maximum=20,
            ),
        )
    except WorldSpecValidationError as exc:
        _fail(str(exc), file=file, path="$.candidate_policy")

    try:
        ModularSystemsContractSpec(
            contract_version=contract_version,
            actions=tuple(actions),
            affordances=tuple(affordances),
            activity_recipes=tuple(recipes),
            stage_recipes=tuple(stage_recipes),
            emergence_policy=emergence_spec,
            plan_policy=plan_spec,
            knowledge_policy=knowledge_spec,
            candidate_policy=candidate_spec,
        )
    except WorldSpecValidationError as exc:
        _fail(str(exc), file=file, path="$")
    # The strict stage graph adds three container levels. Other modular
    # configuration retains the preceding shallow contract.
    if "narrative_arcs" in root:
        from world.narrative_arcs import validate_arcs
        try:
            validate_arcs(root["narrative_arcs"], root)
        except WorldSpecValidationError as exc:
            _fail(str(exc), file=file, path="$.narrative_arcs")
    shallow = {key: value for key, value in root.items() if key not in ("stage_recipes", "narrative_arcs")}
    result = dict(_safe_config_value(shallow, file=file, path="$"))
    result["stage_recipes"] = _safe_config_value(root["stage_recipes"], file=file, path="$.stage_recipes", max_depth=7)
    if "narrative_arcs" in root:
        result["narrative_arcs"] = _safe_config_value(root["narrative_arcs"], file=file, path="$.narrative_arcs", max_depth=7)
    return result


def _parse_locations(
    document: Any,
    *,
    world_version: str,
) -> dict[str, LocationSpec]:
    file = "locations.json"
    root = _object(document, file=file, path="$")
    _keys(root, required={"locations"}, file=file, path="$")
    rows = _array(root["locations"], file=file, path="$.locations")
    if not rows:
        _fail("must contain at least one location", file=file, path="$.locations")
    result: dict[str, LocationSpec] = {}
    for index, raw in enumerate(rows):
        path = f"$.locations[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "location_id", "name", "description", "scene_type", "version",
                "connected_location_ids", "opening_hours", "interaction_points",
                "allowed_actions", "event_pool_ids",
            },
            file=file,
            path=path,
        )
        location_id = _identifier(item["location_id"], file=file, path=f"{path}.location_id")
        if location_id in result:
            _fail(f"duplicate location_id {location_id!r}", file=file, path=f"{path}.location_id")
        version = _identifier(item["version"], file=file, path=f"{path}.version")
        if version != world_version:
            _fail("must match manifest world_version", file=file, path=f"{path}.version")
        opening = _object(item["opening_hours"], file=file, path=f"{path}.opening_hours")
        _keys(opening, required={"always_open"}, file=file, path=f"{path}.opening_hours")
        _boolean(opening["always_open"], file=file, path=f"{path}.opening_hours.always_open")
        if opening["always_open"] is not True:
            _fail("content-pack-v1 currently requires always_open=true", file=file, path=f"{path}.opening_hours.always_open")

        interaction_rows = _array(item["interaction_points"], file=file, path=f"{path}.interaction_points")
        interaction_points: list[dict[str, Any]] = []
        object_ids: list[str] = []
        for object_index, raw_object in enumerate(interaction_rows):
            object_path = f"{path}.interaction_points[{object_index}]"
            object_item = _object(raw_object, file=file, path=object_path)
            _keys(
                object_item,
                required={"object_id", "type", "name", "description", "renderer_key"},
                optional={"interaction_event_id"},
                file=file,
                path=object_path,
            )
            object_id = _identifier(object_item["object_id"], file=file, path=f"{object_path}.object_id")
            renderer_key = _identifier(object_item["renderer_key"], file=file, path=f"{object_path}.renderer_key")
            if renderer_key not in INTERACTION_RENDERER_KEYS:
                _fail("renderer_key is not in the safe allowlist", file=file, path=f"{object_path}.renderer_key")
            object_ids.append(object_id)
            normalized_object = {
                    "object_id": object_id,
                    "type": _identifier(object_item["type"], file=file, path=f"{object_path}.type"),
                    "name": _localized(object_item["name"], file=file, path=f"{object_path}.name"),
                    "description": _localized(object_item["description"], file=file, path=f"{object_path}.description"),
                    "renderer_key": renderer_key,
                }
            if "interaction_event_id" in object_item:
                normalized_object["interaction_event_id"] = _identifier(
                    object_item["interaction_event_id"],
                    file=file,
                    path=f"{object_path}.interaction_event_id",
                )
            interaction_points.append(normalized_object)
        _unique(object_ids, label="object_id", file=file, path=f"{path}.interaction_points")
        allowed_actions = _identifier_array(item["allowed_actions"], file=file, path=f"{path}.allowed_actions")
        unsupported_actions = sorted(set(allowed_actions) - ALLOWED_ACTIONS)
        if unsupported_actions:
            _fail(f"unsupported action(s): {', '.join(unsupported_actions)}", file=file, path=f"{path}.allowed_actions")

        result[location_id] = LocationSpec(
            location_id=location_id,
            name=_localized(item["name"], file=file, path=f"{path}.name"),
            description=_localized(item["description"], file=file, path=f"{path}.description"),
            scene_type=_identifier(item["scene_type"], file=file, path=f"{path}.scene_type"),
            connected_location_ids=_identifier_array(item["connected_location_ids"], file=file, path=f"{path}.connected_location_ids"),
            interaction_points=tuple(interaction_points),
            version=version,
            opening_hours=dict(opening),
            allowed_actions=allowed_actions,
            event_pool_ids=_identifier_array(item["event_pool_ids"], file=file, path=f"{path}.event_pool_ids"),
        )
    return result


def _validate_location_connections(locations: Mapping[str, LocationSpec]) -> set[tuple[str, str]]:
    file = "locations.json"
    edges: set[tuple[str, str]] = set()
    for location in locations.values():
        for target in location.connected_location_ids:
            if target == location.location_id:
                _fail("a location cannot connect to itself", file=file, path=f"$.locations[{location.location_id}].connected_location_ids")
            if target not in locations:
                _fail(f"references missing location {target!r}", file=file, path=f"$.locations[{location.location_id}].connected_location_ids")
            if location.location_id not in locations[target].connected_location_ids:
                _fail(f"connection to {target!r} is not bidirectional", file=file, path=f"$.locations[{location.location_id}].connected_location_ids")
            edges.add(tuple(sorted((location.location_id, target))))

    start = next(iter(locations))
    visited = {start}
    pending = [start]
    while pending:
        current = pending.pop()
        for target in locations[current].connected_location_ids:
            if target not in visited:
                visited.add(target)
                pending.append(target)
    missing = sorted(set(locations) - visited)
    if missing:
        _fail(f"location graph is disconnected; unreachable: {', '.join(missing)}", file=file, path="$.locations")
    return edges


def _parse_scene_hotspots(
    value: Any,
    *,
    file: str,
    path: str,
    expected_objects: set[str],
    width: float,
    height: float,
) -> tuple[SceneHotspotSpec, ...]:
    result: list[SceneHotspotSpec] = []
    ids: list[str] = []
    for index, raw in enumerate(_array(value, file=file, path=path)):
        item_path = f"{path}[{index}]"
        item = _object(raw, file=file, path=item_path)
        _keys(
            item,
            required={"hotspot_id", "shape", "target_object_id", "x", "y", "label", "log_code"},
            optional={"width", "height", "radius"},
            file=file,
            path=item_path,
        )
        hotspot_id = _identifier(item["hotspot_id"], file=file, path=f"{item_path}.hotspot_id")
        ids.append(hotspot_id)
        shape = item["shape"]
        if shape not in {"circle", "rectangle"}:
            _fail("must be circle or rectangle", file=file, path=f"{item_path}.shape")
        target = _identifier(item["target_object_id"], file=file, path=f"{item_path}.target_object_id")
        if target not in expected_objects:
            _fail("references a missing interaction point", file=file, path=f"{item_path}.target_object_id")
        x = _number(item["x"], file=file, path=f"{item_path}.x", minimum=0, maximum=width)
        y = _number(item["y"], file=file, path=f"{item_path}.y", minimum=0, maximum=height)
        rectangle_width = _number(item["width"], file=file, path=f"{item_path}.width", minimum=0, maximum=width, exclusive_minimum=True) if "width" in item else None
        rectangle_height = _number(item["height"], file=file, path=f"{item_path}.height", minimum=0, maximum=height, exclusive_minimum=True) if "height" in item else None
        radius = _number(item["radius"], file=file, path=f"{item_path}.radius", minimum=0, maximum=max(width, height), exclusive_minimum=True) if "radius" in item else None
        if shape == "circle" and (radius is None or rectangle_width is not None or rectangle_height is not None):
            _fail("circle requires radius and forbids width/height", file=file, path=item_path)
        if shape == "rectangle" and (rectangle_width is None or rectangle_height is None or radius is not None):
            _fail("rectangle requires width/height and forbids radius", file=file, path=item_path)
        result.append(SceneHotspotSpec(
            hotspot_id=hotspot_id,
            shape=shape,
            target_object_id=target,
            x=x,
            y=y,
            width=rectangle_width,
            height=rectangle_height,
            radius=radius,
            label=_localized(item["label"], file=file, path=f"{item_path}.label"),
            log_code=_identifier(item["log_code"], file=file, path=f"{item_path}.log_code"),
        ))
    _unique(ids, label="hotspot_id", file=file, path=path)
    return tuple(result)


def _parse_map(
    document: Any,
    *,
    locations: Mapping[str, LocationSpec],
    schema_version: str = SCHEMA_V1,
) -> MapSpec:
    file = "map.json"
    root = _object(document, file=file, path="$")
    _keys(
        root,
        required={"map_id", "version", "width", "height", "background", "land_polygon", "paths", "location_nodes", "scene_layouts"},
        file=file,
        path="$",
    )
    width = _number(root["width"], file=file, path="$.width", minimum=0, maximum=10000, exclusive_minimum=True)
    height = _number(root["height"], file=file, path="$.height", minimum=0, maximum=10000, exclusive_minimum=True)
    background = _object(root["background"], file=file, path="$.background")
    _keys(background, required=set(BACKGROUND_KEYS), file=file, path="$.background")
    normalized_background: dict[str, str] = {}
    for key, allowed in BACKGROUND_KEYS.items():
        value = _identifier(background[key], file=file, path=f"$.background.{key}")
        if value not in allowed:
            _fail("value is not in the safe style allowlist", file=file, path=f"$.background.{key}")
        normalized_background[key] = value

    polygon_rows = _array(root["land_polygon"], file=file, path="$.land_polygon")
    if len(polygon_rows) < 3:
        _fail("requires at least three points", file=file, path="$.land_polygon")
    polygon = tuple(_point(row, file=file, path=f"$.land_polygon[{index}]") for index, row in enumerate(polygon_rows))
    for index, point in enumerate(polygon):
        _inside(point, width=width, height=height, file=file, path=f"$.land_polygon[{index}]")

    node_rows = _array(root["location_nodes"], file=file, path="$.location_nodes")
    nodes: dict[str, MapLocationNodeSpec] = {}
    for index, raw in enumerate(node_rows):
        path = f"$.location_nodes[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"location_id", "x", "y", "click_radius", "icon_key", "label_offset"}, file=file, path=path)
        location_id = _identifier(item["location_id"], file=file, path=f"{path}.location_id")
        if location_id in nodes:
            _fail(f"duplicate location node {location_id!r}", file=file, path=f"{path}.location_id")
        if location_id not in locations:
            _fail("references a missing location", file=file, path=f"{path}.location_id")
        x = _number(item["x"], file=file, path=f"{path}.x")
        y = _number(item["y"], file=file, path=f"{path}.y")
        _inside((x, y), width=width, height=height, file=file, path=path)
        icon_key = _identifier(item["icon_key"], file=file, path=f"{path}.icon_key")
        if icon_key not in MAP_ICON_KEYS:
            _fail("icon_key is not in the safe allowlist", file=file, path=f"{path}.icon_key")
        nodes[location_id] = MapLocationNodeSpec(
            location_id=location_id,
            x=x,
            y=y,
            click_radius=_number(item["click_radius"], file=file, path=f"{path}.click_radius", minimum=0, exclusive_minimum=True),
            icon_key=icon_key,
            label_offset=_point(item["label_offset"], file=file, path=f"{path}.label_offset"),
        )
    if set(nodes) != set(locations):
        missing = sorted(set(locations) - set(nodes))
        extra = sorted(set(nodes) - set(locations))
        _fail(f"location nodes must exactly match locations; missing={missing}, extra={extra}", file=file, path="$.location_nodes")

    expected_edges = _validate_location_connections(locations)
    path_rows = _array(root["paths"], file=file, path="$.paths")
    paths: dict[str, MapPathSpec] = {}
    path_edges: set[tuple[str, str]] = set()
    for index, raw in enumerate(path_rows):
        path = f"$.paths[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"path_id", "from_location_id", "to_location_id", "points"}, file=file, path=path)
        path_id = _identifier(item["path_id"], file=file, path=f"{path}.path_id")
        if path_id in paths:
            _fail(f"duplicate path_id {path_id!r}", file=file, path=f"{path}.path_id")
        source = _identifier(item["from_location_id"], file=file, path=f"{path}.from_location_id")
        target = _identifier(item["to_location_id"], file=file, path=f"{path}.to_location_id")
        edge = tuple(sorted((source, target)))
        if edge not in expected_edges:
            _fail("path endpoints are not a location graph edge", file=file, path=path)
        if edge in path_edges:
            _fail("only one map path may represent each location graph edge", file=file, path=path)
        point_rows = _array(item["points"], file=file, path=f"{path}.points")
        points = tuple(_point(row, file=file, path=f"{path}.points[{point_index}]") for point_index, row in enumerate(point_rows))
        if len(points) < 2:
            _fail("requires at least two points", file=file, path=f"{path}.points")
        for point_index, point in enumerate(points):
            _inside(point, width=width, height=height, file=file, path=f"{path}.points[{point_index}]")
        if points[0] != (nodes[source].x, nodes[source].y) or points[-1] != (nodes[target].x, nodes[target].y):
            _fail("first and last path points must equal endpoint node coordinates", file=file, path=f"{path}.points")
        paths[path_id] = MapPathSpec(path_id=path_id, from_location_id=source, to_location_id=target, points=points)
        path_edges.add(edge)
    if path_edges != expected_edges:
        _fail(f"paths must exactly cover graph edges; missing={sorted(expected_edges - path_edges)}", file=file, path="$.paths")

    layout_rows = _array(root["scene_layouts"], file=file, path="$.scene_layouts")
    layouts: dict[str, SceneLayoutSpec] = {}
    for index, raw in enumerate(layout_rows):
        path = f"$.scene_layouts[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(item, required={"location_id", "width", "height", "participant_spawn", "resident_slots", "interaction_point_positions"}, optional={"hotspots"} if schema_version in {SCHEMA_V4, SCHEMA_V5} else set(), file=file, path=path)
        location_id = _identifier(item["location_id"], file=file, path=f"{path}.location_id")
        if location_id in layouts:
            _fail(f"duplicate scene layout {location_id!r}", file=file, path=f"{path}.location_id")
        if location_id not in locations:
            _fail("references a missing location", file=file, path=f"{path}.location_id")
        scene_width = _number(item["width"], file=file, path=f"{path}.width", minimum=0, maximum=5000, exclusive_minimum=True)
        scene_height = _number(item["height"], file=file, path=f"{path}.height", minimum=0, maximum=5000, exclusive_minimum=True)
        spawn = _point(item["participant_spawn"], file=file, path=f"{path}.participant_spawn")
        _inside(spawn, width=scene_width, height=scene_height, file=file, path=f"{path}.participant_spawn")
        slot_rows = _array(item["resident_slots"], file=file, path=f"{path}.resident_slots")
        if not slot_rows:
            _fail("must contain at least one resident slot", file=file, path=f"{path}.resident_slots")
        slots = tuple(_point(row, file=file, path=f"{path}.resident_slots[{slot_index}]") for slot_index, row in enumerate(slot_rows))
        for slot_index, slot in enumerate(slots):
            _inside(slot, width=scene_width, height=scene_height, file=file, path=f"{path}.resident_slots[{slot_index}]")
        positions_raw = _object(item["interaction_point_positions"], file=file, path=f"{path}.interaction_point_positions")
        expected_objects = {point["object_id"] for point in locations[location_id].interaction_points}
        if set(positions_raw) != expected_objects:
            _fail(f"object positions must exactly match interaction points; missing={sorted(expected_objects - set(positions_raw))}, extra={sorted(set(positions_raw) - expected_objects)}", file=file, path=f"{path}.interaction_point_positions")
        positions: dict[str, tuple[float, float]] = {}
        for object_id, raw_point in positions_raw.items():
            _identifier(object_id, file=file, path=f"{path}.interaction_point_positions.{object_id}")
            point = _point(raw_point, file=file, path=f"{path}.interaction_point_positions.{object_id}")
            _inside(point, width=scene_width, height=scene_height, file=file, path=f"{path}.interaction_point_positions.{object_id}")
            positions[object_id] = point
        hotspots = _parse_scene_hotspots(
            item.get("hotspots", []),
            file=file,
            path=f"{path}.hotspots",
            expected_objects=expected_objects,
            width=scene_width,
            height=scene_height,
        )
        layouts[location_id] = SceneLayoutSpec(location_id=location_id, width=scene_width, height=scene_height, participant_spawn=spawn, resident_slots=slots, interaction_point_positions=positions, hotspots=hotspots)
    if set(layouts) != set(locations):
        _fail(f"scene layouts must exactly match locations; missing={sorted(set(locations) - set(layouts))}", file=file, path="$.scene_layouts")

    return MapSpec(
        map_id=_identifier(root["map_id"], file=file, path="$.map_id"),
        version=_identifier(root["version"], file=file, path="$.version"),
        width=width,
        height=height,
        background=normalized_background,
        land_polygon=polygon,
        paths=paths,
        location_nodes=nodes,
        scene_layouts=layouts,
    )


def _parse_residents(
    document: Any,
    *,
    locations: Mapping[str, LocationSpec],
    calendar: CalendarSpec,
) -> dict[int, ResidentSpec]:
    file = "residents.json"
    root = _object(document, file=file, path="$")
    _keys(root, required={"residents"}, file=file, path="$")
    rows = _array(root["residents"], file=file, path="$.residents")
    if not rows:
        _fail("must contain at least one resident", file=file, path="$.residents")
    result: dict[int, ResidentSpec] = {}
    for index, raw in enumerate(rows):
        path = f"$.residents[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "agent_id", "name", "adult_age_range", "role", "public_summary",
                "home_location_id", "background", "personality", "values",
                "preferences", "communication_style", "goals", "knowledge_boundaries",
                "avoid_patterns", "safety_rules", "avatar_key", "marker_color_key",
                "profile_version", "prompt_version", "schedule",
            },
            optional={"autonomy"},
            file=file,
            path=path,
        )
        agent_id = _integer(item["agent_id"], file=file, path=f"{path}.agent_id", minimum=1)
        if agent_id in result:
            _fail(f"duplicate agent_id {agent_id}", file=file, path=f"{path}.agent_id")
        home_location_id = _identifier(item["home_location_id"], file=file, path=f"{path}.home_location_id")
        if home_location_id not in locations:
            _fail("references a missing location", file=file, path=f"{path}.home_location_id")
        avatar_key = _identifier(item["avatar_key"], file=file, path=f"{path}.avatar_key")
        if avatar_key not in AVATAR_KEYS:
            _fail("avatar_key is not in the safe allowlist", file=file, path=f"{path}.avatar_key")
        marker_key = _identifier(item["marker_color_key"], file=file, path=f"{path}.marker_color_key")
        if marker_key not in MARKER_COLOR_KEYS:
            _fail("marker_color_key is not in the safe allowlist", file=file, path=f"{path}.marker_color_key")

        schedule_rows = _array(item["schedule"], file=file, path=f"{path}.schedule")
        if not schedule_rows:
            _fail("must contain at least one schedule block", file=file, path=f"{path}.schedule")
        blocks: list[ScheduleBlock] = []
        state_ids: list[str] = []
        for block_index, raw_block in enumerate(schedule_rows):
            block_path = f"{path}.schedule[{block_index}]"
            block_item = _object(raw_block, file=file, path=block_path)
            _keys(block_item, required={"state_id", "start_minute", "end_minute", "location_id", "activity", "goal"}, optional={"days"}, file=file, path=block_path)
            state_id = _identifier(block_item["state_id"], file=file, path=f"{block_path}.state_id")
            state_ids.append(state_id)
            location_id = _identifier(block_item["location_id"], file=file, path=f"{block_path}.location_id")
            if location_id not in locations:
                _fail("references a missing location", file=file, path=f"{block_path}.location_id")
            days: frozenset[int] | None = None
            if "days" in block_item:
                day_rows = _array(block_item["days"], file=file, path=f"{block_path}.days")
                if not day_rows:
                    _fail("days must not be empty when present", file=file, path=f"{block_path}.days")
                normalized_days = tuple(_integer(day, file=file, path=f"{block_path}.days[{day_index}]", minimum=1, maximum=calendar.total_days) for day_index, day in enumerate(day_rows))
                _unique(normalized_days, label="day", file=file, path=f"{block_path}.days")
                days = frozenset(normalized_days)
            start_minute = _integer(
                block_item["start_minute"],
                file=file,
                path=f"{block_path}.start_minute",
                minimum=calendar.day_start_minute,
                maximum=calendar.day_end_minute,
            )
            end_minute = _integer(
                block_item["end_minute"],
                file=file,
                path=f"{block_path}.end_minute",
                minimum=calendar.day_start_minute,
                maximum=calendar.day_end_minute,
            )
            if start_minute > end_minute:
                _fail(
                    "start_minute must not exceed end_minute",
                    file=file,
                    path=block_path,
                )
            blocks.append(
                ScheduleBlock(
                    state_id=state_id,
                    start_minute=start_minute,
                    end_minute=end_minute,
                    location_id=location_id,
                    activity=_localized(block_item["activity"], file=file, path=f"{block_path}.activity"),
                    goal=_localized(block_item["goal"], file=file, path=f"{block_path}.goal"),
                    days=days,
                )
            )
        _unique(state_ids, label="schedule state_id", file=file, path=f"{path}.schedule")

        profile = {
            "personality": _localized(item["personality"], file=file, path=f"{path}.personality"),
            "values": _localized_array(item["values"], file=file, path=f"{path}.values"),
            "preferences": _localized_array(item["preferences"], file=file, path=f"{path}.preferences"),
            "communication_style": _localized(item["communication_style"], file=file, path=f"{path}.communication_style"),
            "goals": _localized_array(item["goals"], file=file, path=f"{path}.goals"),
            "knowledge_boundaries": _localized_array(item["knowledge_boundaries"], file=file, path=f"{path}.knowledge_boundaries"),
            "avoid_patterns": _localized_array(item["avoid_patterns"], file=file, path=f"{path}.avoid_patterns"),
            "safety_rules": _localized_array(item["safety_rules"], file=file, path=f"{path}.safety_rules"),
        }
        autonomy = AutonomySpec()
        if "autonomy" in item:
            autonomy_path = f"{path}.autonomy"
            autonomy_item = _object(item["autonomy"], file=file, path=autonomy_path)
            _keys(
                autonomy_item,
                required=set(),
                optional={
                    "enabled",
                    "allowed_intents",
                    "preferred_location_ids",
                    "free_time_state_ids",
                    "action_cooldown_minutes",
                    "idle_weight",
                    "inspect_weight",
                    "socialize_weight",
                    "greet_weight",
                    "travel_weight",
                },
                file=file,
                path=autonomy_path,
            )
            enabled = autonomy_item.get("enabled", autonomy.enabled)
            _boolean(enabled, file=file, path=f"{autonomy_path}.enabled")
            allowed_intents = (
                _identifier_array(
                    autonomy_item["allowed_intents"],
                    file=file,
                    path=f"{autonomy_path}.allowed_intents",
                    allow_empty=False,
                )
                if "allowed_intents" in autonomy_item
                else autonomy.allowed_intents
            )
            unsupported_intents = sorted(set(allowed_intents) - AUTONOMY_INTENT_TYPES)
            if unsupported_intents:
                _fail(
                    f"unsupported autonomy intent(s): {', '.join(unsupported_intents)}",
                    file=file,
                    path=f"{autonomy_path}.allowed_intents",
                )
            preferred_locations = (
                _identifier_array(
                    autonomy_item["preferred_location_ids"],
                    file=file,
                    path=f"{autonomy_path}.preferred_location_ids",
                )
                if "preferred_location_ids" in autonomy_item
                else ()
            )
            missing_preferred = sorted(set(preferred_locations) - set(locations))
            if missing_preferred:
                _fail(
                    f"references missing location(s): {', '.join(missing_preferred)}",
                    file=file,
                    path=f"{autonomy_path}.preferred_location_ids",
                )
            free_states = (
                _identifier_array(
                    autonomy_item["free_time_state_ids"],
                    file=file,
                    path=f"{autonomy_path}.free_time_state_ids",
                )
                if "free_time_state_ids" in autonomy_item
                else ()
            )
            missing_states = sorted(set(free_states) - set(state_ids))
            if missing_states:
                _fail(
                    f"references missing schedule state(s): {', '.join(missing_states)}",
                    file=file,
                    path=f"{autonomy_path}.free_time_state_ids",
                )

            def autonomy_integer(name: str, default: int, maximum: int) -> int:
                if name not in autonomy_item:
                    return default
                return _integer(
                    autonomy_item[name],
                    file=file,
                    path=f"{autonomy_path}.{name}",
                    minimum=0,
                    maximum=maximum,
                )

            autonomy = AutonomySpec(
                enabled=enabled,
                allowed_intents=allowed_intents,
                preferred_location_ids=preferred_locations,
                free_time_state_ids=free_states,
                action_cooldown_minutes=autonomy_integer(
                    "action_cooldown_minutes", autonomy.action_cooldown_minutes, 240
                ),
                idle_weight=autonomy_integer("idle_weight", autonomy.idle_weight, 100),
                inspect_weight=autonomy_integer(
                    "inspect_weight", autonomy.inspect_weight, 100
                ),
                socialize_weight=autonomy_integer(
                    "socialize_weight", autonomy.socialize_weight, 100
                ),
                greet_weight=autonomy_integer(
                    "greet_weight", autonomy.greet_weight, 100
                ),
                travel_weight=autonomy_integer(
                    "travel_weight", autonomy.travel_weight, 100
                ),
            )
        result[agent_id] = ResidentSpec(
            agent_id=agent_id,
            name=_string(item["name"], file=file, path=f"{path}.name"),
            adult_age_range=_string(item["adult_age_range"], file=file, path=f"{path}.adult_age_range"),
            role=_localized(item["role"], file=file, path=f"{path}.role"),
            public_summary=_localized(item["public_summary"], file=file, path=f"{path}.public_summary"),
            home_location_id=home_location_id,
            background=_localized(item["background"], file=file, path=f"{path}.background"),
            avatar_key=avatar_key,
            marker_color_key=marker_key,
            profile=profile,
            profile_version=_identifier(item["profile_version"], file=file, path=f"{path}.profile_version"),
            prompt_version=_identifier(item["prompt_version"], file=file, path=f"{path}.prompt_version"),
            schedule=tuple(blocks),
            autonomy=autonomy,
        )
    return result


def _parse_flow_effects(
    value: Any,
    *,
    file: str,
    path: str,
    locations: Mapping[str, LocationSpec],
    residents: Mapping[int, ResidentSpec],
    calendar: CalendarSpec,
    event_references: list[tuple[str, str, str]],
    source_event_id: str,
) -> tuple[Mapping[str, Any], ...]:
    rows = _array(value, file=file, path=path)
    if not rows:
        _fail("must contain at least one effect", file=file, path=path)
    normalized: list[Mapping[str, Any]] = []
    control_effects = 0
    for index, raw in enumerate(rows):
        effect_path = f"{path}[{index}]"
        item = _object(raw, file=file, path=effect_path)
        effect_type = _identifier(item.get("type"), file=file, path=f"{effect_path}.type")
        if effect_type not in FLOW_EFFECT_TYPES:
            _fail("effect type is not in the safe allowlist", file=file, path=f"{effect_path}.type")
        result: dict[str, Any] = {"type": effect_type}
        if effect_type == "advance_time":
            _keys(item, required={"type", "minutes"}, file=file, path=effect_path)
            result["minutes"] = _integer(item["minutes"], file=file, path=f"{effect_path}.minutes", minimum=0, maximum=180)
        elif effect_type == "goto_node":
            _keys(item, required={"type", "node_id"}, file=file, path=effect_path)
            result["node_id"] = _identifier(item["node_id"], file=file, path=f"{effect_path}.node_id")
            control_effects += 1
        elif effect_type == "complete_flow":
            _keys(item, required={"type", "outcome_code"}, file=file, path=effect_path)
            result["outcome_code"] = _identifier(item["outcome_code"], file=file, path=f"{effect_path}.outcome_code")
            control_effects += 1
        elif effect_type in {"start_event", "schedule_event"}:
            required = {"type", "event_id"} | ({"delay_minutes"} if effect_type == "schedule_event" else set())
            _keys(item, required=required, file=file, path=effect_path)
            event_id = _identifier(item["event_id"], file=file, path=f"{effect_path}.event_id")
            result["event_id"] = event_id
            event_references.append((source_event_id, event_id, f"{effect_path}.event_id"))
            if effect_type == "schedule_event":
                result["delay_minutes"] = _integer(item["delay_minutes"], file=file, path=f"{effect_path}.delay_minutes", minimum=1, maximum=10080)
            else:
                control_effects += 1
        elif effect_type == "set_flag":
            _keys(item, required={"type", "flag_id", "value"}, file=file, path=effect_path)
            result["flag_id"] = _identifier(item["flag_id"], file=file, path=f"{effect_path}.flag_id")
            result["value"] = _boolean(item["value"], file=file, path=f"{effect_path}.value")
        elif effect_type == "goal_update":
            _keys(item, required={"type", "goal"}, file=file, path=effect_path)
            goal = _object(item["goal"], file=file, path=f"{effect_path}.goal")
            _keys(goal, required={"goal_id", "status"}, optional={"title", "description", "target_location_id", "resolution"}, file=file, path=f"{effect_path}.goal")
            normalized_goal: dict[str, Any] = {
                "goal_id": _identifier(goal["goal_id"], file=file, path=f"{effect_path}.goal.goal_id"),
                "status": _identifier(goal["status"], file=file, path=f"{effect_path}.goal.status"),
            }
            for key in ("title", "description"):
                if key in goal:
                    normalized_goal[key] = _localized(goal[key], file=file, path=f"{effect_path}.goal.{key}")
            if "target_location_id" in goal:
                target = _identifier(goal["target_location_id"], file=file, path=f"{effect_path}.goal.target_location_id")
                if target not in locations:
                    _fail("references a missing location", file=file, path=f"{effect_path}.goal.target_location_id")
                normalized_goal["target_location_id"] = target
            if "resolution" in goal:
                normalized_goal["resolution"] = _identifier(goal["resolution"], file=file, path=f"{effect_path}.goal.resolution")
            result["goal"] = normalized_goal
        elif effect_type == "relationship_delta":
            _keys(item, required={"type", "target_agent_id"}, optional=set(RELATIONSHIP_DELTA_KEYS), file=file, path=effect_path)
            target_agent_id = _integer(item["target_agent_id"], file=file, path=f"{effect_path}.target_agent_id", minimum=1)
            if target_agent_id not in residents:
                _fail("references a missing resident", file=file, path=f"{effect_path}.target_agent_id")
            result["target_agent_id"] = target_agent_id
            for key in RELATIONSHIP_DELTA_KEYS:
                if key in item:
                    result[key] = _integer(item[key], file=file, path=f"{effect_path}.{key}", minimum=-10, maximum=10)
        elif effect_type == "add_memory":
            _keys(item, required={"type", "owner_agent_id", "text"}, optional={"tags"}, file=file, path=effect_path)
            owner = _integer(item["owner_agent_id"], file=file, path=f"{effect_path}.owner_agent_id", minimum=1)
            if owner not in residents:
                _fail("references a missing resident", file=file, path=f"{effect_path}.owner_agent_id")
            result.update({"owner_agent_id": owner, "text": _localized(item["text"], file=file, path=f"{effect_path}.text")})
            if "tags" in item:
                result["tags"] = _identifier_array(item["tags"], file=file, path=f"{effect_path}.tags")
        elif effect_type == "move_participant":
            _keys(item, required={"type", "location_id"}, file=file, path=effect_path)
            location_id = _identifier(item["location_id"], file=file, path=f"{effect_path}.location_id")
            if location_id not in locations:
                _fail("references a missing location", file=file, path=f"{effect_path}.location_id")
            result["location_id"] = location_id
        elif effect_type == "show_message":
            _keys(item, required={"type", "text"}, file=file, path=effect_path)
            result["text"] = _localized(item["text"], file=file, path=f"{effect_path}.text")
        normalized.append(result)
    if control_effects != 1:
        _fail("each choice requires exactly one goto_node, complete_flow, or start_event control effect", file=file, path=path)
    return tuple(normalized)


def _parse_events(
    document: Any,
    *,
    locations: Mapping[str, LocationSpec],
    residents: Mapping[int, ResidentSpec],
    event_pack_version: str,
    calendar: CalendarSpec,
    schema_version: str,
) -> dict[str, EventContentSpec]:
    file = "events.json"
    root = _object(document, file=file, path="$")
    _keys(root, required={"events"}, file=file, path="$")
    rows = _array(root["events"], file=file, path="$.events")
    result: dict[str, EventContentSpec] = {}
    follow_ups: list[tuple[str, str, str]] = []
    handler_keys: set[tuple[str, str]] = set()
    defined_pools: set[str] = set()
    flow_event_references: list[tuple[str, str, str]] = []
    for index, raw in enumerate(rows):
        path = f"$.events[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "event_id", "event_type", "version", "title", "stimulus", "location_ids",
                "event_pool_ids", "trigger", "weight", "cooldown_minutes", "max_occurrences",
                "prerequisites", "exclusion_flags", "actions",
            },
            optional={
                "renderer_key",
                "initial_stage_id",
                "stages",
                "logging_config",
                "llm_context",
                "social_publications",
            },
            file=file,
            path=path,
        )
        event_id = _identifier(item["event_id"], file=file, path=f"{path}.event_id")
        if event_id in result:
            _fail(f"duplicate event_id {event_id!r}", file=file, path=f"{path}.event_id")
        version = _identifier(item["version"], file=file, path=f"{path}.version")
        if version != event_pack_version:
            _fail("must match manifest event_pack_version", file=file, path=f"{path}.version")
        location_ids = _identifier_array(item["location_ids"], file=file, path=f"{path}.location_ids", allow_empty=False)
        missing_locations = sorted(set(location_ids) - set(locations))
        if missing_locations:
            _fail(f"references missing location(s): {', '.join(missing_locations)}", file=file, path=f"{path}.location_ids")
        pool_ids = _identifier_array(item["event_pool_ids"], file=file, path=f"{path}.event_pool_ids")
        defined_pools.update(pool_ids)
        trigger = _object(item["trigger"], file=file, path=f"{path}.trigger")
        _keys(trigger, required={"type"}, optional={"time_window", "conditions"}, file=file, path=f"{path}.trigger")
        trigger_type = _identifier(trigger["type"], file=file, path=f"{path}.trigger.type")
        if trigger_type not in TRIGGER_TYPES:
            _fail("unsupported trigger type", file=file, path=f"{path}.trigger.type")
        time_window: tuple[int, int] | None = None
        if "time_window" in trigger:
            window = _object(trigger["time_window"], file=file, path=f"{path}.trigger.time_window")
            _keys(window, required={"start_minute", "end_minute"}, file=file, path=f"{path}.trigger.time_window")
            start = _integer(window["start_minute"], file=file, path=f"{path}.trigger.time_window.start_minute", minimum=calendar.day_start_minute, maximum=calendar.day_end_minute)
            end = _integer(window["end_minute"], file=file, path=f"{path}.trigger.time_window.end_minute", minimum=calendar.day_start_minute, maximum=calendar.day_end_minute)
            if start > end:
                _fail("start_minute must not exceed end_minute", file=file, path=f"{path}.trigger.time_window")
            time_window = (start, end)
        if trigger_type == "on_time_window" and time_window is None:
            _fail("on_time_window requires time_window", file=file, path=f"{path}.trigger")
        trigger_conditions: dict[str, Any] = {"mode": "all", "items": ()}
        if "conditions" in trigger:
            if schema_version not in {SCHEMA_V3, SCHEMA_V4, SCHEMA_V5}:
                _fail("structured trigger conditions require content-pack-v3 or later", file=file, path=f"{path}.trigger.conditions")
            raw_conditions = _object(trigger["conditions"], file=file, path=f"{path}.trigger.conditions")
            _keys(raw_conditions, required={"mode", "items"}, file=file, path=f"{path}.trigger.conditions")
            mode = _identifier(raw_conditions["mode"], file=file, path=f"{path}.trigger.conditions.mode")
            if mode not in {"all", "any"}:
                _fail("condition mode must be all or any", file=file, path=f"{path}.trigger.conditions.mode")
            condition_rows = _array(raw_conditions["items"], file=file, path=f"{path}.trigger.conditions.items")
            normalized_conditions: list[dict[str, Any]] = []
            for condition_index, raw_condition in enumerate(condition_rows):
                condition_path = f"{path}.trigger.conditions.items[{condition_index}]"
                condition = _object(raw_condition, file=file, path=condition_path)
                _keys(condition, required={"type", "operator", "value"}, file=file, path=condition_path)
                condition_type = _identifier(condition["type"], file=file, path=f"{condition_path}.type")
                operator = _identifier(condition["operator"], file=file, path=f"{condition_path}.operator")
                allowed_operators = {
                    "world_day": {"equals", "at_least", "at_most"},
                    "world_time": {"at_least", "at_most"},
                    "location": {"equals"},
                    "action_type": {"equals"},
                    "object_choice": {"equals"},
                    "resident_present": {"equals"},
                    "flag": {"equals"},
                    "goal_status": {"equals"},
                    "event_status": {"equals"},
                }
                if condition_type not in allowed_operators or operator not in allowed_operators[condition_type]:
                    _fail("unsupported condition type/operator", file=file, path=condition_path)
                raw_value = condition["value"]
                if condition_type in {"world_day", "world_time", "resident_present"}:
                    maximum = calendar.total_days if condition_type == "world_day" else (calendar.day_end_minute if condition_type == "world_time" else None)
                    value = _integer(raw_value, file=file, path=f"{condition_path}.value", minimum=(1 if condition_type != "world_time" else calendar.day_start_minute), maximum=maximum)
                    if condition_type == "resident_present" and value not in residents:
                        _fail("references a missing resident", file=file, path=f"{condition_path}.value")
                else:
                    value = _identifier(raw_value, file=file, path=f"{condition_path}.value")
                    if condition_type == "location" and value not in locations:
                        _fail("references a missing location", file=file, path=f"{condition_path}.value")
                    if condition_type in {"goal_status", "event_status"}:
                        reference_id, separator, status = value.rpartition(".")
                        if not separator or not reference_id or not status:
                            _fail("status conditions use the form id.status", file=file, path=f"{condition_path}.value")
                        if condition_type == "event_status":
                            flow_event_references.append((event_id, reference_id, f"{condition_path}.value"))
                normalized_conditions.append({"type": condition_type, "operator": operator, "value": value})
            trigger_conditions = {"mode": mode, "items": tuple(normalized_conditions)}

        prerequisites = _object(item["prerequisites"], file=file, path=f"{path}.prerequisites")
        _keys(prerequisites, required=set(), optional={"required_resident_ids", "min_day", "max_day", "required_flags", "required_goals"}, file=file, path=f"{path}.prerequisites")
        normalized_prerequisites: dict[str, Any] = {}
        if "required_resident_ids" in prerequisites:
            required_residents_raw = _array(prerequisites["required_resident_ids"], file=file, path=f"{path}.prerequisites.required_resident_ids")
            required_residents = tuple(_integer(value, file=file, path=f"{path}.prerequisites.required_resident_ids[{resident_index}]", minimum=1) for resident_index, value in enumerate(required_residents_raw))
            _unique(required_residents, label="resident id", file=file, path=f"{path}.prerequisites.required_resident_ids")
            missing_residents = sorted(set(required_residents) - set(residents))
            if missing_residents:
                _fail(f"references missing resident(s): {missing_residents}", file=file, path=f"{path}.prerequisites.required_resident_ids")
            normalized_prerequisites["required_resident_ids"] = required_residents
        for key in ("min_day", "max_day"):
            if key in prerequisites:
                normalized_prerequisites[key] = _integer(prerequisites[key], file=file, path=f"{path}.prerequisites.{key}", minimum=1, maximum=calendar.total_days)
        if normalized_prerequisites.get("min_day", 1) > normalized_prerequisites.get("max_day", calendar.total_days):
            _fail("min_day must not exceed max_day", file=file, path=f"{path}.prerequisites")
        if "required_flags" in prerequisites:
            normalized_prerequisites["required_flags"] = _identifier_array(prerequisites["required_flags"], file=file, path=f"{path}.prerequisites.required_flags")
        if "required_goals" in prerequisites:
            required_goal_rows = _array(
                prerequisites["required_goals"],
                file=file,
                path=f"{path}.prerequisites.required_goals",
            )
            required_goals: list[dict[str, Any]] = []
            goal_ids: list[str] = []
            for goal_index, raw_goal in enumerate(required_goal_rows):
                goal_path = f"{path}.prerequisites.required_goals[{goal_index}]"
                goal = _object(raw_goal, file=file, path=goal_path)
                _keys(
                    goal,
                    required={"goal_id", "statuses"},
                    file=file,
                    path=goal_path,
                )
                goal_id = _identifier(goal["goal_id"], file=file, path=f"{goal_path}.goal_id")
                statuses = _identifier_array(
                    goal["statuses"],
                    file=file,
                    path=f"{goal_path}.statuses",
                    allow_empty=False,
                )
                goal_ids.append(goal_id)
                required_goals.append({"goal_id": goal_id, "statuses": statuses})
            _unique(goal_ids, label="goal_id", file=file, path=f"{path}.prerequisites.required_goals")
            normalized_prerequisites["required_goals"] = tuple(required_goals)

        exclusion = _object(item["exclusion_flags"], file=file, path=f"{path}.exclusion_flags")
        _keys(exclusion, required=set(), optional={"active_scenario", "active_event"}, file=file, path=f"{path}.exclusion_flags")
        normalized_exclusion = {
            key: _boolean(value, file=file, path=f"{path}.exclusion_flags.{key}")
            for key, value in exclusion.items()
        }

        action_rows = _array(item["actions"], file=file, path=f"{path}.actions")
        stage_rows = (
            _array(item["stages"], file=file, path=f"{path}.stages")
            if "stages" in item
            else []
        )
        if not action_rows and not stage_rows:
            _fail(
                "must contain at least one simple action or behavioral stage",
                file=file,
                path=path,
            )
        if action_rows and stage_rows:
            _fail(
                "simple actions and behavioral stages are mutually exclusive",
                file=file,
                path=path,
            )
        actions: list[EventActionContentSpec] = []
        action_ids: list[str] = []
        for action_index, raw_action in enumerate(action_rows):
            action_path = f"{path}.actions[{action_index}]"
            action = _object(raw_action, file=file, path=action_path)
            _keys(
                action,
                required={"action_id", "label", "requires_text", "outcome_key"},
                optional={
                    "follow_up_event_id",
                    "memory_text",
                    "memory_owner_agent_id",
                    "relationship_effect",
                },
                file=file,
                path=action_path,
            )
            action_id = _identifier(action["action_id"], file=file, path=f"{action_path}.action_id")
            action_ids.append(action_id)
            outcome = _identifier(action["outcome_key"], file=file, path=f"{action_path}.outcome_key")
            if outcome not in OUTCOME_KEYS:
                _fail("outcome_key is not in the safe allowlist", file=file, path=f"{action_path}.outcome_key")
            follow_up = None
            if "follow_up_event_id" in action:
                follow_up = _identifier(action["follow_up_event_id"], file=file, path=f"{action_path}.follow_up_event_id")
                if outcome != "schedule_follow_up":
                    _fail("follow_up_event_id requires outcome_key=schedule_follow_up", file=file, path=action_path)
                follow_ups.append((event_id, follow_up, f"{action_path}.follow_up_event_id"))
            elif outcome == "schedule_follow_up":
                _fail("schedule_follow_up requires follow_up_event_id", file=file, path=action_path)
            memory_text = None
            memory_owner_agent_id = None
            if "memory_text" in action:
                if outcome != "remember":
                    _fail(
                        "memory_text requires outcome_key=remember",
                        file=file,
                        path=f"{action_path}.memory_text",
                    )
                memory_text = _localized(
                    action["memory_text"],
                    file=file,
                    path=f"{action_path}.memory_text",
                )
            if "memory_owner_agent_id" in action:
                if outcome != "remember":
                    _fail(
                        "memory_owner_agent_id requires outcome_key=remember",
                        file=file,
                        path=f"{action_path}.memory_owner_agent_id",
                    )
                memory_owner_agent_id = _integer(
                    action["memory_owner_agent_id"],
                    file=file,
                    path=f"{action_path}.memory_owner_agent_id",
                    minimum=1,
                )
                if memory_owner_agent_id not in residents:
                    _fail(
                        "references a missing resident",
                        file=file,
                        path=f"{action_path}.memory_owner_agent_id",
                    )
            relationship_effect = None
            if "relationship_effect" in action:
                if outcome != "relationship_delta":
                    _fail(
                        "relationship_effect requires outcome_key=relationship_delta",
                        file=file,
                        path=f"{action_path}.relationship_effect",
                    )
                raw_effect = _object(
                    action["relationship_effect"],
                    file=file,
                    path=f"{action_path}.relationship_effect",
                )
                _keys(
                    raw_effect,
                    required={"target_agent_id"},
                    optional=set(RELATIONSHIP_DELTA_KEYS),
                    file=file,
                    path=f"{action_path}.relationship_effect",
                )
                target_agent_id = _integer(
                    raw_effect["target_agent_id"],
                    file=file,
                    path=f"{action_path}.relationship_effect.target_agent_id",
                    minimum=1,
                )
                if target_agent_id not in residents:
                    _fail(
                        "references a missing resident",
                        file=file,
                        path=f"{action_path}.relationship_effect.target_agent_id",
                    )
                deltas = {
                    key: _integer(
                        raw_effect.get(key, 0),
                        file=file,
                        path=f"{action_path}.relationship_effect.{key}",
                        minimum=-2,
                        maximum=2,
                    )
                    for key in RELATIONSHIP_DELTA_KEYS
                }
                if not any(deltas.values()):
                    _fail(
                        "requires at least one non-zero relationship delta",
                        file=file,
                        path=f"{action_path}.relationship_effect",
                    )
                relationship_effect = {
                    "target_agent_id": target_agent_id,
                    **deltas,
                }
            elif outcome == "relationship_delta":
                _fail(
                    "relationship_delta requires relationship_effect",
                    file=file,
                    path=action_path,
                )
            actions.append(
                EventActionContentSpec(
                    action_id=action_id,
                    label=_localized(
                        action["label"], file=file, path=f"{action_path}.label"
                    ),
                    requires_text=_boolean(
                        action["requires_text"],
                        file=file,
                        path=f"{action_path}.requires_text",
                    ),
                    outcome_key=outcome,
                    follow_up_event_id=follow_up,
                    memory_text=memory_text,
                    memory_owner_agent_id=memory_owner_agent_id,
                    relationship_effect=relationship_effect,
                )
            )
        _unique(action_ids, label="action_id", file=file, path=f"{path}.actions")

        stages: list[BehavioralEventStageContentSpec] = []
        stage_ids: list[str] = []
        referenced_next_stages: list[tuple[str, str]] = []
        for stage_index, raw_stage in enumerate(stage_rows):
            stage_path = f"{path}.stages[{stage_index}]"
            stage = _object(raw_stage, file=file, path=stage_path)
            _keys(
                stage,
                required={"stage_id", "title", "stimulus", "actions"},
                file=file,
                path=stage_path,
            )
            stage_id = _identifier(stage["stage_id"], file=file, path=f"{stage_path}.stage_id")
            stage_ids.append(stage_id)
            stage_action_rows = _array(stage["actions"], file=file, path=f"{stage_path}.actions")
            if not stage_action_rows:
                _fail("must contain at least one action", file=file, path=f"{stage_path}.actions")
            stage_actions: list[BehavioralEventActionContentSpec] = []
            stage_action_ids: list[str] = []
            for stage_action_index, raw_stage_action in enumerate(stage_action_rows):
                action_path = f"{stage_path}.actions[{stage_action_index}]"
                stage_action = _object(raw_stage_action, file=file, path=action_path)
                _keys(
                    stage_action,
                    required={
                        "action_id",
                        "label",
                        "requires_text",
                        "action_type",
                        "terminal",
                        "outcome_code",
                    },
                    optional={
                        "next_stage_id",
                        "action_minutes",
                        "target_type",
                        "target_id",
                        "target_agent_id",
                        "target_location_id",
                        "state_updates",
                        "metadata",
                        "npc_response",
                        "goal_effect",
                        "effects",
                    },
                    file=file,
                    path=action_path,
                )
                action_id = _identifier(stage_action["action_id"], file=file, path=f"{action_path}.action_id")
                stage_action_ids.append(action_id)
                terminal = _boolean(stage_action["terminal"], file=file, path=f"{action_path}.terminal")
                next_stage_id = None
                if "next_stage_id" in stage_action:
                    next_stage_id = _identifier(stage_action["next_stage_id"], file=file, path=f"{action_path}.next_stage_id")
                    referenced_next_stages.append((next_stage_id, f"{action_path}.next_stage_id"))
                if terminal and next_stage_id is not None:
                    _fail("terminal actions cannot select a next stage", file=file, path=action_path)
                if not terminal and next_stage_id is None:
                    _fail("non-terminal actions require next_stage_id", file=file, path=action_path)
                target_agent_id = None
                if "target_agent_id" in stage_action:
                    target_agent_id = _integer(stage_action["target_agent_id"], file=file, path=f"{action_path}.target_agent_id", minimum=1)
                    if target_agent_id not in residents:
                        _fail("references a missing resident", file=file, path=f"{action_path}.target_agent_id")
                target_location_id = None
                if "target_location_id" in stage_action:
                    target_location_id = _identifier(stage_action["target_location_id"], file=file, path=f"{action_path}.target_location_id")
                    if target_location_id not in locations:
                        _fail("references a missing location", file=file, path=f"{action_path}.target_location_id")
                npc_response = None
                if "npc_response" in stage_action:
                    response = _object(stage_action["npc_response"], file=file, path=f"{action_path}.npc_response")
                    _keys(
                        response,
                        required={"provider", "npc_id", "text"},
                        optional={"intent"},
                        file=file,
                        path=f"{action_path}.npc_response",
                    )
                    provider = _identifier(response["provider"], file=file, path=f"{action_path}.npc_response.provider")
                    if provider != "static":
                        _fail("current content only permits provider=static", file=file, path=f"{action_path}.npc_response.provider")
                    npc_id = _integer(response["npc_id"], file=file, path=f"{action_path}.npc_response.npc_id", minimum=1)
                    if npc_id not in residents:
                        _fail("references a missing resident", file=file, path=f"{action_path}.npc_response.npc_id")
                    npc_response = {
                        "provider": provider,
                        "npc_id": npc_id,
                        "text": _localized(response["text"], file=file, path=f"{action_path}.npc_response.text"),
                    }
                    if "intent" in response:
                        npc_response["intent"] = _identifier(response["intent"], file=file, path=f"{action_path}.npc_response.intent")
                goal_effect = None
                if "goal_effect" in stage_action:
                    raw_goal_effect = _object(stage_action["goal_effect"], file=file, path=f"{action_path}.goal_effect")
                    _keys(
                        raw_goal_effect,
                        required={"goal_id", "status"},
                        optional={"title", "description", "target_location_id", "due_day", "due_time_minutes", "resolution"},
                        file=file,
                        path=f"{action_path}.goal_effect",
                    )
                    goal_effect = {
                        "goal_id": _identifier(raw_goal_effect["goal_id"], file=file, path=f"{action_path}.goal_effect.goal_id"),
                        "status": _identifier(raw_goal_effect["status"], file=file, path=f"{action_path}.goal_effect.status"),
                    }
                    for localized_key in ("title", "description"):
                        if localized_key in raw_goal_effect:
                            goal_effect[localized_key] = _localized(raw_goal_effect[localized_key], file=file, path=f"{action_path}.goal_effect.{localized_key}")
                    if "target_location_id" in raw_goal_effect:
                        goal_location = _identifier(raw_goal_effect["target_location_id"], file=file, path=f"{action_path}.goal_effect.target_location_id")
                        if goal_location not in locations:
                            _fail("references a missing location", file=file, path=f"{action_path}.goal_effect.target_location_id")
                        goal_effect["target_location_id"] = goal_location
                    if "due_day" in raw_goal_effect:
                        goal_effect["due_day"] = _integer(raw_goal_effect["due_day"], file=file, path=f"{action_path}.goal_effect.due_day", minimum=1, maximum=calendar.total_days)
                    if "due_time_minutes" in raw_goal_effect:
                        goal_effect["due_time_minutes"] = _integer(raw_goal_effect["due_time_minutes"], file=file, path=f"{action_path}.goal_effect.due_time_minutes", minimum=calendar.day_start_minute, maximum=calendar.day_end_minute)
                    if "resolution" in raw_goal_effect:
                        goal_effect["resolution"] = _identifier(raw_goal_effect["resolution"], file=file, path=f"{action_path}.goal_effect.resolution")
                effects: tuple[Mapping[str, Any], ...] = ()
                if "effects" in stage_action:
                    if schema_version not in {SCHEMA_V3, SCHEMA_V4, SCHEMA_V5}:
                        _fail("typed effects require content-pack-v3 or later", file=file, path=f"{action_path}.effects")
                    effects = _parse_flow_effects(
                        stage_action["effects"],
                        file=file,
                        path=f"{action_path}.effects",
                        locations=locations,
                        residents=residents,
                        calendar=calendar,
                        event_references=flow_event_references,
                        source_event_id=event_id,
                    )
                    control = next(dict(effect) for effect in effects if dict(effect)["type"] in {"goto_node", "complete_flow", "start_event"})
                    if control["type"] == "goto_node":
                        if terminal or next_stage_id != control["node_id"]:
                            _fail("goto_node must match a non-terminal next_stage_id", file=file, path=f"{action_path}.effects")
                    elif not terminal or next_stage_id is not None:
                        _fail("complete_flow/start_event requires a terminal action", file=file, path=f"{action_path}.effects")
                    advance_effects = [dict(effect)["minutes"] for effect in effects if dict(effect)["type"] == "advance_time"]
                    if len(advance_effects) > 1:
                        _fail("a choice may contain at most one advance_time effect", file=file, path=f"{action_path}.effects")
                    if advance_effects and stage_action.get("action_minutes", 5) != advance_effects[0]:
                        _fail("advance_time minutes must match action_minutes", file=file, path=f"{action_path}.effects")
                elif schema_version in {SCHEMA_V3, SCHEMA_V4, SCHEMA_V5}:
                    _fail("content-pack-v3 and later choices require typed effects", file=file, path=f"{action_path}.effects")
                stage_actions.append(
                    BehavioralEventActionContentSpec(
                        action_id=action_id,
                        label=_localized(stage_action["label"], file=file, path=f"{action_path}.label"),
                        requires_text=_boolean(stage_action["requires_text"], file=file, path=f"{action_path}.requires_text"),
                        action_type=_identifier(stage_action["action_type"], file=file, path=f"{action_path}.action_type"),
                        next_stage_id=next_stage_id,
                        terminal=terminal,
                        outcome_code=_identifier(stage_action["outcome_code"], file=file, path=f"{action_path}.outcome_code"),
                        action_minutes=_integer(stage_action.get("action_minutes", 5), file=file, path=f"{action_path}.action_minutes", minimum=0, maximum=180),
                        target_type=(_identifier(stage_action["target_type"], file=file, path=f"{action_path}.target_type") if "target_type" in stage_action else None),
                        target_id=(_identifier(stage_action["target_id"], file=file, path=f"{action_path}.target_id") if "target_id" in stage_action else None),
                        target_agent_id=target_agent_id,
                        target_location_id=target_location_id,
                        state_updates=_safe_config_value(stage_action.get("state_updates", {}), file=file, path=f"{action_path}.state_updates"),
                        metadata=_safe_config_value(stage_action.get("metadata", {}), file=file, path=f"{action_path}.metadata"),
                        npc_response=npc_response,
                        goal_effect=goal_effect,
                        effects=effects,
                    )
                )
            _unique(stage_action_ids, label="action_id", file=file, path=f"{stage_path}.actions")
            stages.append(
                BehavioralEventStageContentSpec(
                    stage_id=stage_id,
                    title=_localized(stage["title"], file=file, path=f"{stage_path}.title"),
                    stimulus=_localized(stage["stimulus"], file=file, path=f"{stage_path}.stimulus"),
                    actions=tuple(stage_actions),
                )
            )
        _unique(stage_ids, label="stage_id", file=file, path=f"{path}.stages")
        initial_stage_id = None
        if stages:
            if "initial_stage_id" not in item:
                _fail("behavioral events require initial_stage_id", file=file, path=path)
            initial_stage_id = _identifier(item["initial_stage_id"], file=file, path=f"{path}.initial_stage_id")
            if initial_stage_id not in stage_ids:
                _fail("references a missing stage", file=file, path=f"{path}.initial_stage_id")
            for next_stage, next_path in referenced_next_stages:
                if next_stage not in stage_ids:
                    _fail("references a missing stage", file=file, path=next_path)
            reachable: set[str] = set()
            pending = [initial_stage_id]
            stage_by_id = {stage.stage_id: stage for stage in stages}
            while pending:
                current = pending.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                pending.extend(
                    action.next_stage_id
                    for action in stage_by_id[current].actions
                    if action.next_stage_id is not None
                )
            unreachable = sorted(set(stage_ids) - reachable)
            if unreachable:
                _fail(f"flow contains unreachable stage(s): {', '.join(unreachable)}", file=file, path=f"{path}.stages")
            can_exit = {
                stage.stage_id
                for stage in stages
                if any(action.terminal for action in stage.actions)
            }
            changed = True
            while changed:
                changed = False
                for stage in stages:
                    if stage.stage_id in can_exit:
                        continue
                    if any(action.next_stage_id in can_exit for action in stage.actions):
                        can_exit.add(stage.stage_id)
                        changed = True
            trapped = sorted(set(stage_ids) - can_exit)
            if trapped:
                _fail(f"flow has no terminal path from stage(s): {', '.join(trapped)}", file=file, path=f"{path}.stages")
        elif "initial_stage_id" in item:
            _fail("initial_stage_id requires stages", file=file, path=f"{path}.initial_stage_id")

        social_publications: list[dict[str, Any]] = []
        publication_ids: list[str] = []
        available_outcomes = {
            action.outcome_code
            for stage in stages
            for action in stage.actions
        } | {action.outcome_key for action in actions}
        for publication_index, raw_publication in enumerate(
            _array(item.get("social_publications", []), file=file, path=f"{path}.social_publications")
        ):
            publication_path = f"{path}.social_publications[{publication_index}]"
            publication = _object(raw_publication, file=file, path=publication_path)
            _keys(
                publication,
                required={
                    "publication_id", "trigger_outcomes", "eligible_author_ids",
                    "witness_agent_ids", "visibility", "post_type", "max_posts",
                    "cooldown_minutes", "facts", "templates",
                },
                optional={"allow_comments", "generation_mode"},
                file=file,
                path=publication_path,
            )
            publication_id = _identifier(
                publication["publication_id"], file=file, path=f"{publication_path}.publication_id"
            )
            publication_ids.append(publication_id)
            trigger_outcomes = _identifier_array(
                publication["trigger_outcomes"],
                file=file,
                path=f"{publication_path}.trigger_outcomes",
                allow_empty=False,
            )
            missing_outcomes = sorted(set(trigger_outcomes) - available_outcomes)
            if missing_outcomes:
                _fail(
                    f"references missing outcome(s): {', '.join(missing_outcomes)}",
                    file=file,
                    path=f"{publication_path}.trigger_outcomes",
                )
            eligible_author_ids = tuple(
                _integer(value, file=file, path=f"{publication_path}.eligible_author_ids", minimum=1)
                for value in _array(
                    publication["eligible_author_ids"],
                    file=file,
                    path=f"{publication_path}.eligible_author_ids",
                )
            )
            witness_agent_ids = tuple(
                _integer(value, file=file, path=f"{publication_path}.witness_agent_ids", minimum=1)
                for value in _array(
                    publication["witness_agent_ids"],
                    file=file,
                    path=f"{publication_path}.witness_agent_ids",
                )
            )
            if not eligible_author_ids:
                _fail("must contain at least one author", file=file, path=f"{publication_path}.eligible_author_ids")
            for key, values in (("eligible_author_ids", eligible_author_ids), ("witness_agent_ids", witness_agent_ids)):
                missing_residents = sorted(set(values) - set(residents))
                if missing_residents:
                    _fail(
                        f"references missing resident(s): {', '.join(map(str, missing_residents))}",
                        file=file,
                        path=f"{publication_path}.{key}",
                    )
            if set(eligible_author_ids) - set(witness_agent_ids):
                _fail(
                    "every eligible author must be listed as a witness",
                    file=file,
                    path=f"{publication_path}.eligible_author_ids",
                )
            visibility = _identifier(publication["visibility"], file=file, path=f"{publication_path}.visibility")
            if visibility not in {"island_public", "participants_only"}:
                _fail("unsupported visibility", file=file, path=f"{publication_path}.visibility")
            generation_mode = _identifier(
                publication.get("generation_mode", "static_fallback"),
                file=file,
                path=f"{publication_path}.generation_mode",
            )
            if generation_mode not in {"static_fallback", "llm_with_fallback"}:
                _fail("unsupported generation mode", file=file, path=f"{publication_path}.generation_mode")
            facts = _object(publication["facts"], file=file, path=f"{publication_path}.facts")
            if not facts:
                _fail("must contain at least one public fact", file=file, path=f"{publication_path}.facts")
            if any(key in facts for key in {"participant_response_text", "diagnostic_label", "private_memory"}):
                _fail("contains a prohibited private fact", file=file, path=f"{publication_path}.facts")
            templates: list[dict[str, Any]] = []
            template_authors: list[int] = []
            for template_index, raw_template in enumerate(
                _array(publication["templates"], file=file, path=f"{publication_path}.templates")
            ):
                template_path = f"{publication_path}.templates[{template_index}]"
                template = _object(raw_template, file=file, path=template_path)
                _keys(template, required={"author_agent_id", "content"}, file=file, path=template_path)
                template_author = _integer(template["author_agent_id"], file=file, path=f"{template_path}.author_agent_id", minimum=1)
                if template_author not in eligible_author_ids:
                    _fail("template author is not eligible", file=file, path=f"{template_path}.author_agent_id")
                template_authors.append(template_author)
                templates.append({
                    "author_agent_id": template_author,
                    "content": _localized(template["content"], file=file, path=f"{template_path}.content"),
                })
            if not templates:
                _fail("must contain at least one fallback template", file=file, path=f"{publication_path}.templates")
            _unique(template_authors, label="template author", file=file, path=f"{publication_path}.templates")
            social_publications.append({
                "publication_id": publication_id,
                "trigger_outcomes": trigger_outcomes,
                "eligible_author_ids": eligible_author_ids,
                "witness_agent_ids": witness_agent_ids,
                "visibility": visibility,
                "post_type": _identifier(publication["post_type"], file=file, path=f"{publication_path}.post_type"),
                "max_posts": _integer(publication["max_posts"], file=file, path=f"{publication_path}.max_posts", minimum=0, maximum=10),
                "cooldown_minutes": _integer(publication["cooldown_minutes"], file=file, path=f"{publication_path}.cooldown_minutes", minimum=0, maximum=10080),
                "facts": _safe_config_value(facts, file=file, path=f"{publication_path}.facts"),
                "templates": templates,
                "allow_comments": _boolean(publication.get("allow_comments", True), file=file, path=f"{publication_path}.allow_comments"),
                "generation_mode": generation_mode,
            })
        _unique(publication_ids, label="publication_id", file=file, path=f"{path}.social_publications")

        renderer_key = _identifier(item.get("renderer_key", "declarative_event"), file=file, path=f"{path}.renderer_key")
        logging_config = _safe_config_value(item.get("logging_config", {}), file=file, path=f"{path}.logging_config")
        llm_context = _safe_config_value(item.get("llm_context", {}), file=file, path=f"{path}.llm_context")
        event_type = _identifier(item["event_type"], file=file, path=f"{path}.event_type")
        handler_key = (event_type, version)
        if handler_key in RESERVED_EVENT_HANDLER_KEYS:
            _fail(
                "event_type/version is reserved by a built-in compatibility handler",
                file=file,
                path=f"{path}.event_type",
            )
        if handler_key in handler_keys:
            _fail(
                "event_type/version must be unique within a content pack",
                file=file,
                path=f"{path}.event_type",
            )
        handler_keys.add(handler_key)
        result[event_id] = EventContentSpec(
            event_id=event_id,
            event_type=event_type,
            version=version,
            title=_localized(item["title"], file=file, path=f"{path}.title"),
            stimulus=_localized(item["stimulus"], file=file, path=f"{path}.stimulus"),
            location_ids=location_ids,
            event_pool_ids=pool_ids,
            trigger_type=trigger_type,
            time_window=time_window,
            weight=_number(item["weight"], file=file, path=f"{path}.weight", minimum=0, maximum=1),
            cooldown_minutes=_integer(item["cooldown_minutes"], file=file, path=f"{path}.cooldown_minutes", minimum=0),
            max_occurrences=_integer(item["max_occurrences"], file=file, path=f"{path}.max_occurrences", minimum=1),
            prerequisites=normalized_prerequisites,
            exclusion_flags=normalized_exclusion,
            actions=tuple(actions),
            renderer_key=renderer_key,
            initial_stage_id=initial_stage_id,
            stages=tuple(stages),
            logging_config=logging_config,
            llm_context=llm_context,
            trigger_conditions=trigger_conditions,
            social_publications=tuple(social_publications),
        )

    for source, target, path in follow_ups:
        if target not in result:
            _fail(f"references missing follow-up event {target!r} from {source!r}", file=file, path=path)
    for source, target, reference_path in flow_event_references:
        if target not in result:
            _fail(f"references missing event {target!r}", file=file, path=reference_path)
        if source == target:
            _fail("an event cannot start, schedule, or depend on its own status", file=file, path=reference_path)
    for location in locations.values():
        for interaction in location.interaction_points:
            target = interaction.get("interaction_event_id")
            if target is None:
                continue
            if target not in result:
                _fail(f"interaction object references missing event {target!r}", file="locations.json", path=f"$.locations[{location.location_id}].interaction_points[{interaction['object_id']}].interaction_event_id")
            event = result[target]
            if event.trigger_type != "on_object_interact" or location.location_id not in event.location_ids:
                _fail("interaction event must use on_object_interact and include the object's location", file="locations.json", path=f"$.locations[{location.location_id}].interaction_points[{interaction['object_id']}].interaction_event_id")
    referenced_pools = {pool for location in locations.values() for pool in location.event_pool_ids}
    missing_pools = sorted(referenced_pools - defined_pools)
    if missing_pools:
        _fail(f"location references undefined event pool(s): {', '.join(missing_pools)}", file=file, path="$.events")
    unused_pools = sorted(defined_pools - referenced_pools)
    if unused_pools:
        _fail(f"event pool(s) are not assigned to a location: {', '.join(unused_pools)}", file=file, path="$.events")
    return result


def expected_visual_slots(
    *,
    map_spec: MapSpec,
    locations: Mapping[str, LocationSpec],
    residents: Mapping[int, ResidentSpec],
) -> dict[str, tuple[str, str]]:
    """Return the complete semantic slot contract for an editable world."""

    result: dict[str, tuple[str, str]] = {
        "map.image": ("map_image", map_spec.map_id),
        "actors.participant.map_thumbnail": (
            "actor_map_thumbnail",
            "participant",
        ),
        "actors.participant.dialogue_portrait": (
            "actor_dialogue_portrait",
            "participant",
        ),
    }
    for agent_id in sorted(residents):
        actor_id = f"resident:{agent_id}"
        result[f"actors.{actor_id}.map_thumbnail"] = (
            "actor_map_thumbnail",
            actor_id,
        )
        result[f"actors.{actor_id}.dialogue_portrait"] = (
            "actor_dialogue_portrait",
            actor_id,
        )
    for location_id in sorted(locations):
        result[f"locations.{location_id}.map_thumbnail"] = (
            "location_map_thumbnail",
            location_id,
        )
        result[f"locations.{location_id}.scene_image"] = (
            "location_scene_image",
            location_id,
        )
    return result


def _parse_visuals(
    document: Any,
    *,
    map_spec: MapSpec,
    locations: Mapping[str, LocationSpec],
    residents: Mapping[int, ResidentSpec],
) -> VisualSpec:
    file = "visuals.json"
    root = _object(document, file=file, path="$")
    _keys(
        root,
        required={"visual_version", "visual_assets", "visual_slots"},
        file=file,
        path="$",
    )
    visual_version = _identifier(
        root["visual_version"], file=file, path="$.visual_version"
    )
    asset_rows = _array(root["visual_assets"], file=file, path="$.visual_assets")
    if len(asset_rows) > MAX_VISUAL_ASSETS:
        _fail(
            f"contains more than {MAX_VISUAL_ASSETS} assets",
            file=file,
            path="$.visual_assets",
        )
    assets: dict[str, VisualAssetSpec] = {}
    file_names: list[str] = []
    for index, raw in enumerate(asset_rows):
        path = f"$.visual_assets[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "asset_key",
                "file_name",
                "mime_type",
                "width",
                "height",
                "sha256",
                "source",
                "license",
            },
            file=file,
            path=path,
        )
        asset_key = _identifier(
            item["asset_key"], file=file, path=f"{path}.asset_key"
        )
        if asset_key in assets:
            _fail(
                f"duplicate asset_key {asset_key!r}",
                file=file,
                path=f"{path}.asset_key",
            )
        mime_type = _string(
            item["mime_type"], file=file, path=f"{path}.mime_type"
        )
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            _fail(
                "must be image/png, image/jpeg, or image/webp",
                file=file,
                path=f"{path}.mime_type",
            )
        file_name = _string(
            item["file_name"], file=file, path=f"{path}.file_name"
        )
        try:
            validate_asset_file_name(file_name, mime_type)
        except VisualAssetValidationError as exc:
            _fail(str(exc), file=file, path=f"{path}.file_name")
        width = _integer(
            item["width"],
            file=file,
            path=f"{path}.width",
            minimum=1,
            maximum=MAX_IMAGE_WIDTH,
        )
        height = _integer(
            item["height"],
            file=file,
            path=f"{path}.height",
            minimum=1,
            maximum=MAX_IMAGE_HEIGHT,
        )
        if width * height > MAX_IMAGE_PIXELS:
            _fail(
                f"decoded image exceeds {MAX_IMAGE_PIXELS} pixels",
                file=file,
                path=path,
            )
        sha256 = _string(item["sha256"], file=file, path=f"{path}.sha256")
        if not SHA256_RE.fullmatch(sha256):
            _fail(
                "must be 64 lowercase hexadecimal characters",
                file=file,
                path=f"{path}.sha256",
            )
        assets[asset_key] = VisualAssetSpec(
            asset_key=asset_key,
            file_name=file_name,
            mime_type=mime_type,
            width=width,
            height=height,
            sha256=sha256,
            source=_string(item["source"], file=file, path=f"{path}.source"),
            license=_string(item["license"], file=file, path=f"{path}.license"),
        )
        file_names.append(file_name)
    _unique(file_names, label="asset filename", file=file, path="$.visual_assets")

    expected = expected_visual_slots(
        map_spec=map_spec,
        locations=locations,
        residents=residents,
    )
    slots: dict[str, VisualSlotSpec] = {}
    slot_rows = _array(root["visual_slots"], file=file, path="$.visual_slots")
    for index, raw in enumerate(slot_rows):
        path = f"$.visual_slots[{index}]"
        item = _object(raw, file=file, path=path)
        _keys(
            item,
            required={
                "slot_id",
                "slot_type",
                "target_id",
                "asset_key",
                "fallback_palette_key",
                "fallback_title",
                "fallback_description",
            },
            file=file,
            path=path,
        )
        slot_id = _string(item["slot_id"], file=file, path=f"{path}.slot_id")
        if slot_id in slots:
            _fail(f"duplicate slot_id {slot_id!r}", file=file, path=f"{path}.slot_id")
        if slot_id not in expected:
            _fail("slot is not part of this world's visual contract", file=file, path=f"{path}.slot_id")
        expected_type, expected_target = expected[slot_id]
        slot_type = _identifier(item["slot_type"], file=file, path=f"{path}.slot_type")
        if slot_type != expected_type:
            _fail(f"must be {expected_type!r}", file=file, path=f"{path}.slot_type")
        target_id = _string(item["target_id"], file=file, path=f"{path}.target_id")
        if target_id != expected_target:
            _fail(f"must be {expected_target!r}", file=file, path=f"{path}.target_id")
        asset_key_value = item["asset_key"]
        if asset_key_value is not None:
            asset_key_value = _identifier(
                asset_key_value, file=file, path=f"{path}.asset_key"
            )
            if asset_key_value not in assets:
                _fail("references a missing visual asset", file=file, path=f"{path}.asset_key")
        palette = _identifier(
            item["fallback_palette_key"],
            file=file,
            path=f"{path}.fallback_palette_key",
        )
        if palette not in VISUAL_PALETTE_KEYS:
            _fail("fallback palette key is not in the safe allowlist", file=file, path=f"{path}.fallback_palette_key")
        slots[slot_id] = VisualSlotSpec(
            slot_id=slot_id,
            slot_type=slot_type,  # type: ignore[arg-type]
            target_id=target_id,
            asset_key=asset_key_value,
            fallback_palette_key=palette,
            fallback_title=_localized(item["fallback_title"], file=file, path=f"{path}.fallback_title"),
            fallback_description=_localized(item["fallback_description"], file=file, path=f"{path}.fallback_description"),
        )
    missing_slots = sorted(set(expected) - set(slots))
    if missing_slots:
        _fail(
            "missing required visual slot(s): " + ", ".join(missing_slots),
            file=file,
            path="$.visual_slots",
        )
    return VisualSpec(
        visual_version=visual_version,
        visual_assets=assets,
        visual_slots=slots,
    )


def build_world_spec(*, manifest: Any, documents: Mapping[str, Any]) -> WorldSpec:
    validate_manifest_for_loading(manifest)
    item = _object(manifest, file="manifest.json", path="$")
    calendar_raw = _object(item["calendar"], file="manifest.json", path="$.calendar")
    try:
        calendar = CalendarSpec(
            total_days=calendar_raw["total_days"],
            day_start_minute=calendar_raw["day_start_minute"],
            day_end_minute=calendar_raw["day_end_minute"],
            rollover=calendar_raw["rollover"],
        )
    except WorldSpecValidationError as exc:
        _fail(str(exc), file="manifest.json", path="$.calendar")

    world_version = item["world_version"]
    event_pack_version = item["event_pack_version"]
    locations = _parse_locations(documents["locations"], world_version=world_version)
    rest_location = item.get("experience", {}).get("rest_location_id")
    if rest_location is not None and rest_location not in locations:
        _fail("references a missing location", file="manifest.json", path="$.experience.rest_location_id")
    map_spec = _parse_map(
        documents["map"],
        locations=locations,
        schema_version=item["schema_version"],
    )
    residents = _parse_residents(documents["residents"], locations=locations, calendar=calendar)
    visual_spec = (
        _parse_visuals(
            documents["visuals"],
            map_spec=map_spec,
            locations=locations,
            residents=residents,
        )
        if item["schema_version"] in {SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5}
        else None
    )
    event_specs = _parse_events(
        documents["events"],
        locations=locations,
        residents=residents,
        event_pack_version=event_pack_version,
        calendar=calendar,
        schema_version=item["schema_version"],
    )
    systems = (
        _parse_systems(
            documents["systems"],
            locations=locations,
            schema_version=item["schema_version"],
        )
        if item["schema_version"] in {SCHEMA_V4, SCHEMA_V5}
        else {}
    )
    start_location_id = item["start_location_id"]
    if start_location_id not in locations:
        _fail("references a missing location", file="manifest.json", path="$.start_location_id")

    try:
        spec = WorldSpec(
            world_version=world_version,
            scenario_pack_version=event_pack_version,
            start_location_id=start_location_id,
            calendar=calendar,
            locations=locations,
            residents=residents,
            action_minutes=dict(item["action_minutes"]),
            content_pack_version=item["content_pack_version"],
            event_pack_version=event_pack_version,
            map_spec=map_spec,
            event_specs=event_specs,
            visual_spec=visual_spec,
            content_schema_version=item["schema_version"],
            experience=dict(item.get("experience") or {}),
            systems=systems,
        )
        validate_location_graph(spec)
        validate_resident_schedules(spec)
    except WorldSpecValidationError as exc:
        _fail(str(exc), file="residents.json", path="$.residents")
    for resident in spec.residents.values():
        previous_location: str | None = None
        for day in range(1, spec.calendar.total_days + 1):
            if spec.world_version == 'chaoxi-holiday-v6':
                # Allow overnight commuting; daytime moves must stay adjacent.
                previous_location = None
            for minute in range(
                spec.calendar.day_start_minute,
                spec.calendar.day_end_minute + 1,
            ):
                location_id = resolve_resident_schedule(
                    spec,
                    resident.agent_id,
                    day,
                    minute,
                ).location_id
                if (
                    previous_location is not None
                    and location_id != previous_location
                    and not can_travel(spec, previous_location, location_id)
                ):
                    _fail(
                        "schedule moves between non-adjacent locations "
                        f"{previous_location!r} and {location_id!r}",
                        file="residents.json",
                        path=f"$.residents[agent_id={resident.agent_id}].schedule",
                    )
                previous_location = location_id
    return spec


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a MindScape Island content pack.")
    parser.add_argument("--pack", required=True, help="Path to the content pack directory")
    args = parser.parse_args(argv)
    from content.loader import load_content_pack

    try:
        loaded = load_content_pack(args.pack)
    except ContentPackValidationError as exc:
        print(f"validation failed: {exc}")
        return 1
    print("validation passed")
    print(json.dumps(loaded.summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
