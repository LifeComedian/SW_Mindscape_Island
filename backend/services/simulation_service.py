import json
import random
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session as DBSession

from agents.base import AgentResult
from agents.personas import get_persona
from data.timeline import (
    COMMUNITY_ACTIVITY_BLUEPRINTS,
    EVENT_TRANSITIONS,
    get_timeline_post,
    posts,
    public_post,
)
from models import (
    AgentMemory,
    CommunityActivity,
    Interaction,
    Notification,
    Session as UserSession,
    SimulationEvent,
    UserPost,
    WorldBoardPost,
    WorldPlanSocialProjection,
)


TOTAL_DAYS = 7
USER_POST_ID_OFFSET = 100_000
BOARD_POST_ID_OFFSET = 200_000


class SimulationStateError(RuntimeError):
    pass


def initialize_simulation(
    db: DBSession,
    session: UserSession,
    *,
    commit: bool = True,
) -> None:
    changed = False
    if not session.simulation_seed:
        session.simulation_seed = _seed_for_session(session.id)
        changed = True
    if not session.current_day or session.current_day < 1:
        session.current_day = 1
        changed = True
    if session.total_days != TOTAL_DAYS:
        session.total_days = TOTAL_DAYS
        changed = True
    holiday = bool(session.world_state and session.world_state.world_version.startswith("chaoxi-holiday"))
    if holiday:
        if session.virtual_start_date != date(2026, 10, 1):
            session.virtual_start_date = date(2026, 10, 1)
            changed = True
    elif not session.virtual_start_date or session.virtual_start_date.weekday() != 0:
        source_date = session.started_at.date() if session.started_at else date.today()
        session.virtual_start_date = week_start_for(source_date)
        changed = True

    if not holiday:
        changed = _ensure_day_activities(db, session, session.current_day) or changed
        changed = _ensure_initial_notification(db, session) or changed
    if changed and commit:
        db.commit()
        db.refresh(session)
    elif changed:
        db.flush()


def advance_day(
    db: DBSession,
    session: UserSession,
    expected_day: int,
) -> dict[str, Any]:
    initialize_simulation(db, session)
    if session.status != "active":
        raise SimulationStateError(f"Session is {session.status}.")
    if session.current_day != expected_day:
        raise SimulationStateError(
            f"Session is already on day {session.current_day}; refresh before advancing."
        )
    if session.current_day >= session.total_days:
        raise SimulationStateError("The simulation is already on its final day.")

    next_day = session.current_day + 1
    event = (
        _resolve_transition(db, session, next_day)
        if next_day in EVENT_TRANSITIONS
        else None
    )
    session.current_day = next_day
    _ensure_day_activities(db, session, next_day)
    _ensure_day_notifications(db, session, next_day, event)
    db.commit()
    db.refresh(session)

    return {
        "session_id": session.id,
        "current_day": session.current_day,
        "total_days": session.total_days,
        "virtual_date": _date_for_day(session, session.current_day).isoformat(),
        "resolved_event": _serialize_event(event) if event else None,
    }


