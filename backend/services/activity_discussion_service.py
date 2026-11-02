"""In-scene dialogue with game time paused and database locks released."""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from models import WorldAction
from config import settings
from services import stage_service as stages, plan_service as plans
from services.interaction_time_service import focus_state
from services.world_service import session_write_lock


def discussion_rows(db, session_id, runtime_id):
    rows = db.query(WorldAction).filter_by(session_id=session_id, actor_type="participant", action_type="stage_discussion", event_instance_id=None).order_by(WorldAction.id).all()
    return [(r, json.loads(r.metadata_json)) for r in rows if json.loads(r.metadata_json).get("runtime_id") == runtime_id]


def transcript(db, session_id, runtime_id):
    return [{"id": r.id, "text": r.response_text, "speaker": m.get("speaker", ""), "reply": m.get("reply", ""), "mode": m.get("mode")} for r,m in discussion_rows(db, session_id, runtime_id) if m.get("status") == "completed"]


async def discuss(db, *, session_id, runtime_id, request, provider=None):
    from agents.base import AgentRequest
    from agents.role_prompt import build_role_messages
    from agents.llm_transport import ChatTransport, TransportError
    from services.role_context_service import build_role_context
    from agents.safety import check_user_comment_safety
    key = request.idempotency_key
    text = str(request.inputs.get("message", "")).strip()
    if not text or len(text) > 500:
        stages._fail("Write between 1 and 500 characters.", "invalid_request", 422)
    with session_write_lock(session_id):
        db.rollback()
        world, spec, runtime, plan, definition = stages._binding(db, session_id, runtime_id)
        if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            stages._fail('Use the independent activity scene.', 'activity_scene_required')
        focus = focus_state(world)
        if not focus or focus["runtime_id"] != runtime_id or focus["token"] != request.focus_token or datetime.fromisoformat(focus["lease_expires_at"]) <= datetime.utcnow():
            stages._fail("Enter discussion first.", "focus_changed")
        stage = stages._ensure(db, world, runtime, plan, definition)
        member = stages._member(db, plan, "participant")
        if stage.status != "active" or not stages._present(db, world, plan, member):
            stages._fail("You must be present in an active activity.", "actor_unavailable")
        previous = db.query(WorldAction).filter_by(session_id=session_id, idempotency_key=key).first()
        if previous:
            meta = json.loads(previous.metadata_json)
            if previous.action_type != "stage_discussion" or previous.response_text != text or meta.get("runtime_id") != runtime_id:
                stages._fail("Key reused for different input.", "idempotency_conflict")
            if meta.get("status") != "completed":
                stages._fail("Previous request is pending or failed.", "discussion_not_completed")
            return stages._serialize(db, world, runtime, stage, plan, "participant")
        if request.expected_revision != stage.revision:
            stages._fail("Stage changed before your message was sent.", "stale_revision")
        rows = discussion_rows(db, session_id, runtime_id)
        if len(rows) >= 24 or any(m.get("status") == "pending" and datetime.fromisoformat(m["lease"]) > datetime.utcnow() for _,m in rows):
            stages._fail("Discussion limit or another reply is pending.", "discussion_busy", 429)
        present = [m.actor_agent_id for m in stages._members(db, plan) if m.actor_type == "resident" and stages._present(db, world, plan, m)]
        if not present:
            stages._fail("No resident is present to reply.", "no_discussion_partner")
        aid = present[len(rows) % len(present)]
        context = build_role_context(db, world=world, spec=spec, agent_id=aid, language=request.language, scene_kind="stage_dialogue")
        from data.island import localized
        recipe = plans._recipe(spec, plan.recipe_id)
        current = stages._card(stage)
        context = replace(context,
            activity=f"{localized(recipe['label'], request.language)}正在进行；当前环节：{localized(current['label'], request.language)}；你和玩家都已到场。",
            goal="回应玩家眼前的活动体验；只提出建议，具体动作由玩家选择后执行。")
        history = []
        for row, meta in rows[-6:]:
            if meta.get("status") == "completed":
                history += [{"speaker": "participant", "content": row.response_text, "source_turn_id": row.id}, {"speaker": meta["speaker"], "content": meta["reply"], "source_turn_id": row.id}]
        from services.world_memory_service import build_agent_memory_context
        memory = build_agent_memory_context(db, session_id=session_id, owner_agent_id=aid,
            current_day=world.current_day, current_time_minutes=world.current_time_minutes, location_id=plan.location_id)
        prompt = AgentRequest(session_id=session_id, agent_id=aid, post_id=0, post_content="", user_comment=text, language=request.language, world_role_context=context, recent_history=history, agent_memory=memory)
        row = WorldAction(session_id=session_id, idempotency_key=key, actor_type="participant", action_type="stage_discussion", target_agent_id=aid, target_location_id=plan.location_id, response_text=text, language=request.language, world_day=world.current_day, world_time_minutes=world.current_time_minutes,
            metadata_json=plans._json_dumps({"runtime_id": runtime_id, "stage_id": stage.current_stage_id, "status": "pending", "lease": (datetime.utcnow()+timedelta(seconds=150)).isoformat(), "speaker": context.name}))
        db.add(row); db.commit(); row_id = row.id
        db.rollback()
    transport = provider or ChatTransport()
    try:
        safety = check_user_comment_safety(text, request.language)
        if safety.safety_flag and safety.reply_text:
            reply, mode = safety.reply_text, "safety_rule"
        elif provider is None and settings.agent_mode != "llm":
            reply, mode = f"我们可以先按你喜欢的方式试试。现在是{context.activity}，要不要从眼前这一小步开始？", "rule"
        else:
            reply = await transport.generate(build_role_messages(prompt), max_output_tokens=384, retry=False)
            reply, mode = reply.strip()[:600], "llm"
            if not reply: raise TransportError("empty_output")
    except Exception:
        with session_write_lock(session_id):
            db.rollback(); row = db.get(WorldAction, row_id); meta = json.loads(row.metadata_json); meta["status"] = "failed"; row.metadata_json = plans._json_dumps(meta); db.commit()
        stages._fail("Reply failed. You can retry without advancing game time.", "discussion_provider_failed", 503)
    with session_write_lock(session_id):
        db.rollback()
        world, spec, runtime, plan, definition = stages._binding(db, session_id, runtime_id)
        row = db.get(WorldAction, row_id); meta = json.loads(row.metadata_json)
        focus = focus_state(world); stage = stages._ensure(db, world, runtime, plan, definition)
        member = stages._member(db, plan, "participant")
        if (not focus or focus["token"] != request.focus_token or focus["runtime_id"] != runtime_id
                or datetime.fromisoformat(focus["lease_expires_at"]) <= datetime.utcnow()
                or stage.current_stage_id != meta["stage_id"] or stage.status != "active"
                or not stages._present(db, world, plan, member)):
            meta["status"] = "discarded"; row.metadata_json = plans._json_dumps(meta); db.commit()
            stages._fail("Activity changed before the reply arrived.", "stale_revision")
        meta.update(status="completed", reply=reply, mode=mode, usage=getattr(transport, "last_metrics", {}))
        row.metadata_json = plans._json_dumps(meta)
        from services.world_memory_service import record_memory
        record_memory(db, session_id=session_id, owner_agent_id=aid, memory_type="episodic",
            content=f"活动讨论中，来访者说：{text}。我回应：{reply}",
            occurred_day=world.current_day, occurred_time_minutes=world.current_time_minutes,
            source_action_id=row.id, source_event_type="stage_discussion", source_event_id=row.id,
            importance=2, location_id=plan.location_id, tags=("activity_discussion",))
        db.commit()
        return stages._serialize(db, world, runtime, stage, plan, "participant")
