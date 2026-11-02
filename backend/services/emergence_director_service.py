from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    RelationshipState,
    Session as UserSession,
    WorldActorKnowledge,
    WorldCommitment,
    WorldEmergenceCandidate,
    WorldEmergenceDecision,
    WorldEmergenceEvaluation,
    WorldEmergentEventRuntime,
    WorldEmergentEventTransition,
    WorldEventInstance,
    WorldKnowledgeFact,
    WorldMemory,
    WorldPlanMember,
    WorldPlanTransition,
    WorldSimulationPulse,
    WorldState,
)
from services.phone_plan_service import PhonePlanError, create_phone_invitation
from services.plan_service import (
    ACTIVE_PLAN_STATES,
    PLAN_RUNTIME_VERSION,
    PlanServiceError,
    query_plan_availability,
    transition_plan,
)
from services.world_service import session_write_lock, world_has_ended
from world.emergence_contracts import (
    CANDIDATE_SOURCE_TYPES,
    MODULAR_SYSTEMS_CONTRACT_VERSION,
)
from world.registry import get_world_spec
from world.specs import WorldSpec


DIRECTOR_RUNTIME_VERSION = "emergence-director-v1"
MAX_EVALUATIONS_PER_DAY = 288
OPEN_EVENT_STATES = ("proposed", "active")
TERMINAL_EVENT_STATES = ("rejected", "cancelled", "expired", "completed", "failed")
EVALUATION_SOURCES = ("manual_test", "foreground_pulse")


class EmergenceDirectorError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason_code = reason_code
        self.status_code = status_code


@dataclass
class CandidateDraft:
    candidate_key: str
    recipe: Mapping[str, Any]
    organizer_agent_id: int
    location_id: str
    scheduled_day: int
    scheduled_time_minutes: int
    expires_day: int
    expires_time_minutes: int
    invitees: list[dict[str, Any]]
    source_types: list[str]
    source_facts: list[dict[str, Any]]
    validation: dict[str, Any]
    chain_depth: int = 0
    source_event_runtime_id: int | None = None
    feasible: bool = True
    reason_code: str = "candidate_valid"
    rank: int = 0
    score: dict[str, Any] | None = None
    outcome: str = "blocked"

    @property
    def organizer_key(self) -> str:
        return f"resident:{self.organizer_agent_id}"

    @property
    def player_facing(self) -> bool:
        return bool(self.recipe.get("player_facing", True))

    @property
    def direct_participant_invite(self) -> bool:
        return any(item["actor_type"] == "participant" for item in self.invitees)


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _ordinal(day: int, minute: int) -> int:
    return (day - 1) * 1440 + minute


def _position(ordinal: int) -> tuple[int, int]:
    return ordinal // 1440 + 1, ordinal % 1440


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _world_and_spec(db: DBSession, session_id: int) -> tuple[UserSession, WorldState, WorldSpec]:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
    if session is None or world is None:
        raise EmergenceDirectorError(
            "The bound world is unavailable.", reason_code="unknown_world", status_code=404
        )
    if session.status != "active" or world_has_ended(world):
        raise EmergenceDirectorError("The world is not active.", reason_code="world_inactive")
    try:
        spec = get_world_spec(world.world_version)
    except KeyError as exc:
        raise EmergenceDirectorError(
            "The bound world specification is unavailable.", reason_code="unknown_world"
        ) from exc
    if (
        spec.content_schema_version != "content-pack-v5"
        or spec.systems.get("contract_version") != MODULAR_SYSTEMS_CONTRACT_VERSION
    ):
        raise EmergenceDirectorError(
            "The bound world has not enabled the M7 emergence contract.",
            reason_code="runtime_unavailable",
        )
    if spec.scenario_pack_version != world.scenario_pack_version:
        raise EmergenceDirectorError(
            "The bound world content versions do not match.", reason_code="unknown_world"
        )
    return session, world, spec


def _policy(spec: WorldSpec, name: str) -> Mapping[str, Any]:
    value = spec.systems.get(name)
    if not isinstance(value, Mapping):
        raise EmergenceDirectorError(
            f"The {name} contract is unavailable.", reason_code="runtime_unavailable"
        )
    return value


def auto_emergence_enabled(db: DBSession, *, session_id: int) -> bool:
    """Return true only when authored v5 recipes explicitly opt into pulse evaluation."""

    try:
        _session, _world, spec = _world_and_spec(db, session_id)
    except EmergenceDirectorError:
        return False
    return any(
        _conditions(recipe).get("auto_emergence", False) is True
        for recipe in spec.systems.get("activity_recipes", ())
    )


def _conditions(recipe: Mapping[str, Any]) -> Mapping[str, Any]:
    value = recipe.get("conditions", {})
    return value if isinstance(value, Mapping) else {}


def _request_payload(request: Any) -> dict[str, Any]:
    return {
        "idempotency_key": str(_value(request, "idempotency_key", "")),
        "source": str(_value(request, "source", "manual_test")),
        "source_pulse_id": _value(request, "source_pulse_id"),
        "expected_day": _value(request, "expected_day"),
        "expected_time_minutes": _value(request, "expected_time_minutes"),
        "language": str(_value(request, "language", "en")),
    }


def _validate_request(payload: Mapping[str, Any], world: WorldState) -> None:
    if not payload["idempotency_key"] or len(str(payload["idempotency_key"])) > 120:
        raise EmergenceDirectorError(
            "A valid idempotency key is required.", reason_code="invalid_request", status_code=422
        )
    if payload["source"] not in EVALUATION_SOURCES:
        raise EmergenceDirectorError(
            "Unknown director source.", reason_code="invalid_request", status_code=422
        )
    if payload["expected_day"] is not None and int(payload["expected_day"]) != world.current_day:
        raise EmergenceDirectorError(
            "World day changed before emergence evaluation.", reason_code="stale_world"
        )
    if (
        payload["expected_time_minutes"] is not None
        and int(payload["expected_time_minutes"]) != world.current_time_minutes
    ):
        raise EmergenceDirectorError(
            "World time changed before emergence evaluation.", reason_code="stale_world"
        )


