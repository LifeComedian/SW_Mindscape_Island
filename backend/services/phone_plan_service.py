from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.orm import Session as DBSession

from models import (
    Session as UserSession,
    UserPost,
    WorldActorKnowledge,
    WorldBoardPost,
    WorldCommitment,
    WorldKnowledgeFact,
    WorldPlanMember,
    WorldPlanSocialProjection,
    WorldPlanTransition,
    WorldPlanVariantConsent,
    WorldPlanVariantProposal,
    WorldSocialPostView,
    WorldState,
)
from services.plan_service import (
    PLAN_WAIT_MINUTES,
    PlanServiceError,
    _actor_key,
    _add_notices,
    _add_reservations,
    _json_loads,
    _plan_snapshot,
    _recipe,
    _release_reservations,
    _world_and_spec,
    create_plan,
    join_open_plan,
    serialize_plan,
    transition_plan,
)
from services.simulation_service import USER_POST_ID_OFFSET
from services.world_service import session_write_lock
from world.registry import get_world_spec


PHONE_PLAN_RUNTIME_VERSION = "phone-plan-social-v1"


class PhonePlanError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.reason_code = reason_code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.utcnow()


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_hash(value: Mapping[str, Any]) -> str:
    try:
        encoded = _json_dumps(dict(value)).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhonePlanError(
            "Phone request must be JSON-compatible.",
            reason_code="invalid_request",
            status_code=422,
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _actor_ref_key(ref: Any) -> str:
    return _actor_key(str(_value(ref, "actor_type")), _value(ref, "agent_id"))


def _author_alias(
    db: DBSession, *, session_id: int, actor_type: str, actor_agent_id: int | None
) -> str:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if actor_type == "participant":
        if session is None:
            return "Participant"
        return session.user_alias or session.nickname
    world = db.query(WorldState).filter_by(session_id=session_id).first()
    if world:
        spec = get_world_spec(world.world_version)
        if spec.content_schema_version == "content-pack-v5" and actor_agent_id in spec.residents:
            return spec.residents[actor_agent_id].name
    return f"Resident {actor_agent_id}"


def _format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _new_user_post(
    db: DBSession,
    *,
    session_id: int,
    day: int,
    time_minutes: int,
    actor_type: str,
    actor_agent_id: int | None,
    content: str,
    language: str,
    post_type: str,
    visibility: str,
    commitment_id: int,
    location_id: str,
    facts: Mapping[str, Any],
    metadata: Mapping[str, Any],
    idempotency_key: str,
) -> UserPost:
    post = UserPost(
        feed_post_id=0,
        session_id=session_id,
        day=day,
        author_alias=_author_alias(
            db,
            session_id=session_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
        ),
        content=content,
        language=language,
        simulated_time=_format_time(time_minutes),
        world_time_minutes=time_minutes,
        author_type=actor_type,
        author_agent_id=actor_agent_id,
        post_type=post_type,
        visibility=visibility,
        source_type="world_plan",
        source_id=commitment_id,
        location_id=location_id,
        facts_json=_json_dumps(dict(facts)),
        metadata_json=_json_dumps(dict(metadata)),
        idempotency_key=idempotency_key,
    )
    db.add(post)
    db.flush()
    post.feed_post_id = USER_POST_ID_OFFSET + post.id
    db.flush()
    return post


def _grant_knowledge(
    db: DBSession,
    *,
    fact: WorldKnowledgeFact,
    actor_key: str,
    acquisition_source: str,
    source_post_id: int | None,
    day: int,
    time_minutes: int,
) -> WorldActorKnowledge | None:
    existing = db.query(WorldActorKnowledge).filter(
        WorldActorKnowledge.fact_id == fact.id,
        WorldActorKnowledge.actor_key == actor_key,
    ).first()
    if existing is not None:
        return existing
    world = db.query(WorldState).filter_by(session_id=fact.session_id).one()
    spec = get_world_spec(world.world_version)
    if spec.content_schema_version == "content-pack-v5":
        source = {"experienced": "experienced", "authored": "experienced",
                  "experienced_and_authored": "experienced", "viewed_public_fact": "system_public_fact"}.get(acquisition_source)
        if acquisition_source == "viewed_phone_post":
            post = db.query(UserPost).filter_by(id=source_post_id, session_id=fact.session_id).one()
            source = "public_post" if post.visibility == "island_public" else "direct_message"
        if source not in spec.systems.get("knowledge_policy", {}).get("allowed_source_types", ()):
            return None
    row = WorldActorKnowledge(
        session_id=fact.session_id,
        fact_id=fact.id,
        actor_key=actor_key,
        acquisition_source=acquisition_source,
        source_post_id=source_post_id,
        world_day=day,
        world_time_minutes=time_minutes,
    )
    db.add(row)
    db.flush()
    return row


def _projection_for_feed_post(
    db: DBSession, *, session_id: int, feed_post_id: int
) -> tuple[WorldPlanSocialProjection, UserPost, WorldCommitment]:
    post = db.query(UserPost).filter(
        UserPost.session_id == session_id,
        UserPost.feed_post_id == feed_post_id,
    ).first()
    if post is None:
        raise PhonePlanError("Phone post not found.", reason_code="unknown_post", status_code=404)
    projection = db.query(WorldPlanSocialProjection).filter(
        WorldPlanSocialProjection.session_id == session_id,
        WorldPlanSocialProjection.invitation_post_id == post.id,
    ).first()
    if projection is None:
        raise PhonePlanError("Post is not an invitation.", reason_code="not_an_invitation", status_code=422)
    plan = db.query(WorldCommitment).filter(
        WorldCommitment.session_id == session_id,
        WorldCommitment.id == projection.commitment_id,
    ).first()
    if plan is None:
        raise PhonePlanError("Invitation plan is unavailable.", reason_code="unknown_plan", status_code=404)
    return projection, post, plan


def _can_view_invitation(projection: WorldPlanSocialProjection, actor_key: str, plan: WorldCommitment) -> bool:
    if projection.audience_scope == "public":
        return True
    if actor_key == _actor_key(plan.organizer_type, plan.organizer_agent_id):
        return True
    return actor_key in set(_json_loads(projection.audience_actor_keys_json, []))


def _recipe_card(spec: Any, plan: WorldCommitment) -> dict[str, Any]:
    recipe = _recipe(spec, plan.recipe_id)
    return {
        "recipe_id": plan.recipe_id,
        "label": dict(recipe.get("label", {})),
        "action_ids": list(recipe.get("action_ids", ())),
        "object_ids": list(recipe.get("object_ids", ())),
        "variant_recipe_ids": list(recipe.get("variant_recipe_ids", ())),
    }


def _invitation_card(
    db: DBSession,
    *,
    projection: WorldPlanSocialProjection,
    post: UserPost,
    plan: WorldCommitment,
    spec: Any,
    viewer_actor_key: str,
) -> dict[str, Any]:
    members = db.query(WorldPlanMember).filter(
        WorldPlanMember.commitment_id == plan.id
    ).order_by(WorldPlanMember.id).all()
    accepted = sum(item.response_status == "accepted" for item in members)
    proposed = sum(item.response_status in ("proposed", "deferred") for item in members)
    attending = sum(item.attendance_status in ("present", "late", "left_early") for item in members)
    viewer_member = next((item for item in members if item.actor_key == viewer_actor_key), None)
    recipe = _recipe_card(spec, plan)
    world, _ = _world_and_spec(db, plan.session_id)
    now = (world.current_day-1)*1440 + world.current_time_minutes
    deadline = (int(plan.deadline_day or plan.scheduled_day)-1)*1440 + int(plan.deadline_time_minutes if plan.deadline_time_minutes is not None else plan.scheduled_time_minutes)
    open_event = bool(_recipe(spec,plan.recipe_id).get('conditions', {}).get('open_admission_until_end'))
    start = (plan.scheduled_day-1)*1440 + plan.scheduled_time_minutes
    response_deadline = start + plan.duration_minutes - 1 if open_event else deadline
    expiry = start + plan.duration_minutes + (30 if __import__('content.experience_next',fromlist=['enabled']).enabled() and not open_event else 0) if plan.status == 'in_progress' or open_event else (start + projection.wait_minutes if plan.status == 'accepted' else deadline)
    ended = plan.status not in ('proposed', 'accepted', 'in_progress') or now > expiry
    response_feedback=[]
    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and plan.organizer_type=='participant' and viewer_actor_key=='participant':
        for member in members:
            if member.actor_type!='resident':continue
            reason=member.response_reason_code or ''
            if member.response_status=='accepted':
                detail='曾答应邀请，但没有在等待期限内到场。' if ended and member.attendance_status=='absent' else '答应了邀请。'
            elif member.response_status in ('rejected','withdrawn'):
                detail={'schedule_conflict':'这个时间已有安排，无法参加。','time_conflict':'这个时间与已有安排冲突。','resource_conflict':'这个时间已有约定或场地安排，无法同时参加。','active_action_conflict':'正在完成手头的事情或赶路，暂时无法参加。','travel_from_previous_conflict':'从当前地点赶过去来不及。','travel_to_next_conflict':'之后还有已经答应的安排，往返时间不够。','prefer_own_time':'这次想留点时间给自己的事情，先不参加了。'}.get(reason,'这次没有接受邀请。可以换个时间或继续商量。')
                if reason.startswith('counter:') and len(reason.split(':'))==3 and all(part.isdigit() for part in reason.split(':')[1:]):
                    _,day,minute=reason.split(':');minute=int(minute)
                    detail=f'这个时间先不参加了，可以试试第{day}天 {minute//60:02d}:{minute%60:02d}。如果你也方便，请再约我。'
            elif ended:
                detail='截至邀约期限仍未回应，这次邀请已结束。尚无明确原因，可以私信问问。'
            else:continue
            response_feedback.append({'agent_id':member.actor_agent_id,'name':spec.residents[member.actor_agent_id].name,'status':member.response_status,'text':detail})
    return {
        "post_id": post.feed_post_id,
        "post_type": "invitation",
        "fact_chain_id": plan.id,
        "activity_id": plan.id,
        "plan_id": plan.id,
        "source": {"type": "world_plan", "id": plan.id},
        "author": {
            "actor_type": post.author_type,
            "agent_id": post.author_agent_id,
            "alias": post.author_alias,
        },
        "message": post.content,
        "language": post.language,
        "created_day": post.day,
        "created_time_minutes": post.world_time_minutes,
        "audience_scope": projection.audience_scope,
        "organizer_attending": projection.organizer_attending,
        "scheduled_day": plan.scheduled_day,
        "scheduled_time_minutes": plan.scheduled_time_minutes,
        "duration_minutes": plan.duration_minutes,
        "location_id": plan.location_id,
        "location_label": dict(spec.locations[plan.location_id].name),
        **recipe,
        "deadline_day": plan.deadline_day,
        "deadline_time_minutes": plan.deadline_time_minutes,
        "wait_minutes": projection.wait_minutes,
        "open_admission_until_end": bool(_recipe(spec,plan.recipe_id).get("conditions", {}).get("open_admission_until_end")),
        "min_participants": plan.min_participants,
        "max_participants": plan.max_participants,
        "accepted_count": accepted,
        "pending_count": proposed,
        "remaining_capacity": max(0, plan.max_participants - accepted),
        "actual_attendance_count": attending,
        "formation_count_is_attendance": False,
        "status": 'expired' if ended and plan.status in ('proposed', 'accepted', 'in_progress') else plan.status,
        "can_respond": not ended and now <= response_deadline and (plan.status in ('proposed', 'accepted') or open_event and plan.status == 'in_progress'),
        "revision": plan.revision,
        "reschedule_generation": plan.reschedule_generation,
        "ended_reason_code": plan.ended_reason_code,
        "viewer_response": viewer_member.response_status if viewer_member else None,
        "private_response_reasons_exposed": False,
        "response_feedback": response_feedback,
        "rsvp_source": "world_plan_member",
        "board_is_projection_only": projection.board_post_id is not None,
    }


def create_phone_invitation(
    db: DBSession,
    *,
    session_id: int,
    request: Any,
    organizer_type: str = "participant",
    organizer_agent_id: int | None = None,
) -> dict[str, Any]:
    audience_scope = str(_value(request, "audience_scope"))
    invitees = list(_value(request, "invitees", ()) or ())
    if not bool(_value(request, "organizer_attending", True)):
        raise PhonePlanError(
            "The plan organizer must be counted as attending.",
            reason_code="organizer_attendance_required",
            status_code=422,
        )
    if audience_scope == "direct" and len(invitees) != 1:
        raise PhonePlanError("A direct invitation requires exactly one target.", reason_code="invalid_audience", status_code=422)
    if audience_scope == "targeted" and len(invitees) < 1:
        raise PhonePlanError("A targeted invitation requires at least one target.", reason_code="invalid_audience", status_code=422)
    if audience_scope == "public" and invitees:
        raise PhonePlanError("A public invitation cannot contain hidden targets.", reason_code="invalid_audience", status_code=422)

    payload = {
        "recipe_id": _value(request, "recipe_id"),
        "audience_scope": audience_scope,
        "invitees": [
            {
                "actor_type": _value(item, "actor_type"),
                "agent_id": _value(item, "agent_id"),
                "role_id": _value(item, "role_id"),
                "required": bool(_value(item, "required", False)),
            }
            for item in invitees
        ],
        "location_id": _value(request, "location_id"),
        "start_day": _value(request, "start_day"),
        "start_time_minutes": _value(request, "start_time_minutes"),
        "deadline_day": _value(request, "deadline_day"),
        "deadline_time_minutes": _value(request, "deadline_time_minutes"),
        "organizer_attending": True,
        "public_headcount": bool(_value(request, "public_headcount", True)),
        "project_to_board": bool(_value(request, "project_to_board", True)),
        "message": str(_value(request, "message", "")),
        "language": str(_value(request, "language", "en")),
        "organizer_type": organizer_type,
        "organizer_agent_id": organizer_agent_id,
    }
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key"))
    existing = db.query(WorldPlanSocialProjection).filter(
        WorldPlanSocialProjection.session_id == session_id,
        WorldPlanSocialProjection.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise PhonePlanError("Invitation key was reused with another payload.", reason_code="idempotency_conflict")
        post = db.query(UserPost).filter(UserPost.id == existing.invitation_post_id).one()
        plan = db.query(WorldCommitment).filter(WorldCommitment.id == existing.commitment_id).one()
        _world, spec = _world_and_spec(db, session_id)
        return {
            "status": "existing",
            "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
            "invitation": _invitation_card(
                db,
                projection=existing,
                post=post,
                plan=plan,
                spec=spec,
                viewer_actor_key=_actor_key(organizer_type, organizer_agent_id),
            ),
        }

    plan_request = {
        "recipe_id": payload["recipe_id"],
        "idempotency_key": f"phone-plan:{idempotency_key}",
        "location_id": payload["location_id"],
        "start_day": payload["start_day"],
        "start_time_minutes": payload["start_time_minutes"],
        "invitees": payload["invitees"],
        "deadline_day": payload["deadline_day"],
        "deadline_time_minutes": payload["deadline_time_minutes"],
        "reason_code": "phone_invitation_created",
    }
    try:
        plan_result = create_plan(
            db,
            session_id=session_id,
            request=plan_request,
            organizer_type=organizer_type,
            organizer_agent_id=organizer_agent_id,
        )
    except PlanServiceError:
        raise
    commitment_id = int(plan_result["plan"]["commitment_id"])

    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldPlanSocialProjection).filter(
            WorldPlanSocialProjection.session_id == session_id,
            WorldPlanSocialProjection.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PhonePlanError("Invitation key was reused with another payload.", reason_code="idempotency_conflict")
            post = db.query(UserPost).filter(UserPost.id == existing.invitation_post_id).one()
            plan = db.query(WorldCommitment).filter(WorldCommitment.id == existing.commitment_id).one()
            _world, spec = _world_and_spec(db, session_id)
            return {
                "status": "existing",
                "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
                "invitation": _invitation_card(db, projection=existing, post=post, plan=plan, spec=spec, viewer_actor_key=_actor_key(organizer_type, organizer_agent_id)),
            }
        world, spec = _world_and_spec(db, session_id)
        plan = db.query(WorldCommitment).filter(
            WorldCommitment.id == commitment_id,
            WorldCommitment.session_id == session_id,
        ).one()
        recipe = _recipe_card(spec, plan)
        message = payload["message"].strip() or f"Invitation: {plan.recipe_id}"
        audience_keys = [_actor_ref_key(item) for item in invitees]
        visibility = "island_public" if audience_scope == "public" else "targeted"
        post = _new_user_post(
            db,
            session_id=session_id,
            day=world.current_day,
            time_minutes=world.current_time_minutes,
            actor_type=organizer_type,
            actor_agent_id=organizer_agent_id,
            content=message,
            language=payload["language"],
            post_type="invitation",
            visibility=visibility,
            commitment_id=plan.id,
            location_id=plan.location_id,
            facts={
                "fact_chain_id": plan.id,
                "plan_id": plan.id,
                "activity_id": plan.id,
                "recipe_id": plan.recipe_id,
                "action_ids": recipe["action_ids"],
                "scheduled_day": plan.scheduled_day,
                "scheduled_time_minutes": plan.scheduled_time_minutes,
                "duration_minutes": plan.duration_minutes,
                "location_id": plan.location_id,
                "audience_scope": audience_scope,
            },
            metadata={
                "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
                "initial_plan_revision": plan.revision,
                "rsvp_source": "world_plan_member",
                "allow_comments": True,
                "comments_are_rsvp": False,
            },
            idempotency_key=f"phone-invitation:{idempotency_key}",
        )
        board: WorldBoardPost | None = None
        if audience_scope == "public" and payload["project_to_board"]:
            board = WorldBoardPost(
                session_id=session_id,
                commitment_id=plan.id,
                author_type=organizer_type,
                author_agent_id=organizer_agent_id,
                content_json=_json_dumps({"en": message, "zh-CN": message}),
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
                metadata_json=_json_dumps({
                    "visibility": "island_public",
                    "location_id": plan.location_id,
                    "source_phone_post_id": post.feed_post_id,
                    "projection_only": True,
                    "rsvp_state": None,
                }),
            )
            db.add(board)
            db.flush()
        projection = WorldPlanSocialProjection(
            session_id=session_id,
            commitment_id=plan.id,
            invitation_post_id=post.id,
            board_post_id=board.id if board else None,
            audience_scope=audience_scope,
            audience_actor_keys_json=_json_dumps(audience_keys),
            organizer_attending=True,
            wait_minutes=PLAN_WAIT_MINUTES,
            public_headcount=payload["public_headcount"],
            initial_plan_revision=plan.revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        db.add(projection)
        db.flush()
        fact = WorldKnowledgeFact(
            session_id=session_id,
            fact_key=f"plan:{plan.id}:invitation",
            fact_type="invitation",
            subject_type="world_plan",
            subject_id=plan.id,
            visibility=visibility,
            source_type="phone_post",
            source_id=post.id,
            payload_json=_json_dumps({"plan_id": plan.id, "post_id": post.feed_post_id}),
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(fact)
        db.flush()
        _grant_knowledge(
            db,
            fact=fact,
            actor_key=_actor_key(organizer_type, organizer_agent_id),
            acquisition_source="authored",
            source_post_id=post.id,
            day=world.current_day,
            time_minutes=world.current_time_minutes,
        )
        from services.player_activity_service import attach_player_stage
        attach_player_stage(db, world=world, spec=spec, plan=plan)
        db.commit()
        return {
            "status": "created",
            "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
            "invitation": _invitation_card(db, projection=projection, post=post, plan=plan, spec=spec, viewer_actor_key=_actor_key(organizer_type, organizer_agent_id)),
        }


def list_phone_posts(
    db: DBSession,
    *,
    session_id: int,
    viewer_type: str = "participant",
    viewer_agent_id: int | None = None,
) -> dict[str, Any]:
    world, spec = _world_and_spec(db, session_id)
    actor_key = _actor_key(viewer_type, viewer_agent_id)
    posts: list[dict[str, Any]] = []
    projections = db.query(WorldPlanSocialProjection).filter(
        WorldPlanSocialProjection.session_id == session_id
    ).order_by(WorldPlanSocialProjection.id).all()
    for projection in projections:
        plan = db.query(WorldCommitment).filter(WorldCommitment.id == projection.commitment_id).first()
        post = db.query(UserPost).filter(UserPost.id == projection.invitation_post_id).first()
        if plan is None or post is None or not _can_view_invitation(projection, actor_key, plan):
            continue
        posts.append(_invitation_card(db, projection=projection, post=post, plan=plan, spec=spec, viewer_actor_key=actor_key))

    records = db.query(UserPost).filter(
        UserPost.session_id == session_id,
        UserPost.post_type.in_(("activity_record", "holiday_note")),
    ).order_by(UserPost.id).all()
    for post in records:
        if post.visibility != "island_public" and not db.query(WorldActorKnowledge.id).filter_by(
                session_id=session_id, actor_key=actor_key, source_post_id=post.id).first():
            continue
        facts = _json_loads(post.facts_json, {})
        posts.append({
            "post_id": post.feed_post_id,
            "post_type": "record",
            "fact_chain_id": post.source_id,
            "activity_id": post.source_id,
            "plan_id": post.source_id,
            "source": {"type": post.source_type, "id": post.source_id},
            "author": {"actor_type": post.author_type, "agent_id": post.author_agent_id, "alias": post.author_alias},
            "message": post.content,
            "language": post.language,
            "created_day": post.day,
            "created_time_minutes": post.world_time_minutes,
            "visibility": post.visibility,
            "facts": facts,
        })
    posts.sort(key=lambda item: (int(item.get("created_day") or 0), int(item.get("created_time_minutes") or 0), int(item["post_id"])))
    return {
        "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "viewer_actor_key": actor_key,
        "posts": posts,
    }


def respond_to_phone_invitation(
    db: DBSession,
    *,
    session_id: int,
    feed_post_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
) -> dict[str, Any]:
    projection, post, plan = _projection_for_feed_post(db, session_id=session_id, feed_post_id=feed_post_id)
    actor_key = _actor_key(actor_type, actor_agent_id)
    if not _can_view_invitation(projection, actor_key, plan):
        raise PhonePlanError("Invitation is not visible to this actor.", reason_code="invitation_not_visible", status_code=403)
    response = str(_value(request, "response"))
    member = db.query(WorldPlanMember).filter(
        WorldPlanMember.commitment_id == plan.id,
        WorldPlanMember.actor_key == actor_key,
    ).first()
    plan_request = {
        "transition": response,
        "idempotency_key": f"phone-response:{_value(request, 'idempotency_key')}",
        "expected_revision": int(_value(request, "expected_revision")),
        "reason_code": str(_value(request, "reason_code", "phone_response")),
    }
    if projection.audience_scope == "public" and response == "accept" and (
        member is None or member.response_status in ("rejected", "withdrawn")
    ):
        result = join_open_plan(
            db,
            session_id=session_id,
            commitment_id=plan.id,
            request=plan_request,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
        )
    else:
        if member is None:
            raise PhonePlanError("Actor is not an invitation target.", reason_code="not_an_invitee", status_code=403)
        result = transition_plan(
            db,
            session_id=session_id,
            commitment_id=plan.id,
            request=plan_request,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
        )
    db.rollback()
    world, spec = _world_and_spec(db, session_id)
    projection, post, plan = _projection_for_feed_post(db, session_id=session_id, feed_post_id=feed_post_id)
    return {
        "status": result["status"],
        "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "invitation": _invitation_card(db, projection=projection, post=post, plan=plan, spec=spec, viewer_actor_key=actor_key),
    }


def view_phone_post(
    db: DBSession,
    *,
    session_id: int,
    feed_post_id: int,
    request: Any,
    viewer_type: str = "participant",
    viewer_agent_id: int | None = None,
) -> dict[str, Any]:
    actor_key = _actor_key(viewer_type, viewer_agent_id)
    payload = {"post_id": feed_post_id, "viewer_actor_key": actor_key}
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key"))
    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldSocialPostView).filter(
            WorldSocialPostView.session_id == session_id,
            WorldSocialPostView.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PhonePlanError("View key was reused with another payload.", reason_code="idempotency_conflict")
            known = db.query(WorldActorKnowledge).filter_by(session_id=session_id, actor_key=actor_key, source_post_id=existing.user_post_id).first()
            return {"status": "existing", "view_id": existing.id, "knowledge_acquired": known is not None}
        world, _spec = _world_and_spec(db, session_id)
        post = db.query(UserPost).filter(
            UserPost.session_id == session_id,
            UserPost.feed_post_id == feed_post_id,
        ).first()
        if post is None:
            raise PhonePlanError("Phone post not found.", reason_code="unknown_post", status_code=404)
        if post.post_type == "invitation":
            projection, _post, plan = _projection_for_feed_post(db, session_id=session_id, feed_post_id=feed_post_id)
            if not _can_view_invitation(projection, actor_key, plan):
                raise PhonePlanError("Post is not visible to this actor.", reason_code="post_not_visible", status_code=403)
        elif post.visibility != "island_public" and not db.query(WorldActorKnowledge.id).filter_by(
                session_id=session_id, actor_key=actor_key, source_post_id=post.id).first():
            raise PhonePlanError("Post is not visible to this actor.", reason_code="post_not_visible", status_code=403)
        prior = db.query(WorldSocialPostView).filter(
            WorldSocialPostView.user_post_id == post.id,
            WorldSocialPostView.viewer_actor_key == actor_key,
        ).first()
        if prior is not None:
            known = db.query(WorldActorKnowledge).filter_by(session_id=session_id, actor_key=actor_key, source_post_id=post.id).first()
            return {"status": "existing", "view_id": prior.id, "knowledge_acquired": known is not None}
        view = WorldSocialPostView(
            session_id=session_id,
            user_post_id=post.id,
            viewer_actor_key=actor_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(view)
        db.flush()
        fact = db.query(WorldKnowledgeFact).filter(
            WorldKnowledgeFact.session_id == session_id,
            WorldKnowledgeFact.source_type == "phone_post",
            WorldKnowledgeFact.source_id == post.id,
        ).first()
        if fact is None and _spec.world_version.startswith('chaoxi-holiday-'):
            from services.holiday_social_identity import ensure_note_provenance
            fact=ensure_note_provenance(db,post)
        if fact is None:
            raise PhonePlanError("Post fact provenance is missing.", reason_code="missing_provenance")
        acquired = _grant_knowledge(
            db,
            fact=fact,
            actor_key=actor_key,
            acquisition_source="viewed_phone_post",
            source_post_id=post.id,
            day=world.current_day,
            time_minutes=world.current_time_minutes,
        )
        db.commit()
        return {
            "status": "viewed",
            "view_id": view.id,
            "knowledge_acquired": acquired is not None,
            "world_day": world.current_day,
            "world_time_minutes": world.current_time_minutes,
        }


def publish_activity_record(
    db: DBSession,
    *,
    session_id: int,
    commitment_id: int,
    request: Any,
    author_type: str = "participant",
    author_agent_id: int | None = None,
    managed_transaction: bool = False,
) -> dict[str, Any]:
    actor_key = _actor_key(author_type, author_agent_id)
    idempotency_key = str(_value(request, "idempotency_key"))
    payload_hash = _request_hash({
        "commitment_id": commitment_id,
        "actor_key": actor_key,
        "language": _value(request, "language", "en"),
    })
    with session_write_lock(session_id):
        if not managed_transaction:
            db.rollback()
        existing = db.query(UserPost).filter(
            UserPost.session_id == session_id,
            UserPost.idempotency_key == f"phone-record:{idempotency_key}",
        ).first()
        if existing is not None:
            metadata = _json_loads(existing.metadata_json, {})
            if metadata.get("request_hash") != payload_hash:
                raise PhonePlanError("Record key was reused with another payload.", reason_code="idempotency_conflict")
            return {"status": "existing", "post_id": existing.feed_post_id, "facts": _json_loads(existing.facts_json, {})}
        world, spec = _world_and_spec(db, session_id)
        plan = db.query(WorldCommitment).filter(
            WorldCommitment.session_id == session_id,
            WorldCommitment.id == commitment_id,
        ).first()
        if plan is None:
            raise PhonePlanError("Activity plan not found.", reason_code="unknown_plan", status_code=404)
        if plan.status != "completed":
            raise PhonePlanError("Only a completed activity can be recorded.", reason_code="activity_not_completed")
        from world.interaction_policy import interaction_policy
        if interaction_policy(spec) and _recipe(spec, plan.recipe_id).get("conditions", {}).get("stage_recipe_id"):
            from models import WorldEmergentEventRuntime, WorldEventStage
            stage = db.query(WorldEventStage).join(WorldEmergentEventRuntime, WorldEventStage.runtime_id == WorldEmergentEventRuntime.id).filter(
                WorldEmergentEventRuntime.commitment_id == plan.id, WorldEventStage.session_id == session_id).first()
            if not stage or not stage.public_consent:
                raise PhonePlanError("The stage witnesses have not agreed to publish this outcome.", reason_code="publication_consent_missing", status_code=403)
        member = db.query(WorldPlanMember).filter(
            WorldPlanMember.commitment_id == plan.id,
            WorldPlanMember.actor_key == actor_key,
        ).first()
        if member is None or member.attendance_status not in ("present", "late", "left_early"):
            raise PhonePlanError("Only an actual attendee can publish this record.", reason_code="author_not_attendee", status_code=403)
        attendees = db.query(WorldPlanMember).filter(
            WorldPlanMember.commitment_id == plan.id,
            WorldPlanMember.attendance_status.in_(("present", "late", "left_early")),
        ).all()
        facts = {
            "fact_chain_id": plan.id,
            "plan_id": plan.id,
            "activity_id": plan.id,
            "recipe_id": plan.recipe_id,
            "location_id": plan.location_id,
            "scheduled_day": plan.scheduled_day,
            "scheduled_time_minutes": plan.scheduled_time_minutes,
            "actual_attendance_count": len(attendees),
            "author_attendance": member.attendance_status,
            "outcome": "completed",
        }
        language = str(_value(request, "language", "en"))
        location_name, activity_name = plan.location_id, plan.recipe_id
        if interaction_policy(spec):
            from data.island import localized
            location_name = localized(spec.locations[plan.location_id].name, language)
            activity_name = localized(_recipe(spec, plan.recipe_id)["label"], language)
        if language == "zh-CN":
            content = f"我们在{location_name}完成了{activity_name}，实际到场{len(attendees)}人。"
        else:
            content = f"We completed {activity_name} at {location_name} with {len(attendees)} attendees."
        post = _new_user_post(
            db,
            session_id=session_id,
            day=world.current_day,
            time_minutes=world.current_time_minutes,
            actor_type=author_type,
            actor_agent_id=author_agent_id,
            content=content,
            language=language,
            post_type="activity_record",
            visibility="island_public",
            commitment_id=plan.id,
            location_id=plan.location_id,
            facts=facts,
            metadata={
                "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
                "request_hash": payload_hash,
                "content_mode": "server_grounded_template",
                "allow_comments": True,
            },
            idempotency_key=f"phone-record:{idempotency_key}",
        )
        fact = WorldKnowledgeFact(
            session_id=session_id,
            fact_key=f"plan:{plan.id}:record:{post.id}",
            fact_type="activity_record",
            subject_type="world_plan",
            subject_id=plan.id,
            visibility="island_public",
            source_type="phone_post",
            source_id=post.id,
            payload_json=_json_dumps(facts),
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(fact)
        db.flush()
        _grant_knowledge(
            db,
            fact=fact,
            actor_key=actor_key,
            acquisition_source="experienced_and_authored",
            source_post_id=post.id,
            day=world.current_day,
            time_minutes=world.current_time_minutes,
        )
        if not managed_transaction:
            db.commit()
        return {
            "status": "published",
            "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
            "post_id": post.feed_post_id,
            "world_day": world.current_day,
            "world_time_minutes": world.current_time_minutes,
            "facts": facts,
        }


def _serialize_variant_proposal(
    db: DBSession, proposal: WorldPlanVariantProposal
) -> dict[str, Any]:
    consents = db.query(WorldPlanVariantConsent).filter(
        WorldPlanVariantConsent.proposal_id == proposal.id
    ).order_by(WorldPlanVariantConsent.id).all()
    return {
        "proposal_id": proposal.id,
        "plan_id": proposal.commitment_id,
        "source_recipe_id": proposal.source_recipe_id,
        "target_recipe_id": proposal.target_recipe_id,
        "proposer_actor_key": proposal.proposer_actor_key,
        "required_actor_keys": _json_loads(proposal.attendee_actor_keys_json, []),
        "status": proposal.status,
        "reason_code": proposal.reason_code,
        "requested_revision": proposal.requested_revision,
        "applied_revision": proposal.applied_revision,
        "world_day": proposal.world_day,
        "world_time_minutes": proposal.world_time_minutes,
        "consents": [
            {
                "actor_key": item.actor_key,
                "decision": item.decision,
                "reason_code": item.reason_code,
            }
            for item in consents
        ],
    }


def _apply_registered_variant(
    db: DBSession,
    *,
    world: Any,
    spec: Any,
    plan: WorldCommitment,
    proposal: WorldPlanVariantProposal,
) -> None:
    target = _recipe(spec, proposal.target_recipe_id)
    source_stage = _recipe(spec, plan.recipe_id).get("conditions", {}).get("stage_recipe_id")
    target_stage = target.get("conditions", {}).get("stage_recipe_id")
    if source_stage != target_stage and (source_stage or target_stage):
        raise PhonePlanError("A variant cannot replace the bound stage contract.", reason_code="stage_variant_mismatch")
    attendee_keys = set(_json_loads(proposal.attendee_actor_keys_json, []))
    members = db.query(WorldPlanMember).filter(
        WorldPlanMember.commitment_id == plan.id
    ).all()
    attendee_members = [item for item in members if item.actor_key in attendee_keys]
    before = _plan_snapshot(plan)
    _release_reservations(db, plan=plan, reason_code="registered_variant_applied")
    plan.recipe_id = proposal.target_recipe_id
    plan.duration_minutes = int(target.get("duration_minutes", plan.duration_minutes))
    plan.min_participants = int(target.get("min_participants", 1))
    plan.max_participants = int(target.get("max_participants", len(attendee_members)))
    plan.object_ids_json = _json_dumps(list(target.get("object_ids", ())))
    plan.role_slots_json = _json_dumps(list(target.get("role_slots", ())))
    plan.required_actor_keys_json = _json_dumps(sorted(attendee_keys))
    plan.reschedule_generation += 1
    plan.status = "accepted"
    plan.ended_reason_code = None
    plan.revision += 1
    plan.updated_at = _utc_now()
    for member in members:
        if member.actor_key not in attendee_keys and member.attendance_status == "pending":
            member.attendance_status = "absent"
            member.response_reason_code = "not_present_for_registered_variant"
            member.updated_at = _utc_now()
    _add_reservations(db, plan=plan, members=attendee_members, shared_status="confirmed")
    transition = WorldPlanTransition(
        session_id=plan.session_id,
        commitment_id=plan.id,
        idempotency_key=f"variant-apply:{proposal.id}",
        request_hash=_request_hash({"proposal_id": proposal.id, "target_recipe_id": proposal.target_recipe_id}),
        actor_type=plan.organizer_type,
        actor_agent_id=plan.organizer_agent_id,
        transition_type="switch_variant",
        requested_revision=proposal.requested_revision,
        accepted_revision=plan.revision,
        status="completed",
        reason_code="registered_variant_unanimously_accepted",
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
        notice_type="plan_variant_applied",
        reason_code=transition.reason_code,
        payload={"proposal_id": proposal.id, "target_recipe_id": proposal.target_recipe_id},
    )
    proposal.status = "applied"
    proposal.applied_revision = plan.revision
    transition.result_json = _json_dumps({
        "status": "completed",
        "reason_code": transition.reason_code,
        "plan": serialize_plan(db, plan),
    })


def propose_phone_plan_variant(
    db: DBSession,
    *,
    session_id: int,
    commitment_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
) -> dict[str, Any]:
    actor_key = _actor_key(actor_type, actor_agent_id)
    payload = {
        "plan_id": commitment_id,
        "target_recipe_id": _value(request, "target_recipe_id"),
        "expected_revision": _value(request, "expected_revision"),
        "actor_key": actor_key,
        "reason_code": _value(request, "reason_code"),
    }
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key"))
    with session_write_lock(session_id):
        db.rollback()
        existing = db.query(WorldPlanVariantProposal).filter(
            WorldPlanVariantProposal.session_id == session_id,
            WorldPlanVariantProposal.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PhonePlanError("Variant key was reused with another payload.", reason_code="idempotency_conflict")
            return {"status": "existing", "runtime_version": PHONE_PLAN_RUNTIME_VERSION, "proposal": _serialize_variant_proposal(db, existing)}
        world, spec = _world_and_spec(db, session_id)
        plan = db.query(WorldCommitment).filter(
            WorldCommitment.session_id == session_id,
            WorldCommitment.id == commitment_id,
        ).first()
        if plan is None:
            raise PhonePlanError("Activity plan not found.", reason_code="unknown_plan", status_code=404)
        if actor_key != _actor_key(plan.organizer_type, plan.organizer_agent_id):
            raise PhonePlanError("Only the organizer can propose a variant.", reason_code="organizer_required", status_code=403)
        if int(_value(request, "expected_revision")) != plan.revision:
            raise PhonePlanError("Plan revision is stale.", reason_code="stale_revision")
        if plan.status not in ("proposed", "accepted"):
            raise PhonePlanError("This plan cannot switch variants now.", reason_code="invalid_transition")
        now = world.current_day * 1440 + world.current_time_minutes
        start = plan.scheduled_day * 1440 + plan.scheduled_time_minutes
        if now < start:
            raise PhonePlanError("A fallback is only available when the activity is due.", reason_code="not_due")
        source = _recipe(spec, plan.recipe_id)
        target_recipe_id = str(_value(request, "target_recipe_id"))
        if target_recipe_id not in set(source.get("variant_recipe_ids", ())):
            raise PhonePlanError("Variant is not registered by the source recipe.", reason_code="unregistered_variant", status_code=422)
        target = _recipe(spec, target_recipe_id)
        if plan.location_id not in set(target.get("location_ids", ())):
            raise PhonePlanError("Variant is not available at this location.", reason_code="recipe_location_mismatch", status_code=422)
        attendees = db.query(WorldPlanMember).filter(
            WorldPlanMember.commitment_id == plan.id,
            WorldPlanMember.attendance_status.in_(("present", "late")),
        ).order_by(WorldPlanMember.id).all()
        if len(attendees) >= plan.min_participants:
            raise PhonePlanError("The original activity already has enough attendees.", reason_code="variant_not_needed")
        target_min = int(target.get("min_participants", 1))
        target_max = int(target.get("max_participants", 20))
        if not target_min <= len(attendees) <= target_max:
            raise PhonePlanError("Present attendees do not fit the variant.", reason_code="variant_participant_bounds")
        attendee_keys = [item.actor_key for item in attendees]
        if actor_key not in attendee_keys:
            raise PhonePlanError("The organizer must be present to propose the variant.", reason_code="organizer_not_present")
        proposal = WorldPlanVariantProposal(
            session_id=session_id,
            commitment_id=plan.id,
            source_recipe_id=plan.recipe_id,
            target_recipe_id=target_recipe_id,
            proposer_actor_key=actor_key,
            attendee_actor_keys_json=_json_dumps(attendee_keys),
            status="proposed",
            reason_code=str(_value(request, "reason_code")),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            requested_revision=plan.revision,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(proposal)
        db.flush()
        consent = WorldPlanVariantConsent(
            session_id=session_id,
            proposal_id=proposal.id,
            actor_key=actor_key,
            decision="accept",
            reason_code="proposer_consent",
            idempotency_key=f"variant-proposer:{idempotency_key}",
            request_hash=_request_hash({"proposal_id": proposal.id, "actor_key": actor_key, "decision": "accept"}),
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(consent)
        db.flush()
        if len(attendee_keys) == 1:
            _apply_registered_variant(db, world=world, spec=spec, plan=plan, proposal=proposal)
        db.commit()
        return {"status": "created", "runtime_version": PHONE_PLAN_RUNTIME_VERSION, "proposal": _serialize_variant_proposal(db, proposal)}


def consent_phone_plan_variant(
    db: DBSession,
    *,
    session_id: int,
    proposal_id: int,
    request: Any,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
) -> dict[str, Any]:
    actor_key = _actor_key(actor_type, actor_agent_id)
    decision = str(_value(request, "decision"))
    payload = {"proposal_id": proposal_id, "actor_key": actor_key, "decision": decision, "reason_code": _value(request, "reason_code")}
    request_hash = _request_hash(payload)
    idempotency_key = str(_value(request, "idempotency_key"))
    with session_write_lock(session_id):
        db.rollback()
        replay = db.query(WorldPlanVariantConsent).filter(
            WorldPlanVariantConsent.session_id == session_id,
            WorldPlanVariantConsent.idempotency_key == idempotency_key,
        ).first()
        if replay is not None:
            if replay.request_hash != request_hash:
                raise PhonePlanError("Consent key was reused with another payload.", reason_code="idempotency_conflict")
            proposal = db.query(WorldPlanVariantProposal).filter(WorldPlanVariantProposal.id == replay.proposal_id).one()
            return {"status": "existing", "runtime_version": PHONE_PLAN_RUNTIME_VERSION, "proposal": _serialize_variant_proposal(db, proposal)}
        world, spec = _world_and_spec(db, session_id)
        proposal = db.query(WorldPlanVariantProposal).filter(
            WorldPlanVariantProposal.session_id == session_id,
            WorldPlanVariantProposal.id == proposal_id,
        ).first()
        if proposal is None:
            raise PhonePlanError("Variant proposal not found.", reason_code="unknown_variant_proposal", status_code=404)
        if proposal.status != "proposed":
            raise PhonePlanError("Variant proposal is already closed.", reason_code="invalid_transition")
        attendee_keys = set(_json_loads(proposal.attendee_actor_keys_json, []))
        if actor_key not in attendee_keys:
            raise PhonePlanError("Only a present attendee can consent.", reason_code="not_a_variant_participant", status_code=403)
        prior = db.query(WorldPlanVariantConsent).filter(
            WorldPlanVariantConsent.proposal_id == proposal.id,
            WorldPlanVariantConsent.actor_key == actor_key,
        ).first()
        if prior is not None:
            raise PhonePlanError("This attendee already responded.", reason_code="already_responded")
        consent = WorldPlanVariantConsent(
            session_id=session_id,
            proposal_id=proposal.id,
            actor_key=actor_key,
            decision=decision,
            reason_code=str(_value(request, "reason_code")),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
        )
        db.add(consent)
        db.flush()
        if decision == "reject":
            proposal.status = "rejected"
        else:
            decisions = {
                item.actor_key: item.decision
                for item in db.query(WorldPlanVariantConsent).filter(
                    WorldPlanVariantConsent.proposal_id == proposal.id
                ).all()
            }
            if attendee_keys <= {key for key, value in decisions.items() if value == "accept"}:
                plan = db.query(WorldCommitment).filter(WorldCommitment.id == proposal.commitment_id).one()
                if plan.revision != proposal.requested_revision:
                    proposal.status = "stale"
                    raise PhonePlanError("Plan changed while consent was pending.", reason_code="stale_revision")
                _apply_registered_variant(db, world=world, spec=spec, plan=plan, proposal=proposal)
        db.commit()
        return {"status": "recorded", "runtime_version": PHONE_PLAN_RUNTIME_VERSION, "proposal": _serialize_variant_proposal(db, proposal)}


def list_actor_knowledge(
    db: DBSession,
    *,
    session_id: int,
    actor_type: str = "participant",
    actor_agent_id: int | None = None,
) -> dict[str, Any]:
    actor_key = _actor_key(actor_type, actor_agent_id)
    world, _spec = _world_and_spec(db, session_id)
    rows = db.query(WorldActorKnowledge).filter(
        WorldActorKnowledge.session_id == session_id,
        WorldActorKnowledge.actor_key == actor_key,
    ).order_by(WorldActorKnowledge.id).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        fact = db.query(WorldKnowledgeFact).filter(WorldKnowledgeFact.id == row.fact_id).one()
        items.append({
            "knowledge_id": row.id,
            "fact_id": fact.id,
            "fact_key": fact.fact_key,
            "fact_type": fact.fact_type,
            "subject": {"type": fact.subject_type, "id": fact.subject_id},
            "visibility": fact.visibility,
            "acquisition_source": row.acquisition_source,
            "source_post_id": row.source_post_id,
            "acquired_day": row.world_day,
            "acquired_time_minutes": row.world_time_minutes,
            "payload": _json_loads(fact.payload_json, {}),
        })
    return {
        "runtime_version": PHONE_PLAN_RUNTIME_VERSION,
        "world_day": world.current_day,
        "world_time_minutes": world.current_time_minutes,
        "actor_key": actor_key,
        "knowledge": items,
    }
