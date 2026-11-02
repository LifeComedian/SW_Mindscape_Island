from agents.output_safety import preserve_stop
import json
import os
import random
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from agents import AgentRequest, AgentService
from agents.personas import get_persona
from agents.safety import check_user_comment_safety
from data.island import (
    CONFLICT_SCENARIO_ID,
    CONFLICT_VARIANTS,
    SCENARIO_PACK_VERSION,
    SCENARIO_VERSION,
    SEATING_FORMS,
    SEATING_SCENARIO_ID,
    TEXT,
    WORLD_VERSION,
    localized,
)
from data.restaurant_events import (
    RESTAURANT_CONFLICT_EVENT_TYPE,
    RESTAURANT_CONFLICT_VERSION,
    RESTAURANT_FOLLOW_UP_EVENT_TYPE,
    RESTAURANT_SEATING_EVENT_TYPE,
    RESTAURANT_SEATING_VERSION,
    conflict_event_state,
    seating_event_state,
)
from models import (
    CharacterState,
    ResidentIntentState,
    RelationshipChange,
    RelationshipState,
    ScenarioExposure,
    ScenarioInstance,
    ScenarioResponse,
    Session as UserSession,
    UserPost,
    WorldAction,
    WorldAtomicActionExecution,
    WorldBoardPost,
    WorldCommitment,
    WorldConversation,
    WorldConversationParticipant,
    WorldConversationTurn,
    WorldEventInstance,
    WorldEventTriggerEvaluation,
    WorldEmergenceDecision,
    WorldEmergenceEvaluation,
    WorldEmergenceCandidate,
    WorldEmergentEventRuntime,
    WorldEmergentEventTransition,
    WorldEventStage,
    WorldEventStageOperation,
    WorldDecisionInvocation,
    WorldDecisionAttempt,
    WorldInteractionPrompt,
    WorldMemory,
    WorldPlanMember,
    WorldPlanNotice,
    WorldPlanTransition,
    WorldPlanSocialProjection,
    WorldPlanVariantConsent,
    WorldPlanVariantProposal,
    WorldKnowledgeFact,
    WorldActorKnowledge,
    WorldSocialPostView,
    WorldResourceReservation,
    WorldSimulationPulse,
    WorldScheduledEvent,
    WorldState,
)
from services.world_event_service import (
    WorldEventRuntimeError,
    apply_event_action,
    create_event_instance,
    deliver_due_scheduled_events,
    get_active_event_instance,
    scheduled_event_due_points,
    serialize_event_export,
    serialize_event_instance,
    serialize_scheduled_event_export,
)
from services.behavioral_event_analytics import build_behavioral_event_records
from services.declarative_event_service import (
    evaluate_declarative_events,
    serialize_trigger_evaluation,
)
from services.world_memory_service import (
    build_agent_memory_context,
    record_memory,
)
from services.resident_runtime_service import (
    ResidentRuntimeError,
    _upsert_schedule_intent,
    run_resident_tick,
)
from services.world_relationship_service import (
    RelationshipStateError,
    apply_conversation_first_exchange,
    serialize_relationship,
    serialize_relationship_change,
)
from services.interaction_prompt_service import (
    invalidate_pending_interaction_prompts,
    serialize_interaction_prompt,
)
from services.world_social_publication_service import (
    evaluate_event_social_publications,
)
from world.clock import ClockAdvance, ClockPosition, advance_clock, advance_to_next_day, is_due
from world.graph import can_travel, object_exists, shortest_travel_path
from world.emergence_contracts import MODULAR_SYSTEMS_CONTRACT_VERSION
from world.registry import get_world_spec
from world.schedules import (
    ScheduleResolutionError,
    resolve_resident_schedule,
    schedule_transition_points,
)
from world.specs import LocationSpec, MapSpec, ScheduleBlock, WorldSpec


WORLD_ACTIONS = {
    "move",
    "observe",
    "approach",
    "wait",
    "end_day",
    "event_action",
    "seat_view",
    "seat_select",
    "seat_change",
    "scenario_response",
    "scenario_skip",
    "end_conversation",
    "defined_action",
}
CONFLICT_RESPONSES = {"clarify", "negotiate", "leave", "free_text"}


# The v0.3 server runs as one application process against SQLite. SQLite does not
# provide row-level SELECT ... FOR UPDATE semantics, so keep each session's short
# read/modify/write section serial within that process. Remote reply generation is
# deliberately performed outside this lock; only its optimistic recheck and write
# phase is serialized.
_SESSION_LOCKS: dict[int, threading.RLock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


@contextmanager
def session_write_lock(session_id: int):
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.setdefault(session_id, threading.RLock())
    with lock:
        yield


class WorldStateError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 400, reason_code: str | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.reason_code = reason_code


def _resolve_world_spec(world_version: str | None = None) -> WorldSpec:
    try:
        return get_world_spec(world_version)
    except KeyError as exc:
        raise WorldStateError(
            f"World content version is not available: {world_version}.",
            409,
        ) from exc


def _resolve_bound_world_spec(world: WorldState) -> WorldSpec:
    """Resolve and verify the immutable content versions bound to a session."""

    spec = _resolve_world_spec(world.world_version)
    if world.scenario_pack_version != spec.scenario_pack_version:
        raise WorldStateError(
            "The session's scenario pack does not match its bound world version.",
            409,
        )
    return spec


def _configured_default_world_version() -> str | None:
    return (
        os.getenv("ISLAND_DEFAULT_WORLD_VERSION")
        or os.getenv("WORLD_DEFAULT_VERSION")
        or None
    )


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _time_label(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def list_locations(world_version: str | None = None) -> list[dict[str, Any]]:
    spec = _resolve_world_spec(world_version)
    return [_serialize_location(location) for location in spec.locations.values()]


def _serialize_location(location: LocationSpec) -> dict[str, Any]:
    return {
        "location_id": location.location_id,
        "name": location.name["en"],
        "name_zh_cn": location.name.get("zh-CN", location.name["en"]),
        "description": location.description["en"],
        "description_zh_cn": location.description.get(
            "zh-CN", location.description["en"]
        ),
        "translations": {
            "en": {
                "name": location.name["en"],
                "description": location.description["en"],
            },
            "zh-CN": {
                "name": location.name.get("zh-CN", location.name["en"]),
                "description": location.description.get(
                    "zh-CN", location.description["en"]
                ),
            },
        },
        "scene_type": location.scene_type,
        "connected_location_ids": list(location.connected_location_ids),
        "opening_hours": dict(location.opening_hours),
        "is_open": bool(location.opening_hours.get("always_open", False)),
        "allowed_actions": list(location.allowed_actions),
        "interaction_points": [dict(item) for item in location.interaction_points],
        "version": location.version,
    }


def _schedule_for(
    spec: WorldSpec,
    agent_id: int,
    day: int,
    minute: int,
) -> ScheduleBlock:
    try:
        return resolve_resident_schedule(spec, agent_id, day, minute)
    except ScheduleResolutionError as exc:
        raise WorldStateError(str(exc), 409) from exc


def initialize_world(
    db: DBSession,
    session: UserSession,
    *,
    world_version: str | None = None,
    commit: bool = True,
) -> WorldState:
    world = (
        db.query(WorldState)
        .filter(WorldState.session_id == session.id)
        .first()
    )
    spec = (
        _resolve_bound_world_spec(world)
        if world is not None
        else _resolve_world_spec(world_version or _configured_default_world_version())
    )
    changed = False
    if world is None:
        world = WorldState(
            session_id=session.id,
            current_day=1,
            current_time_minutes=spec.calendar.day_start_minute,
            participant_location_id=spec.start_location_id,
            world_version=spec.world_version,
            scenario_pack_version=spec.scenario_pack_version,
            state_json=_json_dumps(
                {
                    "schema_version": "world-state-v1",
                    "vertical_slice_days": spec.calendar.total_days,
                    "clock_rollover": spec.calendar.rollover,
                }
            ),
        )
        db.add(world)
        db.flush()
        changed = True

    existing_agent_ids = {
        row.agent_id
        for row in db.query(CharacterState)
        .filter(CharacterState.session_id == session.id)
        .all()
    }
    for agent_id in spec.residents:
        if agent_id in existing_agent_ids:
            continue
        schedule = _schedule_for(
            spec,
            agent_id,
            world.current_day,
            world.current_time_minutes,
        )
        db.add(
            CharacterState(
                session_id=session.id,
                agent_id=agent_id,
                current_location_id=schedule.location_id,
                current_activity=localized(schedule.activity, "en"),
                current_goal=localized(schedule.goal, "en"),
                schedule_state=schedule.state_id,
                state_json=_json_dumps(
                    {
                        "schema_version": "resident-state-v1",
                        "last_schedule_day": world.current_day,
                        "flags": {},
                    }
                ),
            )
        )
        changed = True

    db.flush()
    changed = _ensure_resident_intent_states(db, world, spec) or changed
    changed = _sync_residents(db, world, spec) or changed
    if commit and changed:
        world.updated_at = utc_now()
        db.commit()
        db.refresh(world)
    elif not commit:
        db.flush()
    return world


def _ensure_resident_intent_states(
    db: DBSession,
    world: WorldState,
    spec: WorldSpec,
) -> bool:
    existing_agent_ids = {
        row.agent_id
        for row in db.query(ResidentIntentState.agent_id)
        .filter(ResidentIntentState.session_id == world.session_id)
        .all()
    }
    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == world.session_id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    changed = False
    for resident in residents:
        if resident.agent_id in existing_agent_ids:
            continue
        schedule = _schedule_for(
            spec,
            resident.agent_id,
            world.current_day,
            world.current_time_minutes,
        )
        db.add(
            ResidentIntentState(
                session_id=world.session_id,
                agent_id=resident.agent_id,
                intent_type="follow_schedule",
                status="active",
                target_location_id=schedule.location_id,
                started_day=world.current_day,
                started_time_minutes=world.current_time_minutes,
                due_day=world.current_day,
                due_time_minutes=schedule.end_minute,
                policy_id="schedule-driven",
                policy_version="v1",
                summary_json=_json_dumps(
                    {
                        "en": localized(schedule.activity, "en"),
                        "zh-CN": localized(schedule.activity, "zh-CN"),
                    }
                ),
                metadata_json=_json_dumps(
                    {"schedule_state_id": schedule.state_id, "source": "schedule"}
                ),
            )
        )
        changed = True
    if changed:
        db.flush()
    return changed


def _sync_residents(
    db: DBSession,
    world: WorldState,
    spec: WorldSpec | None = None,
) -> bool:
    spec = spec or _resolve_bound_world_spec(world)
    session_id = world.session_id
    changed = False
    rows = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == session_id)
        .all()
    )
    for row in rows:
        if spec.world_version.startswith("chaoxi-holiday-"):
            from services.holiday_routine_service import sync_routine
            sync_routine(db, world=world, spec=spec, resident=row)
            continue
        from services.scheduled_action_service import actor_busy
        if actor_busy(world, f"resident:{row.agent_id}"):
            continue
        if spec.content_schema_version == "content-pack-v5":
            from services.plan_service import resident_is_in_active_plan

            if resident_is_in_active_plan(db, session_id=session_id, agent_id=row.agent_id, location_id=row.current_location_id):
                continue
        schedule = _schedule_for(
            spec,
            row.agent_id,
            world.current_day,
            world.current_time_minutes,
        )
        resident_state = _json_loads(row.state_json, {})
        has_free_time_override = (
            isinstance(resident_state, dict)
            and resident_state.get("autonomy_schedule_override_state")
            == schedule.state_id
            and schedule.state_id
            in spec.residents[row.agent_id].autonomy.free_time_state_ids
        )
        if (
            row.current_location_id != schedule.location_id
            and not has_free_time_override
        ):
            for conversation in (
                db.query(WorldConversation)
                .filter(
                    WorldConversation.session_id == session_id,
                    WorldConversation.agent_id == row.agent_id,
                    WorldConversation.status == "active",
                )
                .all()
            ):
                conversation.status = "ended"
                conversation.updated_at = utc_now()
        if (
            (
                row.current_location_id != schedule.location_id
                and not has_free_time_override
            )
            or row.schedule_state != schedule.state_id
        ):
            row.current_location_id = schedule.location_id
            row.current_activity = localized(schedule.activity, "en")
            row.current_goal = localized(schedule.goal, "en")
            row.schedule_state = schedule.state_id
            state = _json_loads(row.state_json, {})
            state.setdefault("schema_version", "resident-state-v1")
            state.setdefault("flags", {})
            state["last_schedule_day"] = world.current_day
            state.pop("autonomy_schedule_override_state", None)
            row.state_json = _json_dumps(state)
            row.updated_at = utc_now()
            _upsert_schedule_intent(
                db,
                world=world,
                resident=row,
                schedule=schedule,
                source_action_id=None,
            )
            changed = True
    return changed


def _process_clock_advance(
    db: DBSession,
    world: WorldState,
    spec: WorldSpec,
    advanced: ClockAdvance,
    *,
    max_due_events: int | None = None,
) -> list[WorldAction]:
    resident_actions: list[WorldAction] = []
    delivered_due_event_count = 0
    transition_points = set(
        schedule_transition_points(
            spec,
            advanced.before.day,
            advanced.before.minute,
            advanced.after.day,
            advanced.after.minute,
        )
    )
    scheduled_follow_ups = (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.session_id == world.session_id,
            ScenarioInstance.follow_up_status == "scheduled",
            ScenarioInstance.follow_up_due_day.is_not(None),
            ScenarioInstance.follow_up_due_time_minutes.is_not(None),
        )
        .all()
    )
    for scenario in scheduled_follow_ups:
        due = ClockPosition(
            scenario.follow_up_due_day,
            scenario.follow_up_due_time_minutes,
        )
        if advanced.before < due <= advanced.after:
            transition_points.add(due)
    transition_points.update(
        scheduled_event_due_points(
            db,
            world=world,
            before=advanced.before,
            after=advanced.after,
        )
    )
    transition_points.add(advanced.after)
    from services.scheduled_action_service import due_points, reconcile_jobs
    from world.autonomy_policy import autonomy_policy
    shared_clock = autonomy_policy(spec)
    if shared_clock:
        from services.autonomous_world_service import plan_due_points, maintain_confirmed_plans
        transition_points.update(plan_due_points(db, world, spec, advanced.before, advanced.after))
        maintain_confirmed_plans(db, world=world, spec=spec)
        transition_points.update(due_points(world, advanced.before, advanced.after))

    for point in sorted(transition_points):
        world.current_day = point.day
        world.current_time_minutes = point.minute
        world.updated_at = utc_now()
        try:
            if shared_clock:
                reconcile_jobs(db, world=world, spec=spec)
                maintain_confirmed_plans(db, world=world, spec=spec)
                _sync_residents(db, world, spec)
            else:
                resident_actions.extend(
                run_resident_tick(
                    db,
                    spec=spec,
                    world=world,
                    trigger_type="clock_transition",
                )
                )
        except ResidentRuntimeError as exc:
            raise WorldStateError(exc.detail, exc.status_code) from exc
        _deliver_due_follow_ups(db, world)
        try:
            remaining_due_events = (
                None
                if max_due_events is None
                else max(0, max_due_events - delivered_due_event_count)
            )
            delivered_events = (
                deliver_due_scheduled_events(
                    db,
                    world=world,
                    limit=remaining_due_events,
                )
                if remaining_due_events is None or remaining_due_events > 0
                else []
            )
            delivered_due_event_count += len(delivered_events)
        except WorldEventRuntimeError as exc:
            raise WorldStateError(exc.detail, exc.status_code) from exc
        _mirror_delivered_restaurant_follow_ups(db, world, delivered_events)
    return resident_actions


def _advance_clock(
    db: DBSession,
    world: WorldState,
    minutes: int,
    *,
    max_due_events: int | None = None,
) -> list[WorldAction]:
    spec = _resolve_bound_world_spec(world)
    if world.world_version=='chaoxi-holiday-v6':
        minutes=min(max(0,minutes),spec.calendar.day_end_minute-world.current_time_minutes)
    if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and minutes % 5:
        raise WorldStateError('v5 的世界时间必须以 5 分钟为单位。', 422)
    advanced = advance_clock(
        spec.calendar,
        world.current_day,
        world.current_time_minutes,
        max(0, minutes),
    )
    return _process_clock_advance(
        db,
        world,
        spec,
        advanced,
        max_due_events=max_due_events,
    )


def advance_world_clock(
    db: DBSession,
    world: WorldState,
    minutes: int,
    *,
    max_due_events: int | None = None,
) -> list[WorldAction]:
    """Advance a bound world through the same audited clock path used by actions."""

    return _advance_clock(
        db,
        world,
        minutes,
        max_due_events=max_due_events,
    )


def _advance_to_next_day(db: DBSession, world: WorldState) -> ClockAdvance:
    spec = _resolve_bound_world_spec(world)
    advanced = advance_to_next_day(
        spec.calendar,
        world.current_day,
        world.current_time_minutes,
    )
    _process_clock_advance(db, world, spec, advanced)
    return advanced


def world_has_ended(world: WorldState) -> bool:
    return _world_has_ended(world)


def _action_minutes(
    action_type: str,
    metadata: dict[str, Any],
    world_version: str | None = None,
) -> int:
    if action_type == "wait":
        raw = metadata.get("minutes", 15)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise WorldStateError("metadata.minutes must be an integer.")
        if raw < 5 or raw > 120 or raw % 5 != 0:
            raise WorldStateError(
                "metadata.minutes must be between 5 and 120 in 5-minute steps."
            )
        return raw
    if action_type == "event_action":
        return 5
    if action_type == "defined_action":
        raw = metadata.get("defined_action_minutes")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise WorldStateError("defined_action requires a validated duration.", 409)
        return raw
    spec = _resolve_world_spec(world_version)
    if action_type == "move":
        raw_edge_count = metadata.get("travel_edge_count", 1)
        if (
            isinstance(raw_edge_count, bool)
            or not isinstance(raw_edge_count, int)
            or raw_edge_count < 1
        ):
            raise WorldStateError("move travel_edge_count must be a positive integer.")
        try:
            return int(spec.action_minutes[action_type]) * raw_edge_count
        except KeyError as exc:
            raise WorldStateError(
                f"World {spec.world_version} does not define time for {action_type}.",
                409,
            ) from exc
    try:
        return int(spec.action_minutes[action_type])
    except KeyError as exc:
        raise WorldStateError(
            f"World {spec.world_version} does not define time for {action_type}.",
            409,
        ) from exc


def _world_has_ended(
    world: WorldState,
    spec: WorldSpec | None = None,
) -> bool:
    spec = spec or _resolve_bound_world_spec(world)
    if world.world_version=='chaoxi-holiday-v6':
        return bool(_json_loads(world.state_json,{}).get('holiday_v6',{}).get('departure_confirmed'))
    return (
        world.current_day == spec.calendar.total_days
        and world.current_time_minutes >= spec.calendar.day_end_minute
    )


def ensure_session_can_finish(db: DBSession, session: UserSession) -> None:
    """Apply opt-in v4 departure gating without changing legacy worlds."""

    world = initialize_world(db, session)
    spec = _resolve_bound_world_spec(world)
    if (
        spec.experience.get("final_day_departure_required") is True
        and not _world_has_ended(world, spec)
    ):
        raise WorldStateError(
            "Departure becomes available after the final playable day is complete.",
            409,
        )


def _uses_legacy_v03_scenarios(spec: WorldSpec) -> bool:
    return (
        spec.world_version == WORLD_VERSION
        and spec.scenario_pack_version == SCENARIO_PACK_VERSION
    )