def build_feed_state(db: DBSession, session: UserSession) -> dict[str, Any]:
    initialize_simulation(db, session)
    world = session.world_state
    holiday = bool(world and world.world_version.startswith("chaoxi-holiday"))
    if holiday:
        from world.registry import get_world_spec
        residents = get_world_spec(world.world_version).residents
    else:
        residents = None
    # Use the furthest saved day across legacy and island calendars.
    current_day = max(
        session.current_day,
        world.current_day if world is not None else session.current_day,
    )
    current_time_minutes = (
        world.current_time_minutes if world is not None else 0
    )
    event_branches = {
        item.event_key: item.branch
        for item in db.query(SimulationEvent)
        .filter(SimulationEvent.session_id == session.id)
        .all()
    }
    activities = (
        db.query(CommunityActivity)
        .filter(
            CommunityActivity.session_id == session.id,
            CommunityActivity.day <= current_day,
        )
        .order_by(
            CommunityActivity.day.asc(),
            CommunityActivity.simulated_time.asc(),
            CommunityActivity.id.asc(),
        )
        .all()
    )
    activities_by_post: dict[int, list[CommunityActivity]] = {}
    for activity in activities:
        activities_by_post.setdefault(activity.post_id, []).append(activity)

    visible_posts = []
    for source_post in ([] if holiday else posts):
        if source_post["day"] > current_day:
            continue
        post = _apply_event_variant(source_post, event_branches)
        post["is_user_post"] = False
        post_activities = activities_by_post.get(post["id"], [])
        post_date = _date_for_day(session, post["day"])
        post["virtual_date"] = post_date.isoformat()
        post["simulated_at"] = f"{post_date.isoformat()}T{post['time']}:00"
        post["is_current_day"] = post["day"] == current_day
        post.update({
            "post_type": "personal",
            "author_type": "resident",
            "author_agent_id": post.get("agent_id"),
            "world_time_minutes": _time_to_minutes(post["time"]),
            "visibility": "island_public",
            "source": {"type": "legacy_timeline", "id": post["id"]},
            "location_id": None,
            "structured_facts": {},
            "allow_comments": True,
        })
        post["community_like_count"] = sum(
            item.activity_type == "like" for item in post_activities
        )
        post["community_comments"] = [
            _serialize_activity(item, residents)
            for item in post_activities
            if item.activity_type in {"comment", "reply"}
        ]
        visible_posts.append(post)

    user_posts = (
        db.query(UserPost)
        .filter(
            UserPost.session_id == session.id,
            UserPost.day <= current_day,
        )
        .order_by(UserPost.day.asc(), UserPost.simulated_time.asc())
        .all()
    )
    for user_post in user_posts:
        if not _participant_can_view_user_post(db, user_post):
            continue
        if holiday and user_post.day==current_day and (user_post.world_time_minutes or 0)>current_time_minutes:
            continue
        post = _serialize_user_post(user_post)
        post_activities = activities_by_post.get(post["id"], [])
        post_date = _date_for_day(session, user_post.day)
        post["virtual_date"] = post_date.isoformat()
        post["simulated_at"] = (
            f"{post_date.isoformat()}T{user_post.simulated_time}:00"
        )
        post["is_current_day"] = user_post.day == current_day
        post["community_like_count"] = sum(
            item.activity_type == "like" for item in post_activities
        )
        post["community_comments"] = [
            _serialize_activity(item, residents)
            for item in post_activities
            if item.activity_type in {"comment", "reply"}
        ]
        visible_posts.append(post)

    visible_posts.sort(key=lambda item: (item["day"], item["time"]), reverse=True)
    notifications = (
        db.query(Notification)
        .filter(Notification.session_id == session.id)
        .order_by(Notification.day.desc(), Notification.id.desc())
        .all()
    )
    events = (
        db.query(SimulationEvent)
        .filter(SimulationEvent.session_id == session.id)
        .order_by(SimulationEvent.resolved_day.asc())
        .all()
    )
    world_board_posts = (
        db.query(WorldBoardPost)
        .filter(WorldBoardPost.session_id == session.id)
        .order_by(WorldBoardPost.id.desc())
        .all()
    )

    for board_post in ([] if holiday else world_board_posts):
        if board_post.world_day > current_day:
            continue
        post = _serialize_board_post(board_post)
        post_date = _date_for_day(session, board_post.world_day)
        post["virtual_date"] = post_date.isoformat()
        post["simulated_at"] = f"{post_date.isoformat()}T{post['time']}:00"
        post["is_current_day"] = board_post.world_day == current_day
        post["community_like_count"] = 0
        post["community_comments"] = []
        visible_posts.append(post)

    visible_posts.sort(
        key=lambda item: (
            int(item["day"]),
            int(item.get("world_time_minutes") or _time_to_minutes(item["time"])),
            int(item["id"]),
        ),
        reverse=True,
    )

    return {
        "session": {
            "session_id": session.id,
            "nickname": session.user_alias or session.nickname,
            "status": session.status,
            "current_day": current_day,
            "total_days": session.total_days,
            "simulation_seed": session.simulation_seed,
            "virtual_start_date": session.virtual_start_date.isoformat(),
        },
        "timeline": {
            "current_day": current_day,
            "current_time": _minutes_to_time(current_time_minutes),
            "current_time_minutes": current_time_minutes,
            "total_days": session.total_days,
            "virtual_date": _date_for_day(session, current_day).isoformat(),
            "days": [
                {
                    "day": day_number,
                    "date": _date_for_day(session, day_number).isoformat(),
                    "is_unlocked": day_number <= current_day,
                }
                for day_number in range(1, session.total_days + 1)
            ],
        },
        "posts": visible_posts,
        "notifications": [] if holiday else [_serialize_notification(item) for item in notifications],
        "events": [] if holiday else [_serialize_event(item) for item in events],
        "world_board_posts": [
            {
                "board_post_id": item.id,
                "commitment_id": item.commitment_id,
                "author_type": item.author_type,
                "author_agent_id": item.author_agent_id,
                "content": json.loads(item.content_json),
                "day": item.world_day,
                "time_minutes": item.world_time_minutes,
                "metadata": json.loads(item.metadata_json),
            }
            for item in world_board_posts
        ],
    }


