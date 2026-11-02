"""Validate and commit participant and resident actions."""

from __future__ import annotations
from dataclasses import replace

from datetime import datetime
import hashlib
import json
from typing import Any, Callable, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    Session as UserSession,
    WorldAction,
    WorldAtomicActionExecution,
    WorldConversation,
    WorldState,
)
from services.world_service import (
    advance_world_clock,
    session_write_lock,
    world_has_ended,
)
from world.atomic_actions import (
    ATOMIC_ACTION_RUNTIME_VERSION,
    AtomicActionRegistry,
    AtomicActionRuntimeError,
    AtomicActionTarget,
    AtomicActorSnapshot,
    AtomicRuntimeContext,
)
from world.emergence_contracts import MODULAR_SYSTEMS_CONTRACT_VERSION
from world.registry import get_world_spec
from world.specs import WorldSpec


ATOMIC_STATE_SCHEMA_VERSION = "atomic-action-state-v1"


class AtomicActionServiceError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason_code = reason_code
        self.status_code = status_code


class AtomicActionInterrupted(RuntimeError):
    """Testable cancellation signal raised before the transaction commits."""


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_value(request: Any, name: str, default: Any = None) -> Any:
    if isinstance(request, Mapping):
        return request.get(name, default)
    return getattr(request, name, default)


def _request_payload(
    request: Any,
    *,
    actor_type: str,
    actor_agent_id: int | None,
) -> dict[str, Any]:
    return {
        "actor_type": actor_type,
        "actor_agent_id": actor_agent_id,
        "action_id": _request_value(request, "action_id"),
        "expected_revision": _request_value(request, "expected_revision"),
        "target_location_id": _request_value(request, "target_location_id"),
        "target_actor_type": _request_value(request, "target_actor_type"),
        "target_agent_id": _request_value(request, "target_agent_id"),
        "target_object_id": _request_value(request, "target_object_id"),
        "inputs": dict(_request_value(request, "inputs", {}) or {}),
        "language": _request_value(request, "language", "en"),
    }