def _get_active_scenario(
    db: DBSession,
    session_id: int,
    location_id: str | None = None,
) -> ScenarioInstance | None:
    query = db.query(ScenarioInstance).filter(
        ScenarioInstance.session_id == session_id,
        ScenarioInstance.status == "active",
    )
    if location_id is not None:
        query = query.filter(ScenarioInstance.location_id == location_id)
    return query.order_by(
        ScenarioInstance.started_day.asc(),
        ScenarioInstance.started_time_minutes.asc(),
        ScenarioInstance.id.asc(),
    ).first()


def _scenario_actor_at_location(
    db: DBSession,
    session_id: int,
    location_id: str,
) -> int | None:
    present_agent_ids = [
        row[0]
        for row in (
            db.query(CharacterState.agent_id)
            .filter(
                CharacterState.session_id == session_id,
                CharacterState.current_location_id == location_id,
            )
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
    ]
    if 3 in present_agent_ids:
        return 3
    return present_agent_ids[0] if present_agent_ids else None


def _scenario_by_id(
    db: DBSession,
    session_id: int,
    scenario_instance_id: int | None,
) -> ScenarioInstance | None:
    if scenario_instance_id is None:
        return None
    return (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.id == scenario_instance_id,
            ScenarioInstance.session_id == session_id,
        )
        .first()
    )


def _scenario_metadata(scenario: ScenarioInstance) -> dict[str, Any]:
    return _json_loads(scenario.metadata_json, {})


def _set_scenario_metadata(
    scenario: ScenarioInstance,
    metadata: dict[str, Any],
) -> None:
    scenario.metadata_json = _json_dumps(metadata)
    scenario.updated_at = utc_now()


def _scenario_event_instance(
    db: DBSession,
    scenario: ScenarioInstance,
) -> WorldEventInstance | None:
    event_id = _scenario_metadata(scenario).get("event_instance_id")
    if not isinstance(event_id, int):
        return None
    return (
        db.query(WorldEventInstance)
        .filter(
            WorldEventInstance.id == event_id,
            WorldEventInstance.session_id == scenario.session_id,
        )
        .first()
    )


def _scenario_uses_event_runtime(scenario: ScenarioInstance) -> bool:
    metadata = _scenario_metadata(scenario)
    return bool(metadata.get("event_runtime_migrated")) and isinstance(
        metadata.get("event_instance_id"),
        int,
    )


def _event_is_legacy_scenario_bridge(event: WorldEventInstance | None) -> bool:
    if event is None:
        return False
    metadata = _json_loads(event.metadata_json, {})
    return bool(metadata.get("legacy_scenario_bridge"))


def _seating_options_for_scenario(
    db: DBSession,
    scenario: ScenarioInstance,
) -> list[dict[str, Any]]:
    exposure = (
        db.query(ScenarioExposure)
        .filter(ScenarioExposure.scenario_instance_id == scenario.id)
        .order_by(ScenarioExposure.id.asc())
        .first()
    )
    if exposure is not None:
        options = _json_loads(exposure.visible_options_json, [])
        if isinstance(options, list) and options:
            return [dict(item) for item in options if isinstance(item, dict)]
    return [dict(item) for item in SEATING_FORMS[scenario.form]]


def _seating_viewed_ids(
    db: DBSession,
    scenario: ScenarioInstance,
) -> list[str]:
    exposure = (
        db.query(ScenarioExposure)
        .filter(ScenarioExposure.scenario_instance_id == scenario.id)
        .order_by(ScenarioExposure.id.asc())
        .first()
    )
    if exposure is None:
        return []
    metadata = _json_loads(exposure.metadata_json, {})
    raw = metadata.get("viewed_option_ids", [])
    return [str(item) for item in raw if str(item)] if isinstance(raw, list) else []


def _selected_seat_id(
    db: DBSession,
    session_id: int,
) -> str | None:
    seating = (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.session_id == session_id,
            ScenarioInstance.scenario_id == SEATING_SCENARIO_ID,
        )
        .first()
    )
    if seating is None:
        return None
    selected = _scenario_metadata(seating).get("selected_option_id")
    return selected if isinstance(selected, str) and selected else None


def _ensure_restaurant_event_for_scenario(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    scenario: ScenarioInstance,
) -> WorldEventInstance | None:
    if scenario.scenario_type not in {"seating", "conflict"}:
        return None
    existing = _scenario_event_instance(db, scenario)
    if existing is not None:
        return existing
    if scenario.status != "active":
        return None

    metadata = _scenario_metadata(scenario)
    if scenario.scenario_type == "seating":
        event_type = RESTAURANT_SEATING_EVENT_TYPE
        event_version = RESTAURANT_SEATING_VERSION
        state = seating_event_state(
            scenario_instance_id=scenario.id,
            form=scenario.form,
            selected_option_id=metadata.get("selected_option_id"),
            viewed_option_ids=_seating_viewed_ids(db, scenario),
        )
    else:
        seating = (
            db.query(ScenarioInstance)
            .filter(
                ScenarioInstance.session_id == session.id,
                ScenarioInstance.scenario_id == SEATING_SCENARIO_ID,
            )
            .first()
        )
        options = (
            _seating_options_for_scenario(db, seating)
            if seating is not None
            else [dict(item) for item in SEATING_FORMS["layout_a"]]
        )
        event_type = RESTAURANT_CONFLICT_EVENT_TYPE
        event_version = RESTAURANT_CONFLICT_VERSION
        state = conflict_event_state(
            scenario_instance_id=scenario.id,
            variant=scenario.variant,
            selected_option_id=_selected_seat_id(db, session.id),
            options=options,
            assigned_agent_id=scenario.assigned_agent_id,
        )

    event = create_event_instance(
        db,
        session=session,
        world=world,
        event_type=event_type,
        event_version=event_version,
        trigger_key=f"legacy-scenario:{scenario.id}:{scenario.scenario_type}",
        location_id=scenario.location_id,
        state=state,
        metadata={
            "legacy_scenario_bridge": True,
            "scenario_instance_id": scenario.id,
            "scenario_id": scenario.scenario_id,
            "scenario_type": scenario.scenario_type,
            "scenario_version": scenario.scenario_version,
            "form": scenario.form,
            "variant": scenario.variant,
        },
    )
    metadata.update(
        {
            "event_runtime_migrated": True,
            "event_instance_id": event.id,
            "event_type": event.event_type,
            "event_version": event.event_version,
        }
    )
    _set_scenario_metadata(scenario, metadata)
    return event


def _apply_restaurant_event_action(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    scenario: ScenarioInstance,
    action: WorldAction,
    event_action_id: str,
    allow_optional_response_text: bool = False,
) -> WorldEventInstance | None:
    event = _ensure_restaurant_event_for_scenario(
        db,
        session=session,
        world=world,
        scenario=scenario,
    )
    if event is None:
        return None
    try:
        return apply_event_action(
            db,
            session=session,
            world=world,
            action=action,
            event_instance_id=event.id,
            event_action_id=event_action_id,
            replace_action_target_object_id=False,
            allow_optional_response_text=allow_optional_response_text,
        )
    except WorldEventRuntimeError as exc:
        raise WorldStateError(exc.detail, exc.status_code) from exc


def _ensure_seating_scenario(
    db: DBSession,
    session: UserSession,
    world: WorldState,
    language: str,
) -> ScenarioInstance | None:
    spec = _resolve_bound_world_spec(world)
    if not _uses_legacy_v03_scenarios(spec):
        raise WorldStateError(
            "The bound world does not use the legacy v0.3 scenario pack.",
            409,
        )
    existing = (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.session_id == session.id,
            ScenarioInstance.scenario_id == SEATING_SCENARIO_ID,
        )
        .first()
    )
    if existing is not None:
        _ensure_restaurant_event_for_scenario(
            db,
            session=session,
            world=world,
            scenario=existing,
        )
        return existing

    rng = random.Random(f"{session.simulation_seed}:island:seating")
    form = rng.choice(sorted(SEATING_FORMS))
    scenario = ScenarioInstance(
        session_id=session.id,
        scenario_id=SEATING_SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        form=form,
        scenario_type="seating",
        status="active",
        location_id="restaurant",
        variant="balanced_layout",
        assigned_agent_id=_scenario_actor_at_location(db, session.id, "restaurant"),
        started_day=world.current_day,
        started_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps({"selected_option_id": None}),
    )
    db.add(scenario)
    db.flush()
    options = SEATING_FORMS[form]
    db.add(
        ScenarioExposure(
            session_id=session.id,
            scenario_instance_id=scenario.id,
            stimulus_text=localized(TEXT["seating_stimulus"], language),
            visible_options_json=_json_dumps(options),
            layout_json=_json_dumps(
                {"form": form, "option_order": [item["option_id"] for item in options]}
            ),
            exposure_complete=True,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            language=language,
            metadata_json=_json_dumps({"viewed_option_ids": []}),
        )
    )
    _ensure_restaurant_event_for_scenario(
        db,
        session=session,
        world=world,
        scenario=scenario,
    )
    return scenario


def _ensure_conflict_scenario(
    db: DBSession,
    session: UserSession,
    world: WorldState,
    language: str,
) -> ScenarioInstance:
    spec = _resolve_bound_world_spec(world)
    if not _uses_legacy_v03_scenarios(spec):
        raise WorldStateError(
            "The bound world does not use the legacy v0.3 scenario pack.",
            409,
        )
    existing = (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.session_id == session.id,
            ScenarioInstance.scenario_id == CONFLICT_SCENARIO_ID,
        )
        .first()
    )
    if existing is not None:
        _ensure_restaurant_event_for_scenario(
            db,
            session=session,
            world=world,
            scenario=existing,
        )
        return existing

    rng = random.Random(f"{session.simulation_seed}:island:conflict")
    variant = rng.choice(list(CONFLICT_VARIANTS))
    scenario = ScenarioInstance(
        session_id=session.id,
        scenario_id=CONFLICT_SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        form="booking_mixup",
        scenario_type="conflict",
        status="active",
        location_id="restaurant",
        variant=variant,
        assigned_agent_id=_scenario_actor_at_location(db, session.id, "restaurant"),
        started_day=world.current_day,
        started_time_minutes=world.current_time_minutes,
        metadata_json="{}",
    )
    db.add(scenario)
    db.flush()
    options = [
        {"option_id": "clarify", "label": {"en": "Clarify what happened", "zh-CN": "澄清发生了什么"}},
        {"option_id": "negotiate", "label": {"en": "Negotiate another arrangement", "zh-CN": "协商其他安排"}},
        {"option_id": "leave", "label": {"en": "Leave the situation", "zh-CN": "离开当前情境"}},
        {"option_id": "free_text", "label": {"en": "Respond in your own words", "zh-CN": "用自己的话回应"}},
        {"option_id": "skip", "label": {"en": "Skip without penalty", "zh-CN": "无惩罚跳过"}},
    ]
    db.add(
        ScenarioExposure(
            session_id=session.id,
            scenario_instance_id=scenario.id,
            stimulus_text=localized(TEXT[f"conflict_{variant}"], language),
            visible_options_json=_json_dumps(options),
            layout_json=_json_dumps({"form": "booking_mixup"}),
            exposure_complete=True,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            language=language,
            metadata_json="{}",
        )
    )
    _ensure_restaurant_event_for_scenario(
        db,
        session=session,
        world=world,
        scenario=scenario,
    )
    return scenario


def _complete_scenario(
    scenario: ScenarioInstance,
    world: WorldState,
    status: str = "completed",
) -> None:
    scenario.status = status
    scenario.completed_day = world.current_day
    scenario.completed_time_minutes = world.current_time_minutes
    scenario.updated_at = utc_now()


def _record_response(
    db: DBSession,
    *,
    scenario: ScenarioInstance,
    world: WorldState,
    action: WorldAction | None,
    response_type: str,
    selected_option_id: str | None = None,
    response_text: str = "",
    response_latency_ms: int | None = None,
    changed_choice: bool = False,
    outcome: str = "recorded",
    metadata: dict[str, Any] | None = None,
) -> ScenarioResponse:
    response = ScenarioResponse(
        session_id=world.session_id,
        scenario_instance_id=scenario.id,
        action_id=action.id if action is not None else None,
        response_type=response_type,
        selected_option_id=selected_option_id,
        response_text=response_text,
        response_latency_ms=response_latency_ms,
        changed_choice=changed_choice,
        outcome=outcome,
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps(metadata or {}),
    )
    db.add(response)
    return response


def _sync_conflict_follow_up_from_event(
    db: DBSession,
    *,
    scenario: ScenarioInstance,
    event: WorldEventInstance | None,
) -> None:
    if event is None:
        _schedule_follow_up(scenario, _world_state_for_session(db, scenario.session_id))
        return
    state = _json_loads(event.state_json, {})
    if state.get("follow_up_status") == "not_delivered_day_ended":
        scenario.follow_up_due_day = None
        scenario.follow_up_due_time_minutes = None
        scenario.follow_up_status = "not_delivered_day_ended"
        scenario.updated_at = utc_now()
        return
    scheduled = (
        db.query(WorldScheduledEvent)
        .filter(
            WorldScheduledEvent.session_id == scenario.session_id,
            WorldScheduledEvent.parent_event_instance_id == event.id,
            WorldScheduledEvent.event_type == RESTAURANT_FOLLOW_UP_EVENT_TYPE,
        )
        .order_by(WorldScheduledEvent.id.asc())
        .first()
    )
    if scheduled is None:
        scenario.follow_up_due_day = None
        scenario.follow_up_due_time_minutes = None
        scenario.follow_up_status = "not_delivered_day_ended"
    else:
        scenario.follow_up_due_day = scheduled.due_day
        scenario.follow_up_due_time_minutes = scheduled.due_time_minutes
        scenario.follow_up_status = scheduled.status
    scenario.updated_at = utc_now()


def _world_state_for_session(db: DBSession, session_id: int) -> WorldState:
    world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
    if world is None:
        raise WorldStateError("World state not found.", 404)
    return world


def _resolve_departure(
    db: DBSession,
    session: UserSession,
    world: WorldState,
    action: WorldAction,
    scenario: ScenarioInstance | None,
) -> None:
    if scenario is None:
        return
    event = _apply_restaurant_event_action(
        db,
        session=session,
        world=world,
        scenario=scenario,
        action=action,
        event_action_id="depart",
    )
    _record_response(
        db,
        scenario=scenario,
        world=world,
        action=action,
        response_type="leave",
        outcome="left_scene",
    )
    _complete_scenario(scenario, world)
    if scenario.scenario_type == "conflict":
        if _scenario_uses_event_runtime(scenario):
            _sync_conflict_follow_up_from_event(db, scenario=scenario, event=event)
        else:
            _schedule_follow_up(scenario, world)


def _schedule_follow_up(scenario: ScenarioInstance, world: WorldState) -> None:
    spec = _resolve_bound_world_spec(world)
    calendar = spec.calendar
    minutes_until_day_end = calendar.day_end_minute - world.current_time_minutes
    cannot_roll_over = (
        calendar.rollover == "clamp"
        or world.current_day >= calendar.total_days
    )
    if 30 > minutes_until_day_end and cannot_roll_over:
        scenario.follow_up_due_day = None
        scenario.follow_up_due_time_minutes = None
        scenario.follow_up_status = "not_delivered_day_ended"
        return
    deadline = advance_clock(
        calendar,
        world.current_day,
        world.current_time_minutes,
        30,
    ).after
    scenario.follow_up_due_day = deadline.day
    scenario.follow_up_due_time_minutes = deadline.minute
    scenario.follow_up_status = "scheduled"


def _deliver_due_follow_ups(db: DBSession, world: WorldState) -> None:
    scheduled = (
        db.query(ScenarioInstance)
        .filter(
            ScenarioInstance.session_id == world.session_id,
            ScenarioInstance.follow_up_status == "scheduled",
        )
        .order_by(
            ScenarioInstance.follow_up_due_day.asc(),
            ScenarioInstance.follow_up_due_time_minutes.asc(),
            ScenarioInstance.id.asc(),
        )
        .all()
    )
    due = [
        scenario
        for scenario in scheduled
        if not _scenario_uses_event_runtime(scenario)
        and scenario.follow_up_due_day is not None
        and scenario.follow_up_due_time_minutes is not None
        and is_due(
            scenario.follow_up_due_day,
            scenario.follow_up_due_time_minutes,
            world.current_day,
            world.current_time_minutes,
        )
    ]
    for scenario in due:
        language = "en"
        exposure = (
            db.query(ScenarioExposure)
            .filter(ScenarioExposure.scenario_instance_id == scenario.id)
            .order_by(ScenarioExposure.id.asc())
            .first()
        )
        if exposure is not None:
            language = exposure.language
        follow_up_text = localized(TEXT["follow_up"], language)
        participant_response = (
            db.query(ScenarioResponse)
            .filter(
                ScenarioResponse.scenario_instance_id == scenario.id,
                ScenarioResponse.action_id.is_not(None),
            )
            .order_by(ScenarioResponse.id.desc())
            .first()
        )
        follow_up_response = _record_response(
            db,
            scenario=scenario,
            world=world,
            action=None,
            response_type="follow_up",
            response_text=follow_up_text,
            outcome="repair_offered",
            metadata={"variant": scenario.variant},
        )
        db.flush()
        scenario.follow_up_status = "delivered"
        scenario.updated_at = utc_now()
        if scenario.assigned_agent_id is not None:
            record_memory(
                db,
                session_id=world.session_id,
                owner_agent_id=scenario.assigned_agent_id,
                memory_type="relationship_event",
                source_action_id=(
                    participant_response.action_id
                    if participant_response is not None
                    else None
                ),
                source_event_type="scenario_follow_up",
                source_event_id=follow_up_response.id,
                content=(
                    "The restaurant mix-up was followed by a calm repair "
                    "opportunity."
                ),
                importance=2,
                privacy_category="ordinary",
                occurred_day=world.current_day,
                occurred_time_minutes=world.current_time_minutes,
                location_id=scenario.location_id,
                scenario_instance_id=scenario.id,
                source_response_id=follow_up_response.id,
                related_agent_ids=(scenario.assigned_agent_id,),
                tags=("restaurant_mixup", "repair"),
            )
        # SessionLocal disables autoflush. Persist the delivered marker before
        # another sparse clock boundary queries scheduled follow-ups again.
        db.flush()


