"""Activity stages, contributions, and acquired facts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from sqlalchemy.orm import Session as DBSession
from content.serializers import to_plain_data
from world.registry import get_world_spec

from models import (
    WorldActorKnowledge, WorldCommitment, WorldEmergentEventRuntime,
    WorldEventStage, WorldEventStageOperation, WorldKnowledgeFact, WorldPlanMember, WorldPlanTransition, WorldConversation,
)
from services import atomic_action_service as atomic
from services import plan_service as plans
from services.phone_plan_service import _grant_knowledge
from services.world_service import session_write_lock, world_has_ended
from world.specs import WorldSpecValidationError
from world.stage_recipes import validate_stage_cards


STAGE_RUNTIME_VERSION = "modular-stage-runtime-v1"
MAX_OPERATIONS_PER_EVENT = 64


class StageServiceError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409):
        super().__init__(detail)
        self.detail, self.reason_code, self.status_code = detail, reason_code, status_code


def _fail(message, reason="invalid_stage_transition", status=409):
    raise StageServiceError(message, reason_code=reason, status_code=status)


def _hash(value):
    return hashlib.sha256(plans._json_dumps(to_plain_data(value)).encode("utf-8")).hexdigest()


def _state(stage):
    return json.loads(stage.state_json)


def _card(stage):
    return next(c for c in json.loads(stage.definition_json)["stages"] if c["stage_id"] == stage.current_stage_id)


def _binding(db, session_id, runtime_id):
    world, spec = plans._world_and_spec(db, session_id)
    if world_has_ended(world):
        _fail("The world is frozen.", "world_ended")
    runtime = db.query(WorldEmergentEventRuntime).filter_by(id=runtime_id, session_id=session_id).first()
    if runtime is None:
        _fail("Event not found.", "unknown_reference", 404)
    plan = db.query(WorldCommitment).filter_by(id=runtime.commitment_id, session_id=session_id).one()
    recipe = plans._recipe(spec, plan.recipe_id)
    definition_id = recipe.get("conditions", {}).get("stage_recipe_id")
    definition = next((s for s in spec.systems.get("stage_recipes", ()) if s["stage_recipe_id"] == definition_id), None)
    if definition is None or not definition.get("stages"):
        _fail("Event has no executable stage recipe.", "unknown_stage_recipe")
    try:
        validate_stage_cards(definition, spec.systems)
    except WorldSpecValidationError as exc:
        _fail(str(exc), "invalid_stage_recipe")
    return world, spec, runtime, plan, to_plain_data(definition)


def _conversation_frozen(db, session_id):
    return db.query(WorldConversation.id).filter_by(session_id=session_id, status="active", conversation_kind="participant_resident").first() is not None


def _ensure(db, world, runtime, plan, definition):
    stage = db.query(WorldEventStage).filter_by(runtime_id=runtime.id).first()
    if stage is not None:
        if stage.definition_hash != _hash(definition):
            _fail("Bound stage definition changed.", "stage_version_mismatch")
        return stage
    now = _timeline_start(db, world, plan)
    card = definition["stages"][0]
    stage = WorldEventStage(
        session_id=world.session_id, runtime_id=runtime.id,
        stage_recipe_id=definition["stage_recipe_id"], definition_hash=_hash(definition),
        definition_json=plans._json_dumps(definition), current_stage_id=card["stage_id"],
        status="active" if plan.status == "in_progress" else "waiting", revision=0,
        entered_ordinal=now, deadline_ordinal=now + card["duration_minutes"],
        state_json=plans._json_dumps({"proposal": None, "confirmation": None, "visited": [card["stage_id"]], "contributions": [], "fact_ids": [], "public_consents": [], "revoked_by": [], "witnesses": []}),
        public_consent=False,
    )
    db.add(stage)
    db.flush()
    return stage


def _started_ordinal(db, world, plan):
    start = db.query(WorldPlanTransition).filter_by(commitment_id=plan.id, transition_type="start").order_by(WorldPlanTransition.id.desc()).first()
    if plan.status == "in_progress" and start is not None:
        return plans._ordinal(start.world_day, start.world_time_minutes)
    return plans._ordinal(world.current_day, world.current_time_minutes)


def _fixed_timeline(db, world, plan):
    _, spec = plans._world_and_spec(db, world.session_id)
    return plans._recipe(spec, plan.recipe_id).get("conditions", {}).get("fixed_stage_timeline") is True


def _timeline_start(db, world, plan):
    return plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes) if _fixed_timeline(db, world, plan) else _started_ordinal(db, world, plan)


def _members(db, plan):
    return db.query(WorldPlanMember).filter_by(commitment_id=plan.id).order_by(WorldPlanMember.id).all()


def _present(db, world, plan, member):
    return member.response_status == "accepted" and member.attendance_status in ("present", "late") and plans._current_presence(db, world=world, plan=plan, member=member)


def _member(db, plan, actor_key):
    member = db.query(WorldPlanMember).filter_by(commitment_id=plan.id, actor_key=actor_key).first()
    if member is None:
        _fail("Actor is not a member of this event.", "permission_denied", 403)
    return member


def organizer_ready_to_begin(db, world, plan, actor_key="participant"):
    """Read physical presence, including the host who has not clicked arrive yet.

    This is only a readiness projection; the start transition owns attendance.
    Previously the foreground UI required in_progress before exposing that start.
    """
    if plan.status != "accepted" or plans._actor_key(plan.organizer_type, plan.organizer_agent_id) != actor_key:
        return False
    if plans._ordinal(world.current_day, world.current_time_minutes) < plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes):
        return False
    present = {m.actor_key for m in _members(db, plan)
               if m.response_status == "accepted" and m.attendance_status in ("pending", "present", "late")
               and plans._current_presence(db, world=world, plan=plan, member=m)}
    required = set(json.loads(plan.required_actor_keys_json or "[]"))
    return actor_key in present and required <= present and len(present) >= plan.min_participants


def _role(member, plan):
    organizer = plans._actor_key(plan.organizer_type, plan.organizer_agent_id)
    return "organizer" if member.actor_key == organizer else member.role_id


def _has_authority(member, plan, card):
    return _role(member, plan) in card["authority_roles"] and member.actor_type in card.get("authority_actor_types", ("participant", "resident"))


def _facts(db, world, runtime, stage, plan, state, fact_type, payload, witnesses):
    key = f"stage:{runtime.id}:{stage.revision}:{fact_type}"
    fact = WorldKnowledgeFact(
        session_id=world.session_id, fact_key=key, fact_type=fact_type,
        subject_type="emergent_event", subject_id=runtime.id, visibility="private",
        source_type="stage_execution", source_id=runtime.id,
        payload_json=plans._json_dumps({"runtime_id": runtime.id, "commitment_id": plan.id, "stage_id": stage.current_stage_id, "fact_chain_id": runtime.fact_chain_id, "stage_recipe_id": stage.stage_recipe_id, "definition_hash": stage.definition_hash, **payload}),
        world_day=world.current_day, world_time_minutes=world.current_time_minutes,
    )
    db.add(fact)
    db.flush()
    state["fact_ids"].append(fact.id)
    state["witnesses"] = sorted(set(state["witnesses"]) | set(witnesses))
    for actor_key in witnesses:
        _grant_knowledge(db, fact=fact, actor_key=actor_key, acquisition_source="experienced", source_post_id=None, day=world.current_day, time_minutes=world.current_time_minutes)
    return fact


def _refresh_visibility(db, stage, state):
    stage.public_consent = bool(state["witnesses"]) and not state["revoked_by"] and set(state["witnesses"]) <= set(state["public_consents"])
    for fact in db.query(WorldKnowledgeFact).filter(WorldKnowledgeFact.id.in_(state["fact_ids"])).all():
        fact.visibility = "island_public" if stage.public_consent else "private"
    # Revocation blocks new access, not previously acquired knowledge.
    from models import UserPost, WorldState
    from services.interaction_time_service import policy_for
    world = db.query(WorldState).filter_by(session_id=stage.session_id).one()
    if policy_for(world):
        runtime = db.query(WorldEmergentEventRuntime).filter_by(id=stage.runtime_id).one()
        for post in db.query(UserPost).filter_by(session_id=stage.session_id,
                post_type="activity_record", source_type="world_plan", source_id=runtime.commitment_id):
            post.visibility = "island_public" if stage.public_consent else "private"
            for fact in db.query(WorldKnowledgeFact).filter_by(session_id=stage.session_id,
                    source_type="phone_post", source_id=post.id, fact_type="activity_record"):
                fact.visibility = post.visibility


def _advance(stage, choice, state, world):
    if choice["outcome"]:
        stage.status, stage.outcome = "completed", "partial" if state.get("missed_stages") else choice["outcome"]
        return
    target = choice["next_stage_id"]
    if target in state["visited"] or len(state["visited"]) >= 3:
        _fail("Stage cycle or safety bound reached.", "stage_cycle_blocked")
    state["visited"].append(target)
    from services.interaction_time_service import focus_state
    focus = focus_state(world)
    deferred_cost = focus["duration_minutes"] if focus and focus["runtime_id"] == stage.runtime_id and focus["stage_id"] == stage.current_stage_id else 0
    stage.current_stage_id = target
    if _card(stage).get("confirm_in_place"):
        state["confirmation"] = None
    stage.entered_ordinal = plans._ordinal(world.current_day, world.current_time_minutes) + deferred_cost
    stage.deadline_ordinal = stage.entered_ordinal + _card(stage)["duration_minutes"]
    state["proposal"] = None


def _plan_transition(db, world, plan, operation, key, reason):
    return plans.transition_plan(
        db, session_id=world.session_id, commitment_id=plan.id,
        actor_type=plan.organizer_type, actor_agent_id=plan.organizer_agent_id,
        managed_transaction=True,
        request={"transition": operation, "expected_revision": plan.revision,
                 "idempotency_key": key, "reason_code": reason},
    )


def _finish(db, world, runtime, stage, plan, state, reason):
    witnesses = [m.actor_key for m in _members(db, plan) if _present(db, world, plan, m)]
    _facts(db, world, runtime, stage, plan, state, "stage_outcome", {
        "outcome": stage.outcome, "reason_code": reason,
        "pending_tasks": [] if stage.status == "completed" else ["activity_not_completed"],
    }, witnesses)
    _refresh_visibility(db, stage, state)
    stage.state_json = plans._json_dumps(state)
    db.flush()
    if plan.status == "in_progress":
        _plan_transition(db, world, plan, "complete" if stage.status == "completed" else "fail", f"stage-close:{runtime.id}:{stage.revision}", reason)


def guard_plan_stage_completion(db, *, plan, spec):
    if not plans._recipe(spec, plan.recipe_id).get("conditions", {}).get("stage_recipe_id"):
        return
    runtime = db.query(WorldEmergentEventRuntime).filter_by(commitment_id=plan.id).first()
    stage = db.query(WorldEventStage).filter_by(runtime_id=runtime.id).first() if runtime else None
    if stage is None or stage.status != "completed":
        raise plans.PlanServiceError("Complete the registered event stages first.", reason_code="stage_incomplete")


def guard_atomic_stage_action(db, *, session_id, action_id, object_id, stage_runtime_id):
    # Protect the bound action/object even before the first card is requested.
    world, spec = atomic._world_and_spec(db, session_id)
    for plan in db.query(WorldCommitment).filter_by(session_id=session_id, status="in_progress").all():
        stage_id = plans._recipe(spec, plan.recipe_id).get("conditions", {}).get("stage_recipe_id")
        definition = next((d for d in spec.systems.get("stage_recipes", ()) if d["stage_recipe_id"] == stage_id), None)
        if not definition:
            continue
        guarded = any(c["action_id"] == action_id and c["object_id"] == object_id for s in definition.get("stages", ()) for c in s["choices"])
        runtime = db.query(WorldEmergentEventRuntime).filter_by(commitment_id=plan.id).first()
        if guarded and (runtime is None or stage_runtime_id != runtime.id):
            raise atomic.AtomicActionServiceError("This object action requires its event-stage confirmation.", reason_code="permission_denied")


def _serialize(db, world, runtime, stage, plan, actor_key):
    card, state = _card(stage), _state(stage)
    member = _member(db, plan, actor_key)
    here = _present(db, world, plan, member)
    due = plans._ordinal(world.current_day, world.current_time_minutes) >= stage.entered_ordinal
    authority = here and due and _has_authority(member, plan, card)
    choices = list(card["choices"]) if stage.status == "active" and here and due else []
    spec = get_world_spec(world.world_version)
    action_definitions = {a["action_id"]: a for a in spec.systems.get("action_definitions", ())}
    choices = [{**dict(c), "input_fields": [dict(i) for i in action_definitions.get(c["action_id"], {}).get("inputs", ())
                if i["input_id"] not in c["inputs"]]} for c in choices]
    if card["kind"] == "action" and state["confirmation"]:
        choices = [c for c in choices if c["choice_id"] == state["confirmation"]["choice_id"]]
    # Completed contributions are read from acquired facts, never the global ledger.
    known = {k.fact_id for k in db.query(WorldActorKnowledge).filter_by(session_id=world.session_id, actor_key=actor_key)}
    controls = []
    organizer = plans._actor_key(plan.organizer_type, plan.organizer_agent_id) == actor_key
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    at_location = plans._current_presence(db, world=world, plan=plan, member=member)
    if plan.status in ("proposed", "accepted"):
        if member.response_status in ("proposed", "deferred"):
            controls.append("accept")
        if organizer:
            controls.append("cancel")
        elif member.response_status == "accepted":
            controls.append("withdraw")
        if organizer and plan.status == "accepted" and at_location and now >= plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes):
            controls.append("start")
    if plan.status in ("accepted", "in_progress") and member.response_status == "accepted" and at_location and member.attendance_status == "pending" and now >= plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes):
        controls.append("arrive")
    if plan.status == "in_progress" and member.attendance_status in ("present", "late"):
        controls.append("leave")
    from services.activity_discussion_service import transcript
    return {
        "discussion": transcript(db, world.session_id, runtime.id) if actor_key == "participant" else [],
        "runtime_version": STAGE_RUNTIME_VERSION, "runtime_id": runtime.id,
        "commitment_id": plan.id, "location_id": plan.location_id,
        "activity_label": dict(plans._recipe(spec, plan.recipe_id)["label"]),
        "location_label": dict(spec.locations[plan.location_id].name),
        "viewer_response": member.response_status,
        "plan_revision": plan.revision, "plan_controls": controls, "plan_status": plan.status,
        "ready_to_begin": spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and organizer_ready_to_begin(db, world, plan, actor_key),
        "scheduled_day": plan.scheduled_day, "scheduled_time_minutes": plan.scheduled_time_minutes,
        "status": stage.status, "revision": stage.revision,
        "stage_id": stage.current_stage_id, "kind": card["kind"], "label": card["label"],
        "role_goals": card["role_goals"], "choices": choices, "can_confirm": authority,
        "can_finish": authority, "is_present": here,
        "needs_confirmation": bool(card.get("confirm_in_place") and not state["confirmation"]),
        "missed_stages": state.get("missed_stages", []),
        "proposal": state["proposal"] if here else None,
        "deadline_ordinal": stage.deadline_ordinal, "outcome": stage.outcome if here or known.intersection(state["fact_ids"]) else None,
        "public_consent": stage.public_consent,
        "facts": [{"fact_id": f.id, "visibility": f.visibility, "payload": json.loads(f.payload_json)} for f in db.query(WorldKnowledgeFact).filter(WorldKnowledgeFact.id.in_(state["fact_ids"])).order_by(WorldKnowledgeFact.id) if f.id in known],
    }


def reconcile_stages(db, *, session_id):
    """Bounded lazy initialization/expiry, invoked by director reads and pulses."""
    with session_write_lock(session_id):
        world, spec = plans._world_and_spec(db, session_id)
        if world_has_ended(world):
            return
        if _conversation_frozen(db, session_id):
            return
        now = plans._ordinal(world.current_day, world.current_time_minutes)
        for runtime in db.query(WorldEmergentEventRuntime).filter_by(session_id=session_id).order_by(WorldEmergentEventRuntime.id).all():
            plan = db.query(WorldCommitment).filter_by(id=runtime.commitment_id).one()
            if not plans._recipe(spec, plan.recipe_id).get("conditions", {}).get("stage_recipe_id"):
                continue
            _, _, _, _, definition = _binding(db, session_id, runtime.id)
            stage = _ensure(db, world, runtime, plan, definition)
            if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
                # Polling must not advance or time out foreground activity steps.
                if stage.status not in ('completed', 'failed'):
                    stage.status = 'active' if plan.status == 'in_progress' else 'waiting' if plan.status in plans.ACTIVE_PLAN_STATES else 'failed'
                continue
            if stage.status in ("completed", "failed"):
                continue
            state = _state(stage)
            reason = None
            if plan.status not in plans.ACTIVE_PLAN_STATES:
                reason = plan.ended_reason_code or "plan_terminal"
                stage.outcome = _card(stage)["absence_outcome"]
            elif stage.status == "waiting" and plan.status == "in_progress":
                stage.status = "active"
                stage.entered_ordinal = _timeline_start(db, world, plan)
                stage.deadline_ordinal = stage.entered_ordinal + _card(stage)["duration_minutes"]
                stage.revision += 1
            if stage.status == "active" and now >= stage.deadline_ordinal and _fixed_timeline(db, world, plan):
                # Missed windows advance the public clock, never a player's actions.
                cards = definition["stages"]
                while stage.status == "active" and now >= stage.deadline_ordinal:
                    state.setdefault("missed_stages", []).append(stage.current_stage_id)
                    stage.revision += 1
                    index = next(i for i, c in enumerate(cards) if c["stage_id"] == stage.current_stage_id)
                    if index + 1 == len(cards):
                        stage.status = "completed"
                        stage.outcome = "partial" if state["contributions"] else "not_completed"
                        _finish(db, world, runtime, stage, plan, state, "authored_window_ended")
                    else:
                        stage.entered_ordinal = stage.deadline_ordinal
                        stage.current_stage_id = cards[index + 1]["stage_id"]
                        stage.deadline_ordinal += cards[index + 1]["duration_minutes"]
                        state["visited"].append(stage.current_stage_id)
                        state["proposal"], state["confirmation"] = None, None
                stage.state_json = plans._json_dumps(state)
            if stage.status == "active" and now >= stage.deadline_ordinal:
                reason = "stage_timeout"
                stage.outcome = _card(stage)["timeout_outcome"]
                if not any(_has_authority(m, plan, _card(stage)) and _present(db, world, plan, m) for m in _members(db, plan)):
                    reason = "stage_authority_absent"
                    stage.outcome = _card(stage)["absence_outcome"]
            if reason:
                stage.status = "failed"
                stage.revision += 1
                _finish(db, world, runtime, stage, plan, state, reason)
                db.add(WorldEventStageOperation(session_id=session_id, runtime_id=runtime.id, idempotency_key=f"stage-system:{runtime.id}:{stage.revision}", request_hash=_hash({"reason": reason}), actor_key="system", operation="reconcile", stage_id=stage.current_stage_id, world_day=world.current_day, world_time_minutes=world.current_time_minutes, result_json=plans._json_dumps({"reason_code": reason, "status": stage.status})))
            stage.state_json = plans._json_dumps(state)
            stage.updated_at = plans._utc_now()
        db.commit()


def list_stage_cards(db, *, session_id, actor_type="participant", actor_agent_id=None):
    actor_key = plans._actor_key(actor_type, actor_agent_id)
    world, _spec = plans._world_and_spec(db, session_id)
    if not world_has_ended(world):
        reconcile_stages(db, session_id=session_id)
    cards = []
    for stage in db.query(WorldEventStage).filter_by(session_id=session_id).order_by(WorldEventStage.id):
        runtime = db.query(WorldEmergentEventRuntime).filter_by(id=stage.runtime_id).one()
        plan = db.query(WorldCommitment).filter_by(id=runtime.commitment_id).one()
        if db.query(WorldPlanMember).filter_by(commitment_id=plan.id, actor_key=actor_key).first():
            cards.append(_serialize(db, world, runtime, stage, plan, actor_key))
    from services.interaction_time_service import policy_for, focus_state
    focus = focus_state(world) if actor_type == "participant" else None
    return {"runtime_version": STAGE_RUNTIME_VERSION, "cards": cards,
            "interaction_time_policy": bool(policy_for(world)),
            "interaction_focus": {"runtime_id": focus["runtime_id"], "focus_token": focus["token"],
                "lease_expires_at": focus["lease_expires_at"]} if focus else None}


def transition_stage(db: DBSession, *, session_id: int, runtime_id: int, request: Any,
                     actor_type="participant", actor_agent_id=None,
                     failure_injector: Callable | None = None,
                     before_commit: Callable[[dict], None] | None = None):
    actor_key = plans._actor_key(actor_type, actor_agent_id)
    payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
    payload.update(actor_key=actor_key, runtime_id=runtime_id)
    key = str(payload.get("idempotency_key", ""))
    if not 1 <= len(key) <= 120:
        _fail("Invalid stage operation key.", "invalid_request", 422)
    request_hash = _hash(payload)
    with session_write_lock(session_id):
        db.rollback()
        world, spec, runtime, plan, definition = _binding(db, session_id, runtime_id)
        if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            _fail('请从独立活动窗口参与。', 'experience_scene_required')
        if _conversation_frozen(db, session_id):
            _fail("Finish the current conversation before changing an activity.", "active_conversation")
        member = _member(db, plan, actor_key)
        previous = db.query(WorldEventStageOperation).filter_by(session_id=session_id, idempotency_key=key).first()
        if previous:
            if previous.request_hash != request_hash:
                _fail("Stage key was reused.", "idempotency_conflict")
            return json.loads(previous.result_json)
        from services.interaction_time_service import focus_state
        focus = focus_state(world)
        if focus and (focus["runtime_id"] != runtime_id or actor_type == "participant" and payload.get("focus_token") != focus["token"]):
            _fail("Discussion focus changed. Reload the current activity.", "focus_changed")
        if payload.get("operation") != "revoke_publication" and db.query(WorldEventStageOperation).filter_by(runtime_id=runtime_id).count() >= MAX_OPERATIONS_PER_EVENT:
            _fail("Stage operation audit limit reached.", "stage_operation_limit", 429)
        reconcile_stages(db, session_id=session_id)
        stage = _ensure(db, world, runtime, plan, definition)
        if type(payload.get("expected_revision")) is not int or payload["expected_revision"] != stage.revision:
            _fail("Stage revision changed. Reload its current card.", "stale_revision")
        operation, state, card = payload.get("operation"), _state(stage), _card(stage)
        present = _present(db, world, plan, member)
        authority = _has_authority(member, plan, card)
        if operation in ("allow_publication", "revoke_publication"):
            if actor_key not in state["witnesses"]:
                _fail("Only a recorded witness can control publication.", "permission_denied", 403)
        elif stage.status != "active" or plan.status != "in_progress" or not present:
            _fail("This actor cannot act on the current stage.", "actor_unavailable")
        if operation not in ("allow_publication", "revoke_publication"):
            expected = card["enter_conditions"].get("object_state", {})
            atomic_state = atomic._runtime_state(world)[1]
            for object_id in plans._json_loads(plan.object_ids_json, []):
                actual = atomic_state["object_states"].get(object_id, {})
                if any(actual.get(k) != v for k, v in expected.items()):
                    _fail("Stage entry facts no longer hold.", "stage_precondition_failed")
        choice = next((c for c in card["choices"] if c["choice_id"] == payload.get("choice_id")), None)
        now = plans._ordinal(world.current_day, world.current_time_minutes)
        if operation not in ("allow_publication", "revoke_publication") and now < stage.entered_ordinal:
            _fail("Leave the preceding discussion before carrying out the next stage.", "stage_not_due")
        stage_id = stage.current_stage_id

        def persist(result=None):
            nonlocal stage, state
            stage.revision += 1
            stage.updated_at = plans._utc_now()
            if result is not None and result.get("status") == "scheduled":
                from models import WorldAtomicActionExecution
                audit = db.query(WorldAtomicActionExecution).filter_by(id=result["audit_id"]).one()
                metadata = json.loads(audit.metadata_json)
                metadata["stage_context"] = {"stage_id": stage_id, "revision": stage.revision,
                    "choice_id": choice["choice_id"], "actor_key": actor_key, "operation_key": key}
                audit.metadata_json = plans._json_dumps(metadata)
            elif result is not None:
                witnesses = [m.actor_key for m in _members(db, plan) if _present(db, world, plan, m)]
                contribution = {"actor_key": actor_key, "choice_id": choice["choice_id"], "atomic_audit_id": result["audit_id"], "source_action_id": result["action_id"], "effects": result["effects"], "day": world.current_day, "time_minutes": world.current_time_minutes}
                state["contributions"].append(contribution)
                _facts(db, world, runtime, stage, plan, state, "stage_action", contribution, witnesses)
                _advance(stage, choice, state, world)
            if stage.status in ("completed", "failed") and operation not in ("allow_publication", "revoke_publication"):
                _finish(db, world, runtime, stage, plan, state, stage.outcome or "stage_completed")
            _refresh_visibility(db, stage, state)
            stage.state_json = plans._json_dumps(state)
            world.updated_at = plans._utc_now()
            if failure_injector:
                failure_injector()
            db.flush()
            response = _serialize(db, world, runtime, stage, plan, actor_key)
            if result is not None and result.get("status") != "scheduled":
                effects = result.get("effects", [])
                feedback = next((e.get("value") for e in effects if e.get("state_key") == "result"), None)
                if feedback:
                    response["feedback"] = feedback
            elif choice is not None:
                chosen = choice["label"].get(payload.get("language", "en"), choice["label"].get("en", ""))
                response["feedback"] = ("你选择了：" + chosen + "。确认后，可以执行这一步。") if operation == "suggest" else ("已确认：" + chosen + "。点击执行，开始这一环节。") if operation == "confirm" else "当前选择已更新。"

            if result is not None and result.get("status") == "scheduled":
                response["scheduled_action"] = {"audit_id": result["audit_id"], "end_ordinal": result["scheduled_end_ordinal"]}
            db.add(WorldEventStageOperation(session_id=session_id, runtime_id=runtime_id, idempotency_key=key, request_hash=request_hash, actor_key=actor_key, operation=operation, stage_id=stage_id, world_day=world.current_day, world_time_minutes=world.current_time_minutes, result_json=plans._json_dumps(response)))
            if before_commit:
                before_commit(response)
            return response

        try:
            if operation == "suggest":
                if (card["kind"] != "decision" and not card.get("confirm_in_place")) or choice is None:
                    _fail("Choose a registered proposal.", "unknown_reference", 422)
                # Suggestions have no effect, reservation, or confirmation rights.
                state["proposal"] = {"choice_id": choice["choice_id"], "actor_key": actor_key, "revision": stage.revision + 1}
            elif operation == "confirm":
                if not authority:
                    _fail("This role cannot confirm.", "permission_denied", 403)
                if (card["kind"] != "decision" and not card.get("confirm_in_place")) or choice is None or not state["proposal"] or state["proposal"]["choice_id"] != choice["choice_id"]:
                    _fail("Confirm the current explicit proposal.", "proposal_changed")
                state["confirmation"] = {"choice_id": choice["choice_id"], "actor_key": actor_key}
                # Every chosen path must still be executable in the reserved place.
                if choice["next_stage_id"] and not card.get("confirm_in_place"):
                    target_card = next(c for c in definition["stages"] if c["stage_id"] == choice["next_stage_id"])
                    if target_card["kind"] == "action" and not any(c["choice_id"] == choice["choice_id"] for c in target_card["choices"]):
                        _fail("Proposal has no corresponding registered action.", "unknown_reference")
                stage.revision += 1
                _facts(db, world, runtime, stage, plan, state, "stage_confirmation", {"choice_id": choice["choice_id"], "confirmed_by": actor_key}, [m.actor_key for m in _members(db, plan) if _present(db, world, plan, m)])
                stage.revision -= 1
                if not card.get("confirm_in_place"):
                    _advance(stage, choice, state, world)
            elif operation == "reject":
                if not authority or (card["kind"] != "decision" and not card.get("confirm_in_place")):
                    _fail("This role cannot reject the proposal.", "permission_denied", 403)
                # Rejecting a suggestion reopens discussion; no fictitious action occurs.
                state["proposal"] = None
                state["confirmation"] = None
            elif operation == "execute":
                if not authority:
                    _fail("This role cannot execute the stage.", "permission_denied", 403)
                if card["kind"] != "action" or choice is None or not state["confirmation"] or choice["choice_id"] != state["confirmation"]["choice_id"]:
                    _fail("Action does not match the confirmed proposal.", "confirmation_required")
                _root, atomic_state = atomic._runtime_state(world)
                expected_state = card["enter_conditions"].get("object_state", {})
                actual_state = atomic_state["object_states"].get(choice["object_id"], {})
                if any(actual_state.get(k) != v for k, v in expected_state.items()):
                    _fail("Stage entry facts no longer hold.", "stage_precondition_failed")
                action_def = next(a for a in spec.systems["action_definitions"] if a["action_id"] == choice["action_id"])
                submitted_inputs = payload.get("inputs", {})
                if not isinstance(submitted_inputs, dict) or not set(submitted_inputs) <= set(choice.get("runtime_input_ids", ())):
                    _fail("Inputs are not declared by this stage choice.", "unknown_reference", 422)
                if now + int(action_def["duration_minutes"]) > stage.deadline_ordinal:
                    _fail("Action would exceed the stage time window.", "stage_timeout")
                # Apply stage changes in the executor's pre-commit callback.
                response_box = {}
                def finish_action(result):
                    response_box["response"] = persist(result)
                atomic.execute_atomic_action(
                    db, session_id=session_id, actor_type=actor_type, actor_agent_id=actor_agent_id,
                    stage_runtime_id=runtime_id, before_commit=finish_action,
                    stage_duration_minutes=(max(0, stage.deadline_ordinal - now) if card.get("confirm_in_place") and not focus else 0 if card.get("confirm_in_place") else None),
                    request={"action_id": choice["action_id"], "idempotency_key": "stage-action:" + hashlib.sha256(key.encode()).hexdigest(), "expected_revision": atomic_state["revision"], "target_location_id": plan.location_id, "target_object_id": choice["object_id"], "inputs": {**payload.get("inputs", {}), **dict(choice["inputs"])}, "language": payload.get("language", "en")},
                )
                return response_box["response"]
            elif operation == "finish":
                if not authority or card["kind"] != "closure" or choice is None:
                    _fail("This role cannot close this stage.", "permission_denied", 403)
                _advance(stage, choice, state, world)
            elif operation == "allow_publication":
                state["public_consents"] = sorted(set(state["public_consents"]) | {actor_key})
                state["revoked_by"] = [k for k in state["revoked_by"] if k != actor_key]
            elif operation == "revoke_publication":
                if actor_key in state["revoked_by"]:
                    _fail("Public permission has already been withdrawn.", "permission_already_withdrawn")
                state["public_consents"] = [k for k in state["public_consents"] if k != actor_key]
                state["revoked_by"] = sorted(set(state["revoked_by"]) | {actor_key})
            else:
                _fail("Unknown stage operation.", "invalid_request", 422)
            response = persist()
            db.commit()
            return response
        except Exception:
            db.rollback()
            raise


def validate_scheduled_stage(db, session_id, job, audit):
    world, spec, runtime, plan, definition = _binding(db, session_id, job["stage_runtime_id"])
    stage = _ensure(db, world, runtime, plan, definition)
    context = json.loads(audit.metadata_json)["stage_context"]
    member = _member(db, plan, context["actor_key"])
    state = _state(stage)
    if stage.status != "active" or plan.status != "in_progress" or not _present(db, world, plan, member) or (
        stage.revision != context["revision"] or stage.current_stage_id != context["stage_id"] or
        not state["confirmation"] or state["confirmation"]["choice_id"] != context["choice_id"]):
        _fail("The scheduled stage action is no longer lawful.", "stage_precondition_failed")
    return world, runtime, stage, plan, context


def complete_scheduled_stage(db, world, job, audit, result):
    _, runtime, stage, plan, context = validate_scheduled_stage(db, world.session_id, job, audit)
    state = _state(stage)
    choice = next(c for c in _card(stage)["choices"] if c["choice_id"] == context["choice_id"])
    contribution = {"actor_key": context["actor_key"], "choice_id": choice["choice_id"], "atomic_audit_id": audit.id,
        "source_action_id": result["action_id"], "effects": result["effects"], "day": world.current_day,
        "time_minutes": world.current_time_minutes}
    state["contributions"].append(contribution)
    witnesses = [m.actor_key for m in _members(db, plan) if _present(db, world, plan, m)]
    _facts(db, world, runtime, stage, plan, state, "stage_action", contribution, witnesses)
    _advance(stage, choice, state, world)
    stage.revision += 1
    if stage.status in ("completed", "failed"):
        _finish(db, world, runtime, stage, plan, state, stage.outcome or "stage_completed")
    _refresh_visibility(db, stage, state)
    stage.state_json = plans._json_dumps(state)
    operation = db.query(WorldEventStageOperation).filter_by(session_id=world.session_id,
                                                           idempotency_key=context["operation_key"]).one()
    operation.result_json = plans._json_dumps(_serialize(db, world, runtime, stage, plan, context["actor_key"]))


def view_stage_fact(db, *, session_id, fact_id, actor_type="participant", actor_agent_id=None):
    """Explicit actual viewing; revocation blocks future acquisition, not memory."""
    with session_write_lock(session_id):
        world, _spec = plans._world_and_spec(db, session_id)
        if world_has_ended(world):
            _fail("The world is frozen.", "world_ended")
        if _conversation_frozen(db, session_id):
            _fail("The world is frozen during this conversation.", "active_conversation")
        actor_key = plans._actor_key(actor_type, actor_agent_id)
        atomic._actor_snapshot(db, world=world, runtime=atomic._runtime_state(world)[1], actor_type=actor_type, actor_agent_id=actor_agent_id)
        fact = db.query(WorldKnowledgeFact).filter_by(id=fact_id, session_id=session_id, source_type="stage_execution").first()
        if fact is None:
            _fail("Fact not found.", "unknown_reference", 404)
        known = db.query(WorldActorKnowledge).filter_by(session_id=session_id, fact_id=fact.id, actor_key=actor_key).first()
        stage = db.query(WorldEventStage).filter_by(runtime_id=fact.source_id, session_id=session_id).one()
        if known is None and (fact.visibility != "island_public" or not stage.public_consent):
            _fail("Fact is not available to this actor.", "permission_denied", 403)
        acquired = _grant_knowledge(db, fact=fact, actor_key=actor_key, acquisition_source="viewed_public_fact", source_post_id=None, day=world.current_day, time_minutes=world.current_time_minutes)
        if acquired is None:
            _fail("The authored knowledge policy disables acquisition from public facts.", "knowledge_source_disabled", 403)
        db.commit()
        return {"fact_id": fact.id, "payload": json.loads(fact.payload_json)}


def list_visible_stage_facts(db, *, session_id, actor_type="participant", actor_agent_id=None):
    """Discovery is not acquisition: public metadata has no fact payload."""
    plans._world_and_spec(db, session_id)
    actor_key = plans._actor_key(actor_type, actor_agent_id)
    known = {k.fact_id for k in db.query(WorldActorKnowledge).filter_by(session_id=session_id, actor_key=actor_key)}
    rows = db.query(WorldKnowledgeFact, WorldEventStage).join(
        WorldEventStage, WorldEventStage.runtime_id == WorldKnowledgeFact.source_id,
    ).filter(WorldKnowledgeFact.session_id == session_id, WorldKnowledgeFact.source_type == "stage_execution").order_by(WorldKnowledgeFact.id.desc()).limit(200).all()
    return {"facts": [{"fact_id": f.id, "fact_type": f.fact_type, "runtime_id": s.runtime_id,
                       "world_day": f.world_day, "visibility": f.visibility, "already_known": f.id in known}
                      for f, s in rows if f.id in known or (s.public_consent and f.visibility == "island_public")]}