def _serialize_candidate(item: WorldEmergenceCandidate) -> dict[str, Any]:
    return {
        "candidate_id": item.id,
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


def _serialize_event(db: DBSession, item: WorldEmergentEventRuntime) -> dict[str, Any]:
    metadata = _json_loads(item.metadata_json, {})
    experience = metadata.get('experience') or {}
    if (experience.get('game') or {}).get('mode')=='uno':
        from services.holiday_uno_v6 import public
        metadata['experience']={**experience,'game':public(experience['game'])}
    plan = db.query(WorldCommitment).filter(WorldCommitment.id == item.commitment_id).first()
    members = (
        db.query(WorldPlanMember)
        .filter(WorldPlanMember.commitment_id == item.commitment_id)
        .order_by(WorldPlanMember.id.asc())
        .all()
    )
    return {
        "runtime_id": item.id,
        "event_instance_id": item.event_instance_id,
        "commitment_id": item.commitment_id,
        "recipe_id": item.recipe_id,
        "complexity": item.complexity,
        "player_facing": item.player_facing,
        "direct_participant_invite": item.direct_participant_invite,
        "organizer_actor_key": item.organizer_actor_key,
        "status": item.status,
        "plan_status": plan.status if plan else None,
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
        "members": [
            {
                "actor_key": member.actor_key,
                "required": member.required,
                "response_status": member.response_status,
                "attendance_status": member.attendance_status,
            }
            for member in members
        ],
        "metadata": metadata,
    }


def _evaluation_response(db: DBSession, evaluation: WorldEmergenceEvaluation) -> dict[str, Any]:
    candidates = (
        db.query(WorldEmergenceCandidate)
        .filter(WorldEmergenceCandidate.evaluation_id == evaluation.id)
        .order_by(WorldEmergenceCandidate.rank.asc(), WorldEmergenceCandidate.id.asc())
        .all()
    )
    event_ids = [item.selected_commitment_id for item in candidates if item.selected_commitment_id]
    events = (
        db.query(WorldEmergentEventRuntime)
        .filter(WorldEmergentEventRuntime.commitment_id.in_(event_ids))
        .order_by(WorldEmergentEventRuntime.id.asc())
        .all()
        if event_ids
        else []
    )
    return {
        "runtime_version": DIRECTOR_RUNTIME_VERSION,
        "evaluation_id": evaluation.id,
        "status": evaluation.status,
        "source": evaluation.source,
        "source_pulse_id": evaluation.source_pulse_id,
        "world_day": evaluation.world_day,
        "world_time_minutes": evaluation.world_time_minutes,
        "simulation_seed": evaluation.simulation_seed,
        "policy": {"id": evaluation.policy_id, "version": evaluation.policy_version},
        "state_fingerprint": evaluation.state_fingerprint,
        "candidate_count": evaluation.candidate_count,
        "selected_count": evaluation.selected_count,
        "budget": _json_loads(evaluation.budget_json, {}),
        "candidates": [_serialize_candidate(item) for item in candidates],
        "events": [_serialize_event(db, item) for item in events],
    }


def _event_status(plan_status: str) -> str:
    if plan_status in ("proposed", "accepted"):
        return "proposed"
    if plan_status == "in_progress":
        return "active"
    if plan_status in TERMINAL_EVENT_STATES:
        return plan_status
    return "failed"


def _event_instance_status(runtime_status: str) -> str:
    if runtime_status == "proposed":
        return "emergent_pending"
    if runtime_status == "active":
        return "emergent_active"
    return runtime_status


def reconcile_emergent_events(db: DBSession, *, session_id: int) -> list[dict[str, Any]]:
    """Expire due plans and project every plan/member revision into event audit state."""

    from services.stage_service import reconcile_stages

    reconcile_stages(db, session_id=session_id)
    _session, world, _spec = _world_and_spec(db, session_id)
    now_ordinal = _ordinal(world.current_day, world.current_time_minutes)
    linked_plans = (
        db.query(WorldCommitment)
        .join(WorldEmergentEventRuntime, WorldEmergentEventRuntime.commitment_id == WorldCommitment.id)
        .filter(WorldCommitment.session_id == session_id, WorldCommitment.status.in_(ACTIVE_PLAN_STATES))
        .order_by(WorldCommitment.id.asc())
        .all()
    )
    for plan in linked_plans:
        conditions = next(r for r in _spec.systems.get("activity_recipes", ()) if r["recipe_id"] == plan.recipe_id).get("conditions", {})
        if conditions.get("fixed_stage_timeline") and plan.status == "accepted":
            authored_start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
            if authored_start <= now_ordinal < authored_start + plan.duration_minutes:
                transition_plan(db, session_id=session_id, commitment_id=plan.id,
                    actor_type=plan.organizer_type, actor_agent_id=plan.organizer_agent_id,
                    request={"transition": "start", "idempotency_key": f"fixed-start:{plan.id}:{plan.revision}",
                        "expected_revision": plan.revision, "reason_code": "authored_open_event_started"})
        deadline = _ordinal(
            int(plan.deadline_day or plan.scheduled_day),
            int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes),
        )
        start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
        expiry = deadline if plan.status == "proposed" else start + (30 if __import__("content.experience_next",fromlist=["enabled"]).enabled() else 15)
        if conditions.get("open_admission_until_end"):
            expiry = start + plan.duration_minutes
        transition_type = "expire"
        reason = "response_deadline_expired" if plan.status == "proposed" else "start_window_expired"
        if plan.status == "in_progress":
            expiry = start + plan.duration_minutes + (30 if __import__("content.experience_next",fromlist=["enabled"]).enabled() else 15)
            transition_type = "fail"
            reason = "event_execution_timeout"
        if now_ordinal > expiry:
            transition_plan(
                db,
                session_id=session_id,
                commitment_id=plan.id,
                actor_type=plan.organizer_type,
                actor_agent_id=plan.organizer_agent_id,
                request={
                    "transition": transition_type,
                    "idempotency_key": f"m7e-due:{plan.id}:{plan.revision}",
                    "expected_revision": plan.revision,
                    "reason_code": reason,
                },
            )
    reconcile_stages(db, session_id=session_id)
    db.rollback()
    world = db.query(WorldState).filter(WorldState.session_id == session_id).one()
    rows = (
        db.query(WorldEmergentEventRuntime)
        .filter(WorldEmergentEventRuntime.session_id == session_id)
        .order_by(WorldEmergentEventRuntime.id.asc())
        .all()
    )
    changed: list[dict[str, Any]] = []
    for runtime in rows:
        plan = db.query(WorldCommitment).filter(WorldCommitment.id == runtime.commitment_id).first()
        if runtime.status == "failed" and runtime.terminal_reason_code == "emergent_event_technical_failure":
            continue
        if plan is None:
            after = "failed"
            reason = "linked_plan_missing"
            plan_revision = runtime.revision + 1
        else:
            after = _event_status(plan.status)
            reason = plan.ended_reason_code or f"plan_{plan.status}"
            plan_revision = int(plan.revision)
            runtime.expires_day = int(plan.deadline_day or plan.scheduled_day)
            runtime.expires_time_minutes = int(
                plan.deadline_time_minutes
                if plan.deadline_time_minutes is not None
                else plan.scheduled_time_minutes
            )
        transition_key = f"plan:{plan_revision}:{after}"
        existing = db.query(WorldEmergentEventTransition).filter(
            WorldEmergentEventTransition.runtime_id == runtime.id,
            WorldEmergentEventTransition.transition_key == transition_key,
        ).first()
        if existing is not None:
            continue
        before = runtime.status
        runtime.status = after
        runtime.revision = max(runtime.revision + 1, plan_revision)
        runtime.updated_at = _utc_now()
        if after in TERMINAL_EVENT_STATES:
            # Keep the original event time when reconciling late.
            terminal_transition = (
                db.query(WorldPlanTransition)
                .filter(
                    WorldPlanTransition.commitment_id == runtime.commitment_id,
                    WorldPlanTransition.accepted_revision == plan_revision,
                )
                .order_by(WorldPlanTransition.id.desc())
                .first()
            )
            runtime.completed_day = terminal_transition.world_day if terminal_transition else world.current_day
            runtime.completed_time_minutes = (
                terminal_transition.world_time_minutes if terminal_transition else world.current_time_minutes
            )
            runtime.terminal_reason_code = reason
        instance = db.query(WorldEventInstance).filter(
            WorldEventInstance.id == runtime.event_instance_id
        ).first()
        if instance is not None:
            instance.status = _event_instance_status(after)
            instance.updated_at = _utc_now()
            if after in TERMINAL_EVENT_STATES:
                instance.completed_day = runtime.completed_day
                instance.completed_time_minutes = runtime.completed_time_minutes
                instance.outcome_code = reason
                instance.completed_at = _utc_now()
        transition = WorldEmergentEventTransition(
            session_id=session_id,
            runtime_id=runtime.id,
            transition_key=transition_key,
            transition_type="plan_reconcile",
            before_status=before,
            after_status=after,
            reason_code=reason,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json=_json_dumps({"plan_revision": plan_revision}),
        )
        db.add(transition)
        changed.append({"runtime_id": runtime.id, "before": before, "after": after, "reason_code": reason})
    db.commit()
    return changed