def _mirror_delivered_restaurant_follow_ups(
    db: DBSession,
    world: WorldState,
    delivered_events: list[WorldScheduledEvent],
) -> None:
    for scheduled in delivered_events:
        if (
            scheduled.status != "delivered"
            or scheduled.event_type != RESTAURANT_FOLLOW_UP_EVENT_TYPE
            or scheduled.result_event_instance_id is None
        ):
            continue
        payload = _json_loads(scheduled.payload_json, {})
        scenario_id = payload.get("scenario_instance_id")
        if not isinstance(scenario_id, int):
            continue
        scenario = (
            db.query(ScenarioInstance)
            .filter(
                ScenarioInstance.id == scenario_id,
                ScenarioInstance.session_id == world.session_id,
            )
            .first()
        )
        if scenario is None or scenario.follow_up_status == "delivered":
            continue
        language = "en"
        exposure = (
            db.query(ScenarioExposure)
            .filter(ScenarioExposure.scenario_instance_id == scenario.id)
            .order_by(ScenarioExposure.id.asc())
            .first()
        )
        if exposure is not None:
            language = exposure.language
        follow_up_text = localized(TEXT["follow_up"], language)
        participant_response = (
            db.query(ScenarioResponse)
            .filter(
                ScenarioResponse.scenario_instance_id == scenario.id,
                ScenarioResponse.action_id.is_not(None),
            )
            .order_by(ScenarioResponse.id.desc())
            .first()
        )
        follow_up_response = _record_response(
            db,
            scenario=scenario,
            world=world,
            action=None,
            response_type="follow_up",
            response_text=follow_up_text,
            outcome="repair_offered",
            metadata={
                "variant": scenario.variant,
                "event_instance_id": scheduled.result_event_instance_id,
                "scheduled_event_id": scheduled.id,
            },
        )
        db.flush()
        scenario.follow_up_status = "delivered"
        scenario.updated_at = utc_now()
        result_event = (
            db.query(WorldEventInstance)
            .filter(
                WorldEventInstance.id == scheduled.result_event_instance_id,
                WorldEventInstance.session_id == world.session_id,
            )
            .first()
        )
        if result_event is not None:
            state = _json_loads(result_event.state_json, {})
            state["state"] = "delivered"
            result_event.state_json = _json_dumps(state)
            result_event.status = "completed"
            result_event.completed_day = world.current_day
            result_event.completed_time_minutes = world.current_time_minutes
            result_event.completed_at = utc_now()
            result_event.outcome_code = "repair_offered"
            result_event.updated_at = utc_now()
        if scenario.assigned_agent_id is not None:
            record_memory(
                db,
                session_id=world.session_id,
                owner_agent_id=scenario.assigned_agent_id,
                memory_type="relationship_event",
                source_action_id=(
                    participant_response.action_id
                    if participant_response is not None
                    else None
                ),
                source_event_type="scenario_follow_up",
                source_event_id=follow_up_response.id,
                content=(
                    "The restaurant mix-up was followed by a calm repair "
                    "opportunity."
                ),
                importance=2,
                privacy_category="ordinary",
                occurred_day=world.current_day,
                occurred_time_minutes=world.current_time_minutes,
                location_id=scenario.location_id,
                scenario_instance_id=scenario.id,
                source_response_id=follow_up_response.id,
                related_agent_ids=(scenario.assigned_agent_id,),
                tags=("restaurant_mixup", "repair"),
                metadata={
                    "event_instance_id": scheduled.result_event_instance_id,
                    "scheduled_event_id": scheduled.id,
                },
            )
        db.flush()


def _end_active_conversations(
    db: DBSession,
    session_id: int,
    location_id: str,
    *,
    except_agent_id: int | None = None,
) -> None:
    query = db.query(WorldConversation).filter(
        WorldConversation.session_id == session_id,
        WorldConversation.location_id == location_id,
        WorldConversation.status == "active",
        WorldConversation.conversation_kind == "participant_resident",
    )
    if except_agent_id is not None:
        query = query.filter(WorldConversation.agent_id != except_agent_id)
    for conversation in query.all():
        conversation.status = "ended"
        conversation.ended_reason_code = "participant_relocated"
        conversation.updated_at = utc_now()
        for participant in conversation.participants:
            if participant.left_at is None:
                participant.left_at = conversation.updated_at
                participant.leave_reason_code = conversation.ended_reason_code


def _active_conversation_for_agent(
    db: DBSession,
    session_id: int,
    location_id: str,
    agent_id: int | None,
) -> WorldConversation | None:
    if agent_id is None:
        return None
    return (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.location_id == location_id,
            WorldConversation.agent_id == agent_id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .order_by(WorldConversation.id.desc())
        .first()
    )


def _request_event_action_id(request: Any) -> str | None:
    raw = getattr(request, "event_action_id", None) or request.target_object_id
    if raw is None:
        return None
    return str(raw)


def _existing_action_matches_request(action: WorldAction, request: Any) -> bool:
    expected_target_object_id = (
        _request_event_action_id(request)
        if request.action_type == "event_action"
        else request.target_object_id
    )
    server_resolves_event_targets = request.action_type == "event_action"
    if (
        action.action_type != request.action_type
        or (
            not server_resolves_event_targets
            and action.target_location_id != request.target_location_id
        )
        or (
            not server_resolves_event_targets
            and action.target_agent_id != request.target_agent_id
        )
        or action.target_object_id != expected_target_object_id
        or action.response_text != (request.response_text or "")
        or action.language != request.language
    ):
        return False
    if (
        getattr(request, "event_instance_id", None) is not None
        and action.event_instance_id != request.event_instance_id
    ):
        return False
    if (
        request.scenario_instance_id is not None
        and action.scenario_instance_id != request.scenario_instance_id
    ):
        return False
    stored_metadata = _json_loads(action.metadata_json, {})
    request_metadata = dict(request.metadata or {})
    if action.action_type == "end_conversation":
        for server_field in ("conversation_id", "end_reason"):
            stored_metadata.pop(server_field, None)
            request_metadata.pop(server_field, None)
    if action.action_type == "end_day":
        for server_field in (
            "from_day",
            "to_day",
            "to_time_minutes",
            "reached_world_end",
        ):
            stored_metadata.pop(server_field, None)
            request_metadata.pop(server_field, None)
    if action.action_type == "move":
        for server_field in (
            "travel_path",
            "travel_edge_count",
            "travel_minutes",
        ):
            stored_metadata.pop(server_field, None)
            request_metadata.pop(server_field, None)
    for server_field in (
        "event_type",
        "event_version",
        "event_action_id",
        "event_outcome_code",
    ):
        stored_metadata.pop(server_field, None)
        request_metadata.pop(server_field, None)
    # Event runtimes append validated server-owned annotations after the raw
    # request is persisted.  A replay only needs every client-owned key to
    # retain its original value; additional server fields are expected.
    return all(stored_metadata.get(key) == value for key, value in request_metadata.items())


def _validate_action_shape(
    db: DBSession,
    session_id: int,
    world: WorldState,
    request: Any,
) -> None:
    spec = _resolve_bound_world_spec(world)
    action_type = request.action_type
    from services.holiday_calendar_v6 import require_awake
    require_awake(world)
    supplied = {
        "target_location_id": request.target_location_id,
        "target_agent_id": request.target_agent_id,
        "target_object_id": request.target_object_id,
        "scenario_instance_id": request.scenario_instance_id,
        "event_instance_id": getattr(request, "event_instance_id", None),
        "event_action_id": getattr(request, "event_action_id", None),
    }
    allowed_targets = {
        "move": {"target_location_id"},
        "observe": {
            "target_location_id",
            "target_agent_id",
            "target_object_id",
        },
        "approach": {"target_agent_id"},
        "wait": set(),
        "end_day": set(),
        "event_action": {
            "event_instance_id",
            "event_action_id",
            "target_object_id",
        },
        "seat_view": {"target_object_id", "scenario_instance_id"},
        "seat_select": {"target_object_id", "scenario_instance_id"},
        "seat_change": {"target_object_id", "scenario_instance_id"},
        "scenario_response": {"target_object_id", "scenario_instance_id"},
        "scenario_skip": {"scenario_instance_id"},
        "end_conversation": {"target_agent_id"},
        "defined_action": {
            "target_location_id",
            "target_agent_id",
            "target_object_id",
        },
    }[action_type]
    unexpected = [
        name
        for name, value in supplied.items()
        if value is not None and name not in allowed_targets
    ]
    if unexpected:
        raise WorldStateError(
            f"{action_type} does not accept: {', '.join(sorted(unexpected))}."
        )
    if action_type not in {"scenario_response", "event_action"} and (
        request.response_text or ""
    ).strip():
        raise WorldStateError(f"{action_type} does not accept response_text.")

    if action_type == "move" and request.target_location_id is None:
        raise WorldStateError("target_location_id is required for move.")
    if action_type == "approach" and request.target_agent_id is None:
        raise WorldStateError("target_agent_id is required for approach.")
    if action_type == "end_conversation" and request.target_agent_id is None:
        raise WorldStateError("target_agent_id is required for end_conversation.")
    if action_type == "defined_action":
        _resolve_participant_defined_action(spec, world, request)
    if action_type == "event_action":
        if getattr(request, "event_instance_id", None) is None:
            raise WorldStateError("event_instance_id is required for event_action.")
        if _request_event_action_id(request) is None:
            raise WorldStateError(
                "event_action_id or target_object_id is required for event_action."
            )
    if action_type in {"seat_view", "seat_select", "seat_change"}:
        if request.target_object_id is None:
            raise WorldStateError(f"target_object_id is required for {action_type}.")

    if action_type == "observe":
        target_count = sum(value is not None for value in supplied.values())
        if target_count > 1:
            raise WorldStateError("observe accepts at most one target.")
        if (
            request.target_location_id is not None
            and request.target_location_id != world.participant_location_id
        ):
            raise WorldStateError("Only the current location can be observed.", 409)
        if request.target_agent_id is not None:
            resident = _resident_state(db, session_id, request.target_agent_id)
            if resident is None:
                raise WorldStateError("Resident not found.", 404)
            if resident.current_location_id != world.participant_location_id:
                raise WorldStateError(
                    "The resident is not at the participant's location.", 409
                )
        if request.target_object_id is not None:
            if not _visible_interaction_point(spec, world.current_day, request.target_object_id):
                raise WorldStateError('这个互动点今天不开放。', 409)
            if not object_exists(
                spec,
                world.participant_location_id,
                request.target_object_id,
            ):
                raise WorldStateError("Object is not available at this location.", 409)


def _resolve_participant_defined_action(
    spec: WorldSpec,
    world: WorldState,
    request: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    action_id = request.metadata.get("action_id") if isinstance(request.metadata, dict) else None
    definitions = [dict(item) for item in spec.systems.get("action_definitions", ())]
    definition = next((item for item in definitions if item.get("action_id") == action_id), None)
    if definition is None or "participant" not in definition.get("actor_types", ()):
        raise WorldStateError("metadata.action_id does not name a participant action.", 409)
    affordances = [dict(item) for item in spec.systems.get("affordances", ())]
    matching = [
        item for item in affordances
        if item.get("enabled") is True
        and item.get("action_id") == action_id
        and (not item.get("location_ids") or world.participant_location_id in item.get("location_ids", ()))
        and (not item.get("object_ids") or request.target_object_id in item.get("object_ids", ()))
    ]
    if not matching:
        raise WorldStateError("The defined action is not afforded at this place or target.", 409)
    return definition, matching[0]


def _evaluate_activity_emergence(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    action: WorldAction,
    action_id: str,
) -> None:
    """Deterministically arbitrate authored activity candidates and audit every result."""

    policy = dict(spec.systems.get("emergence_policy", {}))
    policy_id = str(policy.get("policy_id", "bounded-emergence-v1"))
    policy_version = str(policy.get("policy_version", "v1"))
    limit = int(policy.get("max_activity_creations_per_tick", 0))
    residents = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == session.id,
            CharacterState.current_location_id == world.participant_location_id,
        )
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    candidates = sorted(
        (
            dict(item) for item in spec.systems.get("activity_recipes", ())
            if action_id in item.get("action_ids", ())
            and world.participant_location_id in item.get("location_ids", ())
        ),
        key=lambda item: str(item.get("recipe_id", "")),
    )
    created = 0
    for rank, recipe in enumerate(candidates, start=1):
        recipe_id = str(recipe["recipe_id"])
        participant_count = 1 + len(residents)
        existing = (
            db.query(WorldCommitment)
            .filter(
                WorldCommitment.session_id == session.id,
                WorldCommitment.recipe_id == recipe_id,
                WorldCommitment.status.in_(("scheduled", "active")),
            )
            .first()
        )
        if existing is not None:
            outcome, reason = "blocked", "active_commitment_exists"
        elif participant_count < int(recipe["min_participants"]):
            outcome, reason = "blocked", "insufficient_participants"
        elif created >= limit:
            outcome, reason = "blocked", "activity_rate_limit"
        else:
            outcome, reason = "selected", "authored_recipe_matched"
            max_residents = max(0, int(recipe["max_participants"]) - 1)
            participants = [
                {"member_type": "participant", "agent_id": None},
                *[
                    {"member_type": "resident", "agent_id": row.agent_id}
                    for row in residents[:max_residents]
                ],
            ]
            commitment = WorldCommitment(
                session_id=session.id,
                recipe_id=recipe_id,
                status="scheduled",
                location_id=world.participant_location_id,
                organizer_type="participant",
                organizer_agent_id=None,
                participants_json=_json_dumps(participants),
                scheduled_day=world.current_day,
                scheduled_time_minutes=world.current_time_minutes,
                source_action_id=action.id,
                policy_id=policy_id,
                policy_version=policy_version,
                metadata_json=_json_dumps({"duration_minutes": recipe["duration_minutes"]}),
            )
            db.add(commitment)
            db.flush()
            content = dict(recipe.get("board_post_template") or recipe.get("label") or {})
            db.add(WorldBoardPost(
                session_id=session.id,
                commitment_id=commitment.id,
                author_type="system",
                author_agent_id=None,
                content_json=_json_dumps(content),
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
                metadata_json=_json_dumps({"recipe_id": recipe_id, "source_action_id": action.id}),
            ))
            created += 1
        db.add(WorldEmergenceDecision(
            session_id=session.id,
            source_action_id=action.id,
            candidate_type="activity_recipe",
            candidate_id=recipe_id,
            outcome=outcome,
            reason_code=reason,
            rank=rank,
            simulation_seed=session.simulation_seed,
            policy_id=policy_id,
            policy_version=policy_version,
            snapshot_json=_json_dumps({
                "day": world.current_day,
                "time_minutes": world.current_time_minutes,
                "location_id": world.participant_location_id,
                "participant_count": participant_count,
                "creation_limit": limit,
            }),
        ))


def perform_world_action(
    db: DBSession,
    session: UserSession,
    request: Any,
) -> dict[str, Any]:
    session_id = session.id
    with session_write_lock(session_id):
        # The endpoint may have loaded this row before waiting for the lock.
        # End that read transaction so a concurrent finish is visible here.
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise WorldStateError("Session not found.", 404)
        if session.status != "active":
            raise WorldStateError(f"Session is {session.status}.", 409)
        if request.action_type == "defined_action":
            world = initialize_world(db, session)
            spec = _resolve_bound_world_spec(world)
            if spec.content_schema_version == "content-pack-v5":
                # All v5 clicks use the same validator/effects as resident actions.
                # The legacy v4 path only recorded definitions and is insufficient
                # for authored object changes, permissions and activity consent.
                from services import atomic_action_service as atomic
                from models import WorldAtomicActionExecution
                previous = db.query(WorldAtomicActionExecution).filter_by(session_id=session_id,
                    idempotency_key=request.idempotency_key).first()
                revision = previous.requested_revision if previous else atomic._runtime_state(world)[1]["revision"]
                try:
                    result = atomic.execute_atomic_action(db, session_id=session_id, request={
                        "action_id": (request.metadata or {}).get("action_id"),
                        "idempotency_key": request.idempotency_key, "expected_revision": revision,
                        "target_location_id": request.target_location_id or world.participant_location_id,
                        "target_object_id": request.target_object_id,
                        "inputs": (request.metadata or {}).get("inputs", {}), "language": request.language})
                except atomic.AtomicActionServiceError as exc:
                    rolled_back = exc.reason_code == 'technical_failure' and exc.detail == 'Atomic action failed before commit; no effects were applied.'
                    raise WorldStateError(exc.detail, exc.status_code, 'action_not_applied' if rolled_back else None) from exc
                result["world"] = build_world_payload(db, session, request.language)
                return result
        return _perform_world_action_locked(db, session, request)