def get_session_post(
    db: DBSession,
    session_id: int,
    post_id: int,
) -> dict[str, Any] | None:
    if post_id >= BOARD_POST_ID_OFFSET:
        board_post = (
            db.query(WorldBoardPost)
            .filter(
                WorldBoardPost.session_id == session_id,
                WorldBoardPost.id == post_id - BOARD_POST_ID_OFFSET,
            )
            .first()
        )
        return _serialize_board_post(board_post) if board_post else None
    source_post = get_timeline_post(post_id)
    if source_post is None:
        user_post = (
            db.query(UserPost)
            .filter(
                UserPost.session_id == session_id,
                UserPost.feed_post_id == post_id,
            )
            .first()
        )
        return (
            _serialize_user_post(user_post)
            if user_post and _participant_can_view_user_post(db, user_post)
            else None
        )
    event_branches = {
        item.event_key: item.branch
        for item in db.query(SimulationEvent)
        .filter(SimulationEvent.session_id == session_id)
        .all()
    }
    return _apply_event_variant(source_post, event_branches)


def _participant_can_view_user_post(db: DBSession, user_post: UserPost) -> bool:
    if user_post.visibility == "private":
        from models import WorldActorKnowledge
        return db.query(WorldActorKnowledge.id).filter_by(session_id=user_post.session_id,
            actor_key="participant", source_post_id=user_post.id).first() is not None
    if user_post.visibility != "targeted":
        return True
    if user_post.author_type == "participant":
        return True
    projection = db.query(WorldPlanSocialProjection).filter(
        WorldPlanSocialProjection.invitation_post_id == user_post.id
    ).first()
    if projection is None:
        return False
    try:
        audience = json.loads(projection.audience_actor_keys_json)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(audience, list) and "participant" in audience


def create_user_post(
    db: DBSession,
    session: UserSession,
    content: str,
    language: str,
    liker_ids: list[int],
    agent_comments: list[tuple[int, AgentResult]],
    *,
    world_day: int | None = None,
    world_time_minutes: int | None = None,
    location_id: str | None = None,
    source_action_id: int | None = None,
    idempotency_key: str | None = None,
) -> UserPost:
    if session.status != "active":
        raise SimulationStateError(f"Session is {session.status}.")
    cleaned = content.strip()
    if not cleaned:
        raise SimulationStateError("Post content is required.")

    effective_day = world_day if world_day is not None else session.current_day
    effective_minutes = (
        world_time_minutes
        if world_time_minutes is not None
        else _time_to_minutes("10:00")
    )
    simulated_time = _minutes_to_time(effective_minutes)
    user_post = UserPost(
        # Use zero until SQLite assigns an ID; do not commit the placeholder.
        feed_post_id=0,
        session_id=session.id,
        day=effective_day,
        author_alias=session.user_alias or session.nickname,
        content=cleaned,
        language=language,
        simulated_time=simulated_time,
        world_time_minutes=effective_minutes,
        author_type="participant",
        author_agent_id=None,
        post_type="personal",
        visibility="island_public",
        source_type="world_action" if source_action_id is not None else "legacy_composer",
        source_id=source_action_id,
        location_id=location_id,
        facts_json=json.dumps({"content_origin": "participant"}),
        metadata_json=json.dumps({"generation_mode": "participant"}),
        idempotency_key=idempotency_key,
    )
    db.add(user_post)
    db.flush()
    user_post.feed_post_id = USER_POST_ID_OFFSET + user_post.id
    db.flush()
    _create_agent_activity_for_user_post(
        db,
        session,
        user_post,
        language,
        liker_ids,
        agent_comments,
    )
    return user_post


