"""Authoritative bridge between the island clock and the social feed."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session as DBSession

from agents.base import AgentResult
from models import Interaction, Session as UserSession, UserPost, WorldAction, WorldEventInstance
from services.simulation_service import create_user_post
from services.world_service import (
    WorldStateError,
    _active_participant_conversation,
    _advance_clock,
    _resolve_bound_world_spec,
    _world_has_ended,
    initialize_world,
    session_write_lock,
)


SOCIAL_POLICY_ID = "world-social-v1"
SOCIAL_POLICY_VERSION = "v1"
PARTICIPANT_POST_MINUTES = 5


def find_post_by_idempotency_key(
    db: DBSession,
    *,
    session_id: int,
    idempotency_key: str | None,
) -> UserPost | None:
    if not idempotency_key:
        return None
    return (
        db.query(UserPost)
        .filter(
            UserPost.session_id == session_id,
            UserPost.idempotency_key == idempotency_key,
        )
        .first()
    )


def publish_participant_post(
    db: DBSession,
    *,
    session_id: int,
    content: str,
    language: str,
    idempotency_key: str,
    liker_ids: list[int],
    agent_comments: list[tuple[int, AgentResult]],
    safety_flag: bool,
) -> tuple[UserPost, WorldAction, Interaction, bool]:
    """Create a post, its audit action and its clock change in one transaction."""

    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise WorldStateError("Session not found.", 404)
        if session.status != "active":
            raise WorldStateError(f"Session is {session.status}.", 409)

        existing = find_post_by_idempotency_key(
            db,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            action = (
                db.query(WorldAction)
                .filter(
                    WorldAction.session_id == session_id,
                    WorldAction.id == existing.source_id,
                )
                .first()
            )
            interaction = (
                db.query(Interaction)
                .filter(
                    Interaction.session_id == session_id,
                    Interaction.event_type == "user_post",
                    Interaction.post_id == existing.feed_post_id,
                )
                .first()
            )
            if action is None or interaction is None:
                raise WorldStateError("The existing social action is incomplete.", 409)
            return existing, action, interaction, True

        world = initialize_world(db, session)
        spec = _resolve_bound_world_spec(world)
        if _world_has_ended(world, spec):
            raise WorldStateError("The virtual world has reached its final time.", 409)
        if _active_participant_conversation(db, session_id) is not None:
            raise WorldStateError(
                "Finish the active conversation before publishing a post.", 409
            )
        active_event = (
            db.query(WorldEventInstance.id)
            .filter(
                WorldEventInstance.session_id == session_id,
                WorldEventInstance.status == "active",
            )
            .first()
        )
        if active_event is not None:
            raise WorldStateError(
                "Resolve the active event before publishing a post.", 409
            )

        before_day = world.current_day
        before_minutes = world.current_time_minutes
        action = WorldAction(
            session_id=session_id,
            idempotency_key=f"social-post:{idempotency_key}",
            actor_type="participant",
            actor_agent_id=None,
            policy_id=SOCIAL_POLICY_ID,
            policy_version=SOCIAL_POLICY_VERSION,
            decision_reason_code="participant_composed_post",
            action_type="create_post",
            response_text=content,
            language=language,
            world_day=before_day,
            world_time_minutes=before_minutes,
            metadata_json=json.dumps(
                {
                    "source": "social_phone",
                    "visibility": "island_public",
                    "duration_minutes": PARTICIPANT_POST_MINUTES,
                    "content_origin": "participant",
                },
                ensure_ascii=False,
            ),
        )
        db.add(action)
        db.flush()

        post = create_user_post(
            db,
            session,
            content,
            language,
            liker_ids,
            agent_comments,
            world_day=before_day,
            world_time_minutes=before_minutes,
            location_id=world.participant_location_id,
            source_action_id=action.id,
            idempotency_key=idempotency_key,
        )
        interaction = Interaction(
            session_id=session_id,
            event_type="user_post",
            action_type="user_post",
            post_id=int(post.feed_post_id or 0),
            content=content,
            safety_flag=safety_flag,
            world_day=before_day,
            world_time_minutes=before_minutes,
            metadata_json=json.dumps(
                {
                    "source": "social_phone",
                    "language": language,
                    "world_day": before_day,
                    "world_time_minutes": before_minutes,
                    "source_action_id": action.id,
                    "commenter_agent_ids": [item[0] for item in agent_comments],
                    "generation_modes": [item[1].generation_mode for item in agent_comments],
                },
                ensure_ascii=False,
            ),
        )
        db.add(interaction)
        _advance_clock(db, world, PARTICIPANT_POST_MINUTES)
        session.current_day = world.current_day
        db.commit()
        db.refresh(post)
        db.refresh(action)
        db.refresh(interaction)
        return post, action, interaction, False


def social_world_position(db: DBSession, session_id: int) -> tuple[int | None, int | None]:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session is None:
        return None, None
    world = session.world_state
    if world is None:
        return session.current_day, None
    return world.current_day, world.current_time_minutes
