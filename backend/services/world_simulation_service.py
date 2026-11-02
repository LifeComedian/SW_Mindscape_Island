"""World clock pulses and foreground pause controls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

import schemas
from models import (
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldConversation,
    WorldEventInstance,
    ResidentIntentState,
    WorldSimulationPulse,
    WorldState,
)
from services.world_service import (
    WorldStateError,
    advance_world_clock,
    build_world_payload,
    initialize_world,
    session_write_lock,
    world_has_ended,
)
from services.resident_autonomy_service import (
    MAX_AUTONOMY_ACTIONS_PER_PULSE,
    MAX_RESIDENT_ACTIONS_PER_PULSE,
    run_resident_autonomy_pulse,
)
from services.interaction_prompt_service import (
    close_invalid_interaction_prompts,
    create_prompt_from_greeting_action,
)
from services.resident_social_service import process_resident_social_tick
from study.models import StudyWorldBoundary
from world.registry import get_world_spec


from content.experience_next import enabled as next_enabled
PULSE_MINUTES = 10 if next_enabled() else 5
PULSE_MAX_DUE_EVENTS = 5
PULSE_INTERVAL_HINT_MS = 10_000
PULSE_MIN_REAL_INTERVAL = timedelta(seconds=8)
PULSE_POLICY_ID = "foreground-pulse"
PULSE_POLICY_VERSION = "v1"
SIMULATION_CONTROL_POLICY_ID = "participant-simulation-control"
SIMULATION_CONTROL_POLICY_VERSION = "v1"


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda item: dict(item) if isinstance(item, Mapping) else list(item),
    )


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _request_fingerprint(request: schemas.WorldPulseRequest) -> dict[str, Any]:
    return {
        "expected_revision": request.expected_revision,
        "source": request.source,
        "language": request.language,
    }


def _pulse_metadata(request: schemas.WorldPulseRequest) -> dict[str, Any]:
    return {
        "request": _request_fingerprint(request),
        "server_limits": {
            "pulse_minutes": PULSE_MINUTES,
            "max_due_events": PULSE_MAX_DUE_EVENTS,
            "max_resident_actions": MAX_RESIDENT_ACTIONS_PER_PULSE,
            "max_autonomy_actions": MAX_AUTONOMY_ACTIONS_PER_PULSE,
        },
    }


def _simulation_mode(world: WorldState) -> str:
    state = _json_loads(world.state_json, {})
    if not isinstance(state, dict):
        return "running"
    simulation = state.get("simulation", {})
    if isinstance(simulation, dict) and simulation.get("mode") == "paused":
        return "paused"
    return "running"


def _serialize_pulse(pulse: WorldSimulationPulse) -> dict[str, Any]:
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


def _response(
    *,
    status: str,
    pulse: WorldSimulationPulse,
    world: dict[str, Any],
    original_status: str | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "reason_code": "duplicate_request" if status == "duplicate" else pulse.reason_code,
        "pulse": _serialize_pulse(pulse),
        "world": world,
    }
    if original_status is not None:
        payload["original_status"] = original_status
    metadata = _json_loads(pulse.metadata_json, {})
    if isinstance(metadata, dict) and isinstance(metadata.get("m7e_emergence"), dict):
        payload["emergence"] = metadata["m7e_emergence"]
    return payload


def _duplicate_response(
    pulse: WorldSimulationPulse,
    request: schemas.WorldPulseRequest,
) -> dict[str, Any]:
    metadata = _json_loads(pulse.metadata_json, {})
    if not isinstance(metadata, dict) or metadata.get("request") != _request_fingerprint(request):
        raise WorldStateError(
            "The pulse idempotency key was already used with a different payload.",
            409,
        )
    snapshot = _json_loads(pulse.result_snapshot_json, {})
    if not isinstance(snapshot, dict) or not snapshot:
        raise WorldStateError("The stored pulse response is unavailable.", 409)
    return _response(
        status="duplicate",
        pulse=pulse,
        world=snapshot,
        original_status=pulse.status,
    )


def _blocking_reason(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
) -> str | None:
    from services.interaction_time_service import expire_focus, focus_state
    expire_focus(db, world)
    if session.status != "active":
        return "session_finished"
    if world_has_ended(world):
        return "world_ended"
    from services.holiday_calendar_v6 import pending
    if pending(world):
        return "day_transition"
    if _simulation_mode(world) == "paused":
        return "participant_paused"
    if focus_state(world):
        return "activity_discussion"
    if (
        db.query(ScenarioInstance.id)
        .filter(
            ScenarioInstance.session_id == session.id,
            ScenarioInstance.status == "active",
            ScenarioInstance.location_id == world.participant_location_id,
        )
        .first()
        is not None
    ):
        return "active_scenario"
    if (
        db.query(WorldEventInstance.id)
        .filter(
            WorldEventInstance.session_id == session.id,
            WorldEventInstance.status == "active",
            WorldEventInstance.location_id == world.participant_location_id,
        )
        .first()
        is not None
    ):
        return "active_event"
    if (
        db.query(WorldConversation.id)
        .filter(
            WorldConversation.session_id == session.id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .first()
        is not None
    ):
        return "active_conversation"
    return None


def _next_sequence(db: DBSession, session_id: int) -> int:
    current = (
        db.query(func.max(WorldSimulationPulse.sequence))
        .filter(WorldSimulationPulse.session_id == session_id)
        .scalar()
    )
    return int(current or 0) + 1


def _record_rejected_pulse(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    request: schemas.WorldPulseRequest,
    status: str,
    reason_code: str,
    now: datetime,
) -> dict[str, Any]:
    pulse = WorldSimulationPulse(
        session_id=session.id,
        sequence=_next_sequence(db, session.id),
        idempotency_key=request.idempotency_key,
        source=request.source,
        requested_revision=request.expected_revision,
        accepted_revision=None,
        status=status,
        reason_code=reason_code,
        before_day=world.current_day,
        before_time_minutes=world.current_time_minutes,
        after_day=world.current_day,
        after_time_minutes=world.current_time_minutes,
        action_ids_json="[]",
        result_snapshot_json="{}",
        policy_id=PULSE_POLICY_ID,
        policy_version=PULSE_POLICY_VERSION,
        metadata_json=_json_dumps(_pulse_metadata(request)),
        created_at=now,
        updated_at=now,
    )
    db.add(pulse)
    db.flush()
    snapshot = build_world_payload(db, session, request.language)
    pulse.result_snapshot_json = _json_dumps(snapshot)
    db.commit()
    db.refresh(pulse)
    return _response(status=status, pulse=pulse, world=snapshot)


def process_world_pulse(
    db: DBSession,
    *,
    session_id: int,
    request: schemas.WorldPulseRequest,
) -> dict[str, Any]:
    """Process one server-bounded foreground pulse under a session lock."""

    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise WorldStateError("Session not found.", 404)
        if session.status != "active":
            frozen_study_world = (
                db.query(StudyWorldBoundary.id)
                .filter(
                    StudyWorldBoundary.world_session_id == session_id,
                    StudyWorldBoundary.frozen_at.is_not(None),
                )
                .first()
                is not None
            )
            if frozen_study_world:
                raise WorldStateError(f"Session is {session.status}.", 409)

        duplicate = (
            db.query(WorldSimulationPulse)
            .filter(
                WorldSimulationPulse.session_id == session_id,
                WorldSimulationPulse.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if duplicate is not None:
            return _duplicate_response(duplicate, request)

        world = initialize_world(db, session)
        snapshot = build_world_payload(db, session, request.language)
        now = utc_now()
        current_revision = int(snapshot["revision"])
        if request.expected_revision != current_revision:
            return _record_rejected_pulse(
                db,
                session=session,
                world=world,
                request=request,
                status="stale_revision",
                reason_code="expected_revision_mismatch",
                now=now,
            )

        blocked_reason = _blocking_reason(db, session=session, world=world)
        if blocked_reason is not None:
            status = (
                "paused"
                if blocked_reason == "participant_paused"
                else "finished"
                if blocked_reason in {"session_finished", "world_ended"}
                else "blocked"
            )
            return _record_rejected_pulse(
                db,
                session=session,
                world=world,
                request=request,
                status=status,
                reason_code=blocked_reason,
                now=now,
            )

        last_accepted = (
            db.query(WorldSimulationPulse)
            .filter(
                WorldSimulationPulse.session_id == session_id,
                WorldSimulationPulse.status == "accepted",
            )
            .order_by(WorldSimulationPulse.created_at.desc(), WorldSimulationPulse.id.desc())
            .first()
        )
        if (
            last_accepted is not None
            and last_accepted.created_at is not None
            and now - last_accepted.created_at < PULSE_MIN_REAL_INTERVAL
        ):
            return _record_rejected_pulse(
                db,
                session=session,
                world=world,
                request=request,
                status="rate_limited",
                reason_code="pulse_interval_not_elapsed",
                now=now,
            )

        pulse = WorldSimulationPulse(
            session_id=session.id,
            sequence=_next_sequence(db, session.id),
            idempotency_key=request.idempotency_key,
            source=request.source,
            requested_revision=request.expected_revision,
            accepted_revision=None,
            status="processing",
            reason_code="processing",
            before_day=world.current_day,
            before_time_minutes=world.current_time_minutes,
            after_day=world.current_day,
            after_time_minutes=world.current_time_minutes,
            action_ids_json="[]",
            result_snapshot_json="{}",
            policy_id=PULSE_POLICY_ID,
            policy_version=PULSE_POLICY_VERSION,
            metadata_json=_json_dumps(_pulse_metadata(request)),
            created_at=now,
            updated_at=now,
        )
        db.add(pulse)
        db.flush()

        actions = advance_world_clock(
            db,
            world,
            PULSE_MINUTES,
            max_due_events=PULSE_MAX_DUE_EVENTS,
        )
        close_invalid_interaction_prompts(db, session=session, world=world)
        spec = get_world_spec(world.world_version)
        autonomy_actions = run_resident_autonomy_pulse(
            db,
            spec=spec,
            session=session,
            world=world,
            pulse=pulse,
            schedule_action_count=len(actions),
        )
        actions.extend(autonomy_actions)
        action_ids = [action.id for action in actions]
        if action_ids:
            for intent in (
                db.query(ResidentIntentState)
                .filter(
                    ResidentIntentState.session_id == session.id,
                    ResidentIntentState.source_action_id.in_(action_ids),
                )
                .all()
            ):
                intent.source_pulse_id = pulse.id
                intent.updated_at = utc_now()
        pulse.status = "accepted"
        pulse.reason_code = "pulse_advanced"
        pulse.after_day = world.current_day
        pulse.after_time_minutes = world.current_time_minutes
        pulse.action_ids_json = _json_dumps(action_ids)
        pulse.updated_at = utc_now()
        db.flush()

        snapshot = build_world_payload(db, session, request.language)
        pulse.accepted_revision = int(snapshot["revision"])
        db.flush()
        snapshot = build_world_payload(db, session, request.language)
        pulse.result_snapshot_json = _json_dumps(snapshot)
        db.commit()
        db.refresh(pulse)
        return _response(status="accepted", pulse=pulse, world=snapshot)


async def finalize_world_pulse_interactions(
    db: DBSession,
    *,
    session_id: int,
    pulse_id: int,
    language: str,
    agent_service: Any,
    response_status: str = "accepted",
) -> dict[str, Any]:
    """Run optional dialogue generation outside transactions, then finalize the pulse."""

    db.rollback()
    pulse = (
        db.query(WorldSimulationPulse)
        .filter(
            WorldSimulationPulse.id == pulse_id,
            WorldSimulationPulse.session_id == session_id,
        )
        .first()
    )
    if pulse is None:
        raise WorldStateError("Simulation pulse not found.", 404)
    metadata = _json_loads(pulse.metadata_json, {})
    if isinstance(metadata, dict) and metadata.get("m3c_interactions_finalized") is True:
        session = db.query(UserSession).filter(UserSession.id == session_id).one()
        snapshot = _json_loads(pulse.result_snapshot_json, {})
        if not isinstance(snapshot, dict) or not snapshot:
            snapshot = build_world_payload(db, session, language)
        return _response(
            status=response_status,
            pulse=pulse,
            world=snapshot,
            original_status=("accepted" if response_status == "duplicate" else None),
        )

    trigger_action_ids = [
        int(value)
        for value in _json_loads(pulse.action_ids_json, [])
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    ]
    trigger_actions = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.id.in_(trigger_action_ids),
        )
        .order_by(WorldAction.id.asc())
        .all()
        if trigger_action_ids
        else []
    )
    social_trigger_ids = []
    for action in trigger_actions:
        action_metadata = _json_loads(action.metadata_json, {})
        autonomy = (
            action_metadata.get("resident_autonomy", {})
            if isinstance(action_metadata, dict)
            else {}
        )
        if isinstance(autonomy, dict) and autonomy.get("source_pulse_id") == pulse.id:
            social_trigger_ids.append(action.id)
    db.rollback()
    social_action_ids: list[int] = []
    from services.interaction_time_service import policy_for
    bound_world = db.query(WorldState).filter_by(session_id=session_id).one()
    if policy_for(bound_world):
        social_trigger_ids = []
    db.rollback()
    for trigger_action_id in social_trigger_ids:
        action = await process_resident_social_tick(
            db,
            session_id=session_id,
            trigger_action_id=trigger_action_id,
            language=language,
            agent_service=agent_service,
        )
        if action is not None:
            social_action_ids.append(action.id)

    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
        pulse = (
            db.query(WorldSimulationPulse)
            .filter(
                WorldSimulationPulse.id == pulse_id,
                WorldSimulationPulse.session_id == session_id,
            )
            .first()
        )
        if session is None or world is None or pulse is None:
            raise WorldStateError("The pulse world state is unavailable.", 409)
        metadata = _json_loads(pulse.metadata_json, {})
        if not isinstance(metadata, dict):
            metadata = {}
        # Finalize emergence before capturing the authoritative pulse snapshot.
        # Lazy import keeps the world/plan/director service dependency acyclic.
        from services.emergence_director_service import (
            EmergenceDirectorError, auto_emergence_enabled, evaluate_emergence, reconcile_emergent_events,
        )
        from services.phone_plan_service import PhonePlanError
        from services.plan_service import PlanServiceError

        bound_spec = get_world_spec(world.world_version)
        if bound_spec.content_schema_version == "content-pack-v5" and not world_has_ended(world):
            # Existing stages expire even when no recipe opts into automatic
            # candidate creation and the participant never opens a stage card.
            reconcile_emergent_events(db, session_id=session_id)
            world = db.query(WorldState).filter_by(session_id=session_id).one()
            pulse = db.query(WorldSimulationPulse).filter_by(id=pulse_id).one()

        if not world_has_ended(world) and auto_emergence_enabled(db, session_id=session_id):
            try:
                emergence = evaluate_emergence(
                    db, session_id=session_id,
                    request={
                        "idempotency_key": f"pulse-emergence:{pulse_id}",
                        "source": "foreground_pulse", "source_pulse_id": pulse_id,
                        "expected_day": world.current_day,
                        "expected_time_minutes": world.current_time_minutes,
                        "language": language,
                    },
                )
                metadata["m7e_emergence"] = {
                    "evaluation_id": emergence["evaluation_id"],
                    "candidate_count": emergence["candidate_count"],
                    "selected_count": emergence["selected_count"],
                }
            except (EmergenceDirectorError, PhonePlanError, PlanServiceError) as exc:
                metadata["m7e_emergence"] = {"status": "blocked", "reason_code": exc.reason_code}
            db.rollback()
            session = db.query(UserSession).filter(UserSession.id == session_id).one()
            world = db.query(WorldState).filter(WorldState.session_id == session_id).one()
            pulse = db.query(WorldSimulationPulse).filter(WorldSimulationPulse.id == pulse_id).one()
        close_invalid_interaction_prompts(db, session=session, world=world)
        actions = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.id.in_(trigger_action_ids),
            )
            .order_by(WorldAction.id.asc())
            .all()
            if trigger_action_ids
            else []
        )
        prompts = [
            prompt
            for action in actions
            if action.action_type == "resident_greet_participant_intent"
            for prompt in [
                create_prompt_from_greeting_action(
                    db,
                    session=session,
                    world=world,
                    pulse=pulse,
                    action=action,
                    language=language,
                )
            ]
            if prompt is not None
        ]
        combined_action_ids = list(
            dict.fromkeys([*trigger_action_ids, *social_action_ids])
        )
        pulse.action_ids_json = _json_dumps(combined_action_ids)
        metadata["m3c_interactions_finalized"] = True
        metadata["resident_social_action_ids"] = social_action_ids
        metadata["interaction_prompt_ids"] = [prompt.id for prompt in prompts]
        pulse.metadata_json = _json_dumps(metadata)
        pulse.updated_at = utc_now()
        db.flush()
        snapshot = build_world_payload(db, session, language)
        pulse.accepted_revision = int(snapshot["revision"])
        db.flush()
        snapshot = build_world_payload(db, session, language)
        pulse.result_snapshot_json = _json_dumps(snapshot)
        db.commit()
        db.refresh(pulse)
        return _response(
            status=response_status,
            pulse=pulse,
            world=snapshot,
            original_status=("accepted" if response_status == "duplicate" else None),
        )


def _control_request_payload(
    request: schemas.WorldSimulationControlRequest,
) -> dict[str, Any]:
    return {
        "mode": request.mode,
        "expected_revision": request.expected_revision,
        "language": request.language,
    }


def set_world_simulation_mode(
    db: DBSession,
    *,
    session_id: int,
    request: schemas.WorldSimulationControlRequest,
) -> dict[str, Any]:
    """Persist participant pause/resume state without ending the Session."""

    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise WorldStateError("Session not found.", 404)
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
            metadata = _json_loads(existing.metadata_json, {})
            if (
                existing.action_type not in {"simulation_pause", "simulation_resume"}
                or not isinstance(metadata, dict)
                or metadata.get("request") != _control_request_payload(request)
            ):
                raise WorldStateError(
                    "The idempotency key was already used with a different payload.",
                    409,
                )
            return {
                "status": "duplicate",
                "action_id": existing.id,
                "world": build_world_payload(db, session, request.language),
            }

        snapshot = build_world_payload(db, session, request.language)
        if request.expected_revision != int(snapshot["revision"]):
            raise WorldStateError("The world snapshot revision is stale.", 409)
        if session.status != "active":
            raise WorldStateError(f"Session is {session.status}.", 409)
        if world_has_ended(world):
            raise WorldStateError("The virtual world has reached its final time.", 409)

        state = _json_loads(world.state_json, {})
        if not isinstance(state, dict):
            state = {}
        before_mode = _simulation_mode(world)
        state["simulation"] = {
            "mode": request.mode,
            "updated_by": "participant",
        }
        world.state_json = _json_dumps(state)
        world.updated_at = utc_now()
        action = WorldAction(
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            actor_type="participant",
            actor_agent_id=None,
            policy_id=SIMULATION_CONTROL_POLICY_ID,
            policy_version=SIMULATION_CONTROL_POLICY_VERSION,
            decision_reason_code=(
                "participant_paused" if request.mode == "paused" else "participant_resumed"
            ),
            action_type=(
                "simulation_pause" if request.mode == "paused" else "simulation_resume"
            ),
            response_text="",
            language=request.language,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json=_json_dumps(
                {
                    "request": _control_request_payload(request),
                    "before_mode": before_mode,
                    "after_mode": request.mode,
                }
            ),
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return {
            "status": "updated" if before_mode != request.mode else "unchanged",
            "action_id": action.id,
            "world": build_world_payload(db, session, request.language),
        }