def next_user_post_sequence(db: DBSession, session_id: int) -> int:
    return db.query(UserPost).filter(UserPost.session_id == session_id).count() + 1


def select_user_post_activity_agents(
    simulation_seed: int,
    post_sequence: int,
) -> tuple[list[int], list[int]]:
    """Choose reproducible, distinct commenters and likers for a user post."""
    rng = random.Random(f"{simulation_seed}:user-post:{post_sequence}")
    agent_ids = [1, 2, 3, 4, 5]
    rng.shuffle(agent_ids)
    return agent_ids[:2], agent_ids[:3]


def mark_notification_read(
    db: DBSession,
    session_id: int,
    notification_id: int,
) -> Notification | None:
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.session_id == session_id,
        )
        .first()
    )
    if notification is None:
        return None
    if not notification.is_read:
        notification.is_read = True
        db.commit()
        db.refresh(notification)
    return notification


def get_agent_memory(
    db: DBSession,
    session_id: int,
    agent_id: int,
) -> dict[str, Any]:
    memory = (
        db.query(AgentMemory)
        .filter(
            AgentMemory.session_id == session_id,
            AgentMemory.agent_id == agent_id,
        )
        .first()
    )
    return _serialize_memory(memory) if memory else {}


def remember_user_interaction(
    db: DBSession,
    session: UserSession,
    agent_id: int | None,
    event_type: str,
    post_id: int,
    content: str = "",
) -> None:
    if agent_id is None or event_type not in {"like", "unlike", "skip", "comment"}:
        return
    memory = (
        db.query(AgentMemory)
        .filter(
            AgentMemory.session_id == session.id,
            AgentMemory.agent_id == agent_id,
        )
        .first()
    )
    if memory is None:
        memory = AgentMemory(
            session_id=session.id,
            agent_id=agent_id,
            comment_count=0,
            like_count=0,
            skip_count=0,
            last_user_comment="",
        )
        db.add(memory)

    if event_type == "like":
        memory.like_count += 1
    elif event_type == "unlike":
        memory.like_count = max(memory.like_count - 1, 0)
    elif event_type == "skip":
        memory.skip_count += 1
    elif event_type == "comment":
        memory.comment_count += 1
        memory.last_user_comment = content[:240]

    memory.last_post_id = post_id
    memory.last_day = session.world_state.current_day if session.world_state else session.current_day
    memory.updated_at = datetime.utcnow()


def list_agent_memories(db: DBSession, session_id: int) -> list[dict[str, Any]]:
    memories = (
        db.query(AgentMemory)
        .filter(AgentMemory.session_id == session_id)
        .order_by(AgentMemory.agent_id.asc())
        .all()
    )
    return [_serialize_memory(item) for item in memories]


def _ensure_day_activities(
    db: DBSession,
    session: UserSession,
    day_number: int,
) -> bool:
    blueprints = COMMUNITY_ACTIVITY_BLUEPRINTS.get(day_number, [])
    if not blueprints:
        return False
    existing = {
        item.blueprint_key: item
        for item in db.query(CommunityActivity)
        .filter(
            CommunityActivity.session_id == session.id,
            CommunityActivity.day == day_number,
        )
        .all()
    }
    changed = False

    for blueprint in blueprints:
        key = blueprint["key"]
        if key in existing:
            continue
        rng = random.Random(f"{session.simulation_seed}:{day_number}:{key}")
        if blueprint["type"] == "like" and rng.random() < 0.15:
            continue
        parent_key = blueprint.get("parent")
        parent = existing.get(parent_key) if parent_key else None
        activity = CommunityActivity(
            session_id=session.id,
            day=day_number,
            post_id=blueprint["post_id"],
            actor_agent_id=blueprint["actor"],
            target_agent_id=blueprint.get("target"),
            parent_activity_id=parent.id if parent else None,
            activity_type=blueprint["type"],
            content_en=blueprint.get("en", ""),
            content_zh_cn=blueprint.get("zh-CN", ""),
            simulated_time=_jitter_time(blueprint["time"], rng),
            blueprint_key=key,
        )
        db.add(activity)
        db.flush()
        existing[key] = activity
        changed = True
    return changed