def _perform_world_action_locked(
    db: DBSession,
    session: UserSession,
    request: Any,
) -> dict[str, Any]:
    world = initialize_world(db, session)
    spec = _resolve_bound_world_spec(world)
    existing = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == session.id,
            WorldAction.idempotency_key == request.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if not _existing_action_matches_request(existing, request):
            raise WorldStateError(
                "Idempotency key was already used with a different action payload.", 409
            )
        return {
            "status": "existing",
            "action_id": existing.id,
            "world": build_world_payload(db, session, request.language),
        }

    action_type = request.action_type
    if action_type not in WORLD_ACTIONS:
        raise WorldStateError(f"Unsupported world action: {action_type}.")
    active_participant_conversation = _active_participant_conversation(db, session.id)
    from services.interaction_time_service import focus_state, expire_focus
    expire_focus(db, world)
    if focus_state(world):
        raise WorldStateError("Leave the activity discussion before advancing the world.", 409)
    if active_participant_conversation is not None and action_type != "end_conversation":
        raise WorldStateError(
            "A participant conversation is active; end it before performing another world action.",
            409,
        )
    if _world_has_ended(world, spec) and action_type != "end_conversation":
        raise WorldStateError("The virtual world has reached its final time.", 409)

    metadata = dict(request.metadata or {})
    _validate_action_shape(db, session.id, world, request)
    active = _get_active_scenario(db, session.id, world.participant_location_id)

    if action_type == "defined_action":
        definition, affordance = _resolve_participant_defined_action(spec, world, request)
        metadata.update({
            "defined_action_minutes": int(definition["duration_minutes"]),
            "defined_action_id": definition["action_id"],
            "affordance_id": affordance["affordance_id"],
            "consequences": definition.get("consequences", []),
        })

    if spec.experience.get("behavior_audit_version"):
        audit_residents = (
            db.query(CharacterState)
            .filter(CharacterState.session_id == session.id)
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
        emergence_policy = spec.systems.get("emergence_policy", {})
        metadata["behavior_audit"] = {
            "schema_version": spec.experience["behavior_audit_version"],
            "source": str(metadata.get("source") or "participant_ui"),
            "before": {
                "day": world.current_day,
                "time_minutes": world.current_time_minutes,
                "location_id": world.participant_location_id,
            },
            "visible_legal_actions": _available_actions(
                db, session, world, active, audit_residents
            ),
            "selection": {
                "action_type": action_type,
                "target_location_id": request.target_location_id,
                "target_agent_id": request.target_agent_id,
                "target_object_id": request.target_object_id,
            },
            "response_latency_ms": request.response_latency_ms,
            "idempotency_key": request.idempotency_key,
            "content_version": spec.content_pack_version,
            "policy_version": emergence_policy.get("policy_version"),
            "simulation_seed": session.simulation_seed,
        }

    if action_type == "move":
        target = request.target_location_id
        if target not in spec.locations:
            raise WorldStateError("A valid target_location_id is required for move.")
        travel_path = shortest_travel_path(
            spec,
            world.participant_location_id,
            target,
        )
        if travel_path is None or len(travel_path) < 2:
            raise WorldStateError(
                f"No travel route from {world.participant_location_id} to {target}.",
                409,
            )
        travel_edge_count = len(travel_path) - 1
        metadata["travel_path"] = list(travel_path)
        metadata["travel_edge_count"] = travel_edge_count
        metadata["travel_minutes"] = (
            int(spec.action_minutes[action_type]) * travel_edge_count
        )
        if world.world_version=='chaoxi-holiday-v6':
            from services.holiday_calendar_v6 import is_open,hours_text
            if not is_open(target,world.current_time_minutes+metadata["travel_minutes"]):
                raise WorldStateError('到达时该地点不开放。开放时间：'+hours_text(target),409)
    elif action_type == "approach":
        resident = _resident_state(db, session.id, request.target_agent_id)
        if resident is None:
            raise WorldStateError("A valid target_agent_id is required for approach.")
        if resident.current_location_id != world.participant_location_id:
            raise WorldStateError("The resident is not at the participant's location.", 409)
    elif action_type in {"seat_view", "seat_select", "seat_change"}:
        if world.participant_location_id != "restaurant":
            raise WorldStateError("Seat actions are only available in the restaurant.", 409)
    elif action_type == "end_conversation":
        active_conversation = _active_participant_conversation(db, session.id)
        if (
            active_conversation is None
            or active_conversation.agent_id != request.target_agent_id
        ):
            raise WorldStateError(
                "No active conversation with that resident exists.",
                409,
            )
        from world.interaction_policy import interaction_policy
        if interaction_policy(spec):
            slot = _json_loads(active_conversation.metadata_json, {})
            if request.metadata.get("focus_token") != slot.get("focus_token"):
                raise WorldStateError("Conversation focus changed. Reload the current conversation.", 409)
    elif action_type == "end_day":
        rest_location = str(spec.experience.get("rest_location_id", "participant_home"))
        if rest_location not in spec.locations:
            raise WorldStateError(
                "The bound world does not support ending the day from a home.",
                409,
            )
        if world.participant_location_id != rest_location:
            raise WorldStateError("end_day is only available at the participant home.", 409)
        if spec.calendar.total_days <= 1 and not spec.experience.get("meeting_demo"):
            raise WorldStateError("The bound world does not have another playable day.", 409)
    elif action_type == "event_action":
        event = (
            db.query(WorldEventInstance)
            .filter(
                WorldEventInstance.id == request.event_instance_id,
                WorldEventInstance.session_id == session.id,
            )
            .first()
        )
        if event is None:
            raise WorldStateError("Event instance was not found.", 404)
        if event.status != "active":
            raise WorldStateError("Event instance is not active.", 409)
        if event.location_id != world.participant_location_id:
            raise WorldStateError(
                "Event instance is not at the participant's current location.",
                409,
            )

    action = WorldAction(
        session_id=session.id,
        idempotency_key=request.idempotency_key,
        action_type=action_type,
        target_location_id=request.target_location_id,
        target_agent_id=request.target_agent_id,
        target_object_id=(
            _request_event_action_id(request)
            if action_type == "event_action"
            else request.target_object_id
        ),
        scenario_instance_id=(
            request.scenario_instance_id
            or (active.id if active is not None and action_type.startswith("scenario_") else None)
        ),
        event_instance_id=(
            request.event_instance_id if action_type == "event_action" else None
        ),
        response_text=request.response_text or "",
        response_latency_ms=request.response_latency_ms,
        language=request.language,
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps(metadata),
    )
    db.add(action)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session.id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if duplicate is None:
            raise
        if not _existing_action_matches_request(duplicate, request):
            raise WorldStateError(
                "Idempotency key was already used with a different action payload.",
                409,
            )
        session = db.query(UserSession).filter(UserSession.id == session.id).one()
        return {
            "status": "existing",
            "action_id": duplicate.id,
            "flow_messages": _flow_messages_from_action(duplicate),
            "world": build_world_payload(db, session, request.language),
        }

    if action_type == "move":
        _end_active_conversations(
            db,
            session.id,
            world.participant_location_id,
        )
        _resolve_departure(db, session, world, action, active)
        from services.holiday_dining_service import leave_venue
        leave_venue(world)
        world.participant_location_id = request.target_location_id
        invalidate_pending_interaction_prompts(
            db,
            world=world,
            reason_code="participant_relocated",
        )
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
        if (
            _uses_legacy_v03_scenarios(spec)
            and world.participant_location_id == "restaurant"
        ):
            _ensure_seating_scenario(db, session, world, request.language)
    elif action_type == "approach":
        _end_active_conversations(
            db,
            session.id,
            world.participant_location_id,
            except_agent_id=request.target_agent_id,
        )
        invalidate_pending_interaction_prompts(
            db,
            world=world,
            reason_code="participant_approached",
        )
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
    elif action_type == "seat_view":
        seating = _require_seating(db, session.id, active_only=True)
        if (
            request.scenario_instance_id is not None
            and request.scenario_instance_id != seating.id
        ):
            raise WorldStateError("The seat action references another scenario.", 409)
        _require_seat_option(seating, request.target_object_id)
        _apply_restaurant_event_action(
            db,
            session=session,
            world=world,
            scenario=seating,
            action=action,
            event_action_id=f"seat_view:{request.target_object_id}",
        )
        exposure = seating.exposures[0]
        exposure_metadata = _json_loads(exposure.metadata_json, {})
        viewed = list(exposure_metadata.get("viewed_option_ids", []))
        if request.target_object_id not in viewed:
            viewed.append(request.target_object_id)
        exposure_metadata["viewed_option_ids"] = viewed
        exposure.metadata_json = _json_dumps(exposure_metadata)
        action.scenario_instance_id = seating.id
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
    elif action_type == "seat_select":
        seating = _require_seating(db, session.id, active_only=True)
        if (
            request.scenario_instance_id is not None
            and request.scenario_instance_id != seating.id
        ):
            raise WorldStateError("The seat action references another scenario.", 409)
        _require_seat_option(seating, request.target_object_id)
        action.scenario_instance_id = seating.id
        _apply_restaurant_event_action(
            db,
            session=session,
            world=world,
            scenario=seating,
            action=action,
            event_action_id=f"seat_select:{request.target_object_id}",
        )
        _record_response(
            db,
            scenario=seating,
            world=world,
            action=action,
            response_type="seat_select",
            selected_option_id=request.target_object_id,
            response_latency_ms=request.response_latency_ms,
            outcome="seat_recorded",
        )
        scenario_metadata = _json_loads(seating.metadata_json, {})
        scenario_metadata["selected_option_id"] = request.target_object_id
        seating.metadata_json = _json_dumps(scenario_metadata)
        _complete_scenario(seating, world)
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
        _ensure_conflict_scenario(db, session, world, request.language)
    elif action_type == "seat_change":
        seating = _require_seating(db, session.id)
        if active is None or active.scenario_type != "conflict":
            raise WorldStateError(
                "A seat can only be changed while the restaurant conflict is active.",
                409,
            )
        if (
            request.scenario_instance_id is not None
            and request.scenario_instance_id != seating.id
        ):
            raise WorldStateError("The seat action references another scenario.", 409)
        _require_seat_option(seating, request.target_object_id)
        scenario_metadata = _json_loads(seating.metadata_json, {})
        previous = scenario_metadata.get("selected_option_id")
        if not previous:
            raise WorldStateError("Select a seat before changing it.", 409)
        action.scenario_instance_id = seating.id
        _apply_restaurant_event_action(
            db,
            session=session,
            world=world,
            scenario=active,
            action=action,
            event_action_id=f"seat_change:{request.target_object_id}",
        )
        _record_response(
            db,
            scenario=seating,
            world=world,
            action=action,
            response_type="seat_change",
            selected_option_id=request.target_object_id,
            response_latency_ms=request.response_latency_ms,
            changed_choice=True,
            outcome="seat_changed",
            metadata={"previous_option_id": previous},
        )
        scenario_metadata["selected_option_id"] = request.target_object_id
        seating.metadata_json = _json_dumps(scenario_metadata)
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
    elif action_type in {"scenario_response", "scenario_skip"}:
        scenario = (
            _scenario_by_id(db, session.id, request.scenario_instance_id)
            if request.scenario_instance_id is not None
            else _get_active_scenario(db, session.id, world.participant_location_id)
        )
        if scenario is None or scenario.status != "active":
            raise WorldStateError("No matching active scenario is available.", 409)
        action.scenario_instance_id = scenario.id
        if action_type == "scenario_skip":
            interruption_reason = metadata.get("interruption_reason")
            if interruption_reason not in {None, "technical_failure"}:
                raise WorldStateError(
                    "metadata.interruption_reason must be technical_failure when provided."
                )
            _apply_restaurant_event_action(
                db,
                session=session,
                world=world,
                scenario=scenario,
                action=action,
                event_action_id=(
                    "technical_failure"
                    if interruption_reason == "technical_failure"
                    else "skip"
                ),
            )
            if interruption_reason == "technical_failure":
                for exposure in scenario.exposures:
                    exposure.exposure_complete = False
                    exposure.interruption_reason = "technical_failure"
            _record_response(
                db,
                scenario=scenario,
                world=world,
                action=action,
                response_type=(
                    "technical_failure"
                    if interruption_reason == "technical_failure"
                    else "skip"
                ),
                response_latency_ms=request.response_latency_ms,
                outcome=(
                    "interrupted_technical"
                    if interruption_reason == "technical_failure"
                    else "skipped_without_penalty"
                ),
            )
            _complete_scenario(
                scenario,
                world,
                "interrupted" if interruption_reason == "technical_failure" else "skipped",
            )
        else:
            if scenario.scenario_type != "conflict":
                raise WorldStateError(
                    "Use seat_select or seat_change for the seating scenario.", 409
                )
            response_type = str(
                metadata.get("response_code")
                or metadata.get("response_type")
                or request.target_object_id
                or "free_text"
            )
            if response_type == "custom":
                response_type = "free_text"
            if response_type not in CONFLICT_RESPONSES:
                raise WorldStateError("Invalid conflict response_type.")
            if response_type == "free_text" and not (request.response_text or "").strip():
                raise WorldStateError("response_text is required for a free_text response.")
            event = _apply_restaurant_event_action(
                db,
                session=session,
                world=world,
                scenario=scenario,
                action=action,
                event_action_id=f"respond:{response_type}",
                allow_optional_response_text=True,
            )
            _record_response(
                db,
                scenario=scenario,
                world=world,
                action=action,
                response_type=response_type,
                response_text=request.response_text or "",
                response_latency_ms=request.response_latency_ms,
                outcome="conflict_response_recorded",
                metadata={"variant": scenario.variant},
            )
            _complete_scenario(scenario, world)
            if scenario.scenario_type == "conflict":
                if _scenario_uses_event_runtime(scenario):
                    _sync_conflict_follow_up_from_event(
                        db,
                        scenario=scenario,
                        event=event,
                    )
                else:
                    _schedule_follow_up(scenario, world)
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
    elif action_type == "end_conversation":
        conversation = _active_participant_conversation(db, session.id)
        if conversation is None or conversation.agent_id != request.target_agent_id:
            raise WorldStateError(
                "No active conversation with that resident exists.",
                409,
            )
        has_participant_turn = (
            db.query(WorldConversationTurn.id)
            .filter(
                WorldConversationTurn.conversation_id == conversation.id,
                WorldConversationTurn.speaker_type.in_(("participant", "user")),
            )
            .first()
            is not None
        )
        end_reason = (
            "participant" if has_participant_turn else "participant_ended_before_message"
        )
        conversation.status = "ended"
        conversation.ended_reason_code = end_reason
        conversation.updated_at = utc_now()
        for participant in conversation.participants:
            if participant.left_at is None:
                participant.left_at = conversation.updated_at
                participant.leave_reason_code = end_reason
        from services.interaction_time_service import settle_conversation
        applied_minutes = settle_conversation(db, world, conversation)
        action.metadata_json = _json_dumps(
            {
                **metadata,
                "conversation_id": conversation.id,
                "end_reason": end_reason,
                "applied_minutes": applied_minutes,
            }
        )
    elif action_type == "end_day":
        from_day = world.current_day
        if spec.experience.get("rest_location_id"):
            from services.day_review_service import pending_arrangements, leave_today
            pending_ids = {plan.id for plan, _ in pending_arrangements(db, world)}
            reviewed = metadata.get("reviewed_plan_ids", [])
            if pending_ids and (metadata.get("confirm_leave_arrangements") is not True or not isinstance(reviewed, list) or not pending_ids <= set(i for i in reviewed if type(i) is int)):
                raise WorldStateError("今天还有已接受的安排，请确认离开这些安排后再休息。", 409)
            leave_today(db, world=world, idempotency_key=action.idempotency_key)
        active = _get_active_scenario(db, session.id, world.participant_location_id)
        _end_active_conversations(
            db,
            session.id,
            world.participant_location_id,
        )
        _resolve_departure(db, session, world, action, active)
        if world.world_version=='chaoxi-holiday-v6':
            from world.clock import ClockAdvance,ClockPosition
            before=ClockPosition(world.current_day,world.current_time_minutes)
            _advance_clock(db,world,spec.calendar.day_end_minute-world.current_time_minutes)
            advanced=ClockAdvance(before,ClockPosition(world.current_day,world.current_time_minutes),0,False)
        else:
            advanced = _advance_to_next_day(db, world)
        invalidate_pending_interaction_prompts(
            db,
            world=world,
            reason_code="day_ended",
        )
        action.metadata_json = _json_dumps(
            {
                **metadata,
                "from_day": from_day,
                "to_day": advanced.after.day,
                "to_time_minutes": advanced.after.minute,
                "reached_world_end": advanced.reached_world_end,
            }
        )
    elif action_type == "observe":
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )
        if request.target_object_id is not None:
            interaction_event = _interaction_event_for_object(
                spec,
                world.participant_location_id,
                request.target_object_id,
            )
            if interaction_event is not None:
                existing_active = get_active_event_instance(
                    db,
                    session_id=session.id,
                    location_id=world.participant_location_id,
                )
                if existing_active is not None:
                    raise WorldStateError(
                        "Resolve the active event before starting an object interaction.",
                        409,
                    )
                started = create_event_instance(
                    db,
                    session=session,
                    world=world,
                    event_type=interaction_event.event_type,
                    event_version=interaction_event.version,
                    trigger_key=f"object:{action.id}:{request.target_object_id}",
                    location_id=world.participant_location_id,
                    state={"state": interaction_event.initial_stage_id or "presented"},
                    metadata={
                        "declarative_event_id": interaction_event.event_id,
                        "object_interaction": True,
                        "object_id": request.target_object_id,
                        "source_action_id": action.id,
                    },
                )
                action.event_instance_id = started.id
                action.metadata_json = _json_dumps({
                    **metadata,
                    "object_interaction_started": True,
                    "interaction_event_id": interaction_event.event_id,
                    "event_instance_id": started.id,
                })
    elif action_type == "event_action":
        try:
            apply_event_action(
                db,
                session=session,
                world=world,
                action=action,
                event_instance_id=request.event_instance_id,
                event_action_id=_request_event_action_id(request) or "",
            )
        except WorldEventRuntimeError as exc:
            raise WorldStateError(exc.detail, exc.status_code) from exc
        event_action_metadata = _json_loads(action.metadata_json, {})
        configured_minutes = event_action_metadata.get("event_action_minutes")
        event_action_minutes = (
            configured_minutes
            if isinstance(configured_minutes, int)
            and not isinstance(configured_minutes, bool)
            and configured_minutes >= 0
            else _action_minutes(action_type, metadata, world.world_version)
        )
        behavior_metadata = event_action_metadata.get("action_metadata")
        if (
            event_action_metadata.get("relocate_participant") is True
            or (
                isinstance(behavior_metadata, dict)
                and behavior_metadata.get("relocate_participant") is True
            )
        ):
            relocation_target = action.target_location_id
            if not relocation_target or relocation_target not in spec.locations:
                raise WorldStateError("Event relocation target is invalid.", 409)
            relocation_path = shortest_travel_path(
                spec,
                world.participant_location_id,
                relocation_target,
            )
            if relocation_path is None:
                raise WorldStateError("Event relocation target is unreachable.", 409)
            relocation_minutes = int(spec.action_minutes.get("move", 0)) * max(
                0, len(relocation_path) - 1
            )
            _end_active_conversations(
                db,
                session.id,
                world.participant_location_id,
            )
            invalidate_pending_interaction_prompts(
                db,
                world=world,
                reason_code="participant_relocated",
            )
            world.participant_location_id = relocation_target
            event_action_minutes = max(event_action_minutes, relocation_minutes)
            event_action_metadata.update(
                {
                    "travel_path": list(relocation_path),
                    "travel_edge_count": max(0, len(relocation_path) - 1),
                    "travel_minutes": relocation_minutes,
                }
            )
            action.metadata_json = _json_dumps(event_action_metadata)
        _advance_clock(
            db,
            world,
            event_action_minutes,
        )
        completed_event = (
            db.query(WorldEventInstance)
            .filter(
                WorldEventInstance.id == request.event_instance_id,
                WorldEventInstance.session_id == session.id,
            )
            .first()
        )
        if completed_event is not None:
            evaluate_event_social_publications(
                db,
                session=session,
                world=world,
                spec=spec,
                source_action=action,
                event=completed_event,
            )
    else:
        _advance_clock(
            db,
            world,
            _action_minutes(action_type, metadata, world.world_version),
        )

    if action_type == "defined_action":
        _evaluate_activity_emergence(
            db,
            session=session,
            world=world,
            spec=spec,
            action=action,
            action_id=str(metadata["defined_action_id"]),
        )

    if action_type in {"move", "wait", "end_day", "event_action"}:
        try:
            evaluate_declarative_events(
                db,
                session=session,
                world=world,
                action=action,
            )
        except WorldEventRuntimeError as exc:
            raise WorldStateError(exc.detail, exc.status_code) from exc

    action_metadata = _json_loads(action.metadata_json, {})
    behavior_audit = action_metadata.get("behavior_audit")
    if isinstance(behavior_audit, dict):
        behavior_audit["after"] = {
            "day": world.current_day,
            "time_minutes": world.current_time_minutes,
            "location_id": world.participant_location_id,
        }
        action_metadata["behavior_audit"] = behavior_audit
        action.metadata_json = _json_dumps(action_metadata)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session.id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if duplicate is None:
            raise
        if not _existing_action_matches_request(duplicate, request):
            raise WorldStateError(
                "Idempotency key was already used with a different action payload.",
                409,
            )
        return {
            "status": "existing",
            "action_id": duplicate.id,
            "world": build_world_payload(db, session, request.language),
        }
    db.refresh(action)
    return {
        "status": "saved",
        "action_id": action.id,
        "flow_messages": _flow_messages_from_action(action),
        "world": build_world_payload(db, session, request.language),
    }


def _flow_messages_from_action(action: WorldAction) -> list[dict[str, str]]:
    metadata = _json_loads(action.metadata_json, {})
    raw_effects = metadata.get("flow_effects", ())
    if not isinstance(raw_effects, list):
        return []
    result: list[dict[str, str]] = []
    for effect in raw_effects:
        if not isinstance(effect, dict) or effect.get("type") != "show_message":
            continue
        text = effect.get("text")
        if isinstance(text, dict):
            localized = {
                key: value
                for key, value in text.items()
                if key in {"en", "zh-CN"} and isinstance(value, str)
            }
            if localized:
                result.append(localized)
    return result


def _resident_state(
    db: DBSession,
    session_id: int,
    agent_id: int | None,
) -> CharacterState | None:
    if agent_id is None:
        return None
    return (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == session_id,
            CharacterState.agent_id == agent_id,
        )
        .first()
    )


def _require_seating(
    db: DBSession,
    session_id: int,
    active_only: bool = False,
) -> ScenarioInstance:
    query = db.query(ScenarioInstance).filter(
        ScenarioInstance.session_id == session_id,
        ScenarioInstance.scenario_id == SEATING_SCENARIO_ID,
    )
    if active_only:
        query = query.filter(ScenarioInstance.status == "active")
    scenario = query.first()
    if scenario is None:
        raise WorldStateError("The seating scenario is not available.", 409)
    return scenario


