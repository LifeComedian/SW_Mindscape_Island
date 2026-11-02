"""Deterministic trigger evaluation for validated declarative content events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldEventInstance,
    WorldEventTriggerEvaluation,
    WorldState,
)
from services.world_event_service import (
    WorldEventRuntimeError,
    create_event_instance,
)
from world.registry import get_world_spec
from world.specs import EventContentSpec, WorldSpec


DECLARATIVE_TRIGGER_VERSION = "declarative-trigger-v1"
TRIGGER_ACTION_TYPES = frozenset({"move", "wait", "end_day"})


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _elapsed_minutes(
    *, from_day: int, from_minute: int, to_day: int, to_minute: int
) -> int:
    return (to_day - from_day) * 1440 + to_minute - from_minute


def _event_id(event: WorldEventInstance) -> str | None:
    metadata = _json_loads(event.metadata_json, {})
    value = metadata.get("declarative_event_id")
    return value if isinstance(value, str) else None


def _event_history(
    db: DBSession,
    *,
    session_id: int,
) -> dict[str, list[WorldEventInstance]]:
    history: dict[str, list[WorldEventInstance]] = {}
    rows = (
        db.query(WorldEventInstance)
        .filter(WorldEventInstance.session_id == session_id)
        .order_by(WorldEventInstance.id.asc())
        .all()
    )
    for row in rows:
        content_event_id = _event_id(row)
        if content_event_id is not None:
            history.setdefault(content_event_id, []).append(row)
    return history


def _world_flags(world: WorldState) -> set[str]:
    state = _json_loads(world.state_json, {})
    raw = state.get("flags", {})
    if isinstance(raw, Mapping):
        return {str(key) for key, value in raw.items() if value is True}
    if isinstance(raw, list):
        return {str(value) for value in raw if isinstance(value, str)}
    return set()


def _trigger_matches(event: EventContentSpec, action: WorldAction) -> bool:
    if event.trigger_type == "on_location_enter":
        return action.action_type == "move"
    if event.trigger_type in {"on_world_tick", "on_time_window"}:
        return action.action_type in TRIGGER_ACTION_TYPES
    return False


def _structured_conditions_match(
    db: DBSession,
    *,
    event: EventContentSpec,
    world: WorldState,
    action: WorldAction,
) -> bool:
    config = event.trigger_conditions
    if not isinstance(config, Mapping):
        return True
    rows = config.get("items", ())
    if not rows:
        return True
    flags = _world_flags(world)
    world_state = _json_loads(world.state_json, {})
    goals = world_state.get("goals", {}) if isinstance(world_state, Mapping) else {}
    action_metadata = _json_loads(action.metadata_json, {})
    results: list[bool] = []
    for row in rows:
        if not isinstance(row, Mapping):
            results.append(False)
            continue
        kind = str(row.get("type", ""))
        operator = str(row.get("operator", "equals"))
        value = row.get("value")
        if kind == "world_day":
            actual = world.current_day
            results.append(actual == value if operator == "equals" else actual >= value if operator == "at_least" else actual <= value)
        elif kind == "world_time":
            actual = world.current_time_minutes
            results.append(actual >= value if operator == "at_least" else actual <= value)
        elif kind == "location":
            results.append(world.participant_location_id == value)
        elif kind == "action_type":
            results.append(action.action_type == value)
        elif kind == "object_choice":
            results.append(action.target_object_id == value)
        elif kind == "resident_present":
            present = db.query(CharacterState.id).filter(
                CharacterState.session_id == world.session_id,
                CharacterState.agent_id == int(value),
                CharacterState.current_location_id == world.participant_location_id,
            ).first()
            results.append(present is not None)
        elif kind == "flag":
            results.append(str(value) in flags)
        elif kind == "goal_status":
            goal_id, _, status = str(value).rpartition(".")
            goal = goals.get(goal_id) if isinstance(goals, Mapping) else None
            results.append(isinstance(goal, Mapping) and str(goal.get("status")) == status)
        elif kind == "event_status":
            event_id, _, status = str(value).rpartition(".")
            found = any(
                _event_id(instance) == event_id and instance.status == status
                for instance in db.query(WorldEventInstance).filter(WorldEventInstance.session_id == world.session_id).all()
            )
            results.append(found)
        else:
            results.append(False)
    return any(results) if config.get("mode") == "any" else all(results)


def _candidate_reasons(
    db: DBSession,
    *,
    spec: WorldSpec,
    event: EventContentSpec,
    world: WorldState,
    action: WorldAction,
    history: dict[str, list[WorldEventInstance]],
) -> list[str]:
    reasons: list[str] = []
    location = spec.locations[world.participant_location_id]
    if world.participant_location_id not in event.location_ids:
        reasons.append("location_mismatch")
    if not set(event.event_pool_ids).intersection(location.event_pool_ids):
        reasons.append("pool_mismatch")
    if not _trigger_matches(event, action):
        reasons.append("trigger_mismatch")
    if not _structured_conditions_match(db, event=event, world=world, action=action):
        reasons.append("structured_conditions")
    if event.time_window is not None:
        start, end = event.time_window
        if not start <= world.current_time_minutes <= end:
            reasons.append("outside_time_window")

    prerequisites = event.prerequisites
    minimum_day = int(prerequisites.get("min_day", 1))
    maximum_day = int(prerequisites.get("max_day", spec.calendar.total_days))
    if not minimum_day <= world.current_day <= maximum_day:
        reasons.append("day_prerequisite")
    required_flags = {str(item) for item in prerequisites.get("required_flags", ())}
    if not required_flags.issubset(_world_flags(world)):
        reasons.append("flag_prerequisite")
    raw_world_state = _json_loads(world.state_json, {})
    raw_goals = raw_world_state.get("goals", {})
    goals = raw_goals if isinstance(raw_goals, Mapping) else {}
    for requirement in prerequisites.get("required_goals", ()):
        if not isinstance(requirement, Mapping):
            reasons.append("goal_prerequisite")
            continue
        goal_id = str(requirement.get("goal_id", ""))
        statuses = {str(item) for item in requirement.get("statuses", ())}
        goal = goals.get(goal_id)
        if not isinstance(goal, Mapping) or str(goal.get("status", "")) not in statuses:
            reasons.append("goal_prerequisite")
            break
    required_residents = {int(item) for item in prerequisites.get("required_resident_ids", ())}
    if required_residents:
        present = {
            int(row[0])
            for row in db.query(CharacterState.agent_id)
            .filter(
                CharacterState.session_id == world.session_id,
                CharacterState.current_location_id == world.participant_location_id,
                CharacterState.agent_id.in_(required_residents),
            )
            .all()
        }
        if present != required_residents:
            reasons.append("resident_prerequisite")

    occurrences = history.get(event.event_id, [])
    if len(occurrences) >= event.max_occurrences:
        reasons.append("max_occurrences")
    if occurrences and event.cooldown_minutes > 0:
        latest = occurrences[-1]
        elapsed = _elapsed_minutes(
            from_day=latest.started_day,
            from_minute=latest.started_time_minutes,
            to_day=world.current_day,
            to_minute=world.current_time_minutes,
        )
        if 0 <= elapsed < event.cooldown_minutes:
            reasons.append("cooldown")
    return reasons


def _deterministic_roll(
    *,
    simulation_seed: int,
    event_pack_version: str,
    day: int,
    minute: int,
    location_id: str,
    trigger_counter: int,
    candidate_ids: list[str],
) -> float:
    payload = "|".join(
        (
            str(simulation_seed),
            event_pack_version,
            str(day),
            str(minute),
            location_id,
            str(trigger_counter),
            ",".join(candidate_ids),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def _select_candidate(
    candidates: list[EventContentSpec],
    roll: float,
) -> tuple[EventContentSpec | None, float, float]:
    total_weight = sum(float(item.weight) for item in candidates)
    selection_span = max(1.0, total_weight)
    point = roll * selection_span
    cursor = 0.0
    for event in candidates:
        cursor += float(event.weight)
        if point < cursor:
            return event, point, total_weight
    return None, point, total_weight


def evaluate_declarative_events(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    action: WorldAction,
) -> WorldEventTriggerEvaluation | None:
    """Evaluate once for a committed-intent write; GET endpoints never call this."""

    if action.action_type not in TRIGGER_ACTION_TYPES:
        return None
    if action.session_id != session.id or world.session_id != session.id:
        raise WorldEventRuntimeError("Trigger source does not belong to this session.", 409)
    spec = get_world_spec(world.world_version)
    if not spec.event_specs or not spec.event_pack_version:
        return None
    trigger_key = f"declarative:{spec.event_pack_version}:{action.id}"
    existing = (
        db.query(WorldEventTriggerEvaluation)
        .filter(
            WorldEventTriggerEvaluation.session_id == session.id,
            WorldEventTriggerEvaluation.trigger_key == trigger_key,
        )
        .first()
    )
    if existing is not None:
        return existing

    trigger_counter = (
        db.query(WorldEventTriggerEvaluation.id)
        .filter(
            WorldEventTriggerEvaluation.session_id == session.id,
            WorldEventTriggerEvaluation.event_pack_version == spec.event_pack_version,
        )
        .count()
        + 1
    )
    history = _event_history(db, session_id=session.id)
    rejected: dict[str, list[str]] = {}
    candidates: list[EventContentSpec] = []
    for event in sorted(spec.event_specs.values(), key=lambda item: item.event_id):
        reasons = _candidate_reasons(
            db,
            spec=spec,
            event=event,
            world=world,
            action=action,
            history=history,
        )
        if reasons:
            rejected[event.event_id] = reasons
        else:
            candidates.append(event)

    candidate_ids = [item.event_id for item in candidates]
    roll = _deterministic_roll(
        simulation_seed=session.simulation_seed,
        event_pack_version=spec.event_pack_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        location_id=world.participant_location_id,
        trigger_counter=trigger_counter,
        candidate_ids=candidate_ids,
    )
    outcome = "no_event"
    reason_code = "no_eligible_candidates"
    selected: EventContentSpec | None = None
    selection_point: float | None = None
    total_weight = 0.0

    active_scenario = (
        db.query(ScenarioInstance.id)
        .filter(
            ScenarioInstance.session_id == session.id,
            ScenarioInstance.location_id == world.participant_location_id,
            ScenarioInstance.status == "active",
        )
        .first()
    )
    active_event = (
        db.query(WorldEventInstance.id)
        .filter(
            WorldEventInstance.session_id == session.id,
            WorldEventInstance.location_id == world.participant_location_id,
            WorldEventInstance.status == "active",
        )
        .first()
    )
    if active_scenario is not None:
        reason_code = "legacy_scenario_priority"
    elif active_event is not None:
        reason_code = "active_event_priority"
    elif candidates:
        selected, selection_point, total_weight = _select_candidate(candidates, roll)
        if selected is None:
            reason_code = "probability_miss"
        else:
            outcome = "selected"
            reason_code = "deterministic_selection"

    evaluation = WorldEventTriggerEvaluation(
        session_id=session.id,
        source_action_id=action.id,
        trigger_key=trigger_key,
        event_pack_version=spec.event_pack_version,
        trigger_counter=trigger_counter,
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        location_id=world.participant_location_id,
        candidate_event_ids_json=_json_dumps(candidate_ids),
        selected_event_id=selected.event_id if selected else None,
        outcome=outcome,
        reason_code=reason_code,
        deterministic_roll=roll,
        metadata_json=_json_dumps(
            {
                "schema_version": DECLARATIVE_TRIGGER_VERSION,
                "action_type": action.action_type,
                "rejected": rejected,
                "selection_point": selection_point,
                "total_weight": total_weight,
            }
        ),
    )
    db.add(evaluation)
    db.flush()
    if selected is None:
        return evaluation

    occurrence = len(history.get(selected.event_id, [])) + 1
    selected_world_state = _json_loads(world.state_json, {})
    raw_selected_goals = selected_world_state.get("goals", {})
    goals = raw_selected_goals if isinstance(raw_selected_goals, Mapping) else {}
    selected_state: dict[str, Any] = {
        "state": selected.initial_stage_id or "presented",
        "event_id": selected.event_id,
    }
    required_goal_snapshots: dict[str, Any] = {}
    for requirement in selected.prerequisites.get("required_goals", ()):
        if not isinstance(requirement, Mapping):
            continue
        goal_id = str(requirement.get("goal_id", ""))
        goal = goals.get(goal_id)
        if goal_id and isinstance(goal, Mapping):
            required_goal_snapshots[goal_id] = dict(goal)
    if required_goal_snapshots:
        selected_state["trigger_goals"] = required_goal_snapshots
    event = create_event_instance(
        db,
        session=session,
        world=world,
        event_type=selected.event_type,
        event_version=selected.version,
        trigger_key=(
            f"declarative:{spec.event_pack_version}:{selected.event_id}:{occurrence}"
        ),
        location_id=world.participant_location_id,
        state=selected_state,
        metadata={
            "source": "declarative_trigger",
            "declarative_event_id": selected.event_id,
            "event_pack_version": spec.event_pack_version,
            "trigger_evaluation_id": evaluation.id,
            "trigger_counter": trigger_counter,
        },
    )
    evaluation.selected_event_instance_id = event.id
    return evaluation


def serialize_trigger_evaluation(
    evaluation: WorldEventTriggerEvaluation,
) -> dict[str, Any]:
    return {
        "trigger_evaluation_id": evaluation.id,
        "session_id": evaluation.session_id,
        "source_action_id": evaluation.source_action_id,
        "selected_event_instance_id": evaluation.selected_event_instance_id,
        "trigger_key": evaluation.trigger_key,
        "event_pack_version": evaluation.event_pack_version,
        "trigger_counter": evaluation.trigger_counter,
        "world_day": evaluation.world_day,
        "world_time_minutes": evaluation.world_time_minutes,
        "location_id": evaluation.location_id,
        "candidate_event_ids": _json_loads(
            evaluation.candidate_event_ids_json, []
        ),
        "selected_event_id": evaluation.selected_event_id,
        "outcome": evaluation.outcome,
        "reason_code": evaluation.reason_code,
        "deterministic_roll": evaluation.deterministic_roll,
        "metadata": _json_loads(evaluation.metadata_json, {}),
        "created_at": (
            evaluation.created_at.isoformat() if evaluation.created_at else None
        ),
    }