def _ensure_initial_notification(db: DBSession, session: UserSession) -> bool:
    existing = (
        db.query(Notification)
        .filter(
            Notification.session_id == session.id,
            Notification.notification_type == "day_1_welcome",
        )
        .first()
    )
    if existing:
        return False
    db.add(
        Notification(
            session_id=session.id,
            day=1,
            notification_type="day_1_welcome",
            content_en="Welcome to the community. Four new posts are waiting.",
            content_zh_cn="欢迎来到社区，今天有 4 条新动态。",
        )
    )
    return True


def _ensure_day_notifications(
    db: DBSession,
    session: UserSession,
    day_number: int,
    event: SimulationEvent | None,
) -> None:
    post_count = sum(post["day"] == day_number for post in posts)
    general_type = f"day_{day_number}_new_posts"
    if not _notification_exists(db, session.id, general_type):
        db.add(
            Notification(
                session_id=session.id,
                day=day_number,
                notification_type=general_type,
                content_en=(
                    f"Day {day_number} is ready. {post_count} new posts were added."
                ),
                content_zh_cn=(
                    f"第 {day_number} 天已开始，社区新增了 {post_count} 条动态。"
                ),
            )
        )

    if event is None:
        return
    event_type = f"event_{event.event_key}"
    if _notification_exists(db, session.id, event_type):
        return
    copy = _event_notification_copy(event.event_key, event.branch)
    db.add(
        Notification(
            session_id=session.id,
            day=day_number,
            agent_id=EVENT_TRANSITIONS[day_number]["agent_id"],
            post_id=event.outcome_post_id,
            notification_type=event_type,
            content_en=copy["en"],
            content_zh_cn=copy["zh-CN"],
        )
    )


def _notification_exists(db: DBSession, session_id: int, notification_type: str) -> bool:
    return (
        db.query(Notification)
        .filter(
            Notification.session_id == session_id,
            Notification.notification_type == notification_type,
        )
        .first()
        is not None
    )


def _resolve_transition(
    db: DBSession,
    session: UserSession,
    next_day: int,
) -> SimulationEvent:
    transition = EVENT_TRANSITIONS[next_day]
    existing = (
        db.query(SimulationEvent)
        .filter(
            SimulationEvent.session_id == session.id,
            SimulationEvent.event_key == transition["event_key"],
        )
        .first()
    )
    if existing:
        return existing

    source_post_id = transition["source_post_id"]
    interactions = (
        db.query(Interaction)
        .filter(
            Interaction.session_id == session.id,
            Interaction.post_id == source_post_id,
        )
        .order_by(Interaction.created_at.asc(), Interaction.id.asc())
        .all()
    )
    branch = _branch_from_interactions(interactions)
    counts: dict[str, int] = {}
    for interaction in interactions:
        counts[interaction.event_type] = counts.get(interaction.event_type, 0) + 1
    event = SimulationEvent(
        session_id=session.id,
        event_key=transition["event_key"],
        source_post_id=source_post_id,
        outcome_post_id=transition["outcome_post_id"],
        resolved_day=next_day,
        branch=branch,
        metadata_json=json.dumps({"source_event_counts": counts}),
    )
    db.add(event)
    db.flush()
    return event


def _branch_from_interactions(interactions: list[Interaction]) -> str:
    if any(item.event_type == "comment" for item in interactions):
        return "commented"
    latest_like_state = next(
        (
            item.event_type
            for item in reversed(interactions)
            if item.event_type in {"like", "unlike"}
        ),
        None,
    )
    if latest_like_state == "like":
        return "liked"
    if any(item.event_type == "skip" for item in interactions):
        return "skipped"
    return "observed"


