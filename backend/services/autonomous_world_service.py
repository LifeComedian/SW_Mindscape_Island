"""Background resident decisions and confirmed-plan duties. Requires one API worker."""
import asyncio
import json
import weakref
import logging
logger=logging.getLogger(__name__)
from models import Session as UserSession, WorldState, WorldCommitment, WorldPlanMember, WorldSocialPostView, WorldDecisionInvocation
from services import plan_service as plans, scheduled_action_service as scheduled
from world.autonomy_policy import autonomy_policy
from world.clock import ClockPosition
from world.graph import shortest_travel_path

_loops = weakref.WeakKeyDictionary()


def _tasks():
    loop = asyncio.get_running_loop()
    return _loops.setdefault(loop, {})


def _focus_blocked(db, world, *, allow_stage=False):
    from services.interaction_time_service import focus_state
    from services.stage_service import _conversation_frozen
    focus = focus_state(world)
    return bool((focus and (not allow_stage or focus.get('full_activity'))) or _conversation_frozen(db, world.session_id))


def plan_due_points(db, world, spec, before, after):
    points = set()
    low, high = plans._ordinal(before.day, before.minute), plans._ordinal(after.day, after.minute)
    rows = db.query(WorldCommitment, WorldPlanMember).join(WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id).filter(
        WorldCommitment.session_id == world.session_id, WorldCommitment.status.in_(("accepted", "in_progress")),
        WorldPlanMember.actor_type == "resident", WorldPlanMember.response_status == "accepted").all()
    from models import CharacterState
    for plan, member in rows:
        row = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=member.actor_agent_id).one()
        path = shortest_travel_path(spec, row.current_location_id, plan.location_id)
        travel = (len(path) - 1) * int(spec.action_minutes["move"]) if path else 0
        start = plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
        for ordinal in (start - travel, start, start + plans.PLAN_WAIT_MINUTES + 1, start + plan.duration_minutes + (30 if plans.next_enabled() else 0)):
            if low < ordinal <= high:
                points.add(ClockPosition(*plans._position(ordinal)))
    return points


def maintain_confirmed_plans(db, *, world, spec):
    if _focus_blocked(db, world):
        return
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    rows = db.query(WorldCommitment, WorldPlanMember).join(WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id).filter(
        WorldCommitment.session_id == world.session_id, WorldCommitment.status.in_(("accepted", "in_progress")),
        WorldPlanMember.actor_type == "resident", WorldPlanMember.response_status == "accepted").order_by(WorldCommitment.id, WorldPlanMember.id).all()
    for plan, member in rows:
        start = plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
        scheduled.schedule_travel(db, world=world, spec=spec, agent_id=member.actor_agent_id, plan=plan)
        operation = None
        if now >= start and member.attendance_status == "pending" and not scheduled.actor_busy(world, member.actor_key) and plans._current_presence(db, world=world, plan=plan, member=member):
            operation = "arrive"
        if operation:
            plans.transition_plan(db, session_id=world.session_id, commitment_id=plan.id,
                actor_type="resident", actor_agent_id=member.actor_agent_id, managed_transaction=True,
                request={"transition": operation, "expected_revision": plan.revision,
                    "idempotency_key": f"autonomy:{plan.id}:{member.id}:arrive:{plan.reschedule_generation}", "reason_code": "actual_resident_arrival"})
    for plan in {p.id: p for p, _ in rows}.values():
        if plan.organizer_type != "resident":
            continue
        start = plans._ordinal(plan.scheduled_day, plan.scheduled_time_minutes)
        operation = "start" if plan.status == "accepted" and now >= start else None
        if plan.status == "in_progress" and now >= start + plan.duration_minutes + (30 if plans.next_enabled() and plan.recipe_id not in ("welcome","bonfire") else 0):
            recipe = plans._recipe(spec, plan.recipe_id)
            if not recipe.get("conditions", {}).get("stage_recipe_id"):
                operation = "complete"
        if operation:
            plans.transition_plan(db, session_id=world.session_id, commitment_id=plan.id,
                actor_type="resident", actor_agent_id=plan.organizer_agent_id, managed_transaction=True,
                request={"transition": operation, "expected_revision": plan.revision,
                    "idempotency_key": f"autonomy:{plan.id}:{operation}:{plan.revision}", "reason_code": "confirmed_plan_duty"})