def _request_hash(payload: Mapping[str, Any]) -> str:
    try:
        encoded = _json_dumps(dict(payload)).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AtomicActionServiceError(
            "Atomic action request must contain JSON-compatible inputs.",
            reason_code="unknown_reference",
            status_code=422,
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _world_and_spec(db: DBSession, session_id: int) -> tuple[WorldState, WorldSpec]:
    world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
    if world is None:
        raise AtomicActionServiceError(
            "World state not found.", reason_code="unknown_reference", status_code=404
        )
    try:
        spec = get_world_spec(world.world_version)
    except KeyError as exc:
        raise AtomicActionServiceError(
            "Bound world specification is unavailable.",
            reason_code="unknown_reference",
        ) from exc
    if spec.scenario_pack_version != world.scenario_pack_version:
        raise AtomicActionServiceError(
            "Bound world versions do not match.", reason_code="unknown_reference"
        )
    return world, spec


def _runtime_state(world: WorldState) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _json_loads(world.state_json, {})
    if not isinstance(root, dict):
        root = {}
    runtime = root.get("modular_runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    runtime.setdefault("schema_version", ATOMIC_STATE_SCHEMA_VERSION)
    runtime.setdefault("revision", 0)
    runtime.setdefault("object_states", {})
    runtime.setdefault("location_states", {})
    runtime.setdefault("actor_grants", {})
    runtime.setdefault("actor_states", {})
    runtime.setdefault("world_flags", {})
    root["modular_runtime"] = runtime
    return root, runtime


def _actor_snapshot(
    db: DBSession,
    *,
    world: WorldState,
    runtime: Mapping[str, Any],
    actor_type: str,
    actor_agent_id: int | None,
) -> AtomicActorSnapshot:
    if actor_type == "participant":
        if actor_agent_id is not None:
            raise AtomicActionServiceError(
                "Participant actions cannot carry an agent id.",
                reason_code="unknown_reference",
            )
        location_id = world.participant_location_id
        actor_key = "participant"
        active_conversation = (
            db.query(WorldConversation.id)
            .filter(
                WorldConversation.session_id == world.session_id,
                WorldConversation.status == "active",
                WorldConversation.conversation_kind == "participant_resident",
            )
            .first()
        )
    elif actor_type == "resident":
        if actor_agent_id is None:
            raise AtomicActionServiceError(
                "Resident actions require an agent id.",
                reason_code="unknown_reference",
            )
        resident = (
            db.query(CharacterState)
            .filter(
                CharacterState.session_id == world.session_id,
                CharacterState.agent_id == actor_agent_id,
            )
            .first()
        )
        if resident is None:
            raise AtomicActionServiceError(
                "Resident actor was not found.",
                reason_code="unknown_reference",
                status_code=404,
            )
        location_id = resident.current_location_id
        actor_key = f"resident:{actor_agent_id}"
        active_conversation = (
            db.query(WorldConversation.id)
            .filter(
                WorldConversation.session_id == world.session_id,
                WorldConversation.status == "active",
                WorldConversation.agent_id == actor_agent_id,
            )
            .first()
        )
    else:
        raise AtomicActionServiceError(
            "Actor type is unsupported.", reason_code="unknown_reference"
        )

    grants_root = runtime.get("actor_grants") or {}
    grants = grants_root.get(actor_key, {}) if isinstance(grants_root, Mapping) else {}
    states_root = runtime.get("actor_states") or {}
    actor_state = states_root.get(actor_key, {}) if isinstance(states_root, Mapping) else {}
    if not isinstance(grants, Mapping):
        grants = {}
    if not isinstance(actor_state, Mapping):
        actor_state = {}
    available = actor_state.get("availability", "available") == "available"
    available = available and active_conversation is None
    from services.scheduled_action_service import actor_busy
    available = available and not actor_busy(world, actor_key)
    return AtomicActorSnapshot(
        actor_type=actor_type,
        agent_id=actor_agent_id,
        location_id=location_id,
        available=available,
        permissions=frozenset(str(item) for item in grants.get("permissions", ())),
        capabilities=frozenset(str(item) for item in grants.get("capabilities", ())),
        state=dict(actor_state),
    )


def _runtime_context(
    db: DBSession,
    *,
    world: WorldState,
    spec: WorldSpec,
    runtime: Mapping[str, Any],
    actor: AtomicActorSnapshot,
    stage_authorized: bool = False,
) -> AtomicRuntimeContext:
    location = spec.locations.get(actor.location_id)
    if location is None:
        raise AtomicActionServiceError(
            "Actor location does not exist in the bound world.",
            reason_code="unknown_reference",
        )
    location_states = runtime.get("location_states") or {}
    location_state = (
        location_states.get(actor.location_id, {})
        if isinstance(location_states, Mapping)
        else {}
    )
    if not isinstance(location_state, Mapping):
        location_state = {}
    location_open = bool(location.opening_hours.get("always_open", False)) and (
        location_state.get("open", True) is True
    )
    co_located_residents = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == world.session_id,
            CharacterState.current_location_id == actor.location_id,
        )
        .all()
    )
    participant_present = world.participant_location_id == actor.location_id
    participant_count = len(co_located_residents) + (1 if participant_present else 0)
    object_states = runtime.get("object_states") or {}
    if not isinstance(object_states, Mapping):
        object_states = {}
    return AtomicRuntimeContext(
        revision=int(runtime.get("revision", 0)),
        location_open=location_open,
        participant_count=participant_count,
        known_object_ids=frozenset(
            str(item["object_id"]) for item in location.interaction_points
        ),
        known_resident_ids=frozenset(
            int(item.agent_id) for item in co_located_residents
        ),
        participant_present=participant_present,
        stage_authorized=stage_authorized,
        object_states={
            str(key): dict(value)
            for key, value in object_states.items()
            if isinstance(value, Mapping)
        },
    )


def _registry(spec: WorldSpec) -> AtomicActionRegistry:
    registry = AtomicActionRegistry(spec.systems)
    if not registry.modular_enabled or spec.content_schema_version != "content-pack-v5":
        raise AtomicActionServiceError(
            "The bound world has not enabled the M7 atomic-action runtime contract.",
            reason_code="unknown_reference",
        )
    return registry


def _candidate_dict(candidate: Any) -> dict[str, Any]:
    return {
        "action_id": candidate.action_id,
        "affordance_id": candidate.affordance_id,
        "label": dict(candidate.label),
        "execution_mode": candidate.execution_mode,
        "target": {
            "location_id": candidate.target.location_id,
            "object_id": candidate.target.object_id,
            "agent_id": candidate.target.agent_id,
            "actor_type": candidate.target.actor_type,
        },
        "duration_minutes": candidate.duration_minutes,
        "inputs": [dict(item) for item in candidate.input_definitions],
        "available": candidate.available,
        "reason_code": candidate.reason_code,
    }