def _state_fingerprint(db: DBSession, world: WorldState, spec: WorldSpec) -> str:
    actors = [
        (row.agent_id, row.current_location_id)
        for row in db.query(CharacterState)
        .filter(CharacterState.session_id == world.session_id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    ]
    plans = [
        (row.id, row.recipe_id, row.status, row.revision, row.scheduled_day, row.scheduled_time_minutes)
        for row in db.query(WorldCommitment)
        .filter(
            WorldCommitment.session_id == world.session_id,
            WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
        )
        .order_by(WorldCommitment.id.asc())
        .all()
    ]
    events = [
        (row.id, row.status, row.revision, row.chain_depth)
        for row in db.query(WorldEmergentEventRuntime)
        .filter(WorldEmergentEventRuntime.session_id == world.session_id)
        .order_by(WorldEmergentEventRuntime.id.asc())
        .all()
    ]
    knowledge_count = db.query(WorldActorKnowledge).filter(
        WorldActorKnowledge.session_id == world.session_id
    ).count()
    return _stable_hash(
        {
            "day": world.current_day,
            "time_bucket": world.current_time_minutes // 30,
            "participant_location": world.participant_location_id,
            "actors": actors,
            "plans": plans,
            "events": events,
            "knowledge_count": knowledge_count,
            "content": [spec.world_version, spec.content_pack_version],
        }
    )


def _start_slot(world: WorldState, spec: WorldSpec, recipe: Mapping[str, Any]) -> tuple[int, int] | None:
    conditions = _conditions(recipe)
    if "fixed_day" in conditions:
        day, minute = int(conditions["fixed_day"]), int(conditions["fixed_start_minute"])
        if day != world.current_day or minute < world.current_time_minutes or minute + int(recipe["duration_minutes"]) > spec.calendar.day_end_minute:
            return None
        return day, minute
    delay = int(conditions.get("start_delay_minutes", 30))
    delay = min(240, max(15, delay))
    absolute = _ordinal(world.current_day, world.current_time_minutes) + delay
    absolute = ((absolute + 14) // 15) * 15
    day, minute = _position(absolute)
    duration = int(recipe.get("duration_minutes", 0))
    if day != world.current_day or minute + duration > spec.calendar.day_end_minute + 1:
        return None
    return day, minute


def _expiry_slot(world: WorldState, start_day: int, start_minute: int, recipe: Mapping[str, Any]) -> tuple[int, int]:
    if "fixed_day" in _conditions(recipe):
        return start_day, start_minute
    minutes = int(_conditions(recipe).get("expires_after_minutes", 30))
    minutes = min(240, max(15, minutes))
    ordinal = min(
        _ordinal(start_day, start_minute),
        _ordinal(world.current_day, world.current_time_minutes) + minutes,
    )
    return _position(ordinal)


def _actor_ref(actor_key: str, *, required: bool = False) -> dict[str, Any]:
    if actor_key == "participant":
        return {"actor_type": "participant", "agent_id": None, "role_id": None, "required": required}
    return {
        "actor_type": "resident",
        "agent_id": int(actor_key.split(":", 1)[1]),
        "role_id": None,
        "required": required,
    }


def _candidate_invitee_sets(
    *, recipe: Mapping[str, Any], organizer_id: int, resident_ids: list[int]
) -> list[list[dict[str, Any]]]:
    conditions = _conditions(recipe)
    participant_mode = str(conditions.get("participant_mode", "optional"))
    if participant_mode not in ("required", "optional", "exclude"):
        return []
    needed = max(0, int(recipe.get("min_participants", 1)) - 1)
    residents = [item for item in resident_ids if item != organizer_id]
    if conditions.get("invite_all_residents") is True:
        return [[{**_actor_ref("participant"), "role_id": "guest"}, *[_actor_ref(f"resident:{i}") for i in residents]]]
    sets: list[list[dict[str, Any]]] = []
    if participant_mode in ("required", "optional"):
        participant = _actor_ref("participant", required=participant_mode == "required")
        extra_needed = max(0, needed - 1)
        if len(residents) >= extra_needed:
            sets.append([participant, *[_actor_ref(f"resident:{item}") for item in residents[:extra_needed]]])
    if participant_mode in ("optional", "exclude") and len(residents) >= needed:
        sets.append([_actor_ref(f"resident:{item}") for item in residents[:needed]])
    if needed == 0 and participant_mode != "required":
        sets.insert(0, [])
    maximum = int(recipe.get("max_participants", 20))
    result = [items for items in sets if len(items) + 1 <= maximum]
    role_ids = conditions.get("invitee_role_ids", ())
    if not isinstance(role_ids, (list, tuple)) or any(not isinstance(role, str) or role not in recipe.get("role_slots", ()) for role in role_ids):
        return []
    for items in result:
        for index, role in enumerate(role_ids):
            if index < len(items):
                items[index]["role_id"] = role
    return result


def _source_evidence(
    db: DBSession,
    *,
    session_id: int,
    spec: WorldSpec,
    recipe: Mapping[str, Any],
    organizer_id: int,
    day: int,
    minute: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    source_types = ["activity_recipe"]
    facts: list[dict[str, Any]] = [
        {"type": "activity_recipe", "id": recipe.get("recipe_id"), "version": spec.content_pack_version}
    ]
    resident = spec.residents.get(organizer_id)
    if resident is not None:
        block = next(
            (
                item
                for item in resident.schedule
                if (item.days is None or day in item.days)
                and item.start_minute <= minute <= item.end_minute
            ),
            None,
        )
        if block is not None:
            source_types.append("actor_goal")
            facts.append({"type": "actor_goal", "actor_key": f"resident:{organizer_id}", "state_id": block.state_id})
    affordance = next(
        (
            item
            for item in spec.systems.get("affordances", ())
            if item.get("enabled", True)
            and any(action in recipe.get("action_ids", ()) for action in [item.get("action_id")])
            and any(location in recipe.get("location_ids", ()) for location in item.get("location_ids", ()))
        ),
        None,
    )
    if affordance is not None:
        source_types.append("affordance")
        facts.append({"type": "affordance", "id": affordance.get("affordance_id")})
    known = db.query(WorldActorKnowledge).join(
        WorldKnowledgeFact, WorldKnowledgeFact.id == WorldActorKnowledge.fact_id,
    ).filter(
        WorldActorKnowledge.session_id == session_id,
        WorldActorKnowledge.actor_key == f"resident:{organizer_id}",
        WorldKnowledgeFact.visibility == "island_public",
    ).first()
    if known is not None:
        source_types.append("public_knowledge")
        facts.append({"type": "public_knowledge", "actor_knowledge_id": known.id, "fact_id": known.fact_id})
    memory = db.query(WorldMemory).filter(
        WorldMemory.session_id == session_id,
        WorldMemory.owner_agent_id == organizer_id,
    ).order_by(WorldMemory.id.desc()).first()
    if memory is not None:
        source_types.append("memory")
        facts.append({"type": "memory", "memory_id": memory.id})
    relationship = db.query(RelationshipState).filter(
        RelationshipState.session_id == session_id,
        RelationshipState.source_agent_id == organizer_id,
    ).first()
    if relationship is not None:
        source_types.append("relationship")
        facts.append({"type": "relationship", "relationship_id": relationship.id})
    commitment = (
        db.query(WorldCommitment)
        .join(WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id)
        .filter(
            WorldCommitment.session_id == session_id,
            WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
            WorldCommitment.status.in_(ACTIVE_PLAN_STATES),
            WorldPlanMember.actor_key == f"resident:{organizer_id}",
        )
        .order_by(WorldCommitment.id.desc())
        .first()
    )
    if commitment is not None:
        source_types.append("commitment")
        facts.append({"type": "commitment", "commitment_id": commitment.id})
    return list(dict.fromkeys(source_types)), facts


def _permission_validation(
    *, world: WorldState, spec: WorldSpec, recipe: Mapping[str, Any], organizer_id: int, location_id: str
) -> dict[str, Any]:
    stage_id = _conditions(recipe).get("stage_recipe_id")
    if stage_id:
        from world.stage_recipes import validate_stage_cards
        from world.specs import WorldSpecValidationError

        definition = next((s for s in spec.systems.get("stage_recipes", ()) if s["stage_recipe_id"] == stage_id), None)
        if definition is None or not definition.get("stages"):
            return {"available": False, "reason_code": "unknown_stage_recipe"}
        try:
            validate_stage_cards(definition, spec.systems)
        except WorldSpecValidationError:
            return {"available": False, "reason_code": "invalid_stage_recipe"}
    root = _json_loads(world.state_json, {})
    runtime = root.get("modular_runtime", {}) if isinstance(root, Mapping) else {}
    if not isinstance(runtime, Mapping):
        runtime = {}
    grants_root = runtime.get("actor_grants", {})
    grants = (
        grants_root.get(f"resident:{organizer_id}", {})
        if isinstance(grants_root, Mapping)
        else {}
    )
    if not isinstance(grants, Mapping):
        grants = {}
    permissions = {str(item) for item in grants.get("permissions", ())}
    capabilities = {str(item) for item in grants.get("capabilities", ())}
    actor_states = runtime.get("actor_states", {})
    actor_state = (
        actor_states.get(f"resident:{organizer_id}", {})
        if isinstance(actor_states, Mapping)
        else {}
    )
    if not isinstance(actor_state, Mapping):
        actor_state = {}
    if isinstance(actor_state, Mapping) and actor_state.get("availability", "available") != "available":
        return {"available": False, "reason_code": "actor_unavailable"}
    definitions = {
        str(item.get("action_id")): item
        for item in spec.systems.get("action_definitions", ())
        if isinstance(item, Mapping)
    }
    required_permissions: set[str] = set()
    required_capabilities: set[str] = set()
    location_states = runtime.get("location_states", {})
    location_state = location_states.get(location_id, {}) if isinstance(location_states, Mapping) else {}
    if isinstance(location_state, Mapping) and location_state.get("open", True) is not True:
        return {"available": False, "reason_code": "location_closed"}
    for action_id in recipe.get("action_ids", ()):
        definition = definitions.get(str(action_id))
        if definition is None:
            return {"available": False, "reason_code": "unknown_action"}
        if "resident" not in definition.get("actor_types", ()):
            # The host can invite a participant to a participant-only stage;
            # this does not grant the host permission to execute that choice.
            if stage_id and "participant" in definition.get("actor_types", ()) and _conditions(recipe).get("participant_mode") in ("required", "optional"):
                continue  # Per-executor grants are checked again at execution.
            return {"available": False, "reason_code": "action_actor_not_allowed"}
        required_permissions.update(str(item) for item in definition.get("permission_keys", ()))
        required_capabilities.update(str(item) for item in definition.get("capability_keys", ()))
        checks = [definition.get("preconditions", {})]
        for affordance in spec.systems.get("affordances", ()):
            if (
                isinstance(affordance, Mapping)
                and affordance.get("enabled", True)
                and affordance.get("action_id") == action_id
                and location_id in affordance.get("location_ids", ())
            ):
                required_permissions.update(str(item) for item in affordance.get("permission_keys", ()))
                required_capabilities.update(str(item) for item in affordance.get("capability_keys", ()))
                checks.append(affordance.get("conditions", {}))
        for check in checks:
            expected_actor_state = check.get("actor_state_equals", {})
            if any(actor_state.get(key) != value for key, value in expected_actor_state.items()):
                return {"available": False, "reason_code": "actor_unavailable"}
            expected_object_state = check.get("object_state_equals", {})
            objects = runtime.get("object_states", {})
            for object_id in recipe.get("object_ids", ()):
                actual = objects.get(object_id, {}) if isinstance(objects, Mapping) else {}
                if any(actual.get(key) != value for key, value in expected_object_state.items()):
                    return {"available": False, "reason_code": "target_unavailable"}
    if not required_permissions <= permissions:
        return {
            "available": False,
            "reason_code": "permission_denied",
            "missing_permissions": sorted(required_permissions - permissions),
        }
    if not required_capabilities <= capabilities:
        return {
            "available": False,
            "reason_code": "capability_missing",
            "missing_capabilities": sorted(required_capabilities - capabilities),
        }
    return {
        "available": True,
        "reason_code": "authorized",
        "required_permissions": sorted(required_permissions),
        "required_capabilities": sorted(required_capabilities),
    }


def _checked_availability(db: DBSession, *, session_id: int, request: dict[str, Any]) -> dict[str, Any]:
    """An unusable registered recipe blocks its candidate, not the entire pass."""

    try:
        return query_plan_availability(db, session_id=session_id, request=request)
    except PlanServiceError as exc:
        return {"available": False, "reason_code": exc.reason_code}


def _base_drafts(db: DBSession, *, world: WorldState, spec: WorldSpec) -> list[CandidateDraft]:
    resident_ids = [
        int(row.agent_id)
        for row in db.query(CharacterState)
        .filter(CharacterState.session_id == world.session_id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    ]
    drafts: list[CandidateDraft] = []
    for recipe in spec.systems.get("activity_recipes", ()):
        conditions = _conditions(recipe)
        if conditions.get("emergence_enabled", True) is False or conditions.get("followup_only", False) is True:
            continue
        slot = _start_slot(world, spec, recipe)
        if slot is None:
            continue
        day, minute = slot
        expiry_day, expiry_minute = _expiry_slot(world, day, minute, recipe)
        preferred = [int(item) for item in conditions.get("organizer_agent_ids", ()) if int(item) in resident_ids]
        organizers = preferred if "organizer_agent_ids" in conditions else resident_ids
        attempted: CandidateDraft | None = None
        for organizer_id in organizers:
            source_types, facts = _source_evidence(
                db,
                session_id=world.session_id,
                spec=spec,
                recipe=recipe,
                organizer_id=organizer_id,
                day=day,
                minute=minute,
            )
            if not set(source_types) <= set(CANDIDATE_SOURCE_TYPES):
                continue
            for location_id in recipe.get("location_ids", ()):
                invitee_sets = _candidate_invitee_sets(
                    recipe=recipe, organizer_id=organizer_id, resident_ids=resident_ids
                )
                if not invitee_sets:
                    attempted = CandidateDraft(
                        candidate_key=f"base:{recipe['recipe_id']}:{organizer_id}:{location_id}:{day}:{minute}",
                        recipe=recipe,
                        organizer_agent_id=organizer_id,
                        location_id=str(location_id),
                        scheduled_day=day,
                        scheduled_time_minutes=minute,
                        expires_day=expiry_day,
                        expires_time_minutes=expiry_minute,
                        invitees=[],
                        source_types=source_types,
                        source_facts=facts,
                        validation={"available": False, "reason_code": "participant_bounds_unsatisfied"},
                        feasible=False,
                        reason_code="participant_bounds_unsatisfied",
                    )
                    continue
                for invitees in invitee_sets:
                    actors = [_actor_ref(f"resident:{organizer_id}", required=True), *invitees]
                    authorization = _permission_validation(
                        world=world,
                        spec=spec,
                        recipe=recipe,
                        organizer_id=organizer_id,
                        location_id=str(location_id),
                    )
                    availability = (
                        _checked_availability(
                            db,
                            session_id=world.session_id,
                            request={
                                "start_day": day,
                                "start_time_minutes": minute,
                                "duration_minutes": int(recipe.get("duration_minutes", 0)),
                                "location_id": location_id,
                                "actors": actors,
                                "object_ids": list(recipe.get("object_ids", ())),
                                "role_slots": list(recipe.get("role_slots", ())),
                            },
                        )
                        if authorization["available"]
                        else authorization
                    )
                    availability = {**availability, "authorization": authorization}
                    if availability.get("conflicts"):
                        source_types = [*source_types, "plan_conflict"]
                        facts = [
                            *facts,
                            {
                                "type": "plan_conflict",
                                "conflicts": availability["conflicts"],
                            },
                        ]
                    draft = CandidateDraft(
                        candidate_key=f"base:{recipe['recipe_id']}:{organizer_id}:{location_id}:{day}:{minute}:{','.join(item['actor_type'] + ':' + str(item.get('agent_id')) for item in invitees)}",
                        recipe=recipe,
                        organizer_agent_id=organizer_id,
                        location_id=str(location_id),
                        scheduled_day=day,
                        scheduled_time_minutes=minute,
                        expires_day=expiry_day,
                        expires_time_minutes=expiry_minute,
                        invitees=invitees,
                        source_types=source_types,
                        source_facts=facts,
                        validation=availability,
                        feasible=bool(availability.get("available")),
                        reason_code="candidate_valid" if availability.get("available") else str(availability.get("reason_code")),
                    )
                    attempted = draft
                    if draft.feasible:
                        break
                if attempted is not None and attempted.feasible:
                    break
            if attempted is not None and attempted.feasible:
                break
        if attempted is not None:
            drafts.append(attempted)
    return drafts


def _candidate_invitation_key(evaluation_id: int, candidate_key: str) -> str:
    key_hash = hashlib.sha256(f"{evaluation_id}:{candidate_key}".encode("utf-8")).hexdigest()[:32]
    return f"m7e-{key_hash}"


def _followup_drafts(db: DBSession, *, world: WorldState, spec: WorldSpec) -> list[CandidateDraft]:
    recipes = {str(item["recipe_id"]): item for item in spec.systems.get("activity_recipes", ())}
    max_depth = int(_policy(spec, "emergence_policy").get("max_event_chain_depth", 0))
    drafts: list[CandidateDraft] = []
    completed = db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.session_id == world.session_id,
        WorldEmergentEventRuntime.status == "completed",
        WorldEmergentEventRuntime.completed_day < world.current_day,
    ).order_by(WorldEmergentEventRuntime.id.asc()).all()
    resident_ids = [
        int(row.agent_id)
        for row in db.query(CharacterState)
        .filter(CharacterState.session_id == world.session_id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    ]
    for source in completed:
        source_recipe = recipes.get(source.recipe_id)
        if source_recipe is None:
            continue
        outcome_facts = []
        if _conditions(source_recipe).get("stage_recipe_id"):
            outcome_facts = db.query(WorldKnowledgeFact).join(
                WorldActorKnowledge, WorldActorKnowledge.fact_id == WorldKnowledgeFact.id,
            ).filter(
                WorldKnowledgeFact.session_id == world.session_id,
                WorldKnowledgeFact.source_type == "stage_execution",
                WorldKnowledgeFact.source_id == source.id,
                WorldKnowledgeFact.fact_type == "stage_outcome",
                WorldActorKnowledge.actor_key == source.organizer_actor_key,
            ).all()
            if not outcome_facts:
                continue  # Global completion is not sufficient character knowledge.
        for recipe_id in _conditions(source_recipe).get("followup_recipe_ids", ()):
            recipe = recipes.get(str(recipe_id))
            if recipe is None:
                continue
            depth = source.chain_depth + 1
            key_prefix = f"followup:{source.id}:{recipe_id}:{world.current_day}"
            duplicate = db.query(WorldEmergenceCandidate.id).filter(
                WorldEmergenceCandidate.session_id == world.session_id,
                WorldEmergenceCandidate.source_event_runtime_id == source.id,
                WorldEmergenceCandidate.recipe_id == str(recipe_id),
                WorldEmergenceCandidate.outcome.in_(("selected", "selected_pending")),
            ).first()
            if duplicate is not None:
                continue
            slot = _start_slot(world, spec, recipe)
            if slot is None:
                continue
            day, minute = slot
            expiry_day, expiry_minute = _expiry_slot(world, day, minute, recipe)
            organizer_id = int(source.organizer_actor_key.split(":", 1)[1])
            invitee_sets = _candidate_invitee_sets(
                recipe=recipe, organizer_id=organizer_id, resident_ids=resident_ids
            )
            invitees = invitee_sets[0] if invitee_sets else []
            location_id = str(next(iter(recipe.get("location_ids", ())), ""))
            authorization = _permission_validation(
                world=world,
                spec=spec,
                recipe=recipe,
                organizer_id=organizer_id,
                location_id=location_id,
            )
            availability = (
                {
                    **_checked_availability(
                        db,
                        session_id=world.session_id,
                        request={
                            "start_day": day,
                            "start_time_minutes": minute,
                            "duration_minutes": int(recipe.get("duration_minutes", 0)),
                            "location_id": location_id,
                            "actors": [_actor_ref(f"resident:{organizer_id}", required=True), *invitees],
                            "object_ids": list(recipe.get("object_ids", ())),
                            "role_slots": list(recipe.get("role_slots", ())),
                        },
                    ),
                    "authorization": authorization,
                }
                if invitee_sets and location_id and authorization["available"]
                else {
                    **(
                        authorization
                        if not authorization["available"]
                        else {"available": False, "reason_code": "participant_bounds_unsatisfied"}
                    ),
                    "authorization": authorization,
                }
            )
            feasible = bool(availability.get("available")) and depth <= max_depth
            reason = "candidate_valid" if feasible else "chain_depth_limit" if depth > max_depth else str(availability.get("reason_code"))
            drafts.append(
                CandidateDraft(
                    candidate_key=f"{key_prefix}:{organizer_id}:{location_id}:{day}:{minute}",
                    recipe=recipe,
                    organizer_agent_id=organizer_id,
                    location_id=location_id,
                    scheduled_day=day,
                    scheduled_time_minutes=minute,
                    expires_day=expiry_day,
                    expires_time_minutes=expiry_minute,
                    invitees=invitees,
                    source_types=["world_outcome", "activity_recipe"],
                    source_facts=[
                        {"type": "world_outcome", "runtime_id": source.id, "status": source.status},
                        *[{"type": "world_outcome", "fact_id": fact.id, "provenance": "stage_execution"} for fact in outcome_facts],
                        {"type": "activity_recipe", "id": recipe_id, "version": spec.content_pack_version},
                    ],
                    validation=availability,
                    chain_depth=depth,
                    source_event_runtime_id=source.id,
                    feasible=feasible,
                    reason_code=reason,
                )
            )
    return drafts


def _daily_recipe_count(db: DBSession, session_id: int, day: int, recipe_id: str) -> int:
    return db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.session_id == session_id,
        WorldEmergentEventRuntime.started_day == day,
        WorldEmergentEventRuntime.recipe_id == recipe_id,
    ).count()


def _organizer_daily_count(db: DBSession, session_id: int, day: int, actor_key: str) -> int:
    return db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.session_id == session_id,
        WorldEmergentEventRuntime.started_day == day,
        WorldEmergentEventRuntime.organizer_actor_key == actor_key,
    ).count()


def _decline_cooldown(
    db: DBSession, *, session_id: int, world: WorldState, organizer_id: int, invitees: Iterable[Mapping[str, Any]], minutes: int
) -> bool:
    if minutes <= 0:
        return False
    keys = ["participant" if item["actor_type"] == "participant" else f"resident:{item['agent_id']}" for item in invitees]
    if not keys:
        return False
    rows = (
        db.query(WorldPlanTransition, WorldCommitment)
        .join(WorldCommitment, WorldCommitment.id == WorldPlanTransition.commitment_id)
        .filter(
            WorldPlanTransition.session_id == session_id,
            WorldPlanTransition.transition_type == "reject",
            WorldCommitment.organizer_type == "resident",
            WorldCommitment.organizer_agent_id == organizer_id,
        )
        .order_by(WorldPlanTransition.id.desc())
        .all()
    )
    now = _ordinal(world.current_day, world.current_time_minutes)
    for transition, _plan in rows:
        key = "participant" if transition.actor_type == "participant" else f"resident:{transition.actor_agent_id}"
        if key in keys and now - _ordinal(transition.world_day, transition.world_time_minutes) < minutes:
            return True
    return False


def _budget_snapshot(db: DBSession, *, world: WorldState, policy: Mapping[str, Any]) -> dict[str, Any]:
    day_rows = db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.session_id == world.session_id,
        WorldEmergentEventRuntime.started_day == world.current_day,
    ).all()
    concurrent = db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.session_id == world.session_id,
        WorldEmergentEventRuntime.player_facing.is_(True),
        WorldEmergentEventRuntime.status.in_(OPEN_EVENT_STATES),
    ).count()
    # A player's own request does not consume the unsolicited-event allowance.
    day_rows = [item for item in day_rows if item.organizer_actor_key != "participant"]
    return {
        "used": {
            "player_facing_today": sum(1 for item in day_rows if item.player_facing),
            "major_today": sum(1 for item in day_rows if item.complexity == "major"),
            "concurrent_player_facing": concurrent,
            "direct_agent_invitations_today": sum(
                1 for item in day_rows if item.direct_participant_invite
            ),
        },
        "limits": {
            key: int(policy.get(key, 0))
            for key in (
                "max_activity_creations_per_tick",
                "max_invitations_per_tick",
                "max_new_player_facing_events_per_day",
                "max_new_major_events_per_day",
                "max_concurrent_player_facing_events",
                "max_direct_agent_invitations_to_player_per_day",
                "same_recipe_daily_limit",
                "declined_pair_cooldown_minutes",
            )
        },
    }