def observe_posts(db, session_id, agent_id, limit):
    from services.phone_plan_service import list_phone_posts, view_phone_post
    posts = list_phone_posts(db, session_id=session_id, viewer_type="resident", viewer_agent_id=agent_id)["posts"]
    read = 0
    # Fresh direct questions must not wait behind an old timeline backlog.
    ordered=list(reversed(posts))
    ordered.sort(key=lambda p:not (p.get('post_type')=='invitation' and p.get('viewer_response') in ('proposed','deferred')))
    for post in ordered:
        if read >= limit:
            break
        from models import UserPost
        if db.query(WorldSocialPostView.id).join(UserPost, WorldSocialPostView.user_post_id == UserPost.id).filter(
            WorldSocialPostView.session_id == session_id, WorldSocialPostView.viewer_actor_key == f"resident:{agent_id}",
            UserPost.feed_post_id == post["post_id"]).first():
            continue
        # View is an explicit bounded actor operation with its own provenance.
        from services.phone_plan_service import PhonePlanError
        try:
            view_phone_post(db, session_id=session_id, viewer_type="resident", viewer_agent_id=agent_id,
                feed_post_id=post["post_id"], request={"idempotency_key": f"autonomy-read:{agent_id}:{post['post_id']}"})
        except PhonePlanError as exc:
            db.rollback()
            if exc.reason_code not in ('missing_provenance','post_not_visible'):raise
            logger.info('Skipped unreadable phone post: session=%s post=%s reason=%s',session_id,post['post_id'],exc.reason_code)
        read += 1