def _require_seat_option(scenario: ScenarioInstance, option_id: str | None) -> None:
    valid_ids = {item["option_id"] for item in SEATING_FORMS[scenario.form]}
    if option_id not in valid_ids:
        raise WorldStateError(
            "target_object_id must be one of: " + ", ".join(sorted(valid_ids)) + "."
        )


def _conversation_action_matches_request(action: WorldAction, request: Any) -> bool:
    matches = (
        action.action_type == "conversation_message"
        and action.target_agent_id == request.agent_id
        and action.response_text == request.message
        and action.language == request.language
    )
    conversation_id = getattr(request, "conversation_id", None)
    if not matches or conversation_id is None:
        return matches
    metadata = _json_loads(action.metadata_json, {})
    return isinstance(metadata, dict) and metadata.get("conversation_id") == conversation_id


def _interaction_event_for_object(
    spec: WorldSpec,
    location_id: str,
    object_id: str,
):
    location = spec.locations.get(location_id)
    if location is None:
        return None
    point = next(
        (item for item in location.interaction_points if item.get("object_id") == object_id),
        None,
    )
    if point is None:
        return None
    event_id = point.get("interaction_event_id")
    return spec.event_specs.get(str(event_id)) if event_id else None


def _active_participant_conversation(
    db: DBSession,
    session_id: int,
) -> WorldConversation | None:
    return (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .order_by(WorldConversation.id.desc())
        .first()
    )


def _start_conversation_action_matches(action: WorldAction, request: Any) -> bool:
    metadata = _json_loads(action.metadata_json, {})
    return (
        action.action_type == "approach"
        and action.target_agent_id == request.agent_id
        and action.language == request.language
        and isinstance(metadata, dict)
        and metadata.get("conversation_start") is True
        and metadata.get("duration_minutes", 10) == getattr(request, "duration_minutes", 10)
    )


def start_world_conversation(
    db: DBSession,
    session: UserSession,
    request: Any,
) -> dict[str, Any]:
    """Atomically create a zero-turn participant conversation."""

    session_id = session.id
    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise WorldStateError("Session not found.", 404)
        if session.status != "active":
            raise WorldStateError(f"Session is {session.status}.", 409)
        world = initialize_world(db, session)
        spec = _resolve_bound_world_spec(world)

        existing_action = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if existing_action is not None:
            if not _start_conversation_action_matches(existing_action, request):
                raise WorldStateError(
                    "Idempotency key was already used with a different conversation-start payload.",
                    409,
                )
            metadata = _json_loads(existing_action.metadata_json, {})
            conversation = (
                db.query(WorldConversation)
                .filter(
                    WorldConversation.id == metadata.get("conversation_id"),
                    WorldConversation.session_id == session_id,
                )
                .first()
            )
            if conversation is None:
                raise WorldStateError("The stored conversation start is unavailable.", 409)
            return {
                "status": "existing",
                "action_id": existing_action.id,
                "conversation": _serialize_conversation(db, conversation),
                "world": build_world_payload(db, session, request.language),
            }

        from services.holiday_calendar_v6 import require_awake
        require_awake(world)
        if _world_has_ended(world, spec):
            raise WorldStateError("The virtual world has reached its final time.", 409)
        from services.interaction_time_service import expire_focus
        expire_focus(db, world)
        resident = _resident_state(db, session_id, request.agent_id)
        if resident is None or request.agent_id not in spec.residents:
            raise WorldStateError("Resident not found.", 404)
        if resident.current_location_id != world.participant_location_id:
            raise WorldStateError("The resident is not at the participant's location.", 409)

        active = _active_participant_conversation(db, session_id)
        if active is not None:
            if (
                active.agent_id == request.agent_id
                and active.location_id == world.participant_location_id
            ):
                return {
                    "status": "existing",
                    "action_id": None,
                    "conversation": _serialize_conversation(db, active),
                    "world": build_world_payload(db, session, request.language),
                }
            raise WorldStateError("Another participant conversation is already active.", 409)

        if _get_active_scenario(db, session_id, world.participant_location_id) is not None:
            raise WorldStateError(
                "A scenario must be resolved before starting a conversation.", 409
            )
        if get_active_event_instance(
            db,
            session_id=session_id,
            location_id=world.participant_location_id,
        ) is not None:
            raise WorldStateError(
                "An event must be resolved before starting a conversation.", 409
            )

        from services.interaction_time_service import conversation_slot
        slot = conversation_slot(db, world, spec, request.agent_id, getattr(request, "duration_minutes", 10))
        action = WorldAction(
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            action_type="approach",
            target_agent_id=request.agent_id,
            language=request.language,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json=_json_dumps({"conversation_start": True}),
        )
        db.add(action)
        db.flush()
        conversation = WorldConversation(
            session_id=session_id,
            agent_id=request.agent_id,
            location_id=world.participant_location_id,
            status="active",
            conversation_kind="participant_resident",
            initiator_type="participant",
            visibility="session_private",
            metadata_json=_json_dumps(
                {
                    "schema_version": "participant-conversation-v1",
                    "source_action_id": action.id,
                    "time_policy": "frozen_while_active",
                    **slot,
                }
            ),
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=session_id,
                    member_type="participant",
                    agent_id=None,
                    member_role="initiator",
                ),
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=session_id,
                    member_type="resident",
                    agent_id=request.agent_id,
                    member_role="target",
                ),
            ]
        )
        action.metadata_json = _json_dumps(
            {
                "conversation_start": True,
                "conversation_id": conversation.id,
                "applied_minutes": 0,
                "duration_minutes": slot.get("duration_minutes", 10),
            }
        )
        invalidate_pending_interaction_prompts(
            db,
            world=world,
            reason_code="participant_started_conversation",
        )
        db.commit()
        db.refresh(conversation)
        return {
            "status": "saved",
            "action_id": action.id,
            "conversation": _serialize_conversation(db, conversation),
            "world": build_world_payload(db, session, request.language),
        }


async def create_world_conversation(
    db: DBSession,
    session: UserSession,
    request: Any,
    agent_service: AgentService,
) -> dict[str, Any]:
    session_id = session.id
    world = initialize_world(db, session)
    spec = _resolve_bound_world_spec(world)
    from world.interaction_policy import interaction_policy
    if interaction_policy(spec) and getattr(request, "conversation_id", None) is None:
        import schemas
        started = start_world_conversation(db, session, schemas.WorldConversationStartRequest(
            agent_id=request.agent_id, idempotency_key="open-" + request.idempotency_key[:115], language=request.language))
        request = request.model_copy(update={"conversation_id": started["conversation"]["conversation_id"],
            "focus_token": started["conversation"]["metadata"]["focus_token"]})
        world = initialize_world(db, session)
    existing = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.idempotency_key == request.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if not _conversation_action_matches_request(existing, request):
            raise WorldStateError(
                "Idempotency key was already used with a different conversation payload.",
                409,
            )
        return _conversation_result_for_action(
            db, session, existing, request.language, "existing"
        )

    if _world_has_ended(world, spec):
        raise WorldStateError("The virtual world has reached its final time.", 409)

    resident = _resident_state(db, session_id, request.agent_id)
    resident_profile = spec.residents.get(request.agent_id)
    if resident is None or resident_profile is None:
        raise WorldStateError("Resident not found.", 404)
    if resident.current_location_id != world.participant_location_id:
        raise WorldStateError("The resident is not at the participant's location.", 409)

    original_day = world.current_day
    original_time = world.current_time_minutes
    original_location_id = world.participant_location_id
    original_goal = resident.current_goal
    conversation_query = db.query(WorldConversation).filter(
        WorldConversation.session_id == session_id,
        WorldConversation.agent_id == request.agent_id,
        WorldConversation.location_id == original_location_id,
        WorldConversation.status == "active",
        WorldConversation.conversation_kind == "participant_resident",
    )
    if getattr(request, "conversation_id", None) is not None:
        conversation_query = conversation_query.filter(
            WorldConversation.id == request.conversation_id
        )
    conversation = conversation_query.order_by(WorldConversation.id.desc()).first()
    if conversation and interaction_policy(spec):
        from datetime import timedelta
        slot = _json_loads(conversation.metadata_json, {})
        if getattr(request, "focus_token", None) != slot.get("focus_token"):
            raise WorldStateError("Conversation focus expired or belongs to another client.", 409)
        slot["lease_expires_at"] = (utc_now() + timedelta(seconds=interaction_policy(spec).focus_lease_seconds)).isoformat()
        conversation.metadata_json = _json_dumps(slot)
        db.commit()
    if getattr(request, "conversation_id", None) is not None and conversation is None:
        raise WorldStateError("The active conversation is no longer available.", 409)
    recent_turn_rows = []
    if conversation is not None:
        recent_turn_rows = (
            db.query(WorldConversationTurn)
            .filter(
                WorldConversationTurn.conversation_id == conversation.id,
                WorldConversationTurn.safety_flag.is_(False),
            )
            .order_by(WorldConversationTurn.id.desc())
            .limit(24 if spec.content_schema_version == "content-pack-v5" else 6)
            .all()
        )
    recent_history = [
        {
            "speaker": (
                resident_profile.name
                if turn.speaker_type == "agent"
                else "Participant"
            ),
            "event_type": "agent_reply" if turn.speaker_type == "agent" else "comment",
            "content": turn.content,
            "safety_flag": turn.safety_flag,
            "source_turn_id": turn.id,
        }
        for turn in reversed(recent_turn_rows)
    ]
    memory = build_agent_memory_context(
        db,
        session_id=session_id,
        owner_agent_id=request.agent_id,
        current_day=original_day,
        current_time_minutes=original_time,
        location_id=original_location_id,
    )

    persona = get_persona(request.agent_id)
    location = spec.locations[original_location_id]
    location_name = localized(location.name, request.language)
    schedule = _schedule_for(
        spec,
        request.agent_id,
        original_day,
        original_time,
    )
    activity = localized(schedule.activity, request.language)
    scene_context = (
        f"位于{location_name}的面对面岛屿交流；这位岛民目前正在{activity}。"
        if request.language == "zh-CN"
        else (
            f"an in-person island conversation at {location_name}; "
            f"the resident is currently {activity}"
        )
    )
    from services.role_context_service import build_role_context
    role_context = build_role_context(db, world=world, spec=spec, agent_id=request.agent_id,
        language=request.language) if spec.content_schema_version == "content-pack-v5" else None
    agent_request = AgentRequest(
        session_id=session_id,
        agent_id=request.agent_id,
        post_id=0,
        post_content=scene_context,
        user_comment=request.message,
        language=request.language,
        recent_history=recent_history,
        agent_memory=memory,
        target_context=original_goal,
        reply_target_author=(
            resident_profile.name if role_context else persona.name if persona else resident_profile.name
        ),
        post_author=(
            resident_profile.name if role_context else persona.name if persona else resident_profile.name
        ),
        post_intent="An ordinary in-person conversation in the island community.",
        reply_relation=(
            "The participant is speaking directly to the resident in the same location."
        ),
        thread_history=[
            {
                "speaker": item["speaker"],
                "content": item["content"],
                "safety_flag": item.get("safety_flag", False),
            }
            for item in recent_history
        ],
        interaction_kind="island_conversation",
        world_role_context=role_context,
        persona_role_context=localized(
            resident_profile.role, request.language
        ),
        persona_background_context=localized(
            resident_profile.background, request.language
        ),
    )
    safety = check_user_comment_safety(request.message, request.language)

    # End the read transaction before waiting on a remote provider. Holding even
    # a read transaction across the await can block another SQLite writer's commit.
    db.rollback()
    try:
        if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            from services.holiday_v5_service import social_reply
            result = await social_reply(db, world, spec, request.agent_id, request.message, recent_history)
        else:
            result = await agent_service.generate_reply(agent_request)
    except Exception as exc:
        from agents.output_safety import record_stop
        record_stop(db,session_id,request.idempotency_key,exc,'in_person',request.agent_id)
        preserve_stop(exc)
        db.rollback()
        raise WorldStateError(
            f"Resident reply generation failed: {type(exc).__name__}", 503
        ) from exc

    with session_write_lock(session_id):
        return _persist_world_conversation(
            db=db,
            session_id=session_id,
            request=request,
            result=result,
            safety=safety,
            original_day=original_day,
            original_time=original_time,
            original_location_id=original_location_id,
        )


def _persist_world_conversation(
    *,
    db: DBSession,
    session_id: int,
    request: Any,
    result: Any,
    safety: Any,
    original_day: int,
    original_time: int,
    original_location_id: str,
) -> dict[str, Any]:
    session = (
        db.query(UserSession)
        .filter(UserSession.id == session_id)
        .first()
    )
    if session is None:
        raise WorldStateError("Session not found.", 404)
    if session.status != "active":
        raise WorldStateError(f"Session is {session.status}.", 409)
    world = (
        db.query(WorldState)
        .filter(WorldState.session_id == session_id)
        .first()
    )
    if world is None:
        raise WorldStateError("Island world is not initialized.", 409)

    existing = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.idempotency_key == request.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if not _conversation_action_matches_request(existing, request):
            raise WorldStateError(
                "Idempotency key was already used with a different conversation payload.",
                409,
            )
        return _conversation_result_for_action(
            db, session, existing, request.language, "existing"
        )

    if world.world_version=='chaoxi-holiday-v6':
        from services.holiday_social_v6 import enforce_proposal_budget
        result=enforce_proposal_budget(db,world,request.agent_id,result)
    resident = _resident_state(db, session_id, request.agent_id)
    if (
        world.current_day != original_day
        or world.current_time_minutes != original_time
        or world.participant_location_id != original_location_id
        or resident is None
        or resident.current_location_id != original_location_id
    ):
        db.rollback()
        raise WorldStateError(
            "The island state changed while the resident was replying; refresh and retry.",
            409,
        )

    conversation_query = db.query(WorldConversation).filter(
        WorldConversation.session_id == session_id,
        WorldConversation.agent_id == request.agent_id,
        WorldConversation.location_id == original_location_id,
        WorldConversation.status == "active",
        WorldConversation.conversation_kind == "participant_resident",
    )
    if getattr(request, "conversation_id", None) is not None:
        conversation_query = conversation_query.filter(
            WorldConversation.id == request.conversation_id
        )
    conversation = conversation_query.order_by(WorldConversation.id.desc()).first()
    if getattr(request, "conversation_id", None) is not None and conversation is None:
        raise WorldStateError("The active conversation is no longer available.", 409)
    if conversation:
        from services.interaction_time_service import expire_focus
        expire_focus(db, world)
        if conversation.status != "active":
            db.commit()
            raise WorldStateError("Conversation focus expired.", 409)
    if conversation is None:
        conversation = WorldConversation(
            session_id=session_id,
            agent_id=request.agent_id,
            location_id=original_location_id,
            status="active",
            conversation_kind="participant_resident",
            initiator_type="participant",
            initiator_agent_id=None,
            visibility="session_private",
            metadata_json=_json_dumps({"schema_version": "participant-conversation-v1"}),
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=session_id,
                    member_type="participant",
                    agent_id=None,
                    member_role="initiator",
                ),
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=session_id,
                    member_type="resident",
                    agent_id=request.agent_id,
                    member_role="target",
                ),
            ]
        )
    is_first_exchange = (
        db.query(WorldConversationTurn.id)
        .filter(
            WorldConversationTurn.conversation_id == conversation.id,
            WorldConversationTurn.speaker_type == "participant",
        )
        .first()
        is None
    )

    action = WorldAction(
        session_id=session_id,
        idempotency_key=request.idempotency_key,
        action_type="conversation_message",
        target_agent_id=request.agent_id,
        response_text=request.message,
        response_latency_ms=request.response_latency_ms,
        language=request.language,
        world_day=original_day,
        world_time_minutes=original_time,
        metadata_json=_json_dumps(
            {"conversation_id": conversation.id, "applied_minutes": 0}
        ),
    )
    db.add(action)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if duplicate is None:
            raise
        if not _conversation_action_matches_request(duplicate, request):
            raise WorldStateError(
                "Idempotency key was already used with a different conversation payload.",
                409,
            )
        session = db.query(UserSession).filter(UserSession.id == session_id).one()
        return _conversation_result_for_action(
            db, session, duplicate, request.language, "existing"
        )
    db.add(
        WorldConversationTurn(
            conversation_id=conversation.id,
            session_id=session_id,
            source_action_id=action.id,
            speaker_type="participant",
            speaker_id=None,
            content=request.message,
            world_day=original_day,
            world_time_minutes=original_time,
            response_latency_ms=request.response_latency_ms,
            safety_flag=safety.safety_flag,
            metadata_json=_json_dumps({"language": request.language}),
        )
    )
    db.add(
        WorldConversationTurn(
            conversation_id=conversation.id,
            session_id=session_id,
            source_action_id=action.id,
            speaker_type="agent",
            speaker_id=request.agent_id,
            content=result.reply_content,
            world_day=original_day,
            world_time_minutes=original_time,
            response_latency_ms=result.latency_ms,
            generation_mode=result.generation_mode,
            model_provider=result.model_provider,
            model_name=result.model_name,
            prompt_version=result.prompt_version,
            safety_flag=result.safety_flag,
            metadata_json=_json_dumps(result.metadata),
        )
    )
    if world.world_version == 'chaoxi-holiday-v6':
        from services.holiday_work_service import remember_observed
        remember_observed(world,request.agent_id,result.metadata.get('observed_works',[]))
    if not safety.safety_flag:
        record_memory(
            db,
            session_id=session_id,
            owner_agent_id=request.agent_id,
            memory_type="episodic",
            source_action_id=action.id,
            source_event_type="conversation_message",
            source_event_id=conversation.id,
            content=f"The participant said: {request.message}",
            importance=1,
            privacy_category="ordinary",
            occurred_day=original_day,
            occurred_time_minutes=original_time,
            location_id=original_location_id,
            related_agent_ids=(request.agent_id,),
            tags=("participant_dialogue",),
            metadata={"conversation_id": conversation.id},
        )
    if (
        is_first_exchange
        and not safety.safety_flag
        and not getattr(result, "safety_flag", False)
    ):
        spec = _resolve_bound_world_spec(world)
        try:
            apply_conversation_first_exchange(
                db,
                spec=spec,
                world=world,
                conversation=conversation,
                action=action,
            )
        except RelationshipStateError as exc:
            raise WorldStateError(exc.detail, exc.status_code) from exc
    conversation.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if duplicate is None:
            raise
        if not _conversation_action_matches_request(duplicate, request):
            raise WorldStateError(
                "Idempotency key was already used with a different conversation payload.",
                409,
            )
        session = (
            db.query(UserSession)
            .filter(UserSession.id == session_id)
            .one()
        )
        return _conversation_result_for_action(
            db, session, duplicate, request.language, "existing"
        )
    db.refresh(action)
    return _conversation_result_for_action(
        db, session, action, request.language, "saved"
    )


def _conversation_result_for_action(
    db: DBSession,
    session: UserSession,
    action: WorldAction,
    language: str,
    status: str,
) -> dict[str, Any]:
    turns = (
        db.query(WorldConversationTurn)
        .filter(
            WorldConversationTurn.session_id == session.id,
            WorldConversationTurn.source_action_id == action.id,
        )
        .order_by(WorldConversationTurn.id.asc())
        .all()
    )
    conversation_id = turns[0].conversation_id if turns else None
    return {
        "status": status,
        "action_id": action.id,
        "conversation_id": conversation_id,
        "turns": [_serialize_turn(item) for item in turns],
        "world": build_world_payload(db, session, language),
    }


