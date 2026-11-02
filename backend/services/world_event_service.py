"""Validate and persist world events and their effects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from data.neutral_events import get_event_registry
from models import (
    CharacterState,
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldEventInstance,
    WorldScheduledEvent,
    WorldState,
)
from services.world_memory_service import MemoryConflictError, record_memory
from services.world_relationship_service import (
    RelationshipStateError,
    apply_relationship_change,
)
from world.clock import ClockPosition, is_due
from world.declarative_events import resolve_declarative_event_handler
from world.events import (
    EventActionDescriptor,
    EventContext,
    EventPresentation,
    EventTransition,
    ImmediateEvent,
    UnknownEventHandlerError,
)
from world.registry import get_world_spec
from world.specs import WorldSpec


WORLD_EVENT_RUNTIME_VERSION = "world-event-runtime-v1"
ACTIVE_EVENT_STATUSES = frozenset({"active"})
TERMINAL_EVENT_STATUSES = frozenset({"completed", "cancelled", "failed"})
SCHEDULED_EVENT_STATUSES = frozenset({"scheduled", "delivered", "cancelled", "failed"})


class WorldEventRuntimeError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _plain(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


def _metadata_payload(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = {"schema_version": WORLD_EVENT_RUNTIME_VERSION}
    if metadata:
        payload.update(_plain(metadata))
    return payload


def _resolve_bound_world_spec(world: WorldState) -> WorldSpec:
    try:
        spec = get_world_spec(world.world_version)
    except KeyError as exc:
        raise WorldEventRuntimeError(
            f"World content version is not available: {world.world_version}.",
            409,
        ) from exc
    if world.scenario_pack_version != spec.scenario_pack_version:
        raise WorldEventRuntimeError(
            "The session's scenario pack does not match its bound world version.",
            409,
        )
    return spec


def _resolve_handler(
    event_type: str,
    event_version: str,
    *,
    spec: WorldSpec | None = None,
    event_id: str | None = None,
):
    try:
        return get_event_registry().resolve(event_type, event_version)
    except UnknownEventHandlerError as exc:
        if spec is not None:
            handler = resolve_declarative_event_handler(
                spec,
                event_type=event_type,
                event_version=event_version,
                event_id=event_id,
            )
            if handler is not None:
                return handler
        raise WorldEventRuntimeError(str(exc), 409) from exc


def _validate_key(value: str, field_name: str, *, max_length: int = 120) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > max_length:
        raise WorldEventRuntimeError(
            f"{field_name} must contain 1 to {max_length} characters."
        )
    return normalized


def _visible_agent_ids(
    db: DBSession,
    *,
    session_id: int,
    location_id: str,
) -> tuple[int, ...]:
    rows = (
        db.query(CharacterState.agent_id)
        .filter(
            CharacterState.session_id == session_id,
            CharacterState.current_location_id == location_id,
        )
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    return tuple(int(row[0]) for row in rows)


def build_event_context(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    event: WorldEventInstance,
) -> EventContext:
    spec = _resolve_bound_world_spec(world)
    metadata = _json_loads(event.metadata_json, {})
    metadata.setdefault(
        "calendar",
        {
            "total_days": spec.calendar.total_days,
            "day_start_minute": spec.calendar.day_start_minute,
            "day_end_minute": spec.calendar.day_end_minute,
        },
    )
    return EventContext(
        session_id=session.id,
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        location_id=event.location_id,
        simulation_seed=session.simulation_seed,
        event_instance_id=event.id,
        visible_agent_ids=_visible_agent_ids(
            db,
            session_id=session.id,
            location_id=event.location_id,
        ),
        state=_json_loads(event.state_json, {}),
        metadata=metadata,
    )


def create_event_instance(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    event_type: str,
    event_version: str,
    trigger_key: str,
    location_id: str | None = None,
    state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorldEventInstance:
    if world.session_id != session.id:
        raise WorldEventRuntimeError("WorldState does not belong to this session.", 409)
    spec = _resolve_bound_world_spec(world)
    normalized_event_type = _validate_key(event_type, "event_type", max_length=80)
    normalized_event_version = _validate_key(
        event_version,
        "event_version",
        max_length=40,
    )
    normalized_trigger = _validate_key(trigger_key, "trigger_key")
    resolved_location = location_id or world.participant_location_id
    if resolved_location not in spec.locations:
        raise WorldEventRuntimeError("Event location is not in the bound world.", 409)
    raw_event_id = (metadata or {}).get("declarative_event_id")
    declarative_event_id = raw_event_id if isinstance(raw_event_id, str) else None
    _resolve_handler(
        normalized_event_type,
        normalized_event_version,
        spec=spec,
        event_id=declarative_event_id,
    )

    state_payload = dict(state or {"state": "presented"})
    metadata_payload = _metadata_payload(metadata)
    existing = (
        db.query(WorldEventInstance)
        .filter(
            WorldEventInstance.session_id == session.id,
            WorldEventInstance.trigger_key == normalized_trigger,
        )
        .first()
    )
    if existing is not None:
        if (
            existing.event_type != normalized_event_type
            or existing.event_version != normalized_event_version
            or existing.location_id != resolved_location
            or _json_loads(existing.state_json, {}) != state_payload
            or _json_loads(existing.metadata_json, {}) != metadata_payload
        ):
            raise WorldEventRuntimeError(
                "Event trigger_key was already used with a different payload.",
                409,
            )
        return existing

    event = WorldEventInstance(
        session_id=session.id,
        event_type=normalized_event_type,
        event_version=normalized_event_version,
        status="active",
        location_id=resolved_location,
        state_json=_json_dumps(state_payload),
        trigger_key=normalized_trigger,
        started_day=world.current_day,
        started_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps(metadata_payload),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        raise WorldEventRuntimeError(
            "Could not create the event instance because its trigger is not unique.",
            409,
        ) from exc
    return event


def get_active_event_instance(
    db: DBSession,
    *,
    session_id: int,
    location_id: str | None = None,
) -> WorldEventInstance | None:
    query = db.query(WorldEventInstance).filter(
        WorldEventInstance.session_id == session_id,
        WorldEventInstance.status.in_(ACTIVE_EVENT_STATUSES),
    )
    if location_id is not None:
        query = query.filter(WorldEventInstance.location_id == location_id)
    return (
        query.order_by(
            WorldEventInstance.started_day.asc(),
            WorldEventInstance.started_time_minutes.asc(),
            WorldEventInstance.id.asc(),
        )
        .first()
    )


def _presentation_action(
    presentation: EventPresentation,
    action_id: str,
) -> EventActionDescriptor | None:
    for descriptor in presentation.actions:
        if descriptor.action_id == action_id:
            return descriptor
    return None


def _label(labels: Mapping[str, str], language: str) -> str:
    return labels.get(language) or labels.get("en") or next(iter(labels.values()), "")


def _public_event_state(state: dict[str, Any], *, behavioral: bool) -> dict[str, Any]:
    if not behavioral:
        return state
    private_keys = {
        "selected_seat_social_density",
        "distance_to_nearest_npc",
        "trigger_goals",
        "conversation_history",
    }
    return {key: value for key, value in state.items() if key not in private_keys}


def serialize_event_instance(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    event: WorldEventInstance,
    language: str,
) -> dict[str, Any]:
    spec = _resolve_bound_world_spec(world)
    instance_metadata = _json_loads(event.metadata_json, {})
    raw_event_id = instance_metadata.get("declarative_event_id")
    handler = _resolve_handler(
        event.event_type,
        event.event_version,
        spec=spec,
        event_id=raw_event_id if isinstance(raw_event_id, str) else None,
    )
    context = build_event_context(db, session=session, world=world, event=event)
    presentation = handler.present(context)
    serialized_state = _json_loads(event.state_json, {})
    behavioral = bool(presentation.metadata.get("behavioral_event"))
    return {
        "event_instance_id": event.id,
        "event_type": event.event_type,
        "version": event.event_version,
        "status": event.status,
        "location_id": event.location_id,
        "renderer_key": presentation.renderer_key,
        "title": _label(presentation.titles, language),
        "title_zh_cn": presentation.titles.get("zh-CN", presentation.titles.get("en", "")),
        "stimulus_text": _label(presentation.stimuli, language),
        "stimulus_text_zh_cn": presentation.stimuli.get(
            "zh-CN",
            presentation.stimuli.get("en", ""),
        ),
        "titles": _plain(presentation.titles),
        "stimuli": _plain(presentation.stimuli),
        "actions": [
            {
                "action_id": action.action_id,
                "label": _label(action.labels, language),
                "label_zh_cn": action.labels.get("zh-CN", action.labels.get("en", "")),
                "labels": _plain(action.labels),
                "kind": action.kind,
                "enabled": action.enabled,
                "requires_text": action.requires_text,
                "target_object_id": action.target_object_id,
                "metadata": _plain(action.metadata),
            }
            for action in presentation.actions
        ],
        "state": _public_event_state(serialized_state, behavioral=behavioral),
        "metadata": {
            **_plain(presentation.metadata),
            "instance": instance_metadata,
        },
        "started_day": event.started_day,
        "started_time_minutes": event.started_time_minutes,
        "completed_day": event.completed_day,
        "completed_time_minutes": event.completed_time_minutes,
        "outcome_code": event.outcome_code,
    }


def _validate_transition(transition: EventTransition) -> None:
    if transition.status not in ACTIVE_EVENT_STATUSES | TERMINAL_EVENT_STATUSES:
        raise WorldEventRuntimeError("Event handler returned an invalid status.", 409)
    if not transition.next_state.strip():
        raise WorldEventRuntimeError("Event handler returned an empty next_state.", 409)
    if not transition.outcome_code.strip():
        raise WorldEventRuntimeError("Event handler returned an empty outcome_code.", 409)


def _record_world_state_effects(
    *,
    world: WorldState,
    event: WorldEventInstance,
    action: WorldAction,
    transition: EventTransition,
) -> None:
    """Apply the small allowlisted state effects returned by a pure handler."""

    if not transition.world_state_effects:
        return
    world_state = _json_loads(world.state_json, {})
    goals = world_state.get("goals")
    if not isinstance(goals, dict):
        goals = {}
    for effect in transition.world_state_effects:
        if effect.effect_type == "set_flag":
            flags = world_state.get("flags")
            if not isinstance(flags, dict):
                flags = {}
            flags[effect.key] = bool(effect.payload.get("value", True))
            world_state["flags"] = flags
            continue
        if effect.effect_type != "upsert_goal":
            raise WorldEventRuntimeError("Unsupported event world-state effect.", 409)
        payload = _plain(effect.payload)
        if not isinstance(payload, dict):
            raise WorldEventRuntimeError("Goal effect payload must be an object.", 409)
        previous = goals.get(effect.key)
        previous_goal = previous if isinstance(previous, dict) else {}
        effect_timestamp = utc_now().isoformat()
        goals[effect.key] = {
            **previous_goal,
            **payload,
            "goal_id": effect.key,
            "created_at": previous_goal.get("created_at", effect_timestamp),
            "updated_at": effect_timestamp,
            "updated_day": world.current_day,
            "updated_time_minutes": world.current_time_minutes,
            "source_event_instance_id": event.id,
            "source_action_id": action.id,
        }
    world_state["goals"] = goals
    world.state_json = _json_dumps(world_state)


def _record_memory_effects(
    db: DBSession,
    *,
    session_id: int,
    world: WorldState,
    event: WorldEventInstance,
    action: WorldAction,
    transition: EventTransition,
) -> None:
    for index, effect in enumerate(transition.memory_effects):
        metadata = _plain(effect.metadata)
        effect_key = str(
            metadata.pop("effect_key", f"{transition.outcome_code}:memory:{index}")
        )
        tags = metadata.pop("tags", ())
        related_agent_ids = metadata.pop("related_agent_ids", ())
        try:
            record_memory(
                db,
                session_id=session_id,
                owner_agent_id=effect.owner_agent_id,
                memory_type=effect.memory_type,
                content=effect.content,
                occurred_day=world.current_day,
                occurred_time_minutes=world.current_time_minutes,
                source_action_id=action.id,
                source_event_type="world_event",
                source_event_id=event.id,
                importance=effect.importance,
                privacy_category=effect.privacy_category,
                location_id=event.location_id,
                related_agent_ids=related_agent_ids,
                tags=tags,
                effect_key=effect_key,
                metadata={
                    **metadata,
                    "event_type": event.event_type,
                    "event_version": event.event_version,
                    "event_outcome_code": transition.outcome_code,
                    "subject_type": effect.subject_type,
                    "subject_id": effect.subject_id,
                },
            )
        except (ValueError, MemoryConflictError) as exc:
            raise WorldEventRuntimeError(str(exc), 409) from exc


def _record_relationship_effects(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    event: WorldEventInstance,
    action: WorldAction,
    transition: EventTransition,
) -> None:
    for index, effect in enumerate(transition.relationship_effects):
        metadata = _plain(effect.metadata)
        effect_key = str(
            metadata.pop("effect_key", f"{transition.outcome_code}:relationship:{index}")
        )
        try:
            apply_relationship_change(
                db,
                spec=spec,
                world=world,
                source_agent_id=effect.source_agent_id,
                target_key="participant",
                idempotency_key=f"event:{event.id}:{effect_key}",
                effect_key=effect_key,
                reason_code=effect.reason_code,
                familiarity_delta=effect.familiarity_delta,
                trust_delta=effect.trust_delta,
                warmth_delta=effect.warmth_delta,
                tension_delta=effect.tension_delta,
                source_action_id=action.id,
                source_event_type="world_event",
                source_event_id=event.id,
            )
        except RelationshipStateError as exc:
            raise WorldEventRuntimeError(exc.detail, exc.status_code) from exc


def _schedule_event_effect(
    db: DBSession,
    *,
    world: WorldState,
    parent_event: WorldEventInstance,
    scheduled,
) -> WorldScheduledEvent:
    spec = _resolve_bound_world_spec(world)
    event_type = _validate_key(scheduled.event_type, "event_type", max_length=80)
    event_version = _validate_key(scheduled.version, "event_version", max_length=40)
    deduplication_key = _validate_key(
        scheduled.deduplication_key,
        "deduplication_key",
    )
    payload = _plain(scheduled.payload)
    raw_event_id = payload.get("event_id") if isinstance(payload, dict) else None
    _resolve_handler(
        event_type,
        event_version,
        spec=spec,
        event_id=raw_event_id if isinstance(raw_event_id, str) else None,
    )
    due = ClockPosition(scheduled.due_day, scheduled.due_time_minutes)
    current = ClockPosition(world.current_day, world.current_time_minutes)
    if due <= current:
        raise WorldEventRuntimeError("Scheduled events must be in the future.", 409)
    if not 1 <= due.day <= spec.calendar.total_days:
        raise WorldEventRuntimeError("Scheduled event day is outside the world.", 409)
    if not spec.calendar.day_start_minute <= due.minute <= spec.calendar.day_end_minute:
        raise WorldEventRuntimeError(
            "Scheduled event time is outside the playable day.",
            409,
        )
    existing = (
        db.query(WorldScheduledEvent)
        .filter(
            WorldScheduledEvent.session_id == world.session_id,
            WorldScheduledEvent.deduplication_key == deduplication_key,
        )
        .first()
    )
    if existing is not None:
        if (
            existing.parent_event_instance_id != parent_event.id
            or existing.event_type != event_type
            or existing.event_version != event_version
            or existing.due_day != due.day
            or existing.due_time_minutes != due.minute
            or _json_loads(existing.payload_json, {}) != payload
        ):
            raise WorldEventRuntimeError(
                "Scheduled event deduplication_key was already used differently.",
                409,
            )
        return existing
    row = WorldScheduledEvent(
        session_id=world.session_id,
        parent_event_instance_id=parent_event.id,
        event_type=event_type,
        event_version=event_version,
        due_day=due.day,
        due_time_minutes=due.minute,
        deduplication_key=deduplication_key,
        payload_json=_json_dumps(payload),
        metadata_json=_json_dumps({"schema_version": WORLD_EVENT_RUNTIME_VERSION}),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise WorldEventRuntimeError(
            "Could not schedule the event because its deduplication key is not unique.",
            409,
        ) from exc
    return row


def apply_event_action(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    action: WorldAction,
    event_instance_id: int,
    event_action_id: str,
    replace_action_target_object_id: bool = True,
    allow_optional_response_text: bool = False,
) -> WorldEventInstance:
    event = (
        db.query(WorldEventInstance)
        .filter(
            WorldEventInstance.id == event_instance_id,
            WorldEventInstance.session_id == session.id,
        )
        .first()
    )
    if event is None:
        raise WorldEventRuntimeError("Event instance was not found.", 404)
    if event.status not in ACTIVE_EVENT_STATUSES:
        raise WorldEventRuntimeError("Event instance is not active.", 409)
    if event.location_id != world.participant_location_id:
        raise WorldEventRuntimeError(
            "Event instance is not at the participant's current location.",
            409,
        )
    spec = _resolve_bound_world_spec(world)
    event_metadata = _json_loads(event.metadata_json, {})
    raw_event_id = event_metadata.get("declarative_event_id")
    handler = _resolve_handler(
        event.event_type,
        event.event_version,
        spec=spec,
        event_id=raw_event_id if isinstance(raw_event_id, str) else None,
    )
    context = build_event_context(db, session=session, world=world, event=event)
    presentation = handler.present(context)
    normalized_action_id = _validate_key(
        event_action_id,
        "event_action_id",
        max_length=80,
    )
    descriptor = _presentation_action(presentation, normalized_action_id)
    if descriptor is None:
        raise WorldEventRuntimeError("Event action is not currently available.", 409)
    if not descriptor.enabled:
        raise WorldEventRuntimeError("Event action is disabled.", 409)
    response_text = (action.response_text or "").strip()
    if descriptor.requires_text and not response_text:
        raise WorldEventRuntimeError("response_text is required for this event action.")
    if not descriptor.requires_text and response_text and not allow_optional_response_text:
        raise WorldEventRuntimeError(
            "response_text is not accepted for this event action."
        )

    try:
        transition = handler.handle_action(
            context,
            normalized_action_id,
            response_text=response_text,
        )
    except Exception as exc:
        raise WorldEventRuntimeError(
            f"Event handler rejected the action: {type(exc).__name__}.",
            409,
        ) from exc
    _validate_transition(transition)

    state = _json_loads(event.state_json, {})
    state["state"] = transition.next_state
    for key, value in transition.state_patch.items():
        if not isinstance(key, str) or not key.strip():
            raise WorldEventRuntimeError("Event state_patch keys must be strings.", 409)
        state[key] = _plain(value)
    event.state_json = _json_dumps(state)
    event.status = transition.status
    event.outcome_code = transition.outcome_code
    event.updated_at = utc_now()
    if transition.status in TERMINAL_EVENT_STATUSES:
        event.completed_day = world.current_day
        event.completed_time_minutes = world.current_time_minutes
        event.completed_at = utc_now()

    action.event_instance_id = event.id
    if replace_action_target_object_id:
        action.target_object_id = normalized_action_id
    action.metadata_json = _json_dumps(
        {
            **_json_loads(action.metadata_json, {}),
            "event_type": event.event_type,
            "event_version": event.event_version,
            "event_action_id": normalized_action_id,
            "event_outcome_code": transition.outcome_code,
            **_plain(transition.metadata),
        }
    )
    transition_metadata = _plain(transition.metadata)
    if isinstance(transition_metadata, dict):
        target_agent_id = transition_metadata.get("target_agent_id")
        target_location_id = transition_metadata.get("target_location_id")
        if isinstance(target_agent_id, int) and target_agent_id > 0:
            action.target_agent_id = target_agent_id
        if isinstance(target_location_id, str) and target_location_id:
            action.target_location_id = target_location_id

    _record_world_state_effects(
        world=world,
        event=event,
        action=action,
        transition=transition,
    )

    _record_memory_effects(
        db,
        session_id=session.id,
        world=world,
        event=event,
        action=action,
        transition=transition,
    )
    _record_relationship_effects(
        db,
        spec=spec,
        world=world,
        event=event,
        action=action,
        transition=transition,
    )
    for scheduled in transition.scheduled_events:
        _schedule_event_effect(
            db,
            world=world,
            parent_event=event,
            scheduled=scheduled,
        )
    for immediate in transition.immediate_events:
        created = create_event_instance(
            db,
            session=session,
            world=world,
            event_type=immediate.event_type,
            event_version=immediate.version,
            trigger_key=immediate.trigger_key,
            location_id=immediate.location_id,
            state=dict(immediate.payload),
            metadata={
                "declarative_event_id": immediate.payload.get("event_id"),
                "started_by_event_instance_id": event.id,
                "started_by_action_id": action.id,
            },
        )
        if created.status != "active":
            raise WorldEventRuntimeError("Immediate event did not become active.", 409)
    return event


def scheduled_event_due_points(
    db: DBSession,
    *,
    world: WorldState,
    before: ClockPosition,
    after: ClockPosition,
) -> set[ClockPosition]:
    rows = (
        db.query(WorldScheduledEvent.due_day, WorldScheduledEvent.due_time_minutes)
        .filter(
            WorldScheduledEvent.session_id == world.session_id,
            WorldScheduledEvent.status == "scheduled",
        )
        .all()
    )
    return {
        ClockPosition(int(day), int(minute))
        for day, minute in rows
        if before < ClockPosition(int(day), int(minute)) <= after
    }


def deliver_due_scheduled_events(
    db: DBSession,
    *,
    world: WorldState,
    limit: int | None = None,
) -> list[WorldScheduledEvent]:
    if limit is not None and limit < 0:
        raise WorldEventRuntimeError("Scheduled-event delivery limit cannot be negative.")
    session = db.query(UserSession).filter(UserSession.id == world.session_id).first()
    if session is None:
        raise WorldEventRuntimeError("Session not found.", 404)
    spec = _resolve_bound_world_spec(world)
    # Flush earlier state changes before priority queries.
    db.flush()
    due_rows = (
        db.query(WorldScheduledEvent)
        .filter(
            WorldScheduledEvent.session_id == world.session_id,
            WorldScheduledEvent.status == "scheduled",
        )
        .order_by(
            WorldScheduledEvent.due_day.asc(),
            WorldScheduledEvent.due_time_minutes.asc(),
            WorldScheduledEvent.id.asc(),
        )
        .all()
    )
    delivered: list[WorldScheduledEvent] = []
    for scheduled in due_rows:
        if limit is not None and len(delivered) >= limit:
            break
        if not is_due(
            scheduled.due_day,
            scheduled.due_time_minutes,
            world.current_day,
            world.current_time_minutes,
        ):
            continue
        metadata = _json_loads(scheduled.metadata_json, {})
        payload = _json_loads(scheduled.payload_json, {})
        try:
            raw_event_id = payload.get("event_id")
            declarative_event_id = raw_event_id if isinstance(raw_event_id, str) else None
            _resolve_handler(
                scheduled.event_type,
                scheduled.event_version,
                spec=spec,
                event_id=declarative_event_id,
            )
            raw_state = payload.get("state")
            if isinstance(raw_state, dict):
                state = dict(raw_state)
            else:
                state = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"location_id"}
                }
            state.setdefault("state", "presented")
            location_id = payload.get("location_id")
            if not isinstance(location_id, str) or not location_id.strip():
                location_id = world.participant_location_id
            if declarative_event_id is not None:
                active_scenario = (
                    db.query(ScenarioInstance.id)
                    .filter(
                        ScenarioInstance.session_id == world.session_id,
                        ScenarioInstance.location_id == location_id,
                        ScenarioInstance.status == "active",
                    )
                    .first()
                )
                active_event = (
                    db.query(WorldEventInstance.id)
                    .filter(
                        WorldEventInstance.session_id == world.session_id,
                        WorldEventInstance.location_id == location_id,
                        WorldEventInstance.status == "active",
                    )
                    .first()
                )
                if active_scenario is not None or active_event is not None:
                    metadata.update(
                        {
                            "delivery_status": "deferred",
                            "deferred_reason_code": (
                                "legacy_scenario_priority"
                                if active_scenario is not None
                                else "active_event_priority"
                            ),
                            "last_attempt_day": world.current_day,
                            "last_attempt_time_minutes": world.current_time_minutes,
                        }
                    )
                    scheduled.metadata_json = _json_dumps(metadata)
                    scheduled.updated_at = utc_now()
                    continue
            result = create_event_instance(
                db,
                session=session,
                world=world,
                event_type=scheduled.event_type,
                event_version=scheduled.event_version,
                trigger_key=f"scheduled:{scheduled.deduplication_key}",
                location_id=location_id,
                state=state,
                metadata={
                    "source": "scheduled_event",
                    "declarative_event_id": declarative_event_id,
                    "scheduled_event_id": scheduled.id,
                    "parent_event_instance_id": scheduled.parent_event_instance_id,
                    "payload": payload,
                },
            )
            scheduled.status = "delivered"
            scheduled.delivered_day = world.current_day
            scheduled.delivered_time_minutes = world.current_time_minutes
            scheduled.result_event_instance_id = result.id
            metadata.update(
                {
                    "delivered_event_instance_id": result.id,
                    "delivery_status": "delivered",
                }
            )
            delivered.append(scheduled)
        except WorldEventRuntimeError as exc:
            scheduled.status = "failed"
            metadata.update(
                {
                    "delivery_status": "failed",
                    "error": exc.detail,
                    "status_code": exc.status_code,
                }
            )
        scheduled.metadata_json = _json_dumps(metadata)
        scheduled.updated_at = utc_now()
    return delivered


def serialize_event_export(event: WorldEventInstance) -> dict[str, Any]:
    return {
        "event_instance_id": event.id,
        "session_id": event.session_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "status": event.status,
        "location_id": event.location_id,
        "state": _json_loads(event.state_json, {}),
        "trigger_key": event.trigger_key,
        "started_day": event.started_day,
        "started_time_minutes": event.started_time_minutes,
        "completed_day": event.completed_day,
        "completed_time_minutes": event.completed_time_minutes,
        "outcome_code": event.outcome_code,
        "metadata": _json_loads(event.metadata_json, {}),
        "started_at": event.started_at.isoformat() if event.started_at else None,
        "completed_at": event.completed_at.isoformat() if event.completed_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


def serialize_scheduled_event_export(event: WorldScheduledEvent) -> dict[str, Any]:
    return {
        "scheduled_event_id": event.id,
        "session_id": event.session_id,
        "parent_event_instance_id": event.parent_event_instance_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "due_day": event.due_day,
        "due_time_minutes": event.due_time_minutes,
        "deduplication_key": event.deduplication_key,
        "payload": _json_loads(event.payload_json, {}),
        "status": event.status,
        "delivered_day": event.delivered_day,
        "delivered_time_minutes": event.delivered_time_minutes,
        "result_event_instance_id": event.result_event_instance_id,
        "metadata": _json_loads(event.metadata_json, {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }
