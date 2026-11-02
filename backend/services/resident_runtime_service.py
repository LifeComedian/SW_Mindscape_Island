"""Resident schedule decisions at island clock ticks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    ResidentIntentState,
    WorldAction,
    WorldConversation,
    WorldMemory,
    WorldState,
)
from services.world_memory_service import MemoryQuery, retrieve_memories
from services.resident_social_service import end_ambient_conversations_for_resident
from world.graph import can_travel
from world.resident_agents import (
    CandidateIntent,
    ResidentDecision,
    ResidentDecisionError,
    ResidentPerception,
    ScheduleDirective,
    ScheduleDrivenPolicy,
    schedule_driven_candidates,
    validate_resident_decision,
)
from world.schedules import ScheduleResolutionError, resolve_resident_schedule
from world.specs import ScheduleBlock, WorldSpec


RESIDENT_DECISION_AUDIT_SCHEMA_VERSION = "resident-decision-audit-v1"
RESIDENT_ACTION_TYPES = frozenset(
    {
        "resident_relocate",
        "resident_continue_schedule",
        "resident_wait",
        "resident_end_intent",
    }
)
RESIDENT_POLICY_ID = "schedule-driven"
RESIDENT_POLICY_VERSION = "v1"
AUTONOMY_RECOVERY_POLICY_ID = "bounded-autonomy"
AUTONOMY_RECOVERY_POLICY_VERSION = "v1"
AUTONOMY_RECOVERY_AUDIT_SCHEMA_VERSION = "resident-autonomy-recovery-v1"


class ResidentRuntimeError(RuntimeError):
    """Raised when a resident tick cannot be safely applied."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _localized(value: Mapping[str, str], language: str = "en") -> str:
    return value.get(language) or value.get("en") or next(iter(value.values()), "")


def _resolve_schedule(
    spec: WorldSpec,
    agent_id: int,
    day: int,
    minute: int,
) -> ScheduleBlock:
    try:
        return resolve_resident_schedule(spec, agent_id, day, minute)
    except ScheduleResolutionError as exc:
        raise ResidentRuntimeError(str(exc), 409) from exc


def _resident_matches_schedule(
    resident: CharacterState,
    schedule: ScheduleBlock,
    *,
    allow_location_override: bool = False,
) -> bool:
    state = _json_loads(resident.state_json)
    has_free_time_override = (
        allow_location_override
        and
        state.get("autonomy_schedule_override_state") == schedule.state_id
    )
    return (
        (resident.current_location_id == schedule.location_id or has_free_time_override)
        and resident.schedule_state == schedule.state_id
    )


def build_resident_perception(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
) -> ResidentPerception:
    """Build one resident's immutable visible-world snapshot."""

    if resident.session_id != world.session_id:
        raise ResidentRuntimeError("Resident state belongs to another session.", 409)
    if resident.agent_id not in spec.residents:
        raise ResidentRuntimeError(
            f"Resident {resident.agent_id} is not in world {spec.world_version}.",
            409,
        )
    if resident.current_location_id not in spec.locations:
        raise ResidentRuntimeError(
            f"Resident {resident.agent_id} is at an unknown location.",
            409,
        )

    schedule = _resolve_schedule(
        spec,
        resident.agent_id,
        world.current_day,
        world.current_time_minutes,
    )
    visible_resident_ids = tuple(
        item[0]
        for item in (
            db.query(CharacterState.agent_id)
            .filter(
                CharacterState.session_id == world.session_id,
                CharacterState.current_location_id == resident.current_location_id,
                CharacterState.agent_id != resident.agent_id,
            )
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
    )
    current_location = spec.locations[resident.current_location_id]
    visible_object_ids = tuple(
        str(item["object_id"])
        for item in current_location.interaction_points
        if item.get("object_id")
    )

    try:
        return ResidentPerception(
            world_version=world.world_version,
            resident_id=resident.agent_id,
            day=world.current_day,
            minute=world.current_time_minutes,
            current_location_id=resident.current_location_id,
            current_schedule_state_id=resident.schedule_state,
            current_activity=resident.current_activity,
            current_goal=resident.current_goal,
            schedule=ScheduleDirective(
                state_id=schedule.state_id,
                location_id=schedule.location_id,
                activity=_localized(schedule.activity, "en"),
                goal=_localized(schedule.goal, "en"),
            ),
            participant_present=(
                world.participant_location_id == resident.current_location_id
            ),
            visible_resident_ids=visible_resident_ids,
            visible_object_ids=visible_object_ids,
        )
    except ResidentDecisionError as exc:
        raise ResidentRuntimeError(str(exc), 409) from exc


def retrieve_resident_decision_memories(
    db: DBSession,
    *,
    session_id: int,
    perception: ResidentPerception,
    limit: int = 5,
) -> list[WorldMemory]:
    """Retrieve ordinary story memories eligible for this resident decision."""

    related_agent_ids = tuple(
        sorted({perception.resident_id, *perception.visible_resident_ids})
    )
    return retrieve_memories(
        db,
        MemoryQuery(
            session_id=session_id,
            owner_agent_id=perception.resident_id,
            current_day=perception.day,
            current_time_minutes=perception.minute,
            location_id=perception.current_location_id,
            related_agent_ids=related_agent_ids,
            limit=limit,
        ),
    )


def build_authoritative_candidates(
    perception: ResidentPerception,
) -> tuple[CandidateIntent, ...]:
    """Return the stable server-owned candidate list for M2-A."""

    try:
        return schedule_driven_candidates(perception)
    except ResidentDecisionError as exc:
        raise ResidentRuntimeError(str(exc), 409) from exc


def select_and_validate_resident_decision(
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
    perception: ResidentPerception,
    candidates: Sequence[CandidateIntent],
) -> tuple[ResidentDecision, CandidateIntent]:
    """Select a deterministic decision and revalidate it against world state."""

    if world.world_version != spec.world_version:
        raise ResidentRuntimeError("World version changed during resident decision.", 409)
    if perception.world_version != spec.world_version:
        raise ResidentRuntimeError(
            "Resident perception does not match the bound world version.",
            409,
        )
    if resident.session_id != world.session_id:
        raise ResidentRuntimeError("Resident state belongs to another session.", 409)
    if resident.agent_id not in spec.residents:
        raise ResidentRuntimeError(
            f"Resident {resident.agent_id} is not in world {spec.world_version}.",
            409,
        )

    schedule = _resolve_schedule(
        spec,
        resident.agent_id,
        world.current_day,
        world.current_time_minutes,
    )
    if schedule.state_id != perception.schedule.state_id:
        raise ResidentRuntimeError("Schedule changed during resident decision.", 409)

    policy = ScheduleDrivenPolicy()
    try:
        decision = policy.decide_now(perception, candidates)
        selected = validate_resident_decision(decision, candidates)
    except ResidentDecisionError as exc:
        raise ResidentRuntimeError(str(exc), 409) from exc

    if selected.intent_type not in {"relocate", "continue_schedule", "wait"}:
        raise ResidentRuntimeError(
            f"Unsupported resident intent type: {selected.intent_type}.",
            409,
        )
    if selected.schedule_state_id != schedule.state_id:
        raise ResidentRuntimeError(
            "Resident intent does not match the current schedule state.",
            409,
        )
    if selected.target_location_id is not None and (
        selected.target_location_id not in spec.locations
    ):
        raise ResidentRuntimeError("Resident intent targets an unknown location.", 409)

    if selected.intent_type == "relocate":
        if selected.target_location_id != schedule.location_id:
            raise ResidentRuntimeError(
                "Resident relocation target does not match the schedule.",
                409,
            )
        if not can_travel(
            spec,
            resident.current_location_id,
            selected.target_location_id,
        ):
            raise ResidentRuntimeError(
                (
                    "Resident schedule requires a non-adjacent move from "
                    f"{resident.current_location_id} to {selected.target_location_id}."
                ),
                409,
            )
    elif selected.intent_type == "continue_schedule":
        if (
            resident.current_location_id != schedule.location_id
            or selected.target_location_id != resident.current_location_id
        ):
            raise ResidentRuntimeError(
                "Resident continue_schedule target is not the current location.",
                409,
            )
    elif selected.intent_type == "wait":
        if selected.target_location_id != resident.current_location_id:
            raise ResidentRuntimeError(
                "Resident wait target is not the current location.",
                409,
            )

    return decision, selected


def _candidate_payload(candidate: CandidateIntent) -> dict[str, Any]:
    return {
        "intent_id": candidate.intent_id,
        "intent_type": candidate.intent_type,
        "priority": candidate.priority,
        "proposed_by": candidate.proposed_by,
        "schedule_state_id": candidate.schedule_state_id,
        "target_location_id": candidate.target_location_id,
        "target_resident_id": candidate.target_resident_id,
        "target_object_id": candidate.target_object_id,
        "weight": candidate.weight,
        "reason_tags": list(candidate.reason_tags),
    }


def _resident_action_type(intent_type: str) -> str:
    mapping = {
        "relocate": "resident_relocate",
        "continue_schedule": "resident_continue_schedule",
        "wait": "resident_wait",
    }
    try:
        return mapping[intent_type]
    except KeyError as exc:
        raise ResidentRuntimeError(
            f"Unsupported resident intent type: {intent_type}.",
            409,
        ) from exc


def _resident_action_idempotency_key(
    *,
    world_version: str,
    day: int,
    minute: int,
    agent_id: int,
    schedule_state_id: str,
    intent_type: str,
) -> str:
    raw = (
        "resident:"
        f"{world_version}:{day}:{minute}:{agent_id}:{schedule_state_id}:{intent_type}"
    )
    if len(raw) <= 120:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"resident:{digest}"


def _decision_audit_payload(
    *,
    spec: WorldSpec,
    world: WorldState,
    perception: ResidentPerception,
    candidates: Sequence[CandidateIntent],
    decision: ResidentDecision,
    selected: CandidateIntent,
    memories: Sequence[WorldMemory],
    trigger_type: str,
) -> dict[str, Any]:
    return {
        "schema_version": RESIDENT_DECISION_AUDIT_SCHEMA_VERSION,
        "trigger_type": trigger_type,
        "considered_intent_ids": list(decision.considered_intent_ids),
        "candidate_intents": [_candidate_payload(candidate) for candidate in candidates],
        "selected_intent": _candidate_payload(selected),
        "recalled_memory_ids": [memory.id for memory in memories],
        "world_version": spec.world_version,
        "scenario_pack_version": spec.scenario_pack_version,
        "day": world.current_day,
        "time_minutes": world.current_time_minutes,
        "resident_id": perception.resident_id,
        "current_schedule_state_id": perception.current_schedule_state_id,
        "schedule_state_id": selected.schedule_state_id,
        "validation_status": "applied",
    }


def _state_json_for_schedule(
    resident: CharacterState,
    world: WorldState,
) -> str:
    state = _json_loads(resident.state_json)
    state.setdefault("schema_version", "resident-state-v1")
    state.setdefault("flags", {})
    state["last_schedule_day"] = world.current_day
    state.pop("autonomy_schedule_override_state", None)
    return _json_dumps(state)


def _end_resident_location_conversations(
    db: DBSession,
    *,
    session_id: int,
    agent_id: int,
    location_id: str,
) -> None:
    conversations = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.agent_id == agent_id,
            WorldConversation.location_id == location_id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .all()
    )
    for conversation in conversations:
        conversation.status = "ended"
        conversation.updated_at = utc_now()


def _expected_action_values(
    *,
    world: WorldState,
    resident: CharacterState,
    decision: ResidentDecision,
    selected: CandidateIntent,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "actor_type": "resident",
        "actor_agent_id": resident.agent_id,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "decision_reason_code": decision.reason_code,
        "action_type": _resident_action_type(selected.intent_type),
        "target_location_id": selected.target_location_id,
        "target_agent_id": selected.target_resident_id,
        "target_object_id": selected.target_object_id,
        "scenario_instance_id": None,
        "response_text": "",
        "response_latency_ms": None,
        "language": "en",
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "metadata": metadata,
    }


def _resident_action_matches(
    action: WorldAction,
    expected: dict[str, Any],
) -> bool:
    return (
        action.actor_type == expected["actor_type"]
        and action.actor_agent_id == expected["actor_agent_id"]
        and action.policy_id == expected["policy_id"]
        and action.policy_version == expected["policy_version"]
        and action.decision_reason_code == expected["decision_reason_code"]
        and action.action_type == expected["action_type"]
        and action.target_location_id == expected["target_location_id"]
        and action.target_agent_id == expected["target_agent_id"]
        and action.target_object_id == expected["target_object_id"]
        and action.scenario_instance_id == expected["scenario_instance_id"]
        and action.response_text == expected["response_text"]
        and action.response_latency_ms == expected["response_latency_ms"]
        and action.language == expected["language"]
        and action.world_day == expected["world_day"]
        and action.world_time_minutes == expected["world_time_minutes"]
        and _json_loads(action.metadata_json) == expected["metadata"]
    )


def apply_resident_decision(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
    perception: ResidentPerception,
    candidates: Sequence[CandidateIntent],
    decision: ResidentDecision,
    selected: CandidateIntent,
    memories: Sequence[WorldMemory],
    trigger_type: str,
) -> WorldAction | None:
    """Apply a validated resident decision and persist its audit action."""

    schedule = _resolve_schedule(
        spec,
        resident.agent_id,
        world.current_day,
        world.current_time_minutes,
    )
    action_type = _resident_action_type(selected.intent_type)
    schedule_activity = _localized(schedule.activity, "en")
    schedule_goal = _localized(schedule.goal, "en")
    needs_state_update = not _resident_matches_schedule(resident, schedule)
    should_record = needs_state_update or selected.intent_type == "wait"
    if not should_record:
        return None

    metadata = {
        "resident_decision": _decision_audit_payload(
            spec=spec,
            world=world,
            perception=perception,
            candidates=candidates,
            decision=decision,
            selected=selected,
            memories=memories,
            trigger_type=trigger_type,
        )
    }
    idempotency_key = _resident_action_idempotency_key(
        world_version=spec.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        agent_id=resident.agent_id,
        schedule_state_id=schedule.state_id,
        intent_type=selected.intent_type,
    )
    expected = _expected_action_values(
        world=world,
        resident=resident,
        decision=decision,
        selected=selected,
        metadata=metadata,
    )
    existing = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == world.session_id,
            WorldAction.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if not _resident_action_matches(existing, expected):
            raise ResidentRuntimeError(
                "Resident action idempotency key has conflicting audit payload.",
                409,
            )
        if needs_state_update:
            _apply_schedule_state(
                db,
                world=world,
                resident=resident,
                selected=selected,
                schedule=schedule,
                schedule_activity=schedule_activity,
                schedule_goal=schedule_goal,
            )
        _upsert_schedule_intent(
            db,
            world=world,
            resident=resident,
            schedule=schedule,
            source_action_id=existing.id,
        )
        return existing

    if needs_state_update:
        _apply_schedule_state(
            db,
            world=world,
            resident=resident,
            selected=selected,
            schedule=schedule,
            schedule_activity=schedule_activity,
            schedule_goal=schedule_goal,
        )

    action = WorldAction(
        session_id=world.session_id,
        idempotency_key=idempotency_key,
        actor_type="resident",
        actor_agent_id=resident.agent_id,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        decision_reason_code=decision.reason_code,
        action_type=action_type,
        target_location_id=selected.target_location_id,
        target_agent_id=selected.target_resident_id,
        target_object_id=selected.target_object_id,
        scenario_instance_id=None,
        response_text="",
        response_latency_ms=None,
        language="en",
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps(metadata),
    )
    db.add(action)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ResidentRuntimeError(
            "Resident action idempotency key was reused concurrently.",
            409,
        ) from exc
    _upsert_schedule_intent(
        db,
        world=world,
        resident=resident,
        schedule=schedule,
        source_action_id=action.id,
    )
    return action


def _upsert_schedule_intent(
    db: DBSession,
    *,
    world: WorldState,
    resident: CharacterState,
    schedule: ScheduleBlock,
    source_action_id: int | None,
) -> ResidentIntentState:
    intent = (
        db.query(ResidentIntentState)
        .filter(
            ResidentIntentState.session_id == world.session_id,
            ResidentIntentState.agent_id == resident.agent_id,
        )
        .first()
    )
    if intent is None:
        intent = ResidentIntentState(
            session_id=world.session_id,
            agent_id=resident.agent_id,
            intent_type="follow_schedule",
            status="active",
            started_day=world.current_day,
            started_time_minutes=world.current_time_minutes,
            due_day=world.current_day,
            due_time_minutes=schedule.end_minute,
            policy_id=RESIDENT_POLICY_ID,
            policy_version=RESIDENT_POLICY_VERSION,
        )
        db.add(intent)
    intent.intent_type = "follow_schedule"
    intent.status = "active"
    intent.target_location_id = schedule.location_id
    intent.target_agent_id = None
    intent.target_object_id = None
    intent.started_day = world.current_day
    intent.started_time_minutes = world.current_time_minutes
    intent.due_day = world.current_day
    intent.due_time_minutes = schedule.end_minute
    intent.source_action_id = source_action_id
    intent.policy_id = RESIDENT_POLICY_ID
    intent.policy_version = RESIDENT_POLICY_VERSION
    intent.summary_json = _json_dumps(
        {
            "en": _localized(schedule.activity, "en"),
            "zh-CN": _localized(schedule.activity, "zh-CN"),
        }
    )
    intent.metadata_json = _json_dumps(
        {"schedule_state_id": schedule.state_id, "source": "schedule"}
    )
    intent.updated_at = utc_now()
    db.flush()
    return intent


def _apply_schedule_state(
    db: DBSession,
    *,
    world: WorldState,
    resident: CharacterState,
    selected: CandidateIntent,
    schedule: ScheduleBlock,
    schedule_activity: str,
    schedule_goal: str,
) -> None:
    previous_location_id = resident.current_location_id
    if selected.intent_type == "relocate":
        if selected.target_location_id is None:
            raise ResidentRuntimeError("Resident relocation target is missing.", 409)
        resident.current_location_id = selected.target_location_id
    elif selected.intent_type == "continue_schedule":
        resident.current_location_id = schedule.location_id
    elif selected.intent_type == "wait":
        return

    resident.current_activity = schedule_activity
    resident.current_goal = schedule_goal
    resident.schedule_state = schedule.state_id
    resident.state_json = _state_json_for_schedule(resident, world)
    resident.updated_at = utc_now()
    if previous_location_id != resident.current_location_id:
        _end_resident_location_conversations(
            db,
            session_id=world.session_id,
            agent_id=resident.agent_id,
            location_id=previous_location_id,
        )
        end_ambient_conversations_for_resident(
            db,
            world=world,
            agent_id=resident.agent_id,
            location_id=previous_location_id,
            reason_code="resident_relocated",
        )


def _recover_stale_autonomy_schedule_override(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
    schedule: ScheduleBlock,
) -> WorldAction | None:
    """Return an old temporary visit to its legal schedule anchor.

    Earlier autonomy pulses could leave a resident one edge away when an
    inclusive schedule block ended. Recover through that prior block instead
    of allowing a non-adjacent jump to the next scheduled location. This also
    makes Sessions persisted before the guard was added recoverable.
    """

    state = _json_loads(resident.state_json)
    override_state_id = state.get("autonomy_schedule_override_state")
    if not isinstance(override_state_id, str) or override_state_id == schedule.state_id:
        return None

    prior_blocks = tuple(
        block
        for block in spec.residents[resident.agent_id].schedule
        if block.state_id == override_state_id
    )
    if len(prior_blocks) != 1:
        raise ResidentRuntimeError(
            "Resident autonomy override references an unknown schedule state.",
            409,
        )
    prior_schedule = prior_blocks[0]
    previous_location_id = resident.current_location_id
    if previous_location_id != prior_schedule.location_id and not can_travel(
        spec,
        previous_location_id,
        prior_schedule.location_id,
    ):
        raise ResidentRuntimeError(
            (
                "Resident autonomy recovery requires a non-adjacent move from "
                f"{previous_location_id} to {prior_schedule.location_id}."
            ),
            409,
        )

    metadata = {
        "resident_autonomy": {
            "schema_version": AUTONOMY_RECOVERY_AUDIT_SCHEMA_VERSION,
            "policy_id": AUTONOMY_RECOVERY_POLICY_ID,
            "policy_version": AUTONOMY_RECOVERY_POLICY_VERSION,
            "reason_code": "schedule_boundary_recovery",
            "world_version": spec.world_version,
            "day": world.current_day,
            "time_minutes": world.current_time_minutes,
            "resident_id": resident.agent_id,
            "from_location_id": previous_location_id,
            "target_location_id": prior_schedule.location_id,
            "previous_schedule_state_id": override_state_id,
            "current_schedule_state_id": schedule.state_id,
            "validation_status": "applied",
        }
    }
    idempotency_key = _resident_action_idempotency_key(
        world_version=spec.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        agent_id=resident.agent_id,
        schedule_state_id=f"{override_state_id}->{schedule.state_id}",
        intent_type="end_intent",
    )
    action = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == world.session_id,
            WorldAction.idempotency_key == idempotency_key,
        )
        .first()
    )
    if action is None:
        action = WorldAction(
            session_id=world.session_id,
            idempotency_key=idempotency_key,
            actor_type="resident",
            actor_agent_id=resident.agent_id,
            policy_id=AUTONOMY_RECOVERY_POLICY_ID,
            policy_version=AUTONOMY_RECOVERY_POLICY_VERSION,
            decision_reason_code="schedule_boundary_recovery",
            action_type="resident_end_intent",
            target_location_id=prior_schedule.location_id,
            target_agent_id=None,
            target_object_id=None,
            scenario_instance_id=None,
            response_text="",
            response_latency_ms=None,
            language="en",
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json=_json_dumps(metadata),
        )
        db.add(action)
        try:
            db.flush()
        except IntegrityError as exc:
            raise ResidentRuntimeError(
                "Resident autonomy recovery was applied concurrently.",
                409,
            ) from exc

    resident.current_location_id = prior_schedule.location_id
    state.pop("autonomy_schedule_override_state", None)
    resident.state_json = _json_dumps(state)
    resident.updated_at = utc_now()
    if previous_location_id != resident.current_location_id:
        _end_resident_location_conversations(
            db,
            session_id=world.session_id,
            agent_id=resident.agent_id,
            location_id=previous_location_id,
        )
        end_ambient_conversations_for_resident(
            db,
            world=world,
            agent_id=resident.agent_id,
            location_id=previous_location_id,
            reason_code="resident_relocated",
        )
    return action


