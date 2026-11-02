"""Activity plans, reservations, and attendance."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    ResidentIntentState,
    Session as UserSession,
    WorldCommitment,
    WorldConversation,
    WorldPlanMember,
    WorldPlanNotice,
    WorldPlanTransition,
    WorldResourceReservation,
    WorldState,
)
from services.world_service import session_write_lock, world_has_ended
from world.emergence_contracts import MODULAR_SYSTEMS_CONTRACT_VERSION
from world.graph import object_exists, shortest_travel_path
from world.registry import get_world_spec
from world.specs import ResidentSpec, ScheduleBlock, WorldSpec


PLAN_RUNTIME_VERSION = "plan-runtime-v1"
from content.experience_next import enabled as next_enabled, active as next_active
PLAN_WAIT_MINUTES = 30 if next_enabled() else 15
ACTIVE_PLAN_STATES = ("proposed", "accepted", "in_progress")
TERMINAL_PLAN_STATES = ("rejected", "cancelled", "expired", "completed", "failed")
ACTIVE_RESERVATION_STATES = ("tentative", "confirmed")


class PlanServiceError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason_code = reason_code
        self.status_code = status_code


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


def _actor_key(actor_type: str, agent_id: int | None) -> str:
    if actor_type == "participant":
        if agent_id is not None:
            raise PlanServiceError(
                "Participant references cannot include an agent id.",
                reason_code="unknown_actor",
                status_code=422,
            )
        return "participant"
    if actor_type == "resident" and isinstance(agent_id, int) and not isinstance(agent_id, bool):
        return f"resident:{agent_id}"
    raise PlanServiceError(
        "Resident references require a valid agent id.",
        reason_code="unknown_actor",
        status_code=422,
    )


def _actor_parts(actor_key: str) -> tuple[str, int | None]:
    if actor_key == "participant":
        return "participant", None
    if actor_key.startswith("resident:"):
        try:
            return "resident", int(actor_key.split(":", 1)[1])
        except ValueError as exc:
            raise PlanServiceError(
                "Stored plan actor key is invalid.", reason_code="unknown_actor"
            ) from exc
    raise PlanServiceError("Stored plan actor key is invalid.", reason_code="unknown_actor")


def _ordinal(day: int, minute: int) -> int:
    return (day - 1) * 1440 + minute


def _position(ordinal: int) -> tuple[int, int]:
    return ordinal // 1440 + 1, ordinal % 1440


def _request_hash(payload: Mapping[str, Any]) -> str:
    try:
        encoded = _json_dumps(dict(payload)).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlanServiceError(
            "Plan request must be JSON-compatible.",
            reason_code="invalid_request",
            status_code=422,
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _world_and_spec(db: DBSession, session_id: int) -> tuple[WorldState, WorldSpec]:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session is None:
        raise PlanServiceError("Session not found.", reason_code="unknown_session", status_code=404)
    if session.status != "active":
        raise PlanServiceError("Session is not active.", reason_code="session_inactive")
    world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
    if world is None:
        raise PlanServiceError("World state not found.", reason_code="unknown_world", status_code=404)
    if world_has_ended(world):
        raise PlanServiceError("The bound world has ended.", reason_code="world_ended")
    try:
        spec = get_world_spec(world.world_version)
    except KeyError as exc:
        raise PlanServiceError("Bound world specification is unavailable.", reason_code="unknown_world") from exc
    if spec.scenario_pack_version != world.scenario_pack_version:
        raise PlanServiceError("Bound world versions do not match.", reason_code="unknown_world")
    if (
        spec.content_schema_version != "content-pack-v5"
        or spec.systems.get("contract_version") != MODULAR_SYSTEMS_CONTRACT_VERSION
    ):
        raise PlanServiceError(
            "The bound world has not enabled the M7 plan runtime contract.",
            reason_code="runtime_unavailable",
        )
    return world, spec


def _recipe(spec: WorldSpec, recipe_id: str) -> Mapping[str, Any]:
    for item in spec.systems.get("activity_recipes", ()):
        if item.get("recipe_id") == recipe_id:
            return item
    if spec.world_version == "chaoxi-holiday-v6" and recipe_id in ("rope_practice", "volley_match"):
        # Tombstones preserve history but cannot create new plans.
        label="绳结练习" if recipe_id=="rope_practice" else "四人排球小场"
        return {"recipe_id":recipe_id,"label":{"zh-CN":label+"（已下架）","en":"Retired activity"},
                "conditions":{},"retired":True,"action_ids":[],"object_ids":[],"location_ids":[]}
    raise PlanServiceError(
        "Activity recipe does not exist in the bound world.",
        reason_code="unknown_recipe",
        status_code=422,
    )


def _plan_policy(spec: WorldSpec) -> Mapping[str, Any]:
    value = spec.systems.get("plan_policy")
    if not isinstance(value, Mapping):
        raise PlanServiceError("Plan policy is unavailable.", reason_code="runtime_unavailable")
    return value


def _emergence_policy(spec: WorldSpec) -> Mapping[str, Any]:
    value = spec.systems.get("emergence_policy")
    if not isinstance(value, Mapping):
        raise PlanServiceError("Emergence policy is unavailable.", reason_code="runtime_unavailable")
    return value


def _validate_interval(
    spec: WorldSpec,
    *,
    start_day: int,
    start_time_minutes: int,
    duration_minutes: int,
) -> tuple[int, int]:
    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and (start_time_minutes%5 or duration_minutes%5):
        raise PlanServiceError('新版安排必须使用五分钟刻度。',reason_code='invalid_time_quantum',status_code=422)
    if not 1 <= start_day <= spec.calendar.total_days:
        raise PlanServiceError("Plan day is outside the world calendar.", reason_code="invalid_time", status_code=422)
    if duration_minutes <= 0 or duration_minutes > 480:
        raise PlanServiceError("Plan duration must be between 1 and 480 minutes.", reason_code="invalid_time", status_code=422)
    if not spec.calendar.day_start_minute <= start_time_minutes <= spec.calendar.day_end_minute:
        raise PlanServiceError("Plan start is outside the playable day.", reason_code="invalid_time", status_code=422)
    end_time = start_time_minutes + duration_minutes
    if end_time > spec.calendar.day_end_minute + 1:
        raise PlanServiceError("Plans cannot cross the playable-day boundary.", reason_code="invalid_time", status_code=422)
    return _ordinal(start_day, start_time_minutes), _ordinal(start_day, end_time)


def _travel_minutes(spec: WorldSpec, source_id: str, target_id: str) -> int | None:
    path = shortest_travel_path(spec, source_id, target_id)
    if path is None:
        return None
    return max(0, len(path) - 1) * int(spec.action_minutes.get("move", 0))


def _resident_free_block(
    resident: ResidentSpec,
    *,
    day: int,
    start_minute: int,
    end_minute: int,
) -> ScheduleBlock | None:
    for block in resident.schedule:
        if block.days is not None and day not in block.days:
            continue
        if (
            block.state_id in resident.autonomy.free_time_state_ids
            and block.start_minute <= start_minute
            and end_minute - 1 <= block.end_minute
        ):
            return block
    return None


def _next_fixed_block(
    resident: ResidentSpec, *, day: int, after_minute: int
) -> ScheduleBlock | None:
    candidates = [
        block
        for block in resident.schedule
        if (block.days is None or day in block.days)
        and block.state_id not in resident.autonomy.free_time_state_ids
        and block.start_minute >= after_minute
    ]
    return min(candidates, key=lambda item: (item.start_minute, item.state_id), default=None)


def resident_is_in_active_plan(db: DBSession, *, session_id: int, agent_id: int, location_id: str) -> bool:
    return db.query(WorldCommitment.id).join(
        WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id,
    ).filter(
        WorldCommitment.session_id == session_id,
        WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
        WorldCommitment.status == "in_progress",
        WorldPlanMember.actor_key == f"resident:{agent_id}",
        WorldPlanMember.attendance_status.in_(("present", "late")),
        WorldCommitment.location_id == location_id,
    ).first() is not None


def _actor_location(
    db: DBSession, *, world: WorldState, actor_type: str, agent_id: int | None
) -> str:
    if actor_type == "participant":
        return world.participant_location_id
    row = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == world.session_id,
            CharacterState.agent_id == agent_id,
        )
        .first()
    )
    if row is None:
        raise PlanServiceError("Resident actor was not found.", reason_code="unknown_actor", status_code=404)
    return row.current_location_id


def _active_actor_plans(
    db: DBSession,
    *,
    session_id: int,
    actor_key: str,
    exclude_commitment_id: int | None,
    accepted_only: bool = False,
) -> list[tuple[WorldCommitment, WorldPlanMember]]:
    query = (
        db.query(WorldCommitment, WorldPlanMember)
        .join(WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id)
        .filter(
            WorldCommitment.session_id == session_id,
            WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
            WorldCommitment.status.in_(ACTIVE_PLAN_STATES),
            WorldPlanMember.actor_key == actor_key,
            WorldPlanMember.response_status.in_(("accepted",) if accepted_only else ("proposed", "deferred", "accepted")),
        )
    )
    if exclude_commitment_id is not None:
        query = query.filter(WorldCommitment.id != exclude_commitment_id)
    return query.order_by(WorldCommitment.scheduled_day, WorldCommitment.scheduled_time_minutes).all()


def _route_feasibility(
    db: DBSession,
    *,
    world: WorldState,
    spec: WorldSpec,
    actor_type: str,
    agent_id: int | None,
    actor_key: str,
    location_id: str,
    start_ordinal: int,
    end_ordinal: int,
    exclude_commitment_id: int | None,
) -> tuple[bool, str, dict[str, Any]]:
    start_day, start_minute = _position(start_ordinal)
    _, end_minute = _position(end_ordinal)
    plans = _active_actor_plans(
        db,
        session_id=world.session_id,
        actor_key=actor_key,
        exclude_commitment_id=exclude_commitment_id,
        accepted_only=spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'),
    )

    previous_ordinal: int | None = None
    previous_location: str | None = None
    next_ordinal: int | None = None
    next_location: str | None = None
    for plan, _member in plans:
        plan_start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
        plan_end = plan_start + plan.duration_minutes + (30 if next_enabled() and plan.recipe_id not in ("welcome","bonfire") else 0)
        if plan_end <= start_ordinal and (previous_ordinal is None or plan_end > previous_ordinal):
            previous_ordinal, previous_location = plan_end, plan.location_id
        if plan_start >= end_ordinal and (next_ordinal is None or plan_start < next_ordinal):
            next_ordinal, next_location = plan_start, plan.location_id

    if actor_type == "resident":
        resident = spec.residents.get(int(agent_id or 0))
        if resident is None:
            return False, "unknown_actor", {}
        free_block = _resident_free_block(
            resident,
            day=start_day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        soft_schedule = spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6')
        if free_block is None and not soft_schedule:
            return False, "fixed_schedule_conflict", {}
        if soft_schedule and previous_ordinal is None:
            character = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=agent_id).first()
            previous_ordinal = _ordinal(world.current_day, world.current_time_minutes)
            previous_location = character.current_location_id if character else resident.home_location_id
        elif not soft_schedule and (previous_ordinal is None or previous_ordinal < _ordinal(start_day, free_block.start_minute)):
            previous_ordinal = _ordinal(start_day, free_block.start_minute)
            previous_location = free_block.location_id
        from content.experience_next import enabled as next_local, VISITORS
        fixed_next = None if next_local() and agent_id in VISITORS else _next_fixed_block(resident, day=start_day, after_minute=end_minute)
        if fixed_next is not None:
            fixed_ordinal = _ordinal(start_day, fixed_next.start_minute)
            if next_ordinal is None or fixed_ordinal < next_ordinal:
                next_ordinal, next_location = fixed_ordinal, fixed_next.location_id
    elif start_day == world.current_day and previous_ordinal is None:
        previous_ordinal = _ordinal(world.current_day, world.current_time_minutes)
        previous_location = world.participant_location_id

    details: dict[str, Any] = {}
    if previous_ordinal is not None and previous_location is not None:
        travel = _travel_minutes(spec, previous_location, location_id)
        details["travel_from_previous_minutes"] = travel
        if travel is None:
            return False, "route_unreachable", details
        if previous_ordinal + travel > start_ordinal:
            return False, "travel_from_previous_conflict", details
    if next_ordinal is not None and next_location is not None:
        travel = _travel_minutes(spec, location_id, next_location)
        details["travel_to_next_minutes"] = travel
        if travel is None:
            return False, "route_unreachable", details
        if end_ordinal + travel > next_ordinal:
            return False, "travel_to_next_conflict", details
    return True, "available", details


def _runtime_action_conflict(
    db: DBSession,
    *,
    world: WorldState,
    actor_type: str,
    agent_id: int | None,
    start_ordinal: int,
    end_ordinal: int,
    allow_soft_jobs: bool = False,
) -> bool:
    from services.scheduled_action_service import jobs
    key = _actor_key(actor_type, agent_id)
    from services.holiday_flex_service import can_pause
    if any(j["actor_key"] == key and start_ordinal < j["end_ordinal"] and end_ordinal > j["start_ordinal"] and not (allow_soft_jobs and can_pause(db,world,j)) for j in jobs(world)):
        return True
    now = _ordinal(world.current_day, world.current_time_minutes)
    for conversation in db.query(WorldConversation).filter_by(session_id=world.session_id, status="active", conversation_kind="participant_resident"):
        if actor_type == "resident" and conversation.agent_id != agent_id:
            continue
        metadata = _json_loads(conversation.metadata_json, {})
        if metadata.get("time_policy") == "session-interaction-v1" and metadata["slot_start_ordinal"] < end_ordinal and start_ordinal < metadata["slot_end_ordinal"]:
            return True
    if actor_type == "participant":
        if not start_ordinal <= now < end_ordinal:
            return False
        return (
            db.query(WorldConversation.id)
            .filter(
                WorldConversation.session_id == world.session_id,
                WorldConversation.status == "active",
                WorldConversation.conversation_kind == "participant_resident",
            )
            .first()
            is not None
        )
    intent = (
        db.query(ResidentIntentState)
        .filter(
            ResidentIntentState.session_id == world.session_id,
            ResidentIntentState.agent_id == agent_id,
            ResidentIntentState.status == "active",
        )
        .first()
    )
    if intent is None:
        return False
    # Do not count the resolved schedule block as another reservation.
    if intent.intent_type == "follow_schedule":
        return False
    if intent.intent_type == "greet_participant":
        from world.interaction_policy import interaction_policy
        if interaction_policy(get_world_spec(world.world_version)):
            return False
    intent_start = _ordinal(intent.started_day, intent.started_time_minutes)
    intent_end = _ordinal(intent.due_day, intent.due_time_minutes)
    return intent_start < end_ordinal and start_ordinal < intent_end


def _resource_conflicts(
    db: DBSession,
    *,
    session_id: int,
    resource_keys: Iterable[tuple[str, str]],
    start_ordinal: int,
    end_ordinal: int,
    exclude_commitment_id: int | None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for resource_type, resource_key in resource_keys:
        query = db.query(WorldResourceReservation).filter(
            WorldResourceReservation.session_id == session_id,
            WorldResourceReservation.resource_type == resource_type,
            WorldResourceReservation.resource_key == resource_key,
            WorldResourceReservation.status.in_(ACTIVE_RESERVATION_STATES),
            WorldResourceReservation.start_ordinal < end_ordinal,
            WorldResourceReservation.end_ordinal > start_ordinal,
        )
        if exclude_commitment_id is not None:
            query = query.filter(WorldResourceReservation.commitment_id != exclude_commitment_id)
        row = query.order_by(WorldResourceReservation.id.asc()).first()
        if row is not None:
            conflicts.append(
                {
                    "resource_type": resource_type,
                    "resource_key": resource_key,
                    "commitment_id": row.commitment_id,
                    "reservation_status": row.status,
                }
            )
    return conflicts


def _normalize_actor_refs(refs: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    roles: set[str] = set()
    for ref in refs:
        actor_type = str(_value(ref, "actor_type") or "")
        agent_id = _value(ref, "agent_id")
        key = _actor_key(actor_type, agent_id)
        if key in seen:
            raise PlanServiceError("A plan cannot list the same actor twice.", reason_code="duplicate_actor", status_code=422)
        role_id = _value(ref, "role_id")
        if role_id is not None:
            role_id = str(role_id)
            if role_id in roles:
                raise PlanServiceError("A plan role slot cannot be assigned twice.", reason_code="duplicate_role", status_code=422)
            roles.add(role_id)
        seen.add(key)
        result.append(
            {
                "actor_type": actor_type,
                "agent_id": agent_id,
                "actor_key": key,
                "role_id": role_id,
                "required": bool(_value(ref, "required", False)),
            }
        )
    return result


def _availability(
    db: DBSession,
    *,
    world: WorldState,
    spec: WorldSpec,
    start_day: int,
    start_time_minutes: int,
    duration_minutes: int,
    location_id: str,
    actors: list[dict[str, Any]],
    object_ids: list[str],
    role_slots: list[str],
    exclude_commitment_id: int | None = None,
    allow_soft_jobs: bool = False,
) -> dict[str, Any]:
    if next_enabled():
        duration_minutes += 30 if not any(o in ('welcome_table','bonfire_table') for o in object_ids) else 0
        if any(a['actor_type']=='resident' and not next_active(a['agent_id'],start_day) for a in actors):
            return {'available':False,'reason_code':'visitor_not_on_island','conflicts':[],'actor_checks':[]}
    start_ordinal, end_ordinal = _validate_interval(
        spec,
        start_day=start_day,
        start_time_minutes=start_time_minutes,
        duration_minutes=duration_minutes,
    )
    from services.scheduled_action_service import jobs
    from services.holiday_flex_service import can_pause
    for job in jobs(world):
        if allow_soft_jobs and job["actor_key"] in {a["actor_key"] for a in actors} and can_pause(db,world,job):
            continue
        if start_ordinal < job["end_ordinal"] and end_ordinal > job["start_ordinal"] and (
            job["actor_key"] in {a["actor_key"] for a in actors} or job.get("object_id") in object_ids):
            return {"available": False, "reason_code": "active_action_conflict", "conflicts": [{"job_id": job["job_id"]}],
                    "actor_checks": [], "start_ordinal": start_ordinal, "end_ordinal": end_ordinal}
    if location_id not in spec.locations:
        raise PlanServiceError("Plan location does not exist.", reason_code="unknown_location", status_code=422)
    from services.holiday_calendar_v6 import is_open
    if (spec.world_version=='chaoxi-holiday-v6' and not is_open(location_id,start_time_minutes,duration_minutes)
            or not bool(spec.locations[location_id].opening_hours.get("always_open", False))):
        return {
            "available": False,
            "reason_code": "location_closed",
            "conflicts": [{"resource_type": "location", "resource_key": location_id}],
            "actor_checks": [],
            "start_ordinal": start_ordinal,
            "end_ordinal": end_ordinal,
        }
    missing_objects = [item for item in object_ids if not object_exists(spec, location_id, item)]
    if missing_objects:
        raise PlanServiceError(
            "A requested plan object does not exist at the activity location.",
            reason_code="unknown_object",
            status_code=422,
        )

    actor_checks: list[dict[str, Any]] = []
    for actor in actors:
        actor_type = actor["actor_type"]
        agent_id = actor["agent_id"]
        key = actor["actor_key"]
        _actor_location(db, world=world, actor_type=actor_type, agent_id=agent_id)
        if actor_type == "resident" and int(agent_id) not in spec.residents:
            raise PlanServiceError("Resident is not defined by the bound world.", reason_code="unknown_actor", status_code=422)
        if _runtime_action_conflict(
            db,
            world=world,
            actor_type=actor_type,
            agent_id=agent_id,
            start_ordinal=start_ordinal,
            end_ordinal=end_ordinal,
            allow_soft_jobs=allow_soft_jobs,
        ):
            actor_checks.append({"actor_key": key, "available": False, "reason_code": "active_action_conflict"})
            continue
        feasible, reason, details = _route_feasibility(
            db,
            world=world,
            spec=spec,
            actor_type=actor_type,
            agent_id=agent_id,
            actor_key=key,
            location_id=location_id,
            start_ordinal=start_ordinal,
            end_ordinal=end_ordinal,
            exclude_commitment_id=exclude_commitment_id,
        )
        actor_checks.append({"actor_key": key, "available": feasible, "reason_code": reason, **details})

    resource_keys: list[tuple[str, str]] = [("location", location_id)]
    resource_keys.extend(("object", f"{location_id}:{item}") for item in object_ids)
    resource_keys.extend(("role", f"{location_id}:{item}") for item in role_slots)
    resource_keys.extend(("actor", item["actor_key"]) for item in actors)
    conflicts = _resource_conflicts(
        db,
        session_id=world.session_id,
        resource_keys=resource_keys,
        start_ordinal=start_ordinal,
        end_ordinal=end_ordinal,
        exclude_commitment_id=exclude_commitment_id,
    )
    failed_actor = next((item for item in actor_checks if not item["available"]), None)
    reason_code = (
        str(failed_actor["reason_code"])
        if failed_actor is not None
        else "resource_conflict"
        if conflicts
        else "available"
    )
    return {
        "available": failed_actor is None and not conflicts,
        "reason_code": reason_code,
        "conflicts": conflicts,
        "actor_checks": actor_checks,
        "start_ordinal": start_ordinal,
        "end_ordinal": end_ordinal,
    }


def query_plan_availability(db: DBSession, *, session_id: int, request: Any) -> dict[str, Any]:
    world, spec = _world_and_spec(db, session_id)
    actors = _normalize_actor_refs(_value(request, "actors", ()) or ())
    result = _availability(
        db,
        world=world,
        spec=spec,
        start_day=int(_value(request, "start_day")),
        start_time_minutes=int(_value(request, "start_time_minutes")),
        duration_minutes=int(_value(request, "duration_minutes")),
        location_id=str(_value(request, "location_id")),
        actors=actors,
        object_ids=[str(item) for item in (_value(request, "object_ids", ()) or ())],
        role_slots=[str(item) for item in (_value(request, "role_slots", ()) or ())],
        exclude_commitment_id=_value(request, "exclude_commitment_id"),
    )
    return {
        "runtime_version": PLAN_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        **result,
    }


def _member_dict(item: WorldPlanMember) -> dict[str, Any]:
    return {
        "member_id": item.id,
        "actor_type": item.actor_type,
        "agent_id": item.actor_agent_id,
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


def _reservation_dict(item: WorldResourceReservation) -> dict[str, Any]:
    return {
        "reservation_id": item.id,
        "resource_type": item.resource_type,
        "resource_key": item.resource_key,
        "status": item.status,
        "generation": item.generation,
        "start_day": item.start_day,
        "start_time_minutes": item.start_time_minutes,
        "end_day": item.end_day,
        "end_time_minutes": item.end_time_minutes,
        "released_reason_code": item.released_reason_code,
    }


def _notice_dict(item: WorldPlanNotice) -> dict[str, Any]:
    return {
        "notice_id": item.id,
        "transition_id": item.transition_id,
        "recipient_actor_key": item.recipient_actor_key,
        "notice_type": item.notice_type,
        "reason_code": item.reason_code,
        "payload": _json_loads(item.payload_json, {}),
        "world_day": item.world_day,
        "world_time_minutes": item.world_time_minutes,
    }


def serialize_plan(db: DBSession, plan: WorldCommitment) -> dict[str, Any]:
    members = (
        db.query(WorldPlanMember)
        .filter(WorldPlanMember.commitment_id == plan.id)
        .order_by(WorldPlanMember.id.asc())
        .all()
    )
    reservations = (
        db.query(WorldResourceReservation)
        .filter(WorldResourceReservation.commitment_id == plan.id)
        .order_by(WorldResourceReservation.generation.asc(), WorldResourceReservation.id.asc())
        .all()
    )
    notices = (
        db.query(WorldPlanNotice)
        .filter(WorldPlanNotice.commitment_id == plan.id)
        .order_by(WorldPlanNotice.id.asc())
        .all()
    )
    return {
        "commitment_id": plan.id,
        "runtime_version": plan.runtime_version,
        "revision": plan.revision,
        "recipe_id": plan.recipe_id,
        "status": plan.status,
        "location_id": plan.location_id,
        "organizer_type": plan.organizer_type,
        "organizer_agent_id": plan.organizer_agent_id,
        "scheduled_day": plan.scheduled_day,
        "scheduled_time_minutes": plan.scheduled_time_minutes,
        "duration_minutes": plan.duration_minutes,
        "min_participants": plan.min_participants,
        "max_participants": plan.max_participants,
        "deadline_day": plan.deadline_day,
        "deadline_time_minutes": plan.deadline_time_minutes,
        "object_ids": _json_loads(plan.object_ids_json, []),
        "role_slots": _json_loads(plan.role_slots_json, []),
        "required_actor_keys": _json_loads(plan.required_actor_keys_json, []),
        "reschedule_generation": plan.reschedule_generation,
        "ended_reason_code": plan.ended_reason_code,
        "policy_id": plan.policy_id,
        "policy_version": plan.policy_version,
        "members": [_member_dict(item) for item in members],
        "reservations": [_reservation_dict(item) for item in reservations],
        "notices": [_notice_dict(item) for item in notices],
        "metadata": _json_loads(plan.metadata_json, {}),
    }


def list_plans(db: DBSession, *, session_id: int, include_terminal: bool = True) -> dict[str, Any]:
    world, _spec = _world_and_spec(db, session_id)
    query = db.query(WorldCommitment).filter(
        WorldCommitment.session_id == session_id,
        WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
    )
    if not include_terminal:
        query = query.filter(WorldCommitment.status.in_(ACTIVE_PLAN_STATES))
    rows = query.order_by(WorldCommitment.scheduled_day, WorldCommitment.scheduled_time_minutes, WorldCommitment.id).all()
    return {
        "runtime_version": PLAN_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "plans": [serialize_plan(db, item) for item in rows],
    }


def _plan_snapshot(plan: WorldCommitment) -> dict[str, Any]:
    return {
        "status": plan.status,
        "revision": plan.revision,
        "scheduled_day": plan.scheduled_day,
        "scheduled_time_minutes": plan.scheduled_time_minutes,
        "generation": plan.reschedule_generation,
        "ended_reason_code": plan.ended_reason_code,
    }


def _add_reservations(
    db: DBSession,
    *,
    plan: WorldCommitment,
    members: Iterable[WorldPlanMember],
    shared_status: str,
) -> None:
    start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
    end = start + plan.duration_minutes + (30 if next_enabled() and plan.recipe_id not in ('welcome','bonfire') else 0)
    end_day, end_minute = _position(end)
    resources: list[tuple[str, str, str]] = [
        ("location", plan.location_id, shared_status),
    ]
    resources.extend(
        ("object", f"{plan.location_id}:{item}", shared_status)
        for item in _json_loads(plan.object_ids_json, [])
    )
    resources.extend(
        ("role", f"{plan.location_id}:{item}", shared_status)
        for item in _json_loads(plan.role_slots_json, [])
    )
    resources.extend(
        (
            "actor",
            item.actor_key,
            "confirmed" if shared_status == "confirmed" and item.response_status == "accepted" else "tentative",
        )
        for item in members
        if item.response_status in ("proposed", "deferred", "accepted")
    )
    for resource_type, resource_key, status in resources:
        db.add(
            WorldResourceReservation(
                session_id=plan.session_id,
                commitment_id=plan.id,
                resource_type=resource_type,
                resource_key=resource_key,
                start_ordinal=start,
                end_ordinal=end,
                start_day=plan.scheduled_day,
                start_time_minutes=plan.scheduled_time_minutes,
                end_day=end_day,
                end_time_minutes=end_minute,
                status=status,
                generation=plan.reschedule_generation,
            )
        )


def _release_reservations(db: DBSession, *, plan: WorldCommitment, reason_code: str) -> None:
    now = _utc_now()
    rows = db.query(WorldResourceReservation).filter(
        WorldResourceReservation.commitment_id == plan.id,
        WorldResourceReservation.status.in_(ACTIVE_RESERVATION_STATES),
    ).all()
    for item in rows:
        item.status = "released"
        item.released_reason_code = reason_code
        item.released_at = now


def _set_reservation_state(db: DBSession, *, plan: WorldCommitment, confirmed: bool) -> None:
    rows = db.query(WorldResourceReservation).filter(
        WorldResourceReservation.commitment_id == plan.id,
        WorldResourceReservation.generation == plan.reschedule_generation,
        WorldResourceReservation.status.in_(ACTIVE_RESERVATION_STATES),
    ).all()
    members = {
        item.actor_key: item.response_status
        for item in db.query(WorldPlanMember).filter(WorldPlanMember.commitment_id == plan.id).all()
    }
    for item in rows:
        if item.resource_type == "actor":
            item.status = "confirmed" if confirmed and members.get(item.resource_key) == "accepted" else "tentative"
        else:
            item.status = "confirmed" if confirmed else "tentative"


def _release_actor_reservation(
    db: DBSession, *, plan: WorldCommitment, actor_key: str, reason_code: str
) -> None:
    now = _utc_now()
    rows = db.query(WorldResourceReservation).filter(
        WorldResourceReservation.commitment_id == plan.id,
        WorldResourceReservation.resource_type == "actor",
        WorldResourceReservation.resource_key == actor_key,
        WorldResourceReservation.status.in_(ACTIVE_RESERVATION_STATES),
    ).all()
    for item in rows:
        item.status = "released"
        item.released_reason_code = reason_code
        item.released_at = now


def _accepted_requirements(db: DBSession, plan: WorldCommitment) -> tuple[bool, int]:
    members = db.query(WorldPlanMember).filter(WorldPlanMember.commitment_id == plan.id).all()
    accepted = [item for item in members if item.response_status == "accepted"]
    required = set(_json_loads(plan.required_actor_keys_json, []))
    if next_enabled() and plan.recipe_id not in ('welcome','bonfire'):
        required.update(m.actor_key for m in members if m.actor_type=='participant' and m.response_status=='accepted')
    accepted_keys = {item.actor_key for item in accepted}
    return len(accepted) >= plan.min_participants and required <= accepted_keys, len(accepted)


def _refresh_aggregate_state(db: DBSession, plan: WorldCommitment) -> str:
    # Flush membership changes before querying available reservations.
    db.flush()
    ready, _count = _accepted_requirements(db, plan)
    if plan.status in ("proposed", "accepted"):
        plan.status = "accepted" if ready else "proposed"
        _set_reservation_state(db, plan=plan, confirmed=ready)
    return plan.status


def _admission_interval(world, spec, plan):
    """Late admission reserves only the remaining authored open-event window."""
    start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
    end = start + plan.duration_minutes
    now = _ordinal(world.current_day, world.current_time_minutes)
    open_event = _recipe(spec, plan.recipe_id).get("conditions", {}).get("open_admission_until_end") is True
    deadline = end - 1 if open_event else _ordinal(
        int(plan.deadline_day or plan.scheduled_day),
        int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes),
    )
    if now > deadline:
        raise PlanServiceError("The response deadline has passed.", reason_code="response_deadline_expired")
    effective = max(start, now) if open_event else start
    day, minute = _position(effective)
    return day, minute, end - effective, open_event


def _add_notices(
    db: DBSession,
    *,
    plan: WorldCommitment,
    transition: WorldPlanTransition,
    notice_type: str,
    reason_code: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    members = db.query(WorldPlanMember).filter(WorldPlanMember.commitment_id == plan.id).all()
    for member in members:
        db.add(
            WorldPlanNotice(
                session_id=plan.session_id,
                commitment_id=plan.id,
                transition_id=transition.id,
                recipient_actor_key=member.actor_key,
                notice_type=notice_type,
                reason_code=reason_code,
                payload_json=_json_dumps(dict(payload or {})),
                world_day=transition.world_day,
                world_time_minutes=transition.world_time_minutes,
            )
        )


def _transition_result(db: DBSession, transition: WorldPlanTransition) -> dict[str, Any]:
    result = _json_loads(transition.result_json, {})
    result["transition_id"] = transition.id
    result["transition_status"] = transition.status
    result["reason_code"] = transition.reason_code
    return result


def create_plan(
    db: DBSession,
    *,
    session_id: int,
    request: Any,
    organizer_type: str = "participant",
    organizer_agent_id: int | None = None,
) -> dict[str, Any]:
    organizer_key = _actor_key(organizer_type, organizer_agent_id)
    invitees = _normalize_actor_refs(_value(request, "invitees", ()) or ())
    if organizer_key in {item["actor_key"] for item in invitees}:
        raise PlanServiceError("The organizer cannot also be an invitee.", reason_code="duplicate_actor", status_code=422)
    payload = {
        "operation": "create",
        "organizer_type": organizer_type,
        "organizer_agent_id": organizer_agent_id,
        "recipe_id": _value(request, "recipe_id"),
        "location_id": _value(request, "location_id"),
        "start_day": _value(request, "start_day"),
        "start_time_minutes": _value(request, "start_time_minutes"),
        "invitees": invitees,
        "deadline_day": _value(request, "deadline_day"),
        "deadline_time_minutes": _value(request, "deadline_time_minutes"),
        "reason_code": _value(request, "reason_code", "plan_proposed"),
    }
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key") or "")

    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldPlanTransition).filter(
            WorldPlanTransition.session_id == session_id,
            WorldPlanTransition.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PlanServiceError("Plan idempotency key was reused with another payload.", reason_code="idempotency_conflict")
            result = _transition_result(db, existing)
            result["status"] = "existing"
            return result

        world, spec = _world_and_spec(db, session_id)
        from services.holiday_calendar_v6 import pending
        if pending(world):
            raise PlanServiceError('今天已经结束，请确认下一天。', reason_code='world_ended')
        recipe = _recipe(spec, str(payload["recipe_id"]))
        if recipe.get("retired"):
            raise PlanServiceError("这个活动已下架，请选择其他活动。",reason_code="interaction_retired",status_code=422)
        required_residents = set(recipe.get("conditions", {}).get("required_resident_ids", ()))
        proposed_residents = {i["agent_id"] for i in invitees if i["actor_type"] == "resident"}
        if organizer_type == "resident":
            proposed_residents.add(organizer_agent_id)
        if not required_residents <= proposed_residents:
            raise PlanServiceError("The activity requires its named resident.", reason_code="required_resident_missing", status_code=422)
        location_id = str(payload["location_id"])
        if location_id not in recipe.get("location_ids", ()):
            raise PlanServiceError("Recipe is not available at the requested location.", reason_code="recipe_location_mismatch", status_code=422)
        duration = int(recipe.get("duration_minutes", 0))
        min_participants = int(recipe.get("min_participants", 1))
        max_participants = int(recipe.get("max_participants", 20))
        # Minimum attendance gates start; maximum attendance also gates joining.
        if not 1 <= len(invitees) + 1 <= max_participants:
            raise PlanServiceError("Invitee count violates recipe participant bounds.", reason_code="participant_bounds_unsatisfied", status_code=422)
        allowed_roles = [str(item) for item in recipe.get("role_slots", ())]
        assigned_roles = [item["role_id"] for item in invitees if item["role_id"] is not None]
        if any(item not in allowed_roles for item in assigned_roles):
            raise PlanServiceError("An assigned role is not declared by the recipe.", reason_code="unknown_role", status_code=422)

        start_day = int(payload["start_day"])
        start_time = int(payload["start_time_minutes"])
        conditions = recipe.get("conditions", {})
        if "fixed_day" in conditions and (
            start_day != conditions["fixed_day"] or start_time != conditions["fixed_start_minute"]
            or organizer_type != "resident" or organizer_agent_id not in conditions.get("organizer_agent_ids", ())
        ):
            raise PlanServiceError("This invitation has an authored host and fixed time.", reason_code="fixed_invitation_contract", status_code=422)
        now_ordinal = _ordinal(world.current_day, world.current_time_minutes)
        start_ordinal, _end = _validate_interval(
            spec, start_day=start_day, start_time_minutes=start_time, duration_minutes=duration
        )
        if start_ordinal < now_ordinal:
            raise PlanServiceError("A plan cannot start in the past.", reason_code="invalid_time", status_code=422)
        deadline_day = payload["deadline_day"] if payload["deadline_day"] is not None else start_day
        deadline_time = payload["deadline_time_minutes"] if payload["deadline_time_minutes"] is not None else start_time
        deadline_ordinal = _ordinal(int(deadline_day), int(deadline_time))
        if deadline_ordinal < now_ordinal or deadline_ordinal > start_ordinal:
            raise PlanServiceError("Plan response deadline must fall between now and the start.", reason_code="invalid_deadline", status_code=422)

        actors = [
            {
                "actor_type": organizer_type,
                "agent_id": organizer_agent_id,
                "actor_key": organizer_key,
                "role_id": None,
                "required": True,
            },
            *invitees,
        ]
        max_open = int(_emergence_policy(spec).get("max_open_commitments_per_actor", 0))
        for actor in actors:
            if len(_active_actor_plans(db, session_id=session_id, actor_key=actor["actor_key"], exclude_commitment_id=None)) >= max_open:
                raise PlanServiceError("Actor has reached the open-commitment limit.", reason_code="open_commitment_limit")
        availability = _availability(
            db,
            world=world,
            spec=spec,
            start_day=start_day,
            start_time_minutes=start_time,
            duration_minutes=duration,
            location_id=location_id,
            actors=actors,
            object_ids=[str(item) for item in recipe.get("object_ids", ())],
            role_slots=allowed_roles,
        )
        if not availability["available"]:
            raise PlanServiceError("Plan resources or actors are unavailable.", reason_code=str(availability["reason_code"]))

        policy = _plan_policy(spec)
        plan = WorldCommitment(
            session_id=session_id,
            recipe_id=str(payload["recipe_id"]),
            status="proposed",
            location_id=location_id,
            organizer_type=organizer_type,
            organizer_agent_id=organizer_agent_id,
            participants_json=_json_dumps([item["actor_key"] for item in actors]),
            scheduled_day=start_day,
            scheduled_time_minutes=start_time,
            source_action_id=None,
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            runtime_version=PLAN_RUNTIME_VERSION,
            revision=0,
            duration_minutes=duration,
            min_participants=min_participants,
            max_participants=max_participants,
            deadline_day=int(deadline_day),
            deadline_time_minutes=int(deadline_time),
            object_ids_json=_json_dumps(list(recipe.get("object_ids", ()))),
            role_slots_json=_json_dumps(allowed_roles),
            required_actor_keys_json=_json_dumps([item["actor_key"] for item in actors if item["required"]]),
            reschedule_generation=0,
            metadata_json=_json_dumps({"recipe_complexity": recipe.get("complexity")}),
            updated_at=_utc_now(),
        )
        db.add(plan)
        db.flush()
        members: list[WorldPlanMember] = []
        for actor in actors:
            member = WorldPlanMember(
                session_id=session_id,
                commitment_id=plan.id,
                actor_type=actor["actor_type"],
                actor_agent_id=actor["agent_id"],
                actor_key=actor["actor_key"],
                role_id=actor["role_id"],
                required=actor["required"],
                response_status="accepted" if actor["actor_key"] == organizer_key else "proposed",
                response_reason_code="organizer_created" if actor["actor_key"] == organizer_key else "invited",
            )
            db.add(member)
            members.append(member)
        db.flush()
        ready = min_participants <= 1 and set(_json_loads(plan.required_actor_keys_json, [])) <= {organizer_key}
        plan.status = "accepted" if ready else "proposed"
        _add_reservations(db, plan=plan, members=members, shared_status="confirmed" if ready else "tentative")
        transition = WorldPlanTransition(
            session_id=session_id,
            commitment_id=plan.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor_type=organizer_type,
            actor_agent_id=organizer_agent_id,
            transition_type="create",
            requested_revision=0,
            accepted_revision=0,
            status="completed",
            reason_code=str(payload["reason_code"]),
            before_json="{}",
            after_json=_json_dumps(_plan_snapshot(plan)),
            result_json="{}",
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(transition)
        db.flush()
        _add_notices(db, plan=plan, transition=transition, notice_type="plan_created", reason_code=str(payload["reason_code"]))
        db.flush()
        result = {
            "status": "created",
            "runtime_version": PLAN_RUNTIME_VERSION,
            "transition_id": transition.id,
            "reason_code": transition.reason_code,
            "plan": serialize_plan(db, plan),
        }
        transition.result_json = _json_dumps(result)
        db.commit()
        return result


def join_open_plan(
    db: DBSession,
    *,
    session_id: int,
    commitment_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
) -> dict[str, Any]:
    """Accept an open invitation without creating a parallel membership state."""

    actor_key = _actor_key(actor_type, actor_agent_id)
    payload = {
        "operation": "join_open_plan",
        "commitment_id": commitment_id,
        "actor_type": actor_type,
        "actor_agent_id": actor_agent_id,
        "expected_revision": _value(request, "expected_revision"),
        "reason_code": _value(request, "reason_code"),
    }
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key") or "")
    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldPlanTransition).filter(
            WorldPlanTransition.session_id == session_id,
            WorldPlanTransition.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PlanServiceError(
                    "Plan idempotency key was reused with another payload.",
                    reason_code="idempotency_conflict",
                )
            result = _transition_result(db, existing)
            result["status"] = "existing"
            return result

        world, spec = _world_and_spec(db, session_id)
        from services.holiday_calendar_v6 import pending
        if pending(world):
            raise PlanServiceError('今天已经结束，请确认下一天。', reason_code='world_ended')
        plan = db.query(WorldCommitment).filter(
            WorldCommitment.id == commitment_id,
            WorldCommitment.session_id == session_id,
            WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
        ).first()
        if plan is None:
            raise PlanServiceError("Plan not found.", reason_code="unknown_plan", status_code=404)
        if _value(request, "expected_revision") != plan.revision:
            raise PlanServiceError("Plan revision is stale.", reason_code="stale_revision")
        admission_day, admission_minute, admission_duration, open_event = _admission_interval(world, spec, plan)
        if plan.status not in (("proposed", "accepted", "in_progress") if open_event else ("proposed", "accepted")):
            raise PlanServiceError("This invitation is no longer open.", reason_code="invalid_transition")
        deadline = _ordinal(
            int(plan.deadline_day or plan.scheduled_day),
            int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes),
        )
        if not open_event and _ordinal(world.current_day, world.current_time_minutes) > deadline:
            raise PlanServiceError("The response deadline has passed.", reason_code="response_deadline_expired")

        members = db.query(WorldPlanMember).filter(
            WorldPlanMember.commitment_id == plan.id
        ).all()
        accepted_count = sum(item.response_status == "accepted" for item in members)
        member = next((item for item in members if item.actor_key == actor_key), None)
        if member is not None and member.response_status == "accepted":
            raise PlanServiceError("Actor already accepted this plan.", reason_code="invalid_transition")
        if accepted_count >= plan.max_participants:
            raise PlanServiceError("The activity is already full.", reason_code="capacity_reached")
        max_open = int(_emergence_policy(spec).get("max_open_commitments_per_actor", 0))
        if len(_active_actor_plans(
            db,
            session_id=session_id,
            actor_key=actor_key,
            exclude_commitment_id=plan.id,
        )) >= max_open:
            raise PlanServiceError("Actor has reached the open-commitment limit.", reason_code="open_commitment_limit")
        availability = _availability(
            db,
            world=world,
            spec=spec,
            start_day=admission_day,
            start_time_minutes=admission_minute,
            duration_minutes=admission_duration,
            location_id=plan.location_id,
            actors=[{
                "actor_type": actor_type,
                "agent_id": actor_agent_id,
                "actor_key": actor_key,
                "role_id": None,
                "required": False,
            }],
            object_ids=[],
            role_slots=[],
            exclude_commitment_id=plan.id,
        )
        if not availability["available"]:
            raise PlanServiceError("Actor is unavailable.", reason_code=str(availability["reason_code"]))

        before = _plan_snapshot(plan)
        now = _utc_now()
        if member is None:
            member = WorldPlanMember(
                session_id=session_id,
                commitment_id=plan.id,
                actor_type=actor_type,
                actor_agent_id=actor_agent_id,
                actor_key=actor_key,
                required=False,
                response_status="accepted",
                role_id=next(iter(_recipe(spec, plan.recipe_id).get("conditions", {}).get("invitee_role_ids", ())), None),
                response_reason_code=str(_value(request, "reason_code") or "public_invitation_accepted"),
            )
            db.add(member)
        else:
            member.response_status = "accepted"
            member.response_reason_code = str(_value(request, "reason_code") or "public_invitation_accepted")
            member.attendance_status = "pending"
            member.updated_at = now
        db.flush()

        reservation = db.query(WorldResourceReservation).filter(
            WorldResourceReservation.commitment_id == plan.id,
            WorldResourceReservation.resource_type == "actor",
            WorldResourceReservation.resource_key == actor_key,
            WorldResourceReservation.generation == plan.reschedule_generation,
        ).first()
        start = _ordinal(admission_day, admission_minute)
        end = start + admission_duration
        end_day, end_minute = _position(end)
        if reservation is None:
            reservation = WorldResourceReservation(
                session_id=session_id,
                commitment_id=plan.id,
                resource_type="actor",
                resource_key=actor_key,
                start_ordinal=start,
                end_ordinal=end,
                start_day=admission_day,
                start_time_minutes=admission_minute,
                end_day=end_day,
                end_time_minutes=end_minute,
                status="tentative",
                generation=plan.reschedule_generation,
            )
            db.add(reservation)
        else:
            reservation.status = "tentative"
            reservation.released_reason_code = None
            reservation.released_at = None
            reservation.start_ordinal = start
            reservation.start_day, reservation.start_time_minutes = admission_day, admission_minute
        actor_keys = [item.actor_key for item in members if item.actor_key != actor_key]
        actor_keys.append(actor_key)
        plan.participants_json = _json_dumps(actor_keys)
        _refresh_aggregate_state(db, plan)
        if plan.status == "in_progress":
            reservation.status = "confirmed"
            _mark_arrivals(db, world=world, plan=plan)
        plan.revision += 1
        plan.updated_at = now
        reason_code = str(_value(request, "reason_code") or "public_invitation_accepted")
        transition = WorldPlanTransition(
            session_id=session_id,
            commitment_id=plan.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            transition_type="join",
            requested_revision=int(_value(request, "expected_revision")),
            accepted_revision=plan.revision,
            status="completed",
            reason_code=reason_code,
            before_json=_json_dumps(before),
            after_json=_json_dumps(_plan_snapshot(plan)),
            result_json="{}",
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(transition)
        db.flush()
        _add_notices(
            db,
            plan=plan,
            transition=transition,
            notice_type="plan_joined",
            reason_code=reason_code,
            payload={"actor_key": actor_key, "revision": plan.revision},
        )
        result = {
            "status": "completed",
            "runtime_version": PLAN_RUNTIME_VERSION,
            "transition_id": transition.id,
            "transition_status": transition.status,
            "reason_code": reason_code,
            "plan": serialize_plan(db, plan),
        }
        transition.result_json = _json_dumps(result)
        db.commit()
        return result


def _member_for_actor(db: DBSession, *, plan: WorldCommitment, actor_key: str) -> WorldPlanMember:
    member = db.query(WorldPlanMember).filter(
        WorldPlanMember.commitment_id == plan.id,
        WorldPlanMember.actor_key == actor_key,
    ).first()
    if member is None:
        raise PlanServiceError("Actor is not a member of this plan.", reason_code="not_a_member", status_code=403)
    return member


def _is_organizer(plan: WorldCommitment, actor_type: str, agent_id: int | None) -> bool:
    return plan.organizer_type == actor_type and plan.organizer_agent_id == agent_id


def _require_organizer(plan: WorldCommitment, actor_type: str, agent_id: int | None) -> None:
    if not _is_organizer(plan, actor_type, agent_id):
        raise PlanServiceError("Only the plan organizer can perform this transition.", reason_code="organizer_required", status_code=403)


def _current_presence(
    db: DBSession, *, world: WorldState, plan: WorldCommitment, member: WorldPlanMember
) -> bool:
    return _actor_location(
        db,
        world=world,
        actor_type=member.actor_type,
        agent_id=member.actor_agent_id,
    ) == plan.location_id


def _mark_arrivals(db: DBSession, *, world: WorldState, plan: WorldCommitment) -> None:
    now = _ordinal(world.current_day, world.current_time_minutes)
    start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
    for member in db.query(WorldPlanMember).filter(
        WorldPlanMember.commitment_id == plan.id,
        WorldPlanMember.response_status == "accepted",
        WorldPlanMember.attendance_status == "pending",
    ).all():
        if _current_presence(db, world=world, plan=plan, member=member):
            member.attendance_status = "late" if now > start + (30 if next_enabled() else 0) else "present"
            member.arrival_day = world.current_day
            member.arrival_time_minutes = world.current_time_minutes
            member.updated_at = _utc_now()


def _present_requirements(db: DBSession, plan: WorldCommitment) -> tuple[bool, int]:
    members = db.query(WorldPlanMember).filter(WorldPlanMember.commitment_id == plan.id).all()
    present = [item for item in members if item.attendance_status in ("present", "late")]
    required = set(_json_loads(plan.required_actor_keys_json, []))
    present_keys = {item.actor_key for item in present}
    return len(present) >= plan.min_participants and required <= present_keys, len(present)


def transition_plan(
    db: DBSession,
    *,
    session_id: int,
    commitment_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
    managed_transaction: bool = False,
) -> dict[str, Any]:
    actor_key = _actor_key(actor_type, actor_agent_id)
    transition_type = str(_value(request, "transition") or "")
    payload = {
        "operation": "transition",
        "commitment_id": commitment_id,
        "actor_type": actor_type,
        "actor_agent_id": actor_agent_id,
        "transition": transition_type,
        "expected_revision": _value(request, "expected_revision"),
        "reason_code": _value(request, "reason_code"),
        "start_day": _value(request, "start_day"),
        "start_time_minutes": _value(request, "start_time_minutes"),
    }
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key") or "")

    with session_write_lock(session_id):
        if not managed_transaction:
            db.rollback()
        existing = db.query(WorldPlanTransition).filter(
            WorldPlanTransition.session_id == session_id,
            WorldPlanTransition.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PlanServiceError("Plan idempotency key was reused with another payload.", reason_code="idempotency_conflict")
            result = _transition_result(db, existing)
            result["status"] = "existing"
            return result

        world, spec = _world_and_spec(db, session_id)
        from services.holiday_calendar_v6 import pending
        if pending(world):
            raise PlanServiceError('今天已经结束，请确认下一天。', reason_code='world_ended')
        plan = db.query(WorldCommitment).filter(
            WorldCommitment.id == commitment_id,
            WorldCommitment.session_id == session_id,
            WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
        ).first()
        if plan is None:
            raise PlanServiceError("Plan not found.", reason_code="unknown_plan", status_code=404)
        expected_revision = _value(request, "expected_revision")
        if expected_revision != plan.revision:
            raise PlanServiceError("Plan revision is stale.", reason_code="stale_revision")
        before = _plan_snapshot(plan)
        reason_code = str(_value(request, "reason_code") or "")
        member = _member_for_actor(db, plan=plan, actor_key=actor_key)
        notice_type = f"plan_{transition_type}"

        if transition_type == "accept":
            admission_day, admission_minute, admission_duration, open_event = _admission_interval(world, spec, plan)
            if plan.status not in (("proposed", "accepted", "in_progress") if open_event else ("proposed", "accepted")) or member.response_status not in ("proposed", "deferred"):
                raise PlanServiceError("This invitation cannot be accepted now.", reason_code="invalid_transition")
            availability = _availability(
                db,
                world=world,
                spec=spec,
                start_day=admission_day,
                start_time_minutes=admission_minute,
                duration_minutes=admission_duration,
                location_id=plan.location_id,
                actors=[{
                    "actor_type": member.actor_type,
                    "agent_id": member.actor_agent_id,
                    "actor_key": member.actor_key,
                    "role_id": member.role_id,
                    "required": member.required,
                }],
                object_ids=[],
                role_slots=[],
                exclude_commitment_id=plan.id,
                allow_soft_jobs=spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and actor_type=="resident",
            )
            if not availability["available"]:
                raise PlanServiceError("Actor is no longer available.", reason_code=str(availability["reason_code"]))
            if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and actor_type=="resident":
                from services.holiday_flex_service import pause_routine
                pause_routine(db,world,actor_agent_id,"paused_for_invitation")
            member.response_status = "accepted"
            member.response_reason_code = reason_code
            _refresh_aggregate_state(db, plan)
            if plan.status == "in_progress":
                _mark_arrivals(db, world=world, plan=plan)
        elif transition_type == "reject":
            if plan.status not in ("proposed", "accepted") or member.response_status not in ("proposed", "deferred"):
                raise PlanServiceError("This invitation cannot be rejected now.", reason_code="invalid_transition")
            member.response_status = "rejected"
            member.response_reason_code = reason_code
            _release_actor_reservation(db, plan=plan, actor_key=actor_key, reason_code=reason_code)
            if member.required:
                plan.status = "rejected"
                plan.ended_reason_code = "required_actor_rejected"
                _release_reservations(db, plan=plan, reason_code=plan.ended_reason_code)
            else:
                _refresh_aggregate_state(db, plan)
        elif transition_type == "defer":
            if plan.status not in ("proposed", "accepted") or member.response_status != "proposed":
                raise PlanServiceError("This invitation cannot be deferred now.", reason_code="invalid_transition")
            member.response_status = "deferred"
            member.response_reason_code = reason_code
        elif transition_type == "withdraw":
            unarrived_optional = plan.status == "in_progress" and not member.required and member.attendance_status == "pending"
            if (plan.status not in ("proposed", "accepted") and not unarrived_optional) or member.response_status != "accepted" or _is_organizer(plan, actor_type, actor_agent_id):
                raise PlanServiceError("This member cannot withdraw now.", reason_code="invalid_transition")
            member.response_status = "withdrawn"
            member.response_reason_code = reason_code
            _release_actor_reservation(db, plan=plan, actor_key=actor_key, reason_code=reason_code)
            _refresh_aggregate_state(db, plan)
        elif transition_type == "cancel":
            _require_organizer(plan, actor_type, actor_agent_id)
            if plan.status not in ("proposed", "accepted"):
                raise PlanServiceError("This plan cannot be cancelled now.", reason_code="invalid_transition")
            plan.status = "cancelled"
            plan.ended_reason_code = reason_code
            _release_reservations(db, plan=plan, reason_code=reason_code)
        elif transition_type == "reschedule":
            _require_organizer(plan, actor_type, actor_agent_id)
            if "fixed_day" in _recipe(spec, plan.recipe_id).get("conditions", {}):
                raise PlanServiceError("This invitation has a fixed time.", reason_code="fixed_invitation_contract")
            if plan.status not in ("proposed", "accepted"):
                raise PlanServiceError("This plan cannot be rescheduled now.", reason_code="invalid_transition")
            start_day = _value(request, "start_day")
            start_time = _value(request, "start_time_minutes")
            if start_day is None or start_time is None:
                raise PlanServiceError("Reschedule requires a new day and time.", reason_code="invalid_request", status_code=422)
            members = db.query(WorldPlanMember).filter(WorldPlanMember.commitment_id == plan.id).all()
            actors = [
                {
                    "actor_type": item.actor_type,
                    "agent_id": item.actor_agent_id,
                    "actor_key": item.actor_key,
                    "role_id": item.role_id,
                    "required": item.required,
                }
                for item in members
                if item.response_status not in ("rejected", "withdrawn")
            ]
            availability = _availability(
                db,
                world=world,
                spec=spec,
                start_day=int(start_day),
                start_time_minutes=int(start_time),
                duration_minutes=plan.duration_minutes,
                location_id=plan.location_id,
                actors=actors,
                object_ids=_json_loads(plan.object_ids_json, []),
                role_slots=_json_loads(plan.role_slots_json, []),
                exclude_commitment_id=plan.id,
            )
            if not availability["available"]:
                raise PlanServiceError("Rescheduled slot is unavailable.", reason_code=str(availability["reason_code"]))
            _release_reservations(db, plan=plan, reason_code="rescheduled")
            plan.scheduled_day = int(start_day)
            plan.scheduled_time_minutes = int(start_time)
            plan.deadline_day = int(start_day)
            plan.deadline_time_minutes = int(start_time)
            plan.reschedule_generation += 1
            plan.status = "proposed"
            plan.ended_reason_code = None
            for item in members:
                item.attendance_status = "pending"
                item.arrival_day = None
                item.arrival_time_minutes = None
                item.departure_day = None
                item.departure_time_minutes = None
                if item.actor_key == actor_key:
                    item.response_status = "accepted"
                    item.response_reason_code = "organizer_rescheduled"
                elif item.response_status not in ("rejected", "withdrawn"):
                    item.response_status = "proposed"
                    item.response_reason_code = "reschedule_reconfirmation_required"
                item.updated_at = _utc_now()
            _add_reservations(db, plan=plan, members=[item for item in members if item.response_status not in ("rejected", "withdrawn")], shared_status="tentative")
            _refresh_aggregate_state(db, plan)
        elif transition_type == "arrive":
            if plan.status not in ("accepted", "in_progress") or member.response_status != "accepted":
                raise PlanServiceError("This member cannot arrive for the plan now.", reason_code="invalid_transition")
            now = _ordinal(world.current_day, world.current_time_minutes)
            start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
            if now < start:
                raise PlanServiceError("Arrival cannot be recorded before the plan starts.", reason_code="not_due")
            if next_enabled() and plan.status=='accepted' and plan.recipe_id not in ('welcome','bonfire') and now > start+30:
                raise PlanServiceError('已经超过半小时到场时间，请重新约一个时间。',reason_code='arrival_window_expired')
            if not _current_presence(db, world=world, plan=plan, member=member):
                raise PlanServiceError("Actor has not reached the plan location.", reason_code="not_at_location")
            member.attendance_status = "late" if now > start + (30 if next_enabled() else 0) else "present"
            member.arrival_day = world.current_day
            member.arrival_time_minutes = world.current_time_minutes
            notice_type = "plan_late_arrival" if member.attendance_status == "late" else "plan_arrival"
        elif transition_type == "start":
            _require_organizer(plan, actor_type, actor_agent_id)
            if plan.status != "accepted":
                raise PlanServiceError("This plan is not ready to start.", reason_code="invalid_transition")
            now = _ordinal(world.current_day, world.current_time_minutes)
            start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
            if now < start:
                raise PlanServiceError("Plan start time has not arrived.", reason_code="not_due")
            if next_enabled() and plan.recipe_id not in ('welcome','bonfire') and now > start+30:
                raise PlanServiceError('已经超过半小时到场时间。',reason_code='arrival_window_expired')
            _mark_arrivals(db, world=world, plan=plan)
            present_ready, _present_count = _present_requirements(db, plan)
            if present_ready:
                plan.status = "in_progress"
                reason_code = reason_code or "activity_started"
            elif now <= start + PLAN_WAIT_MINUTES:
                reason_code = "waiting_for_arrivals"
                notice_type = "plan_waiting"
            else:
                for item in db.query(WorldPlanMember).filter(
                    WorldPlanMember.commitment_id == plan.id,
                    WorldPlanMember.response_status == "accepted",
                    WorldPlanMember.attendance_status == "pending",
                ).all():
                    item.attendance_status = "absent"
                    item.response_reason_code = "absence_after_wait_timeout"
                plan.status = "failed"
                plan.ended_reason_code = "wait_timeout_insufficient_attendance"
                reason_code = plan.ended_reason_code
                notice_type = "plan_failed"
                _release_reservations(db, plan=plan, reason_code=reason_code)
        elif transition_type == "leave":
            if plan.status != "in_progress" or member.attendance_status not in ("present", "late"):
                raise PlanServiceError("This member cannot leave the plan now.", reason_code="invalid_transition")
            member.attendance_status = "left_early"
            member.departure_day = world.current_day
            member.departure_time_minutes = world.current_time_minutes
            _release_actor_reservation(db, plan=plan, actor_key=actor_key, reason_code="left_early")
            present_ready, _count = _present_requirements(db, plan)
            if not present_ready:
                plan.status = "failed"
                plan.ended_reason_code = "early_leave_below_minimum"
                reason_code = plan.ended_reason_code
                notice_type = "plan_failed"
                _release_reservations(db, plan=plan, reason_code=reason_code)
            else:
                reason_code = reason_code or "left_early"
                notice_type = "plan_early_leave"
        elif transition_type == "complete":
            _require_organizer(plan, actor_type, actor_agent_id)
            if plan.status != "in_progress":
                raise PlanServiceError("Only an in-progress plan can complete.", reason_code="invalid_transition")
            from services.stage_service import guard_plan_stage_completion

            guard_plan_stage_completion(db, plan=plan, spec=spec)
            plan.status = "completed"
            plan.ended_reason_code = reason_code
            _release_reservations(db, plan=plan, reason_code=reason_code)
        elif transition_type == "fail":
            # Internal failure cleanup must release reservations after activity start.
            _require_organizer(plan, actor_type, actor_agent_id)
            if plan.status not in ACTIVE_PLAN_STATES:
                raise PlanServiceError("This plan cannot fail now.", reason_code="invalid_transition")
            plan.status = "failed"
            plan.ended_reason_code = reason_code
            _release_reservations(db, plan=plan, reason_code=reason_code)
        elif transition_type == "expire":
            _require_organizer(plan, actor_type, actor_agent_id)
            if plan.status not in ("proposed", "accepted"):
                raise PlanServiceError("This plan cannot expire now.", reason_code="invalid_transition")
            deadline = _ordinal(int(plan.deadline_day or plan.scheduled_day), int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes))
            if next_enabled() and plan.status=='accepted' and plan.recipe_id not in ('welcome','bonfire'):
                deadline = _ordinal(plan.scheduled_day,plan.scheduled_time_minutes)+30
            now = _ordinal(world.current_day, world.current_time_minutes)
            if now <= deadline:
                raise PlanServiceError("Plan response deadline has not passed.", reason_code="not_due")
            plan.status = "expired"
            plan.ended_reason_code = reason_code
            _release_reservations(db, plan=plan, reason_code=reason_code)
        else:
            raise PlanServiceError("Unsupported plan transition.", reason_code="invalid_transition", status_code=422)

        member.updated_at = _utc_now()
        plan.revision += 1
        plan.updated_at = _utc_now()
        transition = WorldPlanTransition(
            session_id=session_id,
            commitment_id=plan.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            transition_type=transition_type,
            requested_revision=int(expected_revision),
            accepted_revision=plan.revision,
            status="completed",
            reason_code=reason_code,
            before_json=_json_dumps(before),
            after_json=_json_dumps(_plan_snapshot(plan)),
            result_json="{}",
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(transition)
        db.flush()
        _add_notices(
            db,
            plan=plan,
            transition=transition,
            notice_type=notice_type,
            reason_code=reason_code,
            payload={"actor_key": actor_key, "revision": plan.revision},
        )
        db.flush()
        result = {
            "status": "completed",
            "runtime_version": PLAN_RUNTIME_VERSION,
            "transition_id": transition.id,
            "transition_status": transition.status,
            "reason_code": reason_code,
            "plan": serialize_plan(db, plan),
        }
        transition.result_json = _json_dumps(result)
        if not managed_transaction:
            db.commit()
        return result


def reconcile_due_plans(db: DBSession, *, session_id: int, idempotency_prefix: str) -> list[dict[str, Any]]:
    """Expire overdue open plans once; replay is safe through transition idempotency."""

    world, _spec = _world_and_spec(db, session_id)
    now = _ordinal(world.current_day, world.current_time_minutes)
    rows = db.query(WorldCommitment).filter(
        WorldCommitment.session_id == session_id,
        WorldCommitment.runtime_version == PLAN_RUNTIME_VERSION,
        WorldCommitment.status.in_(("proposed", "accepted")),
    ).all()
    results: list[dict[str, Any]] = []
    for plan in rows:
        deadline = _ordinal(
            int(plan.deadline_day or plan.scheduled_day),
            int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes),
        )
        if next_enabled() and plan.status=='accepted' and plan.recipe_id not in ('welcome','bonfire'):
            deadline = _ordinal(plan.scheduled_day,plan.scheduled_time_minutes)+30
        if now <= deadline:
            continue
        request = {
            "transition": "expire",
            "idempotency_key": f"{idempotency_prefix}:{plan.id}",
            "expected_revision": plan.revision,
            "reason_code": "response_deadline_expired",
        }
        results.append(
            transition_plan(
                db,
                session_id=session_id,
                commitment_id=plan.id,
                request=request,
                actor_type=plan.organizer_type,
                actor_agent_id=plan.organizer_agent_id,
            )
        )
    return results
