"""Daily summaries of completed participant actions."""
from models import WorldAction, WorldCommitment, WorldPlanMember, WorldAtomicActionExecution
from services import plan_service as plans
from data.island import localized


def pending_arrangements(db, world):
    return db.query(WorldCommitment, WorldPlanMember).join(WorldPlanMember,
        WorldPlanMember.commitment_id == WorldCommitment.id).filter(
        WorldCommitment.session_id == world.session_id,
        WorldCommitment.scheduled_day == world.current_day,
        WorldCommitment.status.in_(("proposed", "accepted", "in_progress")),
        WorldPlanMember.actor_key == "participant", WorldPlanMember.response_status == "accepted",
        WorldPlanMember.attendance_status.notin_(("left_early", "absent"))).all()


def review(db, *, session_id, day=None, language="zh-CN"):
    from models import WorldState
    from world.registry import get_world_spec
    world = db.query(WorldState).filter_by(session_id=session_id).one()
    spec = get_world_spec(world.world_version)
    day = world.current_day if day is None else day
    if not 1 <= day <= world.current_day:
        raise plans.PlanServiceError("This day has not happened.", reason_code="invalid_day", status_code=422)
    definitions = {a["action_id"]: a for a in spec.systems.get("action_definitions", ())}
    events = []
    actions = db.query(WorldAction).filter_by(session_id=session_id, actor_type="participant", world_day=day).order_by(WorldAction.id).all()
    completed = {a.source_action_id: a for a in db.query(WorldAtomicActionExecution).filter_by(session_id=session_id, actor_type="participant", status="completed").all()}
    for action in actions:
        audit = completed.get(action.id)
        if audit and audit.action_id in definitions:
            label = localized(definitions[audit.action_id]["label"], language)
        elif action.action_type == "end_conversation":
            label = "结束了一次交谈" if language == "zh-CN" else "Finished a conversation"
        elif action.action_type == 'activity_experience':
            metadata = plans._json_loads(action.metadata_json,{})
            if metadata.get('request',{}).get('operation') != 'end':
                continue
            label = '参加了' + metadata.get('result',{}).get('title','活动')
        elif action.action_type == "move" and action.target_location_id in spec.locations:
            label = ("前往" if language == "zh-CN" else "Visited ") + localized(spec.locations[action.target_location_id].name, language)
        else:
            continue
        events.append({"event_id": action.id, "minute": action.world_time_minutes, "label": label})
    pending = []
    if day == world.current_day:
        for plan, _member in pending_arrangements(db, world):
            recipe = plans._recipe(spec, plan.recipe_id)
            pending.append({"plan_id": plan.id, "revision": plan.revision, "label": localized(recipe["label"], language)})
    return {"day": day, "events": events, "pending_arrangements": pending,
        "empty_message": "今天还没有可列出的已完成互动。安静度过一天也是一种选择。" if language == "zh-CN" else "No completed interactions to list. A quiet day is a valid choice."}


def leave_today(db, *, world, idempotency_key):
    for plan, member in pending_arrangements(db, world):
        operation = "leave" if plan.status == "in_progress" and member.attendance_status in ("present", "late") else "cancel" if plan.organizer_type == "participant" else "withdraw"
        plans.transition_plan(db, session_id=world.session_id, commitment_id=plan.id, managed_transaction=True,
            request={"transition": operation, "expected_revision": plan.revision,
                "idempotency_key": f"{idempotency_key}:rest:{plan.id}", "reason_code": "participant_ended_day"})