def run_resident_tick(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    trigger_type: str = "clock_transition",
) -> list[WorldAction]:
    """Run one deterministic resident tick for all residents in agent order."""

    actions: list[WorldAction] = []
    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == world.session_id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    for resident in residents:
        if spec.world_version.startswith("chaoxi-holiday-"):
            from services.holiday_routine_service import sync_routine
            sync_routine(db, world=world, spec=spec, resident=resident)
            continue
        if spec.content_schema_version == "content-pack-v5":
            from services.plan_service import resident_is_in_active_plan

            # A present resident's explicit plan takes precedence over a generic
            # schedule tick. This retains the actual position; it never moves an
            # absent/late resident into the activity.
            if resident_is_in_active_plan(db, session_id=world.session_id, agent_id=resident.agent_id, location_id=resident.current_location_id):
                continue
        if resident.agent_id not in spec.residents:
            raise ResidentRuntimeError(
                f"Resident {resident.agent_id} is not in world {spec.world_version}.",
                409,
            )
        schedule = _resolve_schedule(
            spec,
            resident.agent_id,
            world.current_day,
            world.current_time_minutes,
        )
        recovered_action = _recover_stale_autonomy_schedule_override(
            db,
            spec=spec,
            world=world,
            resident=resident,
            schedule=schedule,
        )
        if recovered_action is not None:
            actions.append(recovered_action)
        allow_location_override = (
            schedule.state_id
            in spec.residents[resident.agent_id].autonomy.free_time_state_ids
        )
        if _resident_matches_schedule(
            resident,
            schedule,
            allow_location_override=allow_location_override,
        ):
            continue

        perception = build_resident_perception(
            db,
            spec=spec,
            world=world,
            resident=resident,
        )
        memories = retrieve_resident_decision_memories(
            db,
            session_id=world.session_id,
            perception=perception,
        )
        candidates = build_authoritative_candidates(perception)
        decision, selected = select_and_validate_resident_decision(
            spec=spec,
            world=world,
            resident=resident,
            perception=perception,
            candidates=candidates,
        )
        action = apply_resident_decision(
            db,
            spec=spec,
            world=world,
            resident=resident,
            perception=perception,
            candidates=candidates,
            decision=decision,
            selected=selected,
            memories=memories,
            trigger_type=trigger_type,
        )
        if action is not None:
            actions.append(action)
    return actions