def list_atomic_action_candidates(
    db: DBSession,
    *,
    session_id: int,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
    include_blocked: bool = False,
) -> dict[str, Any]:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session is None:
        raise AtomicActionServiceError(
            "Session not found.", reason_code="unknown_reference", status_code=404
        )
    if session.status != "active":
        raise AtomicActionServiceError(
            "Session is not active.", reason_code="actor_unavailable"
        )
    world, spec = _world_and_spec(db, session_id)
    if world_has_ended(world):
        raise AtomicActionServiceError(
            "The bound world has ended.", reason_code="actor_unavailable"
        )
    registry = _registry(spec)
    _, runtime = _runtime_state(world)
    actor = _actor_snapshot(
        db,
        world=world,
        runtime=runtime,
        actor_type=actor_type,
        actor_agent_id=actor_agent_id,
    )
    context = _runtime_context(
        db, world=world, spec=spec, runtime=runtime, actor=actor
    )
    candidates = registry.resolve_candidates(
        actor=actor,
        context=context,
        include_blocked=include_blocked,
    )
    from services.holiday_object_service import visible
    candidates = tuple(c for c in candidates if visible(spec, world.current_day, c.target.object_id))
    return {
        "runtime_version": registry.runtime_version,
        "contract_version": registry.contract_version,
        "revision": context.revision,
        "actor": {"actor_type": actor.actor_type, "agent_id": actor.agent_id},
        "candidates": [_candidate_dict(item) for item in candidates],
    }


def _existing_result(
    execution: WorldAtomicActionExecution,
    *,
    request_hash: str,
) -> dict[str, Any]:
    if execution.request_hash != request_hash:
        raise AtomicActionServiceError(
            "Atomic idempotency key was reused with a different payload.",
            reason_code="idempotency_conflict",
        )
    result = _json_loads(execution.result_json, {})
    if execution.status in {"completed", "proposed", "scheduled"}:
        result["status"] = "existing"
        result["execution_status"] = execution.status
        result["audit_id"] = execution.id
        return result
    raise AtomicActionServiceError(
        str(result.get("detail") or "The previous atomic action attempt failed."),
        reason_code=execution.reason_code,
        status_code=execution.status_code,
    )


def _persist_failure(
    db: DBSession,
    *,
    session_id: int,
    idempotency_key: str,
    request_hash: str,
    payload: Mapping[str, Any],
    requested_revision: int,
    status: str,
    reason_code: str,
    status_code: int,
    detail: str,
    runtime_version: str = ATOMIC_ACTION_RUNTIME_VERSION,
    contract_version: str = MODULAR_SYSTEMS_CONTRACT_VERSION,
) -> None:
    result = {
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "revision": requested_revision,
    }
    db.add(
        WorldAtomicActionExecution(
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor_type=str(payload["actor_type"]),
            actor_agent_id=payload.get("actor_agent_id"),
            action_id=str(payload.get("action_id") or "unknown"),
            target_location_id=payload.get("target_location_id"),
            target_actor_type=payload.get("target_actor_type"),
            target_agent_id=payload.get("target_agent_id"),
            target_object_id=payload.get("target_object_id"),
            requested_revision=requested_revision,
            accepted_revision=None,
            status=status,
            reason_code=reason_code,
            status_code=status_code,
            inputs_json=_json_dumps(payload.get("inputs") or {}),
            effects_json="[]",
            result_json=_json_dumps(result),
            runtime_version=runtime_version,
            contract_version=contract_version,
            metadata_json="{}",
        )
    )
    db.commit()


def _apply_effect(
    runtime: dict[str, Any],
    *,
    target: AtomicActionTarget,
    effect: Mapping[str, Any],
) -> dict[str, Any]:
    effect_type = effect.get("effect_type")
    if effect_type == "set_object_state":
        if target.object_id is None:
            raise AtomicActionRuntimeError(
                "Object-state effect requires an object target.",
                reason_code="target_unavailable",
            )
        object_states = runtime.setdefault("object_states", {})
        object_state = object_states.setdefault(target.object_id, {})
        state_key = str(effect["state_key"])
        object_state[state_key] = effect.get("value")
        return {
            "effect_type": effect_type,
            "object_id": target.object_id,
            "state_key": state_key,
            "value": effect.get("value"),
        }
    if effect_type == "set_world_flag":
        flags = runtime.setdefault("world_flags", {})
        flag_id = str(effect["flag_id"])
        flags[flag_id] = bool(effect.get("value"))
        return {
            "effect_type": effect_type,
            "flag_id": flag_id,
            "value": flags[flag_id],
        }
    raise AtomicActionRuntimeError(
        "Atomic effect type is not allowlisted.",
        reason_code="unknown_reference",
    )