def build_world_payload(
    db: DBSession,
    session: UserSession,
    language: str = "en",
) -> dict[str, Any]:
    world = initialize_world(db, session)
    spec = _resolve_bound_world_spec(world)
    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == session.id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    intent_states = (
        db.query(ResidentIntentState)
        .filter(ResidentIntentState.session_id == session.id)
        .order_by(ResidentIntentState.agent_id.asc())
        .all()
    )
    intents_by_agent = {item.agent_id: item for item in intent_states}
    latest_pulse = (
        db.query(WorldSimulationPulse)
        .filter(WorldSimulationPulse.session_id == session.id)
        .order_by(WorldSimulationPulse.id.desc())
        .first()
    )
    active = _get_active_scenario(db, session.id, world.participant_location_id)
    recent_actions = (
        db.query(WorldAction)
        .filter(WorldAction.session_id == session.id)
        .order_by(WorldAction.id.desc())
        .limit(20)
        .all()
    )
    follow_up = (
        db.query(ScenarioResponse)
        .filter(
            ScenarioResponse.session_id == session.id,
            ScenarioResponse.response_type == "follow_up",
        )
        .order_by(ScenarioResponse.id.desc())
        .first()
    )
    conversations = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session.id,
            WorldConversation.conversation_kind == "participant_resident",
        )
        .order_by(WorldConversation.updated_at.desc(), WorldConversation.id.desc())
        .limit(5)
        .all()
    )
    interaction_prompts = (
        db.query(WorldInteractionPrompt)
        .filter(WorldInteractionPrompt.session_id == session.id)
        .order_by(WorldInteractionPrompt.updated_at.desc(), WorldInteractionPrompt.id.desc())
        .limit(10)
        .all()
    )
    pending_interaction_prompt = next(
        (
            item
            for item in interaction_prompts
            if item.status == "pending"
            and item.location_id == world.participant_location_id
        ),
        None,
    )
    commitments = (
        db.query(WorldCommitment)
        .filter(WorldCommitment.session_id == session.id)
        .order_by(WorldCommitment.id.desc())
        .limit(20)
        .all()
    )
    board_posts = (
        db.query(WorldBoardPost)
        .filter(WorldBoardPost.session_id == session.id)
        .order_by(WorldBoardPost.id.desc())
        .limit(20)
        .all()
    )
    emergence_decisions = (
        db.query(WorldEmergenceDecision)
        .filter(WorldEmergenceDecision.session_id == session.id)
        .order_by(WorldEmergenceDecision.id.desc())
        .limit(50)
        .all()
    )
    try:
        current_location = spec.locations[world.participant_location_id]
    except KeyError as exc:
        raise WorldStateError(
            "The participant location is missing from the bound world version.",
            409,
        ) from exc
    serialized_location = _serialize_location(current_location)
    legacy_events_enabled = _uses_legacy_v03_scenarios(spec)
    behavioral_events_enabled = any(
        event_spec.stages for event_spec in spec.event_specs.values()
    )
    active_event = get_active_event_instance(
        db,
        session_id=session.id,
        location_id=world.participant_location_id,
    )
    visible_active_event = (
        None if _event_is_legacy_scenario_bridge(active_event) else active_event
    )
    ambient_conversations = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session.id,
            WorldConversation.conversation_kind == "resident_resident",
            WorldConversation.visibility == "public",
            WorldConversation.location_id == world.participant_location_id,
        )
        .order_by(WorldConversation.updated_at.desc(), WorldConversation.id.desc())
        .limit(5)
        .all()
    )
    serialized_residents = [
        _serialize_resident(
            item,
            language,
            spec,
            intent=intents_by_agent.get(item.agent_id),
        )
        for item in residents
        if not __import__('content.experience_next',fromlist=['enabled']).enabled() or __import__('content.experience_next',fromlist=['active']).active(item.agent_id,world.current_day)
    ]
    snapshot_updated_at = _snapshot_updated_at(
        world=world,
        residents=residents,
        intent_states=intent_states,
        recent_actions=recent_actions,
        conversations=[*conversations, *ambient_conversations],
        interaction_prompts=interaction_prompts,
        commitments=commitments,
    )
    return {
        "contract_version": "world-snapshot-v1",
        "revision": int(snapshot_updated_at.timestamp() * 1_000_000),
        "snapshot_updated_at": snapshot_updated_at.isoformat(),
        "capabilities": {
            "conversations": True,
            "events": legacy_events_enabled,
            "event_contract": True,
            "event_runtime": True,
            "declarative_events": bool(spec.event_specs),
            "neutral_test_events": True,
            "research_events": behavioral_events_enabled,
            "custom_events": behavioral_events_enabled,
            **({"behavioral_events": True} if behavioral_events_enabled else {}),
            "resident_decision_contract": True,
            "resident_decision_runtime": True,
            "resident_policy": (
                "bounded-autonomy-v1"
                if spec.map_spec is not None
                else "schedule-driven-v1"
            ),
            "resident_llm_policy": False,
            "numeric_relationships": True,
            "memory_view": False,
            "multi_day_clock": spec.calendar.total_days > 1,
            **(
                {
                    "authored_action_system": True,
                    "bounded_emergence": True,
                    "world_commitments": True,
                    "world_board_posts": True,
                }
                if spec.systems
                else {}
            ),
            **(
                {
                    "atomic_action_contract": True,
                    "atomic_action_runtime": True,
                    "atomic_action_runtime_version": "atomic-action-runtime-v1",
                    "plan_runtime": True,
                    "plan_runtime_version": "plan-runtime-v1",
                    "schedule_availability": True,
                    "resource_reservations": True,
                    "phone_plan_social": True,
                    "knowledge_provenance": True,
                    "emergence_director": True,
                    "emergence_director_runtime_version": "emergence-director-v1",
                    "modular_stages": True,
                    "modular_stage_runtime_version": "modular-stage-runtime-v1",
                    "modular_decision_gateway": True,
                    "modular_decision_gateway_runtime_version": "modular-decision-gateway-v1",
                }
                if spec.content_schema_version == "content-pack-v5"
                and spec.systems.get("contract_version")
                == MODULAR_SYSTEMS_CONTRACT_VERSION
                else {}
            ),
            "map_geometry": spec.map_spec is not None,
            "actor_markers": spec.map_spec is not None,
            "scene_layouts": spec.map_spec is not None,
            **({"visual_assets": True} if spec.visual_spec is not None else {}),
            "resident_social_runtime": spec.map_spec is not None,
            "resident_social_llm_layer": spec.map_spec is not None,
            **(
                {
                    "foreground_simulation_pulse": True,
                    "resident_intent_state": True,
                    "bounded_resident_autonomy": any(
                        resident.autonomy.enabled
                        for resident in spec.residents.values()
                    ),
                    "resident_interaction_prompts": True,
                    "parallel_resident_conversations": True,
                }
                if spec.map_spec is not None
                else {}
            ),
        },
        "session": {
            "session_id": session.id,
            "status": session.status,
            "simulation_seed": session.simulation_seed,
        },
        "world": _serialize_world(world, spec),
        "simulation": _serialize_simulation(
            session=session,
            world=world,
            spec=spec,
            latest_pulse=latest_pulse,
            active_scenario=active,
            active_event=active_event,
            conversations=conversations,
        ),
        "map": _serialize_map(spec.map_spec),
        "visuals": _serialize_visuals(spec, language, world),
        "actors": _serialize_actors(
            session=session,
            world=world,
            spec=spec,
            residents=serialized_residents,
            language=language,
        ),
        "locations": list_locations(spec.world_version),
        "current_location": {
            **serialized_location,
            "display_name": localized(current_location.name, language),
            "display_description": localized(current_location.description, language),
        },
        "interaction_points": [
            dict(item) for item in current_location.interaction_points
            if _visible_interaction_point(spec, world.current_day, item['object_id'])
        ],
        "residents": serialized_residents,
        "visible_residents": [
            item
            for item in serialized_residents
            if item["current_location_id"] == world.participant_location_id
        ],
        "available_actions": _available_actions(db, session, world, active, residents),
        "active_scenario": (
            _serialize_scenario(db, active, language) if active else None
        ),
        "active_event": (
            serialize_event_instance(
                db,
                session=session,
                world=world,
                event=visible_active_event,
                language=language,
            )
            if visible_active_event is not None
            else None
        ),
        "recent_actions": [_serialize_action(item) for item in reversed(recent_actions)],
        "recent_follow_up": _serialize_response(follow_up) if follow_up else None,
        "conversations": [_serialize_conversation(db, item) for item in conversations],
        "ambient_conversations": [
            _serialize_conversation(db, item) for item in ambient_conversations
        ],
        "pending_interaction_prompt": (
            serialize_interaction_prompt(
                pending_interaction_prompt,
                language=language,
            )
            if pending_interaction_prompt is not None
            else None
        ),
        "interaction_prompts": [
            serialize_interaction_prompt(item, language=language)
            for item in interaction_prompts
        ],
        "commitments": [_serialize_commitment(item) for item in commitments],
        "board_posts": [_serialize_board_post(item) for item in board_posts],
        "emergence_decisions": [_serialize_emergence_decision(item) for item in emergence_decisions],
        "versions": _serialize_content_versions(world, spec),
    }


def _snapshot_updated_at(
    *,
    world: WorldState,
    residents: list[CharacterState],
    intent_states: list[ResidentIntentState],
    recent_actions: list[WorldAction],
    conversations: list[WorldConversation],
    interaction_prompts: list[WorldInteractionPrompt],
    commitments: list[WorldCommitment],
) -> datetime:
    """Return a comparable marker for every persisted value in a world snapshot."""

    candidates = [world.updated_at, world.created_at]
    candidates.extend(item.updated_at for item in residents)
    candidates.extend(item.updated_at for item in intent_states)
    candidates.extend(item.created_at for item in recent_actions)
    candidates.extend(item.updated_at for item in conversations)
    candidates.extend(item.updated_at for item in interaction_prompts)
    candidates.extend(item.updated_at for item in commitments)
    return max(item for item in candidates if item is not None)


def _simulation_mode(world: WorldState) -> str:
    state = _json_loads(world.state_json, {})
    simulation = state.get("simulation", {}) if isinstance(state, dict) else {}
    if isinstance(simulation, dict) and simulation.get("mode") == "paused":
        return "paused"
    return "running"


def _serialize_pulse(pulse: WorldSimulationPulse | None) -> dict[str, Any] | None:
    if pulse is None:
        return None
    return {
        "pulse_id": pulse.id,
        "sequence": pulse.sequence,
        "source": pulse.source,
        "status": pulse.status,
        "reason_code": pulse.reason_code,
        "requested_revision": pulse.requested_revision,
        "accepted_revision": pulse.accepted_revision,
        "before_day": pulse.before_day,
        "before_time_minutes": pulse.before_time_minutes,
        "after_day": pulse.after_day,
        "after_time_minutes": pulse.after_time_minutes,
        "action_ids": _json_loads(pulse.action_ids_json, []),
        "policy_id": pulse.policy_id,
        "policy_version": pulse.policy_version,
        "created_at": pulse.created_at.isoformat() if pulse.created_at else None,
        "updated_at": pulse.updated_at.isoformat() if pulse.updated_at else None,
    }


def _serialize_simulation(
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    latest_pulse: WorldSimulationPulse | None,
    active_scenario: ScenarioInstance | None,
    active_event: WorldEventInstance | None,
    conversations: list[WorldConversation],
) -> dict[str, Any]:
    mode = _simulation_mode(world)
    paused_reason: str | None = None
    active_conversation = next(
        (item for item in conversations if item.status == "active"), None
    )
    if active_conversation is not None:
        expiry = _json_loads(active_conversation.metadata_json, {}).get("lease_expires_at")
        if expiry and datetime.fromisoformat(expiry) <= utc_now():
            active_conversation = None
    if session.status != "active":
        paused_reason = "session_not_active"
    elif _world_has_ended(world, spec):
        paused_reason = "world_ended"
    elif mode == "paused":
        paused_reason = "participant_paused"
    elif active_scenario is not None:
        paused_reason = "active_scenario"
    elif active_event is not None:
        paused_reason = "active_event"
    elif active_conversation is not None:
        paused_reason = "active_conversation"
    from services.interaction_time_service import focus_state
    focus = focus_state(world)
    if focus and datetime.fromisoformat(focus["lease_expires_at"]) > utc_now():
        paused_reason = "activity_discussion"
    from services.holiday_calendar_v6 import pending
    if pending(world):
        paused_reason="day_transition"
    return {
        "mode": mode,
        "pulse_interval_hint_ms": 10_000,
        "pulse_minutes": 10 if __import__("content.experience_next",fromlist=["enabled"]).enabled() else 5,
        "can_pulse": paused_reason is None,
        "paused_reason": paused_reason,
        "effective_paused": paused_reason is not None,
        "active_conversation_id": (
            active_conversation.id if active_conversation is not None else None
        ),
        "last_pulse": _serialize_pulse(latest_pulse),
    }


def _serialize_map(map_spec: MapSpec | None) -> dict[str, Any] | None:
    if map_spec is None:
        return None
    return {
        "map_id": map_spec.map_id,
        "version": map_spec.version,
        "width": map_spec.width,
        "height": map_spec.height,
        "background": dict(map_spec.background),
        "land_polygon": [list(point) for point in map_spec.land_polygon],
        "paths": [
            {
                "path_id": path.path_id,
                "from_location_id": path.from_location_id,
                "to_location_id": path.to_location_id,
                "points": [list(point) for point in path.points],
            }
            for path in map_spec.paths.values()
        ],
        "location_nodes": [
            {
                "location_id": node.location_id,
                "x": node.x,
                "y": node.y,
                "click_radius": node.click_radius,
                "icon_key": node.icon_key,
                "label_offset": list(node.label_offset),
            }
            for node in map_spec.location_nodes.values()
        ],
        "scene_layouts": [
            {
                "location_id": layout.location_id,
                "width": layout.width,
                "height": layout.height,
                "participant_spawn": list(layout.participant_spawn),
                "resident_slots": [list(point) for point in layout.resident_slots],
                "interaction_point_positions": {
                    object_id: list(point)
                    for object_id, point in layout.interaction_point_positions.items()
                },
                "hotspots": [
                    {
                        "hotspot_id": hotspot.hotspot_id,
                        "shape": hotspot.shape,
                        "target_object_id": hotspot.target_object_id,
                        "x": hotspot.x,
                        "y": hotspot.y,
                        "width": hotspot.width,
                        "height": hotspot.height,
                        "radius": hotspot.radius,
                        "label": dict(hotspot.label),
                        "log_code": hotspot.log_code,
                    }
                    for hotspot in layout.hotspots
                ],
            }
            for layout in map_spec.scene_layouts.values()
        ],
    }


def _serialize_visuals(spec: WorldSpec, language: str, world: WorldState | None = None) -> dict[str, Any] | None:
    visual_spec = spec.visual_spec
    if visual_spec is None:
        return None
    slots: dict[str, dict[str, Any]] = {}
    for slot_id, slot in visual_spec.visual_slots.items():
        asset = (
            visual_spec.visual_assets.get(slot.asset_key)
            if slot.asset_key is not None
            else None
        )
        slots[slot_id] = {
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "target_id": slot.target_id,
            "asset_key": slot.asset_key,
            "fallback_palette_key": slot.fallback_palette_key,
            "fallback_title": localized(slot.fallback_title, language),
            "fallback_description": localized(
                slot.fallback_description, language
            ),
            "asset": (
                {
                    "asset_key": asset.asset_key,
                    "url": f"/world-assets/{spec.world_version}/{asset.asset_key}",
                    "mime_type": asset.mime_type,
                    "width": asset.width,
                    "height": asset.height,
                    "sha256": asset.sha256,
                    "source": asset.source,
                    "license": asset.license,
                }
                if asset is not None
                else None
            ),
        }
    if world and spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        from content.holiday_art import apply_visuals
        apply_visuals(slots,world)
        profile=_json_loads(world.state_json,{}).get('holiday_v5',{}).get('profile')
        if profile:
            for kind in ('map_thumbnail','dialogue_portrait'):
                slot=slots.get('actors.participant.'+kind)
                if slot:
                    slot['asset_key']='player-'+profile['gender']
                    slot['asset']={'asset_key':slot['asset_key'],'url':profile['portrait_url'],'mime_type':'image/png','width':1086,'height':1448,'sha256':'','source':'generated_player_art_v5','license':'project_generated'}
    return {
        "visual_version": visual_spec.visual_version,
        "slots": slots,
    }


_MAP_ACTOR_OFFSETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (-20.0, -17.0),
    (20.0, -17.0),
    (-20.0, 18.0),
    (20.0, 18.0),
    (0.0, -29.0),
    (0.0, 29.0),
)


def _serialize_actors(
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    residents: list[dict[str, Any]],
    language: str,
) -> list[dict[str, Any]]:
    participant_name = session.nickname or session.user_alias or "Participant"
    actors = [
        {
            "actor_type": "participant",
            "actor_id": "participant",
            "agent_id": None,
            "name": participant_name,
            "avatar_key": "participant",
            "marker_color_key": "participant_gold",
            "location_id": world.participant_location_id,
            "current_activity": (
                "正在探索岛屿" if language == "zh-CN" else "exploring the island"
            ),
            "role": "参与者" if language == "zh-CN" else "Participant",
            "public_summary": (
                "这是你在岛上的实时位置。"
                if language == "zh-CN"
                else "This is your live position on the island."
            ),
            "is_current_participant": True,
        }
    ]
    actors.extend(
        {
            "actor_type": "resident",
            "actor_id": f"resident:{resident['agent_id']}",
            "agent_id": resident["agent_id"],
            "name": resident["name"],
            "avatar_key": resident["avatar_key"],
            "marker_color_key": resident["marker_color_key"],
            "location_id": resident["current_location_id"],
            "current_activity": resident["current_activity"],
            "role": resident["role"],
            "public_summary": resident["public_summary"],
            "intent_type": resident["intent_type"],
            "intent_summary": resident["intent_summary"],
            "is_busy": resident["is_busy"],
            "is_current_participant": False,
        }
        for resident in residents
    )

    for actor in actors:
        map_x: float | None = None
        map_y: float | None = None
        scene_x: float | None = None
        scene_y: float | None = None
        if spec.map_spec is not None:
            node = spec.map_spec.location_nodes.get(actor["location_id"])
            layout = spec.map_spec.scene_layouts.get(actor["location_id"])
            if node is not None:
                offset_index = (
                    0
                    if actor["is_current_participant"]
                    else int(actor["agent_id"]) % len(_MAP_ACTOR_OFFSETS)
                )
                offset_x, offset_y = _MAP_ACTOR_OFFSETS[offset_index]
                map_x = min(max(node.x + offset_x, 0.0), spec.map_spec.width)
                map_y = min(max(node.y + offset_y, 0.0), spec.map_spec.height)
            if layout is not None:
                if actor["is_current_participant"]:
                    scene_x, scene_y = layout.participant_spawn
                elif layout.resident_slots:
                    slot_index = (int(actor["agent_id"]) - 1) % len(
                        layout.resident_slots
                    )
                    scene_x, scene_y = layout.resident_slots[slot_index]
        actor["x"] = map_x
        actor["y"] = map_y
        actor["scene_x"] = scene_x
        actor["scene_y"] = scene_y
    return actors


