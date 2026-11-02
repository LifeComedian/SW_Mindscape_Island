"""Scheduled jobs driven by the shared island clock."""
from dataclasses import asdict
import json
from models import CharacterState, WorldAtomicActionExecution, WorldAction
from world.autonomy_policy import autonomy_policy
from world.clock import ClockPosition
from world.atomic_actions import AtomicActionRuntimeError, AtomicActionTarget
from world.graph import shortest_travel_path


def _state(world):
    return json.loads(world.state_json or "{}")


def jobs(world):
    return _state(world).get("scheduled_actions_v1", [])


def _write(world, values):
    state = _state(world)
    # Retain only pending jobs. Completed/failed history remains in audit tables.
    state["scheduled_actions_v1"] = [j for j in values if j["status"] == "pending"]
    world.state_json = json.dumps(state, ensure_ascii=False)


def actor_busy(world, actor_key):
    return any(j["actor_key"] == actor_key and j["status"] == "pending" for j in jobs(world))


def guard_action(world, actor_key, object_id, stage_runtime_id=None):
    from services.interaction_time_service import focus_state, policy_for
    focus = focus_state(world) if policy_for(world) else None
    if focus and stage_runtime_id != focus.get("runtime_id"):
        raise AtomicActionRuntimeError("Leave the current discussion before another action.", reason_code="actor_unavailable")
    if any(j["status"] == "pending" and (j["actor_key"] == actor_key or
        object_id and j.get("object_id") == object_id) for j in jobs(world)):
        raise AtomicActionRuntimeError("Actor or object is reserved by an ongoing action.", reason_code="actor_unavailable")


def should_schedule(world, spec, actor_type, duration):
    return bool(autonomy_policy(spec) and actor_type == "resident" and duration > 0)


def register_action(db, *, world, spec, execution, actor, target, prepared, stage_runtime_id):
    from services import plan_service as plans
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    if world.current_time_minutes + prepared.duration_minutes > spec.calendar.day_end_minute:
        raise AtomicActionRuntimeError("Action exceeds today's time window.", reason_code="actor_unavailable")
    # Same shared resource and route checks used by plans. A stage already owns
    # its plan reservation, so only that particular commitment is excluded.
    plan_id = None
    if stage_runtime_id is not None:
        from services.stage_service import _binding
        plan_id = _binding(db, world.session_id, stage_runtime_id)[3].id
    available = plans._availability(db, world=world, spec=spec, start_day=world.current_day,
        start_time_minutes=world.current_time_minutes, duration_minutes=prepared.duration_minutes,
        location_id=actor.location_id, actors=[{"actor_type": "resident", "agent_id": actor.agent_id,
        "actor_key": actor.actor_key, "role_id": None, "required": True}],
        object_ids=[target.object_id] if target.object_id else [], role_slots=[], exclude_commitment_id=plan_id)
    if not available["available"]:
        raise AtomicActionRuntimeError("Scheduled action conflicts with an arrangement.", reason_code="actor_unavailable")
    value = {"job_id": f"atomic:{execution.id}", "kind": "atomic", "status": "pending", "audit_id": execution.id,
        "actor_key": actor.actor_key, "agent_id": actor.agent_id, "object_id": target.object_id,
        "start_ordinal": now, "end_ordinal": now + prepared.duration_minutes,
        "location_id": actor.location_id, "target": asdict(target), "stage_runtime_id": stage_runtime_id}
    _write(world, [*jobs(world), value])
    execution.metadata_json = json.dumps({"interruptible": prepared.interruptible, "clock_contract": "scheduled-execution-v1",
                                          "end_ordinal": value["end_ordinal"]})