def _rank_and_select(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    drafts: list[CandidateDraft],
) -> dict[str, Any]:
    emergence = _policy(spec, "emergence_policy")
    candidate_policy = _policy(spec, "candidate_policy")
    max_candidates = int(candidate_policy.get("max_candidates_per_evaluation", 0))
    allowed_sources = set(candidate_policy.get("allowed_source_types", ()))
    allowed_complexities = set(candidate_policy.get("allowed_complexities", ()))
    from services.contact_budget_service import daily_contacts, pending_fixed_recipes
    from world.interaction_policy import interaction_policy
    contact_policy = interaction_policy(spec)
    contacts = daily_contacts(db, world)
    pending_fixed = pending_fixed_recipes(db, world, spec)
    # Authored invitations must survive candidate truncation and ordinary ranking.
    drafts.sort(key=lambda item: item.recipe["recipe_id"] not in pending_fixed)
    # Remove unranked candidates before persistence.
    del drafts[max_candidates:]
    budget = _budget_snapshot(db, world=world, policy=emergence)
    for draft in drafts:
        complexity = str(draft.recipe.get("complexity", "ordinary"))
        if not set(draft.source_types) <= allowed_sources:
            draft.feasible = False
            draft.reason_code = "candidate_source_not_allowed"
        if complexity not in allowed_complexities:
            draft.feasible = False
            draft.reason_code = "candidate_complexity_not_allowed"
        repetition = _daily_recipe_count(db, world.session_id, world.current_day, str(draft.recipe["recipe_id"]))
        organizer_load = _organizer_daily_count(db, world.session_id, world.current_day, draft.organizer_key)
        stable_tiebreak = int(
            hashlib.sha256(f"{session.simulation_seed}:{draft.candidate_key}".encode("utf-8")).hexdigest()[:8], 16
        )
        score_total = 50 + (20 if "actor_goal" in draft.source_types else 0) - repetition * 10 - organizer_load * 5
        preferences = _json_loads(world.state_json, {}).get("resident_event_preferences_v1", {})
        preference = preferences.get(str(draft.organizer_agent_id), {})
        from services.plan_service import _ordinal
        preference_bonus = 5 if preference.get("recipe_id") == draft.recipe["recipe_id"] and preference.get("expires_ordinal", -1) >= _ordinal(world.current_day, world.current_time_minutes) else 0
        score_total += preference_bonus
        fixed_priority = 1000 if draft.recipe["recipe_id"] in pending_fixed else 0
        score_total += fixed_priority
        if draft.player_facing:
            score_total -= int(budget["used"]["player_facing_today"]) * 8
        draft.score = {
            "fixed_invitation_priority": fixed_priority,
            "resident_preference": preference_bonus,
            "goal_relevance": 20 if "actor_goal" in draft.source_types else 0,
            "feasibility": 50 if draft.feasible else 0,
            "recent_repetition_penalty": repetition * 10,
            "actor_distribution_penalty": organizer_load * 5,
            "player_pressure_penalty": int(budget["used"]["player_facing_today"]) * 8 if draft.player_facing else 0,
            "total": score_total if draft.feasible else -1000,
            "seed_tiebreak": stable_tiebreak,
        }
    drafts.sort(key=lambda item: (-int((item.score or {})["total"]), int((item.score or {})["seed_tiebreak"]), item.candidate_key))
    selected = 0
    invitations = 0
    reserved_proactive_agents = []
    used = dict(budget["used"])
    for rank, draft in enumerate(drafts, start=1):
        draft.rank = rank
        if not draft.feasible:
            draft.outcome = "blocked"
            continue
        complexity = str(draft.recipe.get("complexity", "ordinary"))
        recipe_count = _daily_recipe_count(db, world.session_id, world.current_day, str(draft.recipe["recipe_id"]))
        reason: str | None = None
        if (spec.world_version=='chaoxi-holiday-v6' and draft.player_facing
            and draft.recipe['recipe_id'] not in ('welcome','bonfire')):
            from services.holiday_social_v6 import daily_invitation_budget
            if not daily_invitation_budget(db,world,draft.organizer_agent_id,reserved_proactive_agents):
                draft.outcome='blocked';draft.reason_code='shared_resident_invitation_daily_limit'
                continue
        reserved_contacts = len(pending_fixed - {draft.recipe["recipe_id"]})
        if selected >= int(emergence.get("max_activity_creations_per_tick", 0)):
            reason = "activity_creation_tick_limit"
        elif invitations >= int(emergence.get("max_invitations_per_tick", 0)):
            reason = "invitation_tick_limit"
        elif recipe_count >= int(emergence.get("same_recipe_daily_limit", 0)):
            reason = "same_recipe_daily_limit"
        elif complexity == "major" and used["major_today"] >= int(emergence.get("max_new_major_events_per_day", 0)):
            reason = "major_daily_limit"
        elif draft.player_facing and used["player_facing_today"] >= int(emergence.get("max_new_player_facing_events_per_day", 0)):
            reason = "player_facing_daily_limit"
        elif draft.player_facing and used["concurrent_player_facing"] >= int(emergence.get("max_concurrent_player_facing_events", 0)):
            reason = "player_facing_concurrent_limit"
        elif draft.direct_participant_invite and used["direct_agent_invitations_today"] >= int(emergence.get("max_direct_agent_invitations_to_player_per_day", 0)):
            reason = "direct_invitation_daily_limit"
        elif draft.direct_participant_invite and contact_policy and contacts >= max(0, contact_policy.max_contacts_per_day - reserved_contacts):
            reason = "shared_contact_daily_limit"
        elif _decline_cooldown(
            db,
            session_id=world.session_id,
            world=world,
            organizer_id=draft.organizer_agent_id,
            invitees=draft.invitees,
            minutes=int(emergence.get("declined_pair_cooldown_minutes", 0)),
        ):
            reason = "declined_pair_cooldown"
        if reason is not None:
            draft.outcome = "blocked"
            draft.reason_code = reason
            continue
        draft.outcome = "selected_pending"
        draft.reason_code = "selected_by_budgeted_rank"
        selected += 1
        invitations += 1
        if draft.player_facing and draft.recipe['recipe_id'] not in ('welcome','bonfire'):
            reserved_proactive_agents.append(draft.organizer_agent_id)
        if draft.player_facing:
            used["player_facing_today"] += 1
            used["concurrent_player_facing"] += 1
        if draft.direct_participant_invite:
            used["direct_agent_invitations_today"] += 1
            contacts += 1
        pending_fixed.discard(draft.recipe["recipe_id"])
        if complexity == "major":
            used["major_today"] += 1
    budget["projected"] = used
    budget["selected_this_evaluation"] = selected
    budget["candidate_count"] = len(drafts)
    return budget