def _available_actions(
    db: DBSession,
    session: UserSession,
    world: WorldState,
    active: ScenarioInstance | None,
    residents: list[CharacterState],
) -> list[Any]:
    if session.status != "active":
        return []
    active_participant_conversation = _active_participant_conversation(db, session.id)
    if active_participant_conversation is not None:
        return ["end_conversation"]
    if _world_has_ended(world):
        return []
    actions = ["move", "observe", "wait"]
    if any(
        resident.current_location_id == world.participant_location_id
        for resident in residents
    ):
        actions.append("approach")
    spec = _resolve_bound_world_spec(world)
    active_event = get_active_event_instance(
        db,
        session_id=session.id,
        location_id=world.participant_location_id,
    )
    if active_event is not None and not _event_is_legacy_scenario_bridge(active_event):
        actions.append("event_action")
    if (
        (spec.calendar.total_days > 1 or spec.experience.get("meeting_demo"))
        and str(spec.experience.get("rest_location_id", "participant_home")) in spec.locations
        and world.participant_location_id == str(spec.experience.get("rest_location_id", "participant_home"))
    ):
        actions.append("end_day")
    if active is not None:
        if active.scenario_type == "seating":
            actions.extend(["seat_view", "seat_select", "scenario_skip"])
        elif active.scenario_type == "conflict":
            actions.extend(["seat_change", "scenario_response", "scenario_skip"])
    if spec.content_schema_version == "content-pack-v5":
        from services.atomic_action_service import list_atomic_action_candidates
        candidates = list_atomic_action_candidates(db, session_id=session.id)["candidates"]
        actions.extend({"action_type": "defined_action", "action_id": c["action_id"], "label": c["label"],
            "target_object_ids": [c["target"]["object_id"]] if c["target"]["object_id"] else [],
            "affordance_id": c["affordance_id"], "inputs": c["inputs"], "enabled": True} for c in candidates)
        return actions
    for raw_affordance in spec.systems.get("affordances", ()):
        affordance = dict(raw_affordance)
        if affordance.get("enabled") is not True:
            continue
        if affordance.get("location_ids") and world.participant_location_id not in affordance.get("location_ids", ()):
            continue
        definition = next(
            (
                dict(item) for item in spec.systems.get("action_definitions", ())
                if dict(item).get("action_id") == affordance.get("action_id")
                and "participant" in dict(item).get("actor_types", ())
            ),
            None,
        )
        if definition is None:
            continue
        if spec.content_schema_version == "content-pack-v5" and definition.get("preconditions", {}).get("requires_stage"):
            continue  # Collaborative choices are offered by confirmed activity cards.
        actions.append({
            "action_type": "defined_action",
            "action_id": definition["action_id"],
            "label": dict(definition.get("label", {})),
            "target_object_ids": list(affordance.get("object_ids", ())),
            "affordance_id": affordance.get("affordance_id"),
            "inputs": [dict(i) for i in definition.get("inputs", ())],
            "enabled": True,
        })
    return actions


def _serialize_world(
    world: WorldState,
    spec: WorldSpec,
) -> dict[str, Any]:
    departure_required = spec.experience.get("final_day_departure_required") is True
    from services.holiday_calendar_v6 import pending,location_status
    return {
        "world_state_id": world.id,
        "current_day": world.current_day,
        "total_days": spec.calendar.total_days,
        "current_time_minutes": world.current_time_minutes,
        "current_time": _time_label(world.current_time_minutes),
        "participant_location_id": world.participant_location_id,
        "rest_location_id": spec.experience.get("rest_location_id", "participant_home"),
        "current_location_id": world.participant_location_id,
        "participant_move_minutes_per_edge": int(
            spec.action_minutes.get("move", 0)
        ),
        "world_version": world.world_version,
        "scenario_pack_version": world.scenario_pack_version,
        "experience_mode": spec.experience.get("mode"),
        "can_finish": not departure_required or _world_has_ended(world, spec),
        "day_transition_pending":pending(world),
        "location_hours":{lid:location_status(world,lid) for lid in spec.locations} if world.world_version=='chaoxi-holiday-v6' else {},
        "departure_prompt": dict(spec.experience.get("departure_prompt", {})),
        "state": _json_loads(world.state_json, {}),
        "created_at": world.created_at.isoformat() if world.created_at else None,
        "updated_at": world.updated_at.isoformat() if world.updated_at else None,
    }


def _serialize_content_versions(
    world: WorldState,
    spec: WorldSpec,
) -> dict[str, str]:
    versions = {
        "world_version": world.world_version,
        "scenario_pack_version": world.scenario_pack_version,
    }
    if spec.content_pack_version is not None:
        versions["content_pack_version"] = spec.content_pack_version
    if spec.event_pack_version is not None:
        versions["event_pack_version"] = spec.event_pack_version
    if spec.map_spec is not None:
        versions["map_version"] = spec.map_spec.version
    if spec.visual_spec is not None:
        versions["visual_version"] = spec.visual_spec.visual_version
    return versions


def _serialize_resident(
    row: CharacterState,
    language: str,
    spec: WorldSpec,
    *,
    intent: ResidentIntentState | None = None,
) -> dict[str, Any]:
    try:
        resident = spec.residents[row.agent_id]
    except KeyError as exc:
        raise WorldStateError(
            f"Resident {row.agent_id} is missing from world {spec.world_version}.",
            409,
        ) from exc
    schedule = next(
        (
            item
            for item in resident.schedule
            if item.state_id == row.schedule_state
        ),
        None,
    )
    intent_summary = _json_loads(intent.summary_json, {}) if intent is not None else {}
    has_autonomous_intent = bool(
        intent is not None
        and intent.status == "active"
        and intent.intent_type != "follow_schedule"
    )
    activity_translations = (
        intent_summary
        if has_autonomous_intent and isinstance(intent_summary, dict)
        else schedule.activity if schedule is not None else {"en": row.current_activity}
    )
    goal_translations = (
        schedule.goal if schedule is not None else {"en": row.current_goal}
    )
    return {
        "agent_id": row.agent_id,
        "name": resident.name,
        "role": localized(resident.role, language),
        "background": localized(resident.background, language),
        "public_summary": localized(
            resident.public_summary or resident.background,
            language,
        ),
        "avatar_key": resident.avatar_key,
        "marker_color_key": resident.marker_color_key,
        "current_location_id": row.current_location_id,
        "current_activity": localized(activity_translations, language),
        "current_goal": localized(goal_translations, language),
        "schedule_state": row.schedule_state,
        "intent_type": intent.intent_type if intent is not None else "follow_schedule",
        "intent_status": intent.status if intent is not None else "active",
        "intent_summary": (
            localized(intent_summary, language)
            if isinstance(intent_summary, dict) and intent_summary
            else localized(activity_translations, language)
        ),
        "intent_target_location_id": (
            intent.target_location_id if intent is not None else None
        ),
        "intent_target_agent_id": (
            intent.target_agent_id if intent is not None else None
        ),
        "intent_target_object_id": (
            intent.target_object_id if intent is not None else None
        ),
        "intent_due_day": intent.due_day if intent is not None else None,
        "intent_due_time_minutes": (
            intent.due_time_minutes if intent is not None else None
        ),
        "is_busy": has_autonomous_intent,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "translations": {
            "en": {
                "role": localized(resident.role, "en"),
                "background": localized(resident.background, "en"),
                "public_summary": localized(
                    resident.public_summary or resident.background,
                    "en",
                ),
                "current_activity": localized(activity_translations, "en"),
                "current_goal": localized(goal_translations, "en"),
            },
            "zh-CN": {
                "role": localized(resident.role, "zh-CN"),
                "background": localized(resident.background, "zh-CN"),
                "public_summary": localized(
                    resident.public_summary or resident.background,
                    "zh-CN",
                ),
                "current_activity": localized(activity_translations, "zh-CN"),
                "current_goal": localized(goal_translations, "zh-CN"),
            },
        },
    }


def _serialize_commitment(item: WorldCommitment) -> dict[str, Any]:
    return {
        "commitment_id": item.id,
        "recipe_id": item.recipe_id,
        "status": item.status,
        "location_id": item.location_id,
        "organizer_type": item.organizer_type,
        "organizer_agent_id": item.organizer_agent_id,
        "participants": _json_loads(item.participants_json, []),
        "scheduled_day": item.scheduled_day,
        "scheduled_time_minutes": item.scheduled_time_minutes,
        "source_action_id": item.source_action_id,
        "policy_id": item.policy_id,
        "policy_version": item.policy_version,
        "runtime_version": item.runtime_version,
        "revision": item.revision,
        "duration_minutes": item.duration_minutes,
        "min_participants": item.min_participants,
        "max_participants": item.max_participants,
        "deadline_day": item.deadline_day,
        "deadline_time_minutes": item.deadline_time_minutes,
        "object_ids": _json_loads(item.object_ids_json, []),
        "role_slots": _json_loads(item.role_slots_json, []),
        "required_actor_keys": _json_loads(item.required_actor_keys_json, []),
        "reschedule_generation": item.reschedule_generation,
        "ended_reason_code": item.ended_reason_code,
        "metadata": _json_loads(item.metadata_json, {}),
    }


def _serialize_board_post(item: WorldBoardPost) -> dict[str, Any]:
    return {
        "board_post_id": item.id,
        "commitment_id": item.commitment_id,
        "author_type": item.author_type,
        "author_agent_id": item.author_agent_id,
        "content": _json_loads(item.content_json, {}),
        "world_day": item.world_day,
        "world_time_minutes": item.world_time_minutes,
        "metadata": _json_loads(item.metadata_json, {}),
    }


def _serialize_emergence_decision(item: WorldEmergenceDecision) -> dict[str, Any]:
    return {
        "decision_id": item.id,
        "source_action_id": item.source_action_id,
        "candidate_type": item.candidate_type,
        "candidate_id": item.candidate_id,
        "outcome": item.outcome,
        "reason_code": item.reason_code,
        "rank": item.rank,
        "simulation_seed": item.simulation_seed,
        "policy_id": item.policy_id,
        "policy_version": item.policy_version,
        "snapshot": _json_loads(item.snapshot_json, {}),
    }