def _apply_event_variant(
    source_post: dict[str, Any],
    event_branches: dict[str, str],
) -> dict[str, Any]:
    post = public_post(source_post)
    variants = source_post.get("event_variants")
    event_key = source_post.get("event_key")
    branch = event_branches.get(event_key) if event_key else None
    if not variants or branch not in variants:
        return post

    variant = variants[branch]
    post["content"] = variant["en"]
    post["translations"]["en"]["content"] = variant["en"]
    post["translations"]["zh-CN"]["content"] = variant["zh-CN"]
    return post


def _serialize_activity(activity: CommunityActivity, residents=None) -> dict[str, Any]:
    actor = residents.get(activity.actor_agent_id) if residents is not None else get_persona(activity.actor_agent_id)
    target = (residents.get(activity.target_agent_id) if residents is not None else get_persona(activity.target_agent_id)) if activity.target_agent_id else None
    default_content = activity.content_en or activity.content_zh_cn
    english_content = activity.content_en or default_content
    chinese_content = activity.content_zh_cn or default_content
    return {
        "activity_id": activity.id,
        "activity_type": activity.activity_type,
        "post_id": activity.post_id,
        "parent_activity_id": activity.parent_activity_id,
        "actor": {
            "agent_id": activity.actor_agent_id,
            "name": actor.name if actor else f"Agent {activity.actor_agent_id}",
            "avatar": getattr(actor, "avatar", actor.name[:1]) if actor else "?",
        },
        "target": (
            {
                "agent_id": activity.target_agent_id,
                "name": target.name if target else f"Agent {activity.target_agent_id}",
            }
            if activity.target_agent_id
            else None
        ),
        "content": default_content,
        "translations": {
            "en": {"content": english_content},
            "zh-CN": {"content": chinese_content},
        },
        "response_latency_ms": activity.response_latency_ms,
        "generation_mode": activity.generation_mode,
        "model_provider": activity.model_provider,
        "model_name": activity.model_name,
        "prompt_version": activity.prompt_version,
        "safety_flag": activity.safety_flag,
        "metadata": _json_loads(activity.metadata_json),
        "day": activity.world_day if activity.world_day is not None else activity.day,
        "time": _minutes_to_time(activity.world_time_minutes) if activity.world_time_minutes is not None else activity.simulated_time,
        "world_day": activity.world_day if activity.world_day is not None else activity.day,
        "world_time_minutes": activity.world_time_minutes,
    }


def _serialize_user_post(user_post: UserPost) -> dict[str, Any]:
    author_type = user_post.author_type or "participant"
    is_participant = author_type == "participant"
    metadata = _json_object(user_post.metadata_json)
    localized_content = metadata.get("localized_content")
    if not isinstance(localized_content, dict):
        localized_content = {}
    role_en = "Your post" if is_participant else "Island resident"
    role_zh = "你的帖子" if is_participant else "岛上居民"
    return {
        "id": int(user_post.feed_post_id or 0),
        "agent_id": user_post.author_agent_id or 0,
        "agent_name": user_post.author_alias,
        "agent_role": role_en,
        "content": user_post.content,
        "scenario_tag": "user_post",
        "day": user_post.day,
        "time": user_post.simulated_time,
        "is_user_post": is_participant,
        "post_type": user_post.post_type or "personal",
        "author_type": author_type,
        "author_agent_id": user_post.author_agent_id,
        "world_time_minutes": (
            user_post.world_time_minutes
            if user_post.world_time_minutes is not None
            else _time_to_minutes(user_post.simulated_time)
        ),
        "visibility": user_post.visibility or "island_public",
        "source": {"type": user_post.source_type, "id": user_post.source_id},
        "location_id": user_post.location_id,
        "structured_facts": _json_object(user_post.facts_json),
        "metadata": metadata,
        "allow_comments": bool(metadata.get("allow_comments", not is_participant)),
        "translations": {
            "en": {
                "agent_role": role_en,
                "content": localized_content.get("en") or user_post.content,
                "scenario_label": "Community post",
            },
            "zh-CN": {
                "agent_role": role_zh,
                "content": localized_content.get("zh-CN") or user_post.content,
                "scenario_label": "社区帖子",
            },
        },
    }