def due_points(world, before, after):
    from services.plan_service import _ordinal
    low, high = _ordinal(before.day, before.minute), _ordinal(after.day, after.minute)
    return {ClockPosition((j["end_ordinal"] // 1440) + 1, j["end_ordinal"] % 1440)
            for j in jobs(world) if low < j["end_ordinal"] <= high}


def schedule_travel(db, *, world, spec, agent_id, plan):
    from services.plan_service import _ordinal, _json_loads, _json_dumps
    if actor_busy(world, f"resident:{agent_id}"):
        return False
    resident = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=agent_id).one()
    path = shortest_travel_path(spec, resident.current_location_id, plan.location_id)
    if not path or len(path) < 2:
        return False
    duration = (len(path) - 1) * int(spec.action_minutes["move"])
    now = _ordinal(world.current_day, world.current_time_minutes)
    start = _ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
    if now < start - duration or now + duration > start + 15:
        return False
    value = {"job_id": f"travel:{plan.id}:{agent_id}:{plan.revision}", "kind": "travel", "status": "pending",
        "actor_key": f"resident:{agent_id}", "agent_id": agent_id, "plan_id": plan.id,
        "start_ordinal": now, "end_ordinal": now + duration, "location_id": resident.current_location_id,
        "destination": plan.location_id, "path": list(path), "plan_generation": plan.reschedule_generation}
    _write(world, [*jobs(world), value])
    db.add(WorldAction(session_id=world.session_id, idempotency_key=value["job_id"], action_type="resident_depart",
        actor_type="resident", actor_agent_id=agent_id, target_location_id=plan.location_id,
        world_day=world.current_day, world_time_minutes=world.current_time_minutes,
        metadata_json=json.dumps(value), response_text="", language="en"))
    db.flush()
    return True


def reconcile_jobs(db, *, world, spec, cancel=False):
    from services import atomic_action_service as atomic, stage_service as stages, plan_service as plans
    from models import WorldCommitment
    from services.world_service import world_has_ended
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    values = sorted(jobs(world), key=lambda j: (j["end_ordinal"], j["actor_key"], j["job_id"]))
    results = []
    for job in values:
        if not cancel and job["end_ordinal"] > now and not world_has_ended(world):
            continue
        job["status"] = "cancelled" if cancel or world_has_ended(world) else "completed"
        # Release this job before revalidating its actor; other reservations remain.
        _write(world, values)
        resident = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=job["agent_id"]).one()
        if job["kind"] == "routine_travel":
            if job["status"] == "completed" and resident.current_location_id == job["location_id"]:
                resident.current_location_id = job["destination"]
                from world.schedules import resolve_resident_schedule
                from data.island import localized
                block = resolve_resident_schedule(spec, resident.agent_id, world.current_day, world.current_time_minutes)
                resident.current_activity = localized(block.activity, "zh-CN") if job["source"] == "daily_schedule" else "在" + localized(spec.locations[job["destination"]].name, "zh-CN") + "自由活动"
                db.add(WorldAction(session_id=world.session_id, idempotency_key=job["job_id"] + ":arrived", actor_type="resident", actor_agent_id=resident.agent_id, action_type="resident_arrival", target_location_id=job["destination"], world_day=world.current_day, world_time_minutes=world.current_time_minutes, response_text="", language="zh-CN", metadata_json=json.dumps(job)))
            continue
        if job["kind"] == "travel":
            plan = db.query(WorldCommitment).filter_by(id=job["plan_id"], session_id=world.session_id).first()
            if job["status"] == "completed" and plan and plan.status in ("accepted", "in_progress") and plan.reschedule_generation == job["plan_generation"] and resident.current_location_id == job["location_id"]:
                resident.current_location_id = job["destination"]
                state = plans._json_loads(resident.state_json, {})
                state["autonomy_schedule_override_state"] = resident.schedule_state
                resident.state_json = plans._json_dumps(state)
                db.add(WorldAction(session_id=world.session_id, idempotency_key=job["job_id"] + ":arrived", action_type="resident_arrival",
                    actor_type="resident", actor_agent_id=job["agent_id"], target_location_id=job["destination"], response_text="", language="en",
                    world_day=world.current_day, world_time_minutes=world.current_time_minutes, metadata_json=json.dumps(job)))
            continue
        audit = db.query(WorldAtomicActionExecution).filter_by(id=job["audit_id"], session_id=world.session_id).one()
        result = json.loads(audit.result_json)
        try:
            if job["status"] != "completed":
                raise AtomicActionRuntimeError("Scheduled action was cancelled.", reason_code="actor_unavailable")
            root, runtime = atomic._runtime_state(world)
            actor = atomic._actor_snapshot(db, world=world, runtime=runtime, actor_type="resident", actor_agent_id=job["agent_id"])
            if actor.location_id != job["location_id"]:
                raise AtomicActionRuntimeError("Actor left the reserved place.", reason_code="actor_unavailable")
            target = AtomicActionTarget(**job["target"])
            prepared = atomic._registry(spec).prepare(action_id=audit.action_id, actor=actor, target=target,
                context=atomic._runtime_context(db, world=world, spec=spec, runtime=runtime, actor=actor), inputs=json.loads(audit.inputs_json))
            # Validate stage participation and unchanged confirmation before effects.
            if job["stage_runtime_id"] is not None:
                stages.validate_scheduled_stage(db, world.session_id, job, audit)
            effects = [atomic._apply_effect(runtime, target=target, effect=e) for e in prepared.effects]
            runtime["revision"] += 1
            root["modular_runtime"] = runtime
            world.state_json = plans._json_dumps(root)
            result.update(status="completed", execution_status="completed", effects=effects, revision=runtime["revision"],
                          world_day=world.current_day, world_time_minutes=world.current_time_minutes)
            audit.status, audit.accepted_revision = "completed", runtime["revision"]
            audit.effects_json = plans._json_dumps(effects)
            if job["stage_runtime_id"] is not None:
                stages.complete_scheduled_stage(db, world, job, audit, result)
        except (AtomicActionRuntimeError, stages.StageServiceError) as exc:
            audit.status = job["status"] if job["status"] == "cancelled" else "failed"
            audit.reason_code = exc.reason_code
            result.update(status=audit.status, execution_status=audit.status, reason_code=exc.reason_code, effects=[])
        audit.result_json = plans._json_dumps(result)
        results.append(result)
    _write(world, values)
    db.flush()
    return results