async def _step(factory, session_id, agent_id, key, provider, language, invitations_only=False):
    from services import decision_gateway_service as gateway
    try:
        with factory() as db:
            world, spec = plans._world_and_spec(db, session_id)
            policy = autonomy_policy(spec)
            if not policy or _focus_blocked(db, world, allow_stage=True):
                return
            from services.interaction_time_service import focus_state
            if not focus_state(world):
                observe_posts(db, session_id, agent_id, policy.read_posts_per_step)
            # Resolve existing commitments before requesting a new decision.
            kinds = ("stage_action",) if focus_state(world) else (("invitation_response", "record_expression", "event_preference", "atomic_action") if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') else ("stage_action", "invitation_response", "record_expression", "atomic_action", "event_preference"))
            if invitations_only:kinds=("invitation_response",)
            for kind in kinds:
                if kind == 'record_expression' and spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
                    from services.holiday_social_identity import naturalize_note
                    if await naturalize_note(db, world, spec, agent_id):
                        return
                try:
                    packet = gateway._context(db, session_id=session_id, agent_id=agent_id, decision_type=kind, language=language)[0]
                except gateway.DecisionGatewayError:
                    return
                if any(c["kind"] == "record_publication" if kind == "record_expression" else c["kind"] not in ("idle", "continue_plan") for c in packet["candidates"]):
                    db.rollback()
                    await gateway.decide_resident(db, session_id=session_id, agent_id=agent_id,
                        decision_type=kind, idempotency_key=key, provider=provider, language=language)
                    return
    except asyncio.CancelledError:
        raise
    except (plans.PlanServiceError, gateway.DecisionGatewayError) as exc:
        logger.info("Resident decision postponed: session=%s actor=%s reason=%s",session_id,agent_id,exc.reason_code)
        return


def dispatch_autonomy(db, *, session_id, language="en", provider=None, factory=None, invitations_only=False):
    from database import SessionLocal
    from services.decision_gateway_service import server_decision_provider
    from services.world_service import session_write_lock, world_has_ended
    tasks = _tasks()
    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter_by(id=session_id).one()
        world = db.query(WorldState).filter_by(session_id=session_id).first()
        if world is None:
            return {"dispatched": 0, "pending": 0}
        from world.registry import get_world_spec
        spec = get_world_spec(world.world_version)
        policy = autonomy_policy(spec)
        own = {k: t for k, t in tasks.items() if k[0] == session_id and not t.done()}
        if session.status != "active" or world_has_ended(world):
            for task in own.values():
                task.cancel()
            if policy and scheduled.jobs(world):
                scheduled.reconcile_jobs(db, world=world, spec=spec, cancel=True)
                db.commit()
            return {"dispatched": 0, "pending": 0}
        if not policy or _focus_blocked(db, world, allow_stage=True):
            return {"dispatched": 0, "pending": len(own)}
        durable_actors = {r.actor_key for r in db.query(WorldDecisionInvocation).filter_by(session_id=session_id, status="pending").filter(
            WorldDecisionInvocation.lease_expires_at > plans._utc_now()).all()}
        occupied = len(durable_actors | {f"resident:{k[1]}" for k in own})
        state = json.loads(world.state_json)
        tracking = state.setdefault("autonomy_queue_v1", {"cursor": 0, "last": {}, "dispatch_count": 0})
        ids = sorted(spec.residents)
        from services.interaction_time_service import focus_state
        focus = focus_state(world)
        focus_revision = None
        if focus:
            from services import stage_service as stages
            _, _, event, plan, definition = stages._binding(db, session_id, focus["runtime_id"])
            stage = stages._ensure(db, world, event, plan, definition)
            focus_revision = f"{focus['runtime_id']}:{stage.revision}"
            ids = [m.actor_agent_id for m in stages._members(db, plan) if m.actor_type == "resident" and stages._present(db, world, plan, m)]
        order = ids[tracking["cursor"] % len(ids):] + ids[:tracking["cursor"] % len(ids)] if ids else []
        urgent_rows = list(db.query(WorldCommitment,WorldPlanMember).join(WorldPlanMember,WorldPlanMember.commitment_id==WorldCommitment.id).filter(
            WorldCommitment.session_id==session_id,WorldCommitment.organizer_type=='participant',WorldCommitment.status.in_(('proposed','accepted')),
            WorldPlanMember.actor_type=='resident',WorldPlanMember.response_status.in_(('proposed','deferred')))) if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') else []
        urgent={m.actor_agent_id for p,m in urgent_rows}
        signatures={aid:','.join(sorted(f'{p.id}:{p.reschedule_generation}' for p,m in urgent_rows if m.actor_agent_id==aid)) for aid in urgent}
        order.sort(key=lambda aid: aid not in urgent)
        if invitations_only:order=[aid for aid in order if aid in urgent]
        now = plans._ordinal(world.current_day, world.current_time_minutes)
        selected = []
        for aid in order:
            key = (session_id, aid)
            pending = db.query(WorldDecisionInvocation).filter_by(session_id=session_id, actor_key=f"resident:{aid}", status="pending").filter(
                WorldDecisionInvocation.lease_expires_at > plans._utc_now()).first()
            if occupied + len(selected) >= policy.max_pending or len(selected) >= policy.dispatch_per_pulse:
                break
            recent = tracking.get("last_stage", {}).get(str(aid)) == focus_revision if focus else now - tracking["last"].get(str(aid), -10000) < policy.cooldown_minutes
            if key in own or pending or (scheduled.actor_busy(world, f"resident:{aid}") and not (spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and aid in urgent)) or (recent and aid not in urgent):
                continue
            # Limit no-clock dispatches to two per resident and clock point.
            attempts=tracking.setdefault('invitation_attempts',{})
            previous=attempts.get(str(aid),{})
            count=previous.get('count',0) if previous.get('ordinal')==now and previous.get('signature')==signatures.get(aid) else 0
            if invitations_only and count>=2:continue
            if aid in urgent:attempts[str(aid)]={'ordinal':now,'count':count+1,'signature':signatures.get(aid)}
            selected.append(aid)
            tracking["last"][str(aid)] = now
            if focus:
                tracking.setdefault("last_stage", {})[str(aid)] = focus_revision
            tracking["dispatch_count"] += 1
            tracking["cursor"] = (ids.index(aid) + 1) % len(ids)
        world.state_json = json.dumps(state, ensure_ascii=False)
        if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and not focus:
            from services.holiday_social_identity import publish_daily_note
            publish_daily_note(db,world,spec)
        db.commit()
        for aid in selected:
            key = (session_id, aid)
            task = asyncio.create_task(_step(factory or SessionLocal, session_id, aid,
                f"autonomy:{aid}:{now}:{tracking['dispatch_count']}", provider or server_decision_provider(), language,invitations_only=invitations_only))
            tasks[key] = task
            def finish(done, task_key=key):
                if tasks.get(task_key) is done:
                    tasks.pop(task_key, None)
                if not done.cancelled():
                    failure=done.exception()
                    if failure:logger.error("Resident background step failed: session=%s actor=%s",*task_key,exc_info=(type(failure),failure,failure.__traceback__))
                    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
                        # Process only unanswered invitations while the phone pauses the clock.
                        with (factory or SessionLocal)() as follow_db:
                            dispatch_autonomy(follow_db,session_id=session_id,language=language,provider=provider,
                                              factory=factory,invitations_only=True)
            task.add_done_callback(finish)
        return {"dispatched": len(selected), "pending": occupied + len(selected)}


async def drain_autonomy(session_id):
    """Testing/shutdown helper; a pulse never calls this."""
    for _ in range(16):
        tasks = [t for k,t in _tasks().items() if k[0]==session_id and not t.done()]
        if not tasks:return
        await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.sleep(0)