def _serialize_board_post(board_post: WorldBoardPost) -> dict[str, Any]:
    content = _json_object(board_post.content_json)
    metadata = _json_object(board_post.metadata_json)
    author_agent_id = board_post.author_agent_id
    persona = get_persona(author_agent_id) if author_agent_id is not None else None
    author_name = persona.name if persona is not None else "Island notice"
    time_label = _minutes_to_time(board_post.world_time_minutes)
    return {
        "id": BOARD_POST_ID_OFFSET + board_post.id,
        "agent_id": author_agent_id or 0,
        "agent_name": author_name,
        "agent_role": "Island announcement",
        "content": content.get("en") or content.get("zh-CN") or "",
        "scenario_tag": "island_announcement",
        "day": board_post.world_day,
        "time": time_label,
        "is_user_post": False,
        "post_type": "announcement",
        "author_type": board_post.author_type,
        "author_agent_id": author_agent_id,
        "world_time_minutes": board_post.world_time_minutes,
        "visibility": str(metadata.get("visibility") or "island_public"),
        "source": {
            "type": "commitment" if board_post.commitment_id is not None else "board_post",
            "id": board_post.commitment_id or board_post.id,
        },
        "location_id": metadata.get("location_id"),
        "structured_facts": metadata.get("facts") or {},
        "metadata": metadata,
        "allow_comments": bool(metadata.get("allow_comments", False)),
        "translations": {
            "en": {
                "agent_role": "Island announcement",
                "content": content.get("en") or content.get("zh-CN") or "",
                "scenario_label": "Island announcement",
            },
            "zh-CN": {
                "agent_role": "岛内公告",
                "content": content.get("zh-CN") or content.get("en") or "",
                "scenario_label": "岛内公告",
            },
        },
    }


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _time_to_minutes(value: str) -> int:
    try:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except (AttributeError, TypeError, ValueError):
        return 0


def _minutes_to_time(value: int) -> str:
    normalized = max(0, int(value))
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def _create_agent_activity_for_user_post(
    db: DBSession,
    session: UserSession,
    user_post: UserPost,
    language: str,
    liker_ids: list[int],
    agent_comments: list[tuple[int, AgentResult]],
) -> None:
    post_id = int(user_post.feed_post_id or 0)
    base_minutes = (
        user_post.world_time_minutes
        if user_post.world_time_minutes is not None
        else _time_to_minutes(user_post.simulated_time)
    )

    for index, agent_id in enumerate(liker_ids):
        activity_minutes = base_minutes + 3 + index * 2
        db.add(
            CommunityActivity(
                session_id=session.id,
                day=user_post.day,
                post_id=post_id,
                actor_agent_id=agent_id,
                activity_type="like",
                simulated_time=_minutes_to_time(activity_minutes),
                world_day=user_post.day,
                world_time_minutes=activity_minutes,
                blueprint_key=f"user-post-{user_post.id}-like-{agent_id}",
            )
        )

    for index, (agent_id, result) in enumerate(agent_comments):
        activity_minutes = base_minutes + 7 + index * 8
        content_en = result.reply_content if language == "en" else ""
        content_zh_cn = result.reply_content if language == "zh-CN" else ""
        generation_metadata = {
            **result.metadata,
            "source": "user_post_agent_comment",
            "language": language,
        }
        activity = CommunityActivity(
            session_id=session.id,
            day=user_post.day,
            post_id=post_id,
            actor_agent_id=agent_id,
            activity_type="comment",
            content_en=content_en,
            content_zh_cn=content_zh_cn,
            response_latency_ms=result.latency_ms,
            generation_mode=result.generation_mode,
            model_provider=result.model_provider,
            model_name=result.model_name,
            prompt_version=result.prompt_version,
            safety_flag=result.safety_flag,
            world_day=user_post.day,
            world_time_minutes=activity_minutes,
            metadata_json=json.dumps(generation_metadata, ensure_ascii=False),
            simulated_time=_minutes_to_time(activity_minutes),
            blueprint_key=f"user-post-{user_post.id}-comment-{agent_id}",
        )
        db.add(activity)
        persona = get_persona(agent_id)
        db.add(
            Notification(
                session_id=session.id,
                day=user_post.day,
                agent_id=agent_id,
                post_id=post_id,
                notification_type=f"user_post_reply_{user_post.id}_{agent_id}",
                content_en=f"{persona.name if persona else 'Someone'} replied to your post.",
                content_zh_cn=f"{persona.name if persona else '有人'} 回复了你的帖子。",
                world_day=user_post.day,
                world_time_minutes=activity_minutes,
            )
        )