def _persist_evaluation(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    payload: Mapping[str, Any],
    request_hash: str,
    fingerprint: str,
    drafts: list[CandidateDraft],
    budget: Mapping[str, Any],
) -> WorldEmergenceEvaluation:
    policy = _policy(spec, "emergence_policy")
    evaluation = WorldEmergenceEvaluation(
        session_id=session.id,
        idempotency_key=str(payload["idempotency_key"]),
        request_hash=request_hash,
        source=str(payload["source"]),
        source_pulse_id=payload.get("source_pulse_id"),
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        simulation_seed=session.simulation_seed,
        policy_id=str(policy.get("policy_id")),
        policy_version=str(policy.get("policy_version")),
        state_fingerprint=fingerprint,
        status="processing",
        candidate_count=len(drafts),
        selected_count=0,
        budget_json=_json_dumps(budget),
        result_json="{}",
    )
    db.add(evaluation)
    db.flush()
    for draft in drafts:
        candidate = WorldEmergenceCandidate(
            evaluation_id=evaluation.id,
            session_id=session.id,
            candidate_key=draft.candidate_key,
            recipe_id=str(draft.recipe["recipe_id"]),
            complexity=str(draft.recipe.get("complexity", "ordinary")),
            player_facing=draft.player_facing,
            direct_participant_invite=draft.direct_participant_invite,
            organizer_actor_key=draft.organizer_key,
            location_id=draft.location_id,
            scheduled_day=draft.scheduled_day,
            scheduled_time_minutes=draft.scheduled_time_minutes,
            expires_day=draft.expires_day,
            expires_time_minutes=draft.expires_time_minutes,
            chain_depth=draft.chain_depth,
            source_event_runtime_id=draft.source_event_runtime_id,
            source_types_json=_json_dumps(draft.source_types),
            source_facts_json=_json_dumps(draft.source_facts),
            invitees_json=_json_dumps(draft.invitees),
            validation_json=_json_dumps(draft.validation),
            score_json=_json_dumps(draft.score or {}),
            rank=draft.rank,
            outcome=draft.outcome,
            reason_code=draft.reason_code,
        )
        db.add(candidate)
        db.flush()
        db.add(
            WorldEmergenceDecision(
                session_id=session.id,
                source_action_id=None,
                candidate_type="activity_recipe",
                candidate_id=draft.candidate_key,
                outcome="selected" if draft.outcome == "selected_pending" else "blocked",
                reason_code=draft.reason_code,
                rank=draft.rank,
                simulation_seed=session.simulation_seed,
                policy_id=evaluation.policy_id,
                policy_version=evaluation.policy_version,
                snapshot_json=_json_dumps(
                    {
                        "evaluation_id": evaluation.id,
                        "source_types": draft.source_types,
                        "source_facts": draft.source_facts,
                        "validation": draft.validation,
                        "score": draft.score,
                    }
                ),
            )
        )
    db.commit()
    db.refresh(evaluation)
    return evaluation