def _serialize_action(action: WorldAction) -> dict[str, Any]:
    return {
        "action_id": action.id,
        "actor_type": action.actor_type,
        "actor_agent_id": action.actor_agent_id,
        "action_type": action.action_type,
        "target_location_id": action.target_location_id,
        "target_agent_id": action.target_agent_id,
        "target_object_id": action.target_object_id,
        "scenario_instance_id": action.scenario_instance_id,
        "event_instance_id": action.event_instance_id,
        "policy_id": action.policy_id,
        "policy_version": action.policy_version,
        "decision_reason_code": action.decision_reason_code,
        "response_text": action.response_text,
        "response_latency_ms": action.response_latency_ms,
        "language": action.language,
        "world_day": action.world_day,
        "world_time_minutes": action.world_time_minutes,
        "world_time": _time_label(action.world_time_minutes),
        "metadata": _json_loads(action.metadata_json, {}),
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


def _serialize_scenario(
    db: DBSession,
    scenario: ScenarioInstance,
    language: str,
) -> dict[str, Any]:
    exposures = sorted(scenario.exposures, key=lambda item: item.id)
    latest = exposures[-1] if exposures else None
    options = _json_loads(latest.visible_options_json, []) if latest else []
    scenario_metadata = _json_loads(scenario.metadata_json, {})
    selected_seat_id = scenario_metadata.get("selected_option_id")
    if scenario.scenario_type == "conflict":
        seating = (
            db.query(ScenarioInstance)
            .filter(
                ScenarioInstance.session_id == scenario.session_id,
                ScenarioInstance.scenario_id == SEATING_SCENARIO_ID,
            )
            .first()
        )
        if seating is not None:
            selected_seat_id = _json_loads(seating.metadata_json, {}).get(
                "selected_option_id"
            )
    return {
        "scenario_instance_id": scenario.id,
        "scenario_id": scenario.scenario_id,
        "version": scenario.scenario_version,
        "scenario_type": scenario.scenario_type,
        "status": scenario.status,
        "location_id": scenario.location_id,
        "form": scenario.form,
        "variant": scenario.variant,
        "assigned_agent_id": scenario.assigned_agent_id,
        "started_day": scenario.started_day,
        "started_time_minutes": scenario.started_time_minutes,
        "completed_day": scenario.completed_day,
        "completed_time_minutes": scenario.completed_time_minutes,
        "stimulus_text": latest.stimulus_text if latest else "",
        "visible_options": options,
        "options": options,
        "seat_options": options if scenario.scenario_type == "seating" else [],
        "layout": _json_loads(latest.layout_json, {}) if latest else {},
        "exposure_id": latest.id if latest else None,
        "available_response_ids": [item.get("option_id") for item in options],
        "selected_seat_id": selected_seat_id,
        "metadata": scenario_metadata,
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
        "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
    }


def _serialize_response(response: ScenarioResponse) -> dict[str, Any]:
    return {
        "response_id": response.id,
        "scenario_instance_id": response.scenario_instance_id,
        "action_id": response.action_id,
        "response_type": response.response_type,
        "selected_option_id": response.selected_option_id,
        "response_text": response.response_text,
        "response_latency_ms": response.response_latency_ms,
        "changed_choice": response.changed_choice,
        "outcome": response.outcome,
        "world_day": response.world_day,
        "world_time_minutes": response.world_time_minutes,
        "metadata": _json_loads(response.metadata_json, {}),
        "created_at": response.created_at.isoformat() if response.created_at else None,
    }


def _serialize_turn(turn: WorldConversationTurn) -> dict[str, Any]:
    return {
        "turn_id": turn.id,
        "speaker_type": turn.speaker_type,
        "speaker_id": turn.speaker_id,
        "content": turn.content,
        "world_day": turn.world_day,
        "world_time_minutes": turn.world_time_minutes,
        "response_latency_ms": turn.response_latency_ms,
        "generation_mode": turn.generation_mode,
        "model_provider": turn.model_provider,
        "model_name": turn.model_name,
        "prompt_version": turn.prompt_version,
        "safety_flag": turn.safety_flag,
        "metadata": _json_loads(turn.metadata_json, {}),
        "created_at": turn.created_at.isoformat() if turn.created_at else None,
    }


def _serialize_conversation(
    db: DBSession,
    conversation: WorldConversation,
) -> dict[str, Any]:
    turns = (
        db.query(WorldConversationTurn)
        .filter(WorldConversationTurn.conversation_id == conversation.id)
        .order_by(WorldConversationTurn.id.asc())
        .all()
    )
    participants = (
        db.query(WorldConversationParticipant)
        .filter(WorldConversationParticipant.conversation_id == conversation.id)
        .order_by(WorldConversationParticipant.id.asc())
        .all()
    )
    serialized_participants = [
        {
            "participant_id": item.id,
            "member_type": item.member_type,
            "agent_id": item.agent_id,
            "member_role": item.member_role,
            "joined_at": item.joined_at.isoformat() if item.joined_at else None,
            "left_at": item.left_at.isoformat() if item.left_at else None,
            "leave_reason_code": item.leave_reason_code,
        }
        for item in participants
    ]
    if not serialized_participants:
        member_specs = (
            [
                ("resident", conversation.initiator_agent_id, "initiator"),
                ("resident", conversation.agent_id, "target"),
            ]
            if conversation.conversation_kind == "resident_resident"
            else [
                ("participant", None, "initiator"),
                ("resident", conversation.agent_id, "target"),
            ]
        )
        serialized_participants = [
            {
                "participant_id": None,
                "member_type": member_type,
                "agent_id": agent_id,
                "member_role": member_role,
                "joined_at": conversation.started_at.isoformat() if conversation.started_at else None,
                "left_at": conversation.updated_at.isoformat() if conversation.status != "active" and conversation.updated_at else None,
                "leave_reason_code": conversation.ended_reason_code,
            }
            for member_type, agent_id, member_role in member_specs
        ]
    return {
        "conversation_id": conversation.id,
        "agent_id": conversation.agent_id,
        "location_id": conversation.location_id,
        "status": conversation.status,
        "conversation_kind": conversation.conversation_kind,
        "initiator_type": conversation.initiator_type,
        "initiator_agent_id": conversation.initiator_agent_id,
        "visibility": conversation.visibility,
        "ended_reason_code": conversation.ended_reason_code,
        "metadata": _json_loads(conversation.metadata_json, {}),
        "participants": serialized_participants,
        "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "turns": [_serialize_turn(item) for item in turns],
    }


def build_island_export(db: DBSession, session: UserSession) -> dict[str, Any]:
    world = (
        db.query(WorldState)
        .filter(WorldState.session_id == session.id)
        .first()
    )
    if world is None:
        return {
            "state": None,
            "map": None,
            "visuals": None,
            "actors": [],
            "residents": [],
            "resident_intents": [],
            "simulation_pulses": [],
            "interaction_prompts": [],
            "actions": [],
            "atomic_action_executions": [],
            "memories": [],
            "scenarios": [],
            "exposures": [],
            "responses": [],
            "event_instances": [],
            "scheduled_events": [],
            "event_trigger_evaluations": [],
            "behavioral_event_records": [],
            "conversations": [],
            "versions": {
                "world_version": WORLD_VERSION,
                "scenario_pack_version": SCENARIO_PACK_VERSION,
                "scenario_version": SCENARIO_VERSION,
            },
        }
    spec = _resolve_bound_world_spec(world)
    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == session.id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    intent_states = (
        db.query(ResidentIntentState)
        .filter(ResidentIntentState.session_id == session.id)
        .order_by(ResidentIntentState.agent_id.asc())
        .all()
    )
    intents_by_agent = {item.agent_id: item for item in intent_states}
    simulation_pulses = (
        db.query(WorldSimulationPulse)
        .filter(WorldSimulationPulse.session_id == session.id)
        .order_by(WorldSimulationPulse.sequence.asc())
        .all()
    )
    actions = (
        db.query(WorldAction)
        .filter(WorldAction.session_id == session.id)
        .order_by(WorldAction.id.asc())
        .all()
    )
    atomic_action_executions = (
        db.query(WorldAtomicActionExecution)
        .filter(WorldAtomicActionExecution.session_id == session.id)
        .order_by(WorldAtomicActionExecution.id.asc())
        .all()
    )
    memories = (
        db.query(WorldMemory)
        .filter(WorldMemory.session_id == session.id)
        .order_by(WorldMemory.id.asc())
        .all()
    )
    relationships = (
        db.query(RelationshipState)
        .filter(RelationshipState.session_id == session.id)
        .order_by(
            RelationshipState.source_agent_id.asc(),
            RelationshipState.target_key.asc(),
            RelationshipState.id.asc(),
        )
        .all()
    )
    relationship_changes = (
        db.query(RelationshipChange)
        .filter(RelationshipChange.session_id == session.id)
        .order_by(RelationshipChange.id.asc())
        .all()
    )
    scenarios = (
        db.query(ScenarioInstance)
        .filter(ScenarioInstance.session_id == session.id)
        .order_by(ScenarioInstance.id.asc())
        .all()
    )
    exposures = (
        db.query(ScenarioExposure)
        .filter(ScenarioExposure.session_id == session.id)
        .order_by(ScenarioExposure.id.asc())
        .all()
    )
    responses = (
        db.query(ScenarioResponse)
        .filter(ScenarioResponse.session_id == session.id)
        .order_by(ScenarioResponse.id.asc())
        .all()
    )
    conversations = (
        db.query(WorldConversation)
        .filter(WorldConversation.session_id == session.id)
        .order_by(WorldConversation.id.asc())
        .all()
    )
    interaction_prompts = (
        db.query(WorldInteractionPrompt)
        .filter(WorldInteractionPrompt.session_id == session.id)
        .order_by(WorldInteractionPrompt.id.asc())
        .all()
    )
    event_instances = (
        db.query(WorldEventInstance)
        .filter(WorldEventInstance.session_id == session.id)
        .order_by(WorldEventInstance.id.asc())
        .all()
    )
    scheduled_events = (
        db.query(WorldScheduledEvent)
        .filter(WorldScheduledEvent.session_id == session.id)
        .order_by(WorldScheduledEvent.id.asc())
        .all()
    )
    trigger_evaluations = (
        db.query(WorldEventTriggerEvaluation)
        .filter(WorldEventTriggerEvaluation.session_id == session.id)
        .order_by(WorldEventTriggerEvaluation.id.asc())
        .all()
    )
    commitments = db.query(WorldCommitment).filter(WorldCommitment.session_id == session.id).order_by(WorldCommitment.id.asc()).all()
    plan_members = db.query(WorldPlanMember).filter(WorldPlanMember.session_id == session.id).order_by(WorldPlanMember.id.asc()).all()
    resource_reservations = db.query(WorldResourceReservation).filter(WorldResourceReservation.session_id == session.id).order_by(WorldResourceReservation.id.asc()).all()
    plan_transitions = db.query(WorldPlanTransition).filter(WorldPlanTransition.session_id == session.id).order_by(WorldPlanTransition.id.asc()).all()
    plan_notices = db.query(WorldPlanNotice).filter(WorldPlanNotice.session_id == session.id).order_by(WorldPlanNotice.id.asc()).all()
    board_posts = db.query(WorldBoardPost).filter(WorldBoardPost.session_id == session.id).order_by(WorldBoardPost.id.asc()).all()
    plan_social_projections = db.query(WorldPlanSocialProjection).filter(WorldPlanSocialProjection.session_id == session.id).order_by(WorldPlanSocialProjection.id.asc()).all()
    knowledge_facts = db.query(WorldKnowledgeFact).filter(WorldKnowledgeFact.session_id == session.id).order_by(WorldKnowledgeFact.id.asc()).all()
    actor_knowledge = db.query(WorldActorKnowledge).filter(WorldActorKnowledge.session_id == session.id).order_by(WorldActorKnowledge.id.asc()).all()
    social_post_views = db.query(WorldSocialPostView).filter(WorldSocialPostView.session_id == session.id).order_by(WorldSocialPostView.id.asc()).all()
    variant_proposals = db.query(WorldPlanVariantProposal).filter(WorldPlanVariantProposal.session_id == session.id).order_by(WorldPlanVariantProposal.id.asc()).all()
    variant_consents = db.query(WorldPlanVariantConsent).filter(WorldPlanVariantConsent.session_id == session.id).order_by(WorldPlanVariantConsent.id.asc()).all()
    phone_posts = db.query(UserPost).filter(UserPost.session_id == session.id, UserPost.post_type.in_(("invitation", "activity_record"))).order_by(UserPost.id.asc()).all()
    emergence_decisions = db.query(WorldEmergenceDecision).filter(WorldEmergenceDecision.session_id == session.id).order_by(WorldEmergenceDecision.id.asc()).all()
    emergence_evaluations = db.query(WorldEmergenceEvaluation).filter(WorldEmergenceEvaluation.session_id == session.id).order_by(WorldEmergenceEvaluation.id.asc()).all()
    emergence_candidates = db.query(WorldEmergenceCandidate).filter(WorldEmergenceCandidate.session_id == session.id).order_by(WorldEmergenceCandidate.id.asc()).all()
    emergent_event_runtimes = db.query(WorldEmergentEventRuntime).filter(WorldEmergentEventRuntime.session_id == session.id).order_by(WorldEmergentEventRuntime.id.asc()).all()
    emergent_event_transitions = db.query(WorldEmergentEventTransition).filter(WorldEmergentEventTransition.session_id == session.id).order_by(WorldEmergentEventTransition.id.asc()).all()
    serialized_residents = [
        _serialize_resident(
            item,
            "en",
            spec,
            intent=intents_by_agent.get(item.agent_id),
        )
        for item in residents
    ]
    return {
        "state": _serialize_world(world, spec),
        "map": _serialize_map(spec.map_spec),
        "visuals": _serialize_visuals(spec, "en"),
        "actors": _serialize_actors(
            session=session,
            world=world,
            spec=spec,
            residents=serialized_residents,
            language="en",
        ),
        "residents": serialized_residents,
        "resident_intents": [
            {
                "intent_state_id": item.id,
                "agent_id": item.agent_id,
                "intent_type": item.intent_type,
                "status": item.status,
                "target_location_id": item.target_location_id,
                "target_actor_type": item.target_actor_type,
                "target_agent_id": item.target_agent_id,
                "target_object_id": item.target_object_id,
                "started_day": item.started_day,
                "started_time_minutes": item.started_time_minutes,
                "due_day": item.due_day,
                "due_time_minutes": item.due_time_minutes,
                "source_pulse_id": item.source_pulse_id,
                "source_action_id": item.source_action_id,
                "policy_id": item.policy_id,
                "policy_version": item.policy_version,
                "summary": _json_loads(item.summary_json, {}),
                "metadata": _json_loads(item.metadata_json, {}),
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in intent_states
        ],
        "simulation_pulses": [
            {
                **_serialize_pulse(item),
                "idempotency_key": item.idempotency_key,
                "metadata": _json_loads(item.metadata_json, {}),
            }
            for item in simulation_pulses
        ],
        "actions": [_serialize_action(item) for item in actions],
        "atomic_action_executions": [
            {
                "execution_id": item.id,
                "idempotency_key": item.idempotency_key,
                "request_hash": item.request_hash,
                "actor_type": item.actor_type,
                "actor_agent_id": item.actor_agent_id,
                "action_id": item.action_id,
                "affordance_id": item.affordance_id,
                "target_location_id": item.target_location_id,
                "target_agent_id": item.target_agent_id,
                "target_object_id": item.target_object_id,
                "requested_revision": item.requested_revision,
                "accepted_revision": item.accepted_revision,
                "status": item.status,
                "reason_code": item.reason_code,
                "status_code": item.status_code,
                "source_action_id": item.source_action_id,
                "inputs": _json_loads(item.inputs_json, {}),
                "effects": _json_loads(item.effects_json, []),
                "result": _json_loads(item.result_json, {}),
                "runtime_version": item.runtime_version,
                "contract_version": item.contract_version,
                "metadata": _json_loads(item.metadata_json, {}),
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in atomic_action_executions
        ],
        "behavior_process": [
            {
                "action_id": item.id,
                "actor_type": item.actor_type,
                "action_type": item.action_type,
                "record": _json_loads(item.metadata_json, {}).get("behavior_audit"),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in actions
            if isinstance(
                _json_loads(item.metadata_json, {}).get("behavior_audit"), dict
            )
        ],
        "memories": [
            {
                "memory_id": item.id,
                "owner_agent_id": item.owner_agent_id,
                "memory_type": item.memory_type,
                "source_action_id": item.source_action_id,
                "content": item.content,
                "importance": item.importance,
                "privacy_category": item.privacy_category,
                "occurred_day": item.occurred_day,
                "occurred_time_minutes": item.occurred_time_minutes,
                "metadata": _json_loads(item.metadata_json, {}),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in memories
        ],
        "relationships": [serialize_relationship(item) for item in relationships],
        "relationship_changes": [
            serialize_relationship_change(item) for item in relationship_changes
        ],
        "scenarios": [
            {
                **_serialize_scenario(db, item, "en"),
                "follow_up_status": item.follow_up_status,
                "follow_up_due_day": item.follow_up_due_day,
                "follow_up_due_time_minutes": item.follow_up_due_time_minutes,
            }
            for item in scenarios
        ],
        "exposures": [
            {
                "exposure_id": item.id,
                "scenario_instance_id": item.scenario_instance_id,
                "stimulus_text": item.stimulus_text,
                "visible_options": _json_loads(item.visible_options_json, []),
                "layout": _json_loads(item.layout_json, {}),
                "exposure_complete": item.exposure_complete,
                "interruption_reason": item.interruption_reason,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
                "language": item.language,
                "metadata": _json_loads(item.metadata_json, {}),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in exposures
        ],
        "responses": [_serialize_response(item) for item in responses],
        "event_instances": [serialize_event_export(item) for item in event_instances],
        "scheduled_events": [
            serialize_scheduled_event_export(item) for item in scheduled_events
        ],
        "event_trigger_evaluations": [
            serialize_trigger_evaluation(item) for item in trigger_evaluations
        ],
        "behavioral_event_records": build_behavioral_event_records(db, session),
        "commitments": [_serialize_commitment(item) for item in commitments],
        "plan_members": [
            {
                "member_id": item.id,
                "commitment_id": item.commitment_id,
                "actor_type": item.actor_type,
                "actor_agent_id": item.actor_agent_id,
                "actor_key": item.actor_key,
                "role_id": item.role_id,
                "required": item.required,
                "response_status": item.response_status,
                "response_reason_code": item.response_reason_code,
                "attendance_status": item.attendance_status,
                "arrival_day": item.arrival_day,
                "arrival_time_minutes": item.arrival_time_minutes,
                "departure_day": item.departure_day,
                "departure_time_minutes": item.departure_time_minutes,
            }
            for item in plan_members
        ],
        "resource_reservations": [
            {
                "reservation_id": item.id,
                "commitment_id": item.commitment_id,
                "resource_type": item.resource_type,
                "resource_key": item.resource_key,
                "start_ordinal": item.start_ordinal,
                "end_ordinal": item.end_ordinal,
                "start_day": item.start_day,
                "start_time_minutes": item.start_time_minutes,
                "end_day": item.end_day,
                "end_time_minutes": item.end_time_minutes,
                "status": item.status,
                "generation": item.generation,
                "released_reason_code": item.released_reason_code,
            }
            for item in resource_reservations
        ],
        "plan_transitions": [
            {
                "transition_id": item.id,
                "commitment_id": item.commitment_id,
                "idempotency_key": item.idempotency_key,
                "request_hash": item.request_hash,
                "actor_type": item.actor_type,
                "actor_agent_id": item.actor_agent_id,
                "transition_type": item.transition_type,
                "requested_revision": item.requested_revision,
                "accepted_revision": item.accepted_revision,
                "status": item.status,
                "reason_code": item.reason_code,
                "status_code": item.status_code,
                "before": _json_loads(item.before_json, {}),
                "after": _json_loads(item.after_json, {}),
                "result": _json_loads(item.result_json, {}),
                "metadata": _json_loads(item.metadata_json, {}),
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in plan_transitions
        ],
        "plan_notices": [
            {
                "notice_id": item.id,
                "commitment_id": item.commitment_id,
                "transition_id": item.transition_id,
                "recipient_actor_key": item.recipient_actor_key,
                "notice_type": item.notice_type,
                "reason_code": item.reason_code,
                "payload": _json_loads(item.payload_json, {}),
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in plan_notices
        ],
        "board_posts": [_serialize_board_post(item) for item in board_posts],
        "phone_plan_social_projections": [
            {
                "projection_id": item.id,
                "commitment_id": item.commitment_id,
                "invitation_post_id": item.invitation_post_id,
                "board_post_id": item.board_post_id,
                "audience_scope": item.audience_scope,
                "audience_actor_keys": _json_loads(item.audience_actor_keys_json, []),
                "organizer_attending": item.organizer_attending,
                "wait_minutes": item.wait_minutes,
                "public_headcount": item.public_headcount,
                "initial_plan_revision": item.initial_plan_revision,
                "idempotency_key": item.idempotency_key,
                "request_hash": item.request_hash,
            }
            for item in plan_social_projections
        ],
        "phone_posts": [
            {
                "database_post_id": item.id,
                "feed_post_id": item.feed_post_id,
                "post_type": item.post_type,
                "author_type": item.author_type,
                "author_agent_id": item.author_agent_id,
                "visibility": item.visibility,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "location_id": item.location_id,
                "day": item.day,
                "world_time_minutes": item.world_time_minutes,
                "facts": _json_loads(item.facts_json, {}),
                "metadata": _json_loads(item.metadata_json, {}),
            }
            for item in phone_posts
        ],
        "knowledge_facts": [
            {
                "fact_id": item.id,
                "fact_key": item.fact_key,
                "fact_type": item.fact_type,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "visibility": item.visibility,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "payload": _json_loads(item.payload_json, {}),
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in knowledge_facts
        ],
        "actor_knowledge": [
            {
                "knowledge_id": item.id,
                "fact_id": item.fact_id,
                "actor_key": item.actor_key,
                "acquisition_source": item.acquisition_source,
                "source_post_id": item.source_post_id,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in actor_knowledge
        ],
        "social_post_views": [
            {
                "view_id": item.id,
                "user_post_id": item.user_post_id,
                "viewer_actor_key": item.viewer_actor_key,
                "idempotency_key": item.idempotency_key,
                "request_hash": item.request_hash,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in social_post_views
        ],
        "plan_variant_proposals": [
            {
                "proposal_id": item.id,
                "commitment_id": item.commitment_id,
                "source_recipe_id": item.source_recipe_id,
                "target_recipe_id": item.target_recipe_id,
                "proposer_actor_key": item.proposer_actor_key,
                "attendee_actor_keys": _json_loads(item.attendee_actor_keys_json, []),
                "status": item.status,
                "reason_code": item.reason_code,
                "requested_revision": item.requested_revision,
                "applied_revision": item.applied_revision,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in variant_proposals
        ],
        "plan_variant_consents": [
            {
                "consent_id": item.id,
                "proposal_id": item.proposal_id,
                "actor_key": item.actor_key,
                "decision": item.decision,
                "reason_code": item.reason_code,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
            }
            for item in variant_consents
        ],
        "emergence_decisions": [_serialize_emergence_decision(item) for item in emergence_decisions],
        "emergence_evaluations": [
            {
                "evaluation_id": item.id,
                "idempotency_key": item.idempotency_key,
                "request_hash": item.request_hash,
                "source": item.source,
                "source_pulse_id": item.source_pulse_id,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
                "simulation_seed": item.simulation_seed,
                "policy_id": item.policy_id,
                "policy_version": item.policy_version,
                "state_fingerprint": item.state_fingerprint,
                "status": item.status,
                "candidate_count": item.candidate_count,
                "selected_count": item.selected_count,
                "budget": _json_loads(item.budget_json, {}),
            }
            for item in emergence_evaluations
        ],
        "emergence_candidates": [
            {
                "candidate_id": item.id,
                "evaluation_id": item.evaluation_id,
                "candidate_key": item.candidate_key,
                "recipe_id": item.recipe_id,
                "complexity": item.complexity,
                "player_facing": item.player_facing,
                "direct_participant_invite": item.direct_participant_invite,
                "organizer_actor_key": item.organizer_actor_key,
                "location_id": item.location_id,
                "scheduled_day": item.scheduled_day,
                "scheduled_time_minutes": item.scheduled_time_minutes,
                "expires_day": item.expires_day,
                "expires_time_minutes": item.expires_time_minutes,
                "chain_depth": item.chain_depth,
                "source_event_runtime_id": item.source_event_runtime_id,
                "source_types": _json_loads(item.source_types_json, []),
                "source_facts": _json_loads(item.source_facts_json, []),
                "invitees": _json_loads(item.invitees_json, []),
                "validation": _json_loads(item.validation_json, {}),
                "score": _json_loads(item.score_json, {}),
                "rank": item.rank,
                "outcome": item.outcome,
                "reason_code": item.reason_code,
                "selected_commitment_id": item.selected_commitment_id,
                "selected_event_instance_id": item.selected_event_instance_id,
            }
            for item in emergence_candidates
        ],
        "emergent_event_runtimes": [
            {
                "runtime_id": item.id,
                "candidate_id": item.candidate_id,
                "event_instance_id": item.event_instance_id,
                "commitment_id": item.commitment_id,
                "recipe_id": item.recipe_id,
                "complexity": item.complexity,
                "player_facing": item.player_facing,
                "direct_participant_invite": item.direct_participant_invite,
                "organizer_actor_key": item.organizer_actor_key,
                "status": item.status,
                "chain_depth": item.chain_depth,
                "fact_chain_id": item.fact_chain_id,
                "started_day": item.started_day,
                "started_time_minutes": item.started_time_minutes,
                "expires_day": item.expires_day,
                "expires_time_minutes": item.expires_time_minutes,
                "completed_day": item.completed_day,
                "completed_time_minutes": item.completed_time_minutes,
                "revision": item.revision,
                "terminal_reason_code": item.terminal_reason_code,
                "metadata": _json_loads(item.metadata_json, {}),
            }
            for item in emergent_event_runtimes
        ],
        "emergent_event_transitions": [
            {
                "transition_id": item.id,
                "runtime_id": item.runtime_id,
                "transition_key": item.transition_key,
                "transition_type": item.transition_type,
                "before_status": item.before_status,
                "after_status": item.after_status,
                "reason_code": item.reason_code,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
                "metadata": _json_loads(item.metadata_json, {}),
            }
            for item in emergent_event_transitions
        ],
        "event_stages": [
            {"runtime_id": item.runtime_id, "stage_recipe_id": item.stage_recipe_id,
             "definition_hash": item.definition_hash, "current_stage_id": item.current_stage_id,
             "status": item.status, "revision": item.revision, "outcome": item.outcome,
             "public_consent": item.public_consent, "state": _json_loads(item.state_json, {})}
            for item in db.query(WorldEventStage).filter_by(session_id=session.id).order_by(WorldEventStage.id)
        ],
        "event_stage_operations": [
            {"operation_id": item.id, "runtime_id": item.runtime_id, "actor_key": item.actor_key,
             "operation": item.operation, "stage_id": item.stage_id,
             "world_day": item.world_day, "world_time_minutes": item.world_time_minutes,
             "result": _json_loads(item.result_json, {})}
            for item in db.query(WorldEventStageOperation).filter_by(session_id=session.id).order_by(WorldEventStageOperation.id)
        ],
        "decision_invocations": [
            {"audit_id": item.id, "actor_key": item.actor_key, "decision_type": item.decision_type,
             "world_day": item.world_day, "status": item.status, "generation_mode": item.generation_mode,
             "provider_id": item.provider_id, "model_version": item.model_version,
             "prompt_version": item.prompt_version, "policy_version": item.policy_version,
             "input_summary": _json_loads(item.input_summary_json, {}), "fallback_reason": item.fallback_reason,
             "latency_ms": item.latency_ms, "result": _json_loads(item.result_json, {})}
            for item in db.query(WorldDecisionInvocation).filter_by(session_id=session.id).order_by(WorldDecisionInvocation.id)
        ],
        "decision_attempts": [
            {"invocation_id": item.invocation_id, "attempt_number": item.attempt_number,
             "world_day": item.world_day, "reserved_units": item.reserved_units, "status": item.status,
             "output_sha256": item.output_sha256, "latency_ms": item.latency_ms}
            for item in db.query(WorldDecisionAttempt).filter_by(session_id=session.id).order_by(WorldDecisionAttempt.id)
        ],
        "conversations": [_serialize_conversation(db, item) for item in conversations],
        "interaction_prompts": [
            {
                **serialize_interaction_prompt(item, language="en"),
                "idempotency_key": item.idempotency_key,
            }
            for item in interaction_prompts
        ],
        "versions": {
            **_serialize_content_versions(world, spec),
            "scenario_version": SCENARIO_VERSION,
        },
    }


def _visible_interaction_point(spec, day, object_id):
    from services.holiday_object_service import visible
    return visible(spec, day, object_id)
