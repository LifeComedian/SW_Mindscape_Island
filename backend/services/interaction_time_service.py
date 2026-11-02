"""Dialogue slots and activity focus leases. Network calls run outside write locks."""
from datetime import datetime, timedelta
import json
import secrets

from models import WorldAction, WorldConversation, WorldConversationTurn, WorldState, Session as UserSession
from world.registry import get_world_spec
from world.interaction_policy import interaction_policy


def policy_for(world):
    return interaction_policy(get_world_spec(world.world_version))


def focus_state(world):
    return json.loads(world.state_json or "{}").get("m8_focus")


def _put_focus(world, value):
    state = json.loads(world.state_json or "{}")
    state["m8_focus"] = value
    world.state_json = json.dumps(state, ensure_ascii=False)
    world.updated_at = datetime.utcnow()


def conversation_slot(db, world, spec, agent_id, duration):
    from services import plan_service as plans
    from services.world_service import WorldStateError
    policy = interaction_policy(spec)
    if policy is None:
        return {}
    if duration not in (policy.conversation_minutes, policy.short_conversation_minutes):
        raise WorldStateError("Choose a 10 or 5 minute conversation.", 422)
    start = plans._ordinal(world.current_day, world.current_time_minutes)
    if world.current_time_minutes + duration > spec.calendar.day_end_minute:
        raise WorldStateError("There is not enough game time to talk. Try a short conversation or later.", 409)
    for actor_type, aid, key in (("participant", None, "participant"), ("resident", agent_id, f"resident:{agent_id}")):
        conflicts = plans._resource_conflicts(db, session_id=world.session_id,
            resource_keys=[("actor", key)], start_ordinal=start, end_ordinal=start + duration,
            exclude_commitment_id=None)
        if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            # Only accepted commitments block conversation time.
            from models import WorldPlanMember
            conflicts = [c for c in conflicts if db.query(WorldPlanMember.id).filter_by(
                commitment_id=c['commitment_id'], actor_key=key, response_status='accepted').first()]
        route_ok, reason, _ = plans._route_feasibility(db, world=world, spec=spec,
            actor_type=actor_type, agent_id=aid, actor_key=key, location_id=world.participant_location_id,
            start_ordinal=start, end_ordinal=start + duration, exclude_commitment_id=None)
        busy = plans._runtime_action_conflict(db, world=world, actor_type=actor_type, agent_id=aid,
                                             start_ordinal=start, end_ordinal=start + duration, allow_soft_jobs=world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'))
        if conflicts or not route_ok or busy:
            raise WorldStateError(f"Conversation time conflicts with an arrangement ({reason if not route_ok else 'actor_busy'}). Try 5 minutes or later.", 409)
    if focus_state(world):
        raise WorldStateError("Finish the current activity discussion first.", 409)
    if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        from services.holiday_flex_service import pause_routine
        pause_routine(db,world,agent_id,"paused_for_conversation")
    return {"time_policy": policy.policy_version, "duration_minutes": duration,
            "slot_start_ordinal": start, "slot_end_ordinal": start + duration,
            "settled": False, "focus_token": secrets.token_urlsafe(24),
            "lease_expires_at": (datetime.utcnow() + timedelta(seconds=policy.focus_lease_seconds)).isoformat()}


def settle_conversation(db, world, conversation):
    """Call only while holding Session write ownership; retry is a no-op."""
    from services.world_service import advance_world_clock
    metadata = json.loads(conversation.metadata_json or "{}")
    if metadata.get("time_policy") != "session-interaction-v1" or metadata.get("settled"):
        return 0
    has_reply = db.query(WorldConversationTurn.id).join(WorldAction, WorldAction.id == WorldConversationTurn.source_action_id).filter(
        WorldConversationTurn.conversation_id == conversation.id,
        WorldConversationTurn.speaker_type == "agent", WorldAction.action_type == "conversation_message").first() is not None
    minutes = int(metadata["duration_minutes"]) if has_reply else 0
    metadata.update(settled=True, applied_minutes=minutes)
    conversation.metadata_json = json.dumps(metadata)
    if minutes:
        advance_world_clock(db, world, minutes)
    return minutes


def expire_focus(db, world):
    """Expire wall-clock leases without offline catch-up. Called under lock."""
    if not policy_for(world):
        return
    focus = focus_state(world)
    if focus and not focus.get('full_activity') and datetime.fromisoformat(focus["lease_expires_at"]) <= datetime.utcnow():
        _release_focus(db, world, focus, expired=True)
    for conversation in db.query(WorldConversation).filter_by(session_id=world.session_id, status="active", conversation_kind="participant_resident"):
        metadata = json.loads(conversation.metadata_json or "{}")
        expiry = metadata.get("lease_expires_at")
        if expiry and datetime.fromisoformat(expiry) <= datetime.utcnow():
            conversation.status = "ended"
            conversation.ended_reason_code = "focus_abandoned"
            conversation.updated_at = datetime.utcnow()
            settle_conversation(db, world, conversation)
            for member in conversation.participants:
                member.left_at = conversation.updated_at
                member.leave_reason_code = "focus_abandoned"


def _release_focus(db, world, focus, *, expired=False):
    from models import WorldEventStageOperation
    from services.world_service import advance_world_clock
    effective = db.query(WorldEventStageOperation.id).filter(
        WorldEventStageOperation.session_id == world.session_id,
        WorldEventStageOperation.runtime_id == focus["runtime_id"],
        WorldEventStageOperation.id > focus["operation_floor"],
        WorldEventStageOperation.operation.in_(("suggest", "confirm", "reject", "execute", "finish")),
    ).first() is not None
    if not effective:
        effective = any(json.loads(row.metadata_json).get("runtime_id") == focus["runtime_id"]
                        and json.loads(row.metadata_json).get("status") == "completed"
                        for row in db.query(WorldAction).filter(WorldAction.session_id == world.session_id,
                            WorldAction.action_type == "stage_discussion",
                            WorldAction.id > focus.get("action_floor", 2**63-1)))
    _put_focus(world, None)
    # Charge time once for participation; viewing alone costs zero.
    minutes = focus["duration_minutes"] if effective else 0
    if minutes:
        advance_world_clock(db, world, minutes)
    return {"applied_minutes": minutes, "expired": expired}


def change_focus(db, *, session_id, request):
    from services import stage_service as stages
    from services import plan_service as plans
    from services.world_service import session_write_lock, WorldStateError, world_has_ended
    from models import WorldEventStageOperation
    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter_by(id=session_id).first()
        world = db.query(WorldState).filter_by(session_id=session_id).first()
        if not session or session.status != "active" or not world or world_has_ended(world) or not policy_for(world):
            raise WorldStateError("Interaction focus is unavailable.", 409)
        existing = db.query(WorldAction).filter_by(session_id=session_id, idempotency_key=request.idempotency_key).first()
        fingerprint = request.model_dump()
        if existing:
            stored = json.loads(existing.metadata_json)
            if stored.get("request") != fingerprint:
                raise WorldStateError("Focus idempotency key has different input.", 409)
            return stored["result"]
        expire_focus(db, world)
        policy = policy_for(world)
        expiry = (datetime.utcnow() + timedelta(seconds=policy.focus_lease_seconds)).isoformat()
        result = {"status": request.operation, "applied_minutes": 0}
        if request.conversation_id:
            conversation = db.query(WorldConversation).filter_by(id=request.conversation_id, session_id=session_id, status="active", conversation_kind="participant_resident").first()
            if not conversation or request.operation != "renew":
                raise WorldStateError("Conversation focus is no longer active.", 409)
            metadata = json.loads(conversation.metadata_json)
            if request.focus_token != metadata.get("focus_token"):
                raise WorldStateError("Another client owns this conversation focus.", 409)
            metadata["lease_expires_at"] = expiry
            conversation.metadata_json = json.dumps(metadata)
            result.update(focus_token=request.focus_token, lease_expires_at=expiry)
        else:
            focus = focus_state(world)
            if focus and focus.get('full_activity') and request.operation != 'renew':
                raise WorldStateError('请在活动窗口选择结束活动。', 409)
            if request.operation == "acquire":
                if focus or db.query(WorldConversation.id).filter_by(session_id=session_id, status="active", conversation_kind="participant_resident").first():
                    raise WorldStateError("Another interaction owns the Session focus.", 409)
                cards = stages.list_stage_cards(db, session_id=session_id)["cards"]
                card = next((c for c in cards if c["runtime_id"] == request.runtime_id and c["status"] == "active" and c["is_present"]), None)
                if not card or (card["kind"] not in ("decision", "closure") and not card.get("needs_confirmation")):
                    raise WorldStateError("Only a present participant can enter a discussion.", 409)
                world, _, runtime, plan, definition = stages._binding(db, session_id, request.runtime_id)
                stage = stages._ensure(db, world, runtime, plan, definition)
                row = db.query(WorldEventStageOperation).filter_by(session_id=session_id).order_by(WorldEventStageOperation.id.desc()).first()
                last_action = db.query(WorldAction).filter_by(session_id=session_id).order_by(WorldAction.id.desc()).first()
                focus = {"token": secrets.token_urlsafe(24), "runtime_id": request.runtime_id,
                         "stage_id": stage.current_stage_id, "operation_floor": row.id if row else 0,
                         "action_floor": last_action.id if last_action else 0,
                         "duration_minutes": max(0, stage.deadline_ordinal - plans._ordinal(world.current_day, world.current_time_minutes)), "lease_expires_at": expiry}
                _put_focus(world, focus)
            elif not focus or focus["token"] != request.focus_token or focus["runtime_id"] != request.runtime_id:
                raise WorldStateError("Activity focus expired or belongs to another client.", 409)
            elif request.operation == "renew":
                focus["lease_expires_at"] = expiry
                _put_focus(world, focus)
            else:
                result.update(_release_focus(db, world, focus))
            result.update(focus_token=focus["token"], lease_expires_at=expiry)
        db.add(WorldAction(session_id=session_id, idempotency_key=request.idempotency_key,
            action_type="interaction_focus", language="en", world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json=json.dumps({"request": fingerprint, "result": result})))
        db.commit()
        return result