def _instantiate_candidate(
    db: DBSession,
    *,
    evaluation: WorldEmergenceEvaluation,
    candidate: WorldEmergenceCandidate,
    spec: WorldSpec,
    language: str,
) -> None:
    recipe = next(
        item
        for item in spec.systems.get("activity_recipes", ())
        if item.get("recipe_id") == candidate.recipe_id
    )
    invitees = _json_loads(candidate.invitees_json, [])
    invitation_key = _candidate_invitation_key(evaluation.id, candidate.candidate_key)
    label = recipe.get("label", {})
    message = str(label.get(language) or label.get("en") or candidate.recipe_id)
    if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        message = (f'今晚准备了一个{message}，大家有空来坐坐，认识一下新邻居。' if candidate.recipe_id == 'welcome'
                   else f'最后一晚想约大家围着篝火坐坐，说说这几天的见闻。' if candidate.recipe_id == 'bonfire'
                   else f'我打算去{spec.locations[candidate.location_id].name.get(language, candidate.location_id)}，想{message}。有人愿意一起吗？')
    result = create_phone_invitation(
        db,
        session_id=evaluation.session_id,
        organizer_type="resident",
        organizer_agent_id=int(candidate.organizer_actor_key.split(":", 1)[1]),
        request={
            "recipe_id": candidate.recipe_id,
            "idempotency_key": invitation_key,
            "audience_scope": "targeted" if invitees else "public",
            "invitees": invitees,
            "location_id": candidate.location_id,
            "start_day": candidate.scheduled_day,
            "start_time_minutes": candidate.scheduled_time_minutes,
            "deadline_day": candidate.expires_day,
            "deadline_time_minutes": candidate.expires_time_minutes,
            "organizer_attending": True,
            "public_headcount": True,
            "project_to_board": (
                True
                if not invitees
                else bool(_conditions(recipe).get("project_to_board", False))
            ),
            "message": message,
            "language": language,
        },
    )
    commitment_id = int(result["invitation"]["plan_id"])
    if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and candidate.recipe_id in ('welcome', 'bonfire'):
        # These two authored community gatherings have a scripted resident cast.
        # Player RSVP is always left for the player; ordinary activities use agents.
        for guest in invitees:
            if guest.get('actor_type') != 'resident':
                continue
            plan = db.get(WorldCommitment, commitment_id)
            try:
                transition_plan(db, session_id=evaluation.session_id, commitment_id=commitment_id,
                    actor_type='resident', actor_agent_id=guest['agent_id'], request={
                        'transition':'accept', 'expected_revision':plan.revision,
                        'idempotency_key':f'authored-party:{commitment_id}:{guest["agent_id"]}',
                        'reason_code':'authored_community_gathering'})
            except PlanServiceError:
                db.rollback()
    db.rollback()
    candidate = db.query(WorldEmergenceCandidate).filter(WorldEmergenceCandidate.id == candidate.id).one()
    existing = db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.commitment_id == commitment_id
    ).first()
    if existing is None:
        instance = WorldEventInstance(
            session_id=evaluation.session_id,
            event_type="emergent_activity",
            event_version=DIRECTOR_RUNTIME_VERSION,
            status="emergent_pending",
            location_id=candidate.location_id,
            state_json=_json_dumps({"plan_status": result["invitation"]["status"]}),
            trigger_key=f"m7e:{commitment_id}",
            started_day=evaluation.world_day,
            started_time_minutes=evaluation.world_time_minutes,
            metadata_json=_json_dumps(
                {
                    "runtime_version": DIRECTOR_RUNTIME_VERSION,
                    "candidate_id": candidate.id,
                    "commitment_id": commitment_id,
                    "fact_chain_id": str(commitment_id),
                    "chain_depth": candidate.chain_depth,
                }
            ),
        )
        db.add(instance)
        db.flush()
        runtime = WorldEmergentEventRuntime(
            session_id=evaluation.session_id,
            candidate_id=candidate.id,
            event_instance_id=instance.id,
            commitment_id=commitment_id,
            recipe_id=candidate.recipe_id,
            complexity=candidate.complexity,
            player_facing=candidate.player_facing,
            direct_participant_invite=candidate.direct_participant_invite,
            organizer_actor_key=candidate.organizer_actor_key,
            status="proposed",
            chain_depth=candidate.chain_depth,
            fact_chain_id=str(commitment_id),
            started_day=evaluation.world_day,
            started_time_minutes=evaluation.world_time_minutes,
            expires_day=candidate.expires_day,
            expires_time_minutes=candidate.expires_time_minutes,
            revision=0,
            metadata_json=_json_dumps(
                {
                    "source_event_runtime_id": candidate.source_event_runtime_id,
                    "source_types": _json_loads(candidate.source_types_json, []),
                }
            ),
        )
        db.add(runtime)
        db.flush()
        candidate.selected_event_instance_id = instance.id
    else:
        candidate.selected_event_instance_id = existing.event_instance_id
    candidate.selected_commitment_id = commitment_id
    candidate.outcome = "selected"
    candidate.reason_code = "event_instantiated"
    db.commit()