def _serialize_notification(notification: Notification) -> dict[str, Any]:
    agent = get_persona(notification.agent_id) if notification.agent_id else None
    return {
        "notification_id": notification.id,
        "day": notification.day,
        "agent_id": notification.agent_id,
        "agent_name": agent.name if agent else None,
        "post_id": notification.post_id,
        "notification_type": notification.notification_type,
        "content": notification.content_en,
        "translations": {
            "en": {"content": notification.content_en},
            "zh-CN": {"content": notification.content_zh_cn},
        },
        "is_read": notification.is_read,
        "world_day": notification.world_day if notification.world_day is not None else notification.day,
        "world_time_minutes": notification.world_time_minutes,
        "created_at": notification.created_at.isoformat() + "Z",
    }


def _serialize_event(event: SimulationEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_key": event.event_key,
        "source_post_id": event.source_post_id,
        "outcome_post_id": event.outcome_post_id,
        "resolved_day": event.resolved_day,
        "branch": event.branch,
        "metadata": _json_loads(event.metadata_json),
    }


def _serialize_memory(memory: AgentMemory) -> dict[str, Any]:
    return {
        "agent_id": memory.agent_id,
        "comment_count": memory.comment_count,
        "like_count": memory.like_count,
        "skip_count": memory.skip_count,
        "last_post_id": memory.last_post_id,
        "last_day": memory.last_day,
        "last_user_comment": memory.last_user_comment,
        "updated_at": memory.updated_at.isoformat() + "Z",
    }


def _event_notification_copy(event_key: str, branch: str) -> dict[str, str]:
    copies = {
        "support_echo": {
            "commented": {
                "en": "Mira posted a follow-up after yesterday's conversation.",
                "zh-CN": "Mira 在昨天的交流后发布了一条后续动态。",
            },
            "liked": {
                "en": "Mira shared an update after yesterday's reactions.",
                "zh-CN": "Mira 在收到昨天的互动后分享了新动态。",
            },
            "skipped": {
                "en": "Mira is trying one small step today.",
                "zh-CN": "Mira 今天正在尝试一个很小的改变。",
            },
            "observed": {
                "en": "Mira added a follow-up to yesterday's post.",
                "zh-CN": "Mira 为昨天的帖子发布了后续动态。",
            },
        },
        "ambiguity_resolved": {
            "commented": {
                "en": "Nova followed up after asking for more context.",
                "zh-CN": "Nova 在主动询问更多信息后发布了后续动态。",
            },
            "liked": {
                "en": "Nova posted an update about yesterday's short reply.",
                "zh-CN": "Nova 更新了昨天那条简短回复的后续情况。",
            },
            "skipped": {
                "en": "Nova returned with more context about yesterday's message.",
                "zh-CN": "Nova 带来了昨天那条消息的更多背景。",
            },
            "observed": {
                "en": "Nova shared what happened after yesterday's uncertain message.",
                "zh-CN": "Nova 分享了昨天那条模糊消息之后发生的事。",
            },
        },
    }
    return copies[event_key][branch]


def _date_for_day(session: UserSession, day_number: int) -> date:
    return session.virtual_start_date + timedelta(days=day_number - 1)


def week_start_for(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _seed_for_session(session_id: int) -> int:
    return 104729 + session_id * 7919


def _jitter_time(value: str, rng: random.Random) -> str:
    hours, minutes = (int(part) for part in value.split(":"))
    total_minutes = hours * 60 + minutes + rng.randint(-2, 3)
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _offset_time(value: str, minutes_to_add: int) -> str:
    hours, minutes = (int(part) for part in value.split(":"))
    total_minutes = min(hours * 60 + minutes + minutes_to_add, 23 * 60 + 59)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _json_loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}