def execute_atomic_action(
    db: DBSession,
    *,
    session_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
    interrupt_before_commit: bool = False,
    failure_injector: Callable[[int, Mapping[str, Any]], None] | None = None,
    stage_runtime_id: int | None = None,
    stage_duration_minutes: int | None = None,
    before_commit: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Validate and atomically commit one participant or resident action."""

    idempotency_key = str(_request_value(request, "idempotency_key") or "").strip()
    if not idempotency_key or len(idempotency_key) > 120:
        raise AtomicActionServiceError(
            "Atomic idempotency key must contain 1 to 120 characters.",
            reason_code="unknown_reference",
            status_code=422,
        )
    payload = _request_payload(
        request, actor_type=actor_type, actor_agent_id=actor_agent_id
    )
    request_hash = _request_hash(payload)
    requested_revision = _request_value(request, "expected_revision")
    if isinstance(requested_revision, bool) or not isinstance(requested_revision, int):
        raise AtomicActionServiceError(
            "Atomic action expected_revision must be an integer.",
            reason_code="stale_revision",
            status_code=422,
        )

    with session_write_lock(session_id):
        db.rollback()
        existing = (
            db.query(WorldAtomicActionExecution)
            .filter(
                WorldAtomicActionExecution.session_id == session_id,
                WorldAtomicActionExecution.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            return _existing_result(existing, request_hash=request_hash)

        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise AtomicActionServiceError(
                "Session not found.", reason_code="unknown_reference", status_code=404
            )
        if session.status != "active":
            raise AtomicActionServiceError(
                "Session is not active.", reason_code="actor_unavailable"
            )

        legacy_action = (
            db.query(WorldAction.id)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.idempotency_key == idempotency_key,
            )
            .first()
        )
        if legacy_action is not None:
            detail = "Atomic idempotency key conflicts with an existing world action."
            _persist_failure(
                db,
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                requested_revision=requested_revision,
                status="rejected",
                reason_code="idempotency_conflict",
                status_code=409,
                detail=detail,
            )
            raise AtomicActionServiceError(
                detail,
                reason_code="idempotency_conflict",
            )

        registry: AtomicActionRegistry | None = None
        try:
            world, spec = _world_and_spec(db, session_id)
            from services.holiday_calendar_v6 import pending
            if pending(world):
                raise AtomicActionRuntimeError('今天已经结束，请确认下一天。',reason_code='actor_unavailable')
            if world_has_ended(world):
                raise AtomicActionRuntimeError(
                    "The bound world has ended.",
                    reason_code="actor_unavailable",
                )
            registry = _registry(spec)
            root_state, runtime = _runtime_state(world)
            actor = _actor_snapshot(
                db,
                world=world,
                runtime=runtime,
                actor_type=actor_type,
                actor_agent_id=actor_agent_id,
            )
            context = _runtime_context(
                db, world=world, spec=spec, runtime=runtime, actor=actor,
                stage_authorized=stage_runtime_id is not None,
            )
            if requested_revision != context.revision:
                raise AtomicActionRuntimeError(
                    "Atomic action expected_revision is stale.",
                    reason_code="stale_revision",
                )
            target_agent_id = _request_value(request, "target_agent_id")
            target_actor_type = _request_value(request, "target_actor_type")
            target_object_id = _request_value(request, "target_object_id")
            requested_target_location = _request_value(
                request, "target_location_id"
            )
            if target_actor_type is None and target_agent_id is not None:
                target_actor_type = "resident"
            if target_object_id is not None and (
                target_actor_type is not None or target_agent_id is not None
            ):
                raise AtomicActionRuntimeError(
                    "An atomic action cannot combine object and actor targets.",
                    reason_code="unknown_reference",
                    status_code=422,
                )
            if target_actor_type == "participant" and target_agent_id is not None:
                raise AtomicActionRuntimeError(
                    "A participant target cannot carry an agent id.",
                    reason_code="unknown_reference",
                    status_code=422,
                )
            if target_actor_type == "resident" and target_agent_id is None:
                raise AtomicActionRuntimeError(
                    "A resident target requires an agent id.",
                    reason_code="unknown_reference",
                    status_code=422,
                )
            target = AtomicActionTarget(
                location_id=(
                    requested_target_location
                    or (
                        actor.location_id
                        if target_object_id is not None
                        or target_actor_type is not None
                        else None
                    )
                ),
                object_id=target_object_id,
                agent_id=target_agent_id,
                actor_type=target_actor_type,
            )
            prepared = registry.prepare(
                action_id=str(_request_value(request, "action_id") or ""),
                actor=actor,
                target=target,
                context=context,
                inputs=dict(_request_value(request, "inputs", {}) or {}),
            )
            from services.holiday_object_service import prepare as prepare_object
            prepared = prepare_object(db, world, spec, runtime, actor, target, prepared, stage_runtime_id)
            if stage_duration_minutes is not None:
                if stage_runtime_id is None or type(stage_duration_minutes) is not int or not 0 <= stage_duration_minutes <= 480:
                    raise AtomicActionRuntimeError("Invalid internal stage time budget.", reason_code="permission_denied")
                prepared = replace(prepared, duration_minutes=stage_duration_minutes)
            from services.scheduled_action_service import guard_action, should_schedule, register_action
            guard_action(world, actor.actor_key, target.object_id, stage_runtime_id)
            scheduled = should_schedule(world, spec, actor_type, prepared.duration_minutes)
            from services.stage_service import guard_atomic_stage_action

            guard_atomic_stage_action(
                db, session_id=session_id, action_id=prepared.action_id,
                object_id=target.object_id, stage_runtime_id=stage_runtime_id,
            )
            if interrupt_before_commit:
                if prepared.interruptible:
                    raise AtomicActionInterrupted("Atomic action was interrupted.")
                raise AtomicActionRuntimeError(
                    "Atomic action is not interruptible.",
                    reason_code="permission_denied",
                )

            action_metadata = {
                "atomic_action": {
                    "runtime_version": registry.runtime_version,
                    "contract_version": registry.contract_version,
                    "action_id": prepared.action_id,
                    "affordance_id": prepared.affordance_id,
                    "execution_mode": prepared.execution_mode,
                    "requested_revision": requested_revision,
                    "inputs": dict(prepared.normalized_inputs),
                    "target_actor_type": target.actor_type,
                }
            }
            action = WorldAction(
                session_id=session_id,
                idempotency_key=idempotency_key,
                actor_type=actor_type,
                actor_agent_id=actor_agent_id,
                policy_id=registry.runtime_version,
                policy_version="v1",
                decision_reason_code="authorized",
                action_type="atomic_action",
                target_location_id=target.location_id,
                target_agent_id=target.agent_id,
                target_object_id=target.object_id,
                response_text="",
                language=str(_request_value(request, "language", "en")),
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
                metadata_json=_json_dumps(action_metadata),
            )
            db.add(action)
            db.flush()

            applied_effects: list[dict[str, Any]] = []
            for index, effect in enumerate(() if scheduled else prepared.effects):
                applied_effects.append(
                    _apply_effect(runtime, target=target, effect=effect)
                )
                if failure_injector is not None:
                    failure_injector(index, effect)

            execution_status = (
                "scheduled" if scheduled else "proposed" if prepared.execution_mode == "proposal" else "completed"
            )
            next_revision = context.revision
            if execution_status == "completed":
                next_revision += 1
                runtime["revision"] = next_revision
                root_state["modular_runtime"] = runtime
                world.state_json = _json_dumps(root_state)
                world.updated_at = _utc_now()
                if prepared.duration_minutes:
                    advance_world_clock(db, world, prepared.duration_minutes)

            result = {
                "status": execution_status,
                "execution_status": execution_status,
                "reason_code": "authorized",
                "action_id": action.id,
                "atomic_action_id": prepared.action_id,
                "affordance_id": prepared.affordance_id,
                "revision": next_revision,
                "world_day": world.current_day,
                "world_time_minutes": world.current_time_minutes,
                "effects": applied_effects,
            }
            if execution_status == "completed" and any(d.get("action_id") == prepared.action_id and d.get("text_record") for d in spec.systems.get("action_definitions", ())):
                from services.player_record_service import save_from_action
                record_id = save_from_action(db, world=world, action=action, inputs=prepared.normalized_inputs)
                if record_id is not None:
                    result["player_record_id"] = record_id
            execution = WorldAtomicActionExecution(
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                actor_type=actor_type,
                actor_agent_id=actor_agent_id,
                action_id=prepared.action_id,
                affordance_id=prepared.affordance_id,
                target_location_id=target.location_id,
                target_actor_type=target.actor_type,
                target_agent_id=target.agent_id,
                target_object_id=target.object_id,
                requested_revision=requested_revision,
                accepted_revision=next_revision,
                status=execution_status,
                reason_code="authorized",
                status_code=200,
                source_action_id=action.id,
                inputs_json=_json_dumps(dict(prepared.normalized_inputs)),
                effects_json=_json_dumps(applied_effects),
                result_json=_json_dumps(result),
                runtime_version=registry.runtime_version,
                contract_version=registry.contract_version,
                metadata_json=_json_dumps({"interruptible": prepared.interruptible}),
                updated_at=_utc_now(),
            )
            db.add(execution)
            db.flush()
            result["audit_id"] = execution.id
            execution.result_json = _json_dumps(result)
            if execution_status == 'completed' and world.world_version == 'chaoxi-holiday-v6':
                from services.holiday_work_service import attach_sources
                attach_sources(world, action, actor.actor_key)
            if scheduled:
                register_action(db, world=world, spec=spec, execution=execution, actor=actor,
                                target=target, prepared=prepared, stage_runtime_id=stage_runtime_id)
                result["scheduled_end_ordinal"] = _json_loads(execution.metadata_json, {})["end_ordinal"]
                execution.result_json = _json_dumps(result)
            if before_commit is not None:
                before_commit(result)
            db.commit()
            return result
        except AtomicActionInterrupted as exc:
            db.rollback()
            _persist_failure(
                db,
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                requested_revision=requested_revision,
                status="interrupted",
                reason_code="interrupted",
                status_code=409,
                detail=str(exc),
                runtime_version=(registry.runtime_version if registry else ATOMIC_ACTION_RUNTIME_VERSION),
                contract_version=(registry.contract_version if registry else MODULAR_SYSTEMS_CONTRACT_VERSION),
            )
            raise AtomicActionServiceError(
                str(exc), reason_code="interrupted", status_code=409
            ) from exc
        except AtomicActionRuntimeError as exc:
            db.rollback()
            _persist_failure(
                db,
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                requested_revision=requested_revision,
                status="rejected",
                reason_code=exc.reason_code,
                status_code=exc.status_code,
                detail=exc.detail,
                runtime_version=(registry.runtime_version if registry else ATOMIC_ACTION_RUNTIME_VERSION),
                contract_version=(registry.contract_version if registry else MODULAR_SYSTEMS_CONTRACT_VERSION),
            )
            raise AtomicActionServiceError(
                exc.detail,
                reason_code=exc.reason_code,
                status_code=exc.status_code,
            ) from exc
        except AtomicActionServiceError as exc:
            db.rollback()
            _persist_failure(
                db,
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                requested_revision=requested_revision,
                status="rejected",
                reason_code=exc.reason_code,
                status_code=exc.status_code,
                detail=exc.detail,
                runtime_version=(
                    registry.runtime_version
                    if registry
                    else ATOMIC_ACTION_RUNTIME_VERSION
                ),
                contract_version=(
                    registry.contract_version
                    if registry
                    else MODULAR_SYSTEMS_CONTRACT_VERSION
                ),
            )
            raise
        except IntegrityError as exc:
            db.rollback()
            duplicate = (
                db.query(WorldAtomicActionExecution)
                .filter(
                    WorldAtomicActionExecution.session_id == session_id,
                    WorldAtomicActionExecution.idempotency_key == idempotency_key,
                )
                .first()
            )
            if duplicate is not None:
                return _existing_result(duplicate, request_hash=request_hash)
            raise AtomicActionServiceError(
                "Atomic action collided with an existing world action.",
                reason_code="idempotency_conflict",
            ) from exc
        except Exception as exc:
            db.rollback()
            _persist_failure(
                db,
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                requested_revision=requested_revision,
                status="technical_failure",
                reason_code="technical_failure",
                status_code=500,
                detail="Atomic action failed before commit; no effects were applied.",
                runtime_version=(registry.runtime_version if registry else ATOMIC_ACTION_RUNTIME_VERSION),
                contract_version=(registry.contract_version if registry else MODULAR_SYSTEMS_CONTRACT_VERSION),
            )
            raise AtomicActionServiceError(
                "Atomic action failed before commit; no effects were applied.",
                reason_code="technical_failure",
                status_code=500,
            ) from exc