def evaluate_emergence(db: DBSession, *, session_id: int, request: Any) -> dict[str, Any]:
    payload = _request_payload(request)
    request_hash = _stable_hash(payload)
    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldEmergenceEvaluation).filter(
            WorldEmergenceEvaluation.session_id == session_id,
            WorldEmergenceEvaluation.idempotency_key == payload["idempotency_key"],
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise EmergenceDirectorError(
                    "Evaluation key was reused with another payload.", reason_code="idempotency_conflict"
                )
        if existing is not None and existing.status == "completed":
            result = _evaluation_response(db, existing)
            result["status"] = "existing"
            return result
        session, world, spec = _world_and_spec(db, session_id)
        if existing is not None:
            evaluation = existing
        else:
            _validate_request(payload, world)
            if payload["source"] == "foreground_pulse":
                pulse = db.query(WorldSimulationPulse).filter(
                    WorldSimulationPulse.id == payload["source_pulse_id"],
                    WorldSimulationPulse.session_id == session_id,
                    WorldSimulationPulse.status == "accepted",
                ).first()
                if pulse is None:
                    raise EmergenceDirectorError(
                        "An accepted pulse in this Session is required.",
                        reason_code="invalid_source_pulse", status_code=422,
                    )
            elif payload["source_pulse_id"] is not None:
                raise EmergenceDirectorError(
                    "Manual evaluations cannot claim a pulse source.",
                    reason_code="invalid_source_pulse", status_code=422,
                )
            evaluation_count = db.query(WorldEmergenceEvaluation).filter(
                WorldEmergenceEvaluation.session_id == session_id,
                WorldEmergenceEvaluation.world_day == world.current_day,
            ).count()
            if evaluation_count >= MAX_EVALUATIONS_PER_DAY:
                raise EmergenceDirectorError(
                    "The daily director evaluation safety bound was reached.",
                    reason_code="evaluation_daily_limit", status_code=429,
                )
            reconcile_emergent_events(db, session_id=session_id)
            db.rollback()
            session, world, spec = _world_and_spec(db, session_id)
            fingerprint = _state_fingerprint(db, world, spec)
            drafts = [*_followup_drafts(db, world=world, spec=spec), *_base_drafts(db, world=world, spec=spec)]
            # One input fact combination enters arbitration only once per pass.
            drafts = list({item.candidate_key: item for item in drafts}.values())
            budget = _rank_and_select(
                db, session=session, world=world, spec=spec, drafts=drafts
            )
            evaluation = _persist_evaluation(
                db,
                session=session,
                world=world,
                spec=spec,
                payload=payload,
                request_hash=request_hash,
                fingerprint=fingerprint,
                drafts=drafts,
                budget=budget,
            )
        selected = (
            db.query(WorldEmergenceCandidate)
            .filter(
                WorldEmergenceCandidate.evaluation_id == evaluation.id,
                WorldEmergenceCandidate.outcome == "selected_pending",
            )
            .order_by(WorldEmergenceCandidate.rank.asc())
            .all()
        )
        for candidate in selected:
            try:
                _instantiate_candidate(
                    db,
                    evaluation=evaluation,
                    candidate=candidate,
                    spec=spec,
                    language=str(payload["language"]),
                )
            except (PhonePlanError, PlanServiceError, StopIteration, ValueError, RuntimeError) as exc:
                db.rollback()
                # Close the committed plan if its phone projection fails.
                creation = db.query(WorldPlanTransition).filter(
                    WorldPlanTransition.session_id == session_id,
                    WorldPlanTransition.idempotency_key == f"phone-plan:{_candidate_invitation_key(evaluation.id, candidate.candidate_key)}",
                ).first()
                if creation is not None:
                    plan = db.query(WorldCommitment).filter(WorldCommitment.id == creation.commitment_id).one()
                    if plan.status in ACTIVE_PLAN_STATES:
                        transition_plan(
                            db, session_id=session_id, commitment_id=plan.id,
                            actor_type=plan.organizer_type, actor_agent_id=plan.organizer_agent_id,
                            request={"transition": "fail", "idempotency_key": f"m7e-compensate:{candidate.id}",
                                     "expected_revision": plan.revision, "reason_code": "instantiation_failed"},
                        )
                    db.rollback()
                row = db.query(WorldEmergenceCandidate).filter(
                    WorldEmergenceCandidate.id == candidate.id
                ).one()
                row.outcome = "blocked" if isinstance(exc, PlanServiceError) and creation is None else "technical_failure"
                row.reason_code = getattr(exc, "reason_code", "instantiation_failed")
                decision = db.query(WorldEmergenceDecision).filter(
                    WorldEmergenceDecision.session_id == session_id,
                    WorldEmergenceDecision.candidate_id == row.candidate_key,
                ).order_by(WorldEmergenceDecision.id.desc()).first()
                if decision is not None:
                    decision.outcome = row.outcome
                    decision.reason_code = row.reason_code
                db.commit()
        db.rollback()
        evaluation = db.query(WorldEmergenceEvaluation).filter(
            WorldEmergenceEvaluation.id == evaluation.id
        ).one()
        evaluation.selected_count = db.query(WorldEmergenceCandidate).filter(
            WorldEmergenceCandidate.evaluation_id == evaluation.id,
            WorldEmergenceCandidate.outcome == "selected",
        ).count()
        evaluation.status = "completed"
        evaluation.updated_at = _utc_now()
        budget = _json_loads(evaluation.budget_json, {})
        budget["actual_after"] = _budget_snapshot(db, world=world, policy=_policy(spec, "emergence_policy"))["used"]
        evaluation.budget_json = _json_dumps(budget)
        db.flush()
        result = _evaluation_response(db, evaluation)
        evaluation.result_json = _json_dumps(result)
        db.commit()
        db.refresh(evaluation)
        return _evaluation_response(db, evaluation)


def list_emergence_state(db: DBSession, *, session_id: int) -> dict[str, Any]:
    _session, world, _spec = _world_and_spec(db, session_id)
    reconcile_emergent_events(db, session_id=session_id)
    db.rollback()
    evaluations = (
        db.query(WorldEmergenceEvaluation)
        .filter(WorldEmergenceEvaluation.session_id == session_id)
        .order_by(WorldEmergenceEvaluation.id.desc())
        .all()
    )
    events = (
        db.query(WorldEmergentEventRuntime)
        .filter(WorldEmergentEventRuntime.session_id == session_id)
        .order_by(WorldEmergentEventRuntime.id.asc())
        .all()
    )
    return {
        "runtime_version": DIRECTOR_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "evaluations": [
            {
                "evaluation_id": item.id,
                "status": item.status,
                "source": item.source,
                "world_day": item.world_day,
                "world_time_minutes": item.world_time_minutes,
                "candidate_count": item.candidate_count,
                "selected_count": item.selected_count,
            }
            for item in evaluations
        ],
        "events": [_serialize_event(db, item) for item in events],
    }


def transition_emergent_event(
    db: DBSession, *, session_id: int, runtime_id: int, request: Any
) -> dict[str, Any]:
    with session_write_lock(session_id):
        return _transition_emergent_event(db, session_id=session_id, runtime_id=runtime_id, request=request)


def _transition_emergent_event(
    db: DBSession, *, session_id: int, runtime_id: int, request: Any
) -> dict[str, Any]:
    transition_type = str(_value(request, "transition"))
    key = str(_value(request, "idempotency_key"))
    if transition_type not in ("reconcile", "technical_failure"):
        raise EmergenceDirectorError(
            "Unknown event transition.", reason_code="invalid_request", status_code=422
        )
    _session, world, _spec = _world_and_spec(db, session_id)
    runtime = db.query(WorldEmergentEventRuntime).filter(
        WorldEmergentEventRuntime.id == runtime_id,
        WorldEmergentEventRuntime.session_id == session_id,
    ).first()
    if runtime is None:
        raise EmergenceDirectorError("Emergent event not found.", reason_code="unknown_event", status_code=404)
    existing = db.query(WorldEmergentEventTransition).filter(
        WorldEmergentEventTransition.runtime_id == runtime_id,
        WorldEmergentEventTransition.transition_key == f"manual:{key}",
    ).first()
    if existing is not None:
        if existing.transition_type != transition_type:
            raise EmergenceDirectorError(
                "Event transition key was reused with another operation.",
                reason_code="idempotency_conflict",
            )
        return {"status": "existing", "event": _serialize_event(db, runtime)}
    if transition_type == "technical_failure" and runtime.status not in TERMINAL_EVENT_STATES:
        plan = db.query(WorldCommitment).filter(WorldCommitment.id == runtime.commitment_id).one()
        if plan.status in ACTIVE_PLAN_STATES:
            transition_plan(
                db,
                session_id=session_id,
                commitment_id=plan.id,
                actor_type=plan.organizer_type,
                actor_agent_id=plan.organizer_agent_id,
                request={
                    "transition": "fail",
                    "idempotency_key": f"m7e-technical:{runtime.id}:{key}",
                    "expected_revision": plan.revision,
                    "reason_code": "emergent_event_technical_failure",
                },
            )
        db.rollback()
        runtime = db.query(WorldEmergentEventRuntime).filter(WorldEmergentEventRuntime.id == runtime_id).one()
        before = runtime.status
        runtime.status = "failed"
        runtime.terminal_reason_code = "emergent_event_technical_failure"
        runtime.completed_day = world.current_day
        runtime.completed_time_minutes = world.current_time_minutes
        runtime.revision += 1
        instance = db.query(WorldEventInstance).filter(WorldEventInstance.id == runtime.event_instance_id).one()
        instance.status = "failed"
        instance.outcome_code = "emergent_event_technical_failure"
        instance.completed_day = world.current_day
        instance.completed_time_minutes = world.current_time_minutes
        instance.completed_at = _utc_now()
        db.add(
            WorldEmergentEventTransition(
                session_id=session_id,
                runtime_id=runtime.id,
                transition_key=f"manual:{key}",
                transition_type="technical_failure",
                before_status=before,
                after_status="failed",
                reason_code="emergent_event_technical_failure",
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
            )
        )
        db.commit()
    else:
        reconcile_emergent_events(db, session_id=session_id)
        runtime = db.query(WorldEmergentEventRuntime).filter(WorldEmergentEventRuntime.id == runtime_id).one()
        db.add(WorldEmergentEventTransition(
            session_id=session_id, runtime_id=runtime_id,
            transition_key=f"manual:{key}", transition_type=transition_type,
            before_status=runtime.status, after_status=runtime.status,
            reason_code="explicit_reconciliation",
            world_day=world.current_day, world_time_minutes=world.current_time_minutes,
        ))
        db.commit()
    db.rollback()
    runtime = db.query(WorldEmergentEventRuntime).filter(WorldEmergentEventRuntime.id == runtime_id).one()
    return {"status": "completed", "event": _serialize_event(db, runtime)}
