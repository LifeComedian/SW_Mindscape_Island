"""Resident posts derived from world events."""

from __future__ import annotations
from agents.output_safety import preserve_stop

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session as DBSession

from models import (
    Notification,
    Session as UserSession,
    UserPost,
    WorldAction,
    WorldEmergenceDecision,
    WorldEventInstance,
    WorldState,
)
from services.simulation_service import USER_POST_ID_OFFSET
from world.specs import EventContentSpec, WorldSpec


DraftGenerator = Callable[[dict[str, Any]], Mapping[str, Any]]
SOCIAL_POLICY_ID = "grounded-event-publication"
SOCIAL_POLICY_VERSION = "m5-g3-v1"


class GroundedPostDraftError(ValueError):
    """Raised when generated social text exceeds its authored fact boundary."""


def validate_grounded_post_draft(
    draft: Mapping[str, Any],
    *,
    author_agent_id: int,
    allowed_fact_ids: set[str],
) -> dict[str, Any]:
    """Validate the structured boundary expected from a future LLM adapter."""

    if draft.get("author_agent_id") != author_agent_id:
        raise GroundedPostDraftError("generated_author_not_eligible")
    content = draft.get("content")
    if not isinstance(content, str) or not content.strip() or len(content.strip()) > 500:
        raise GroundedPostDraftError("generated_content_invalid")
    raw_fact_ids = draft.get("used_fact_ids")
    if not isinstance(raw_fact_ids, (list, tuple)) or not raw_fact_ids:
        raise GroundedPostDraftError("generated_facts_missing")
    used_fact_ids = {value for value in raw_fact_ids if isinstance(value, str)}
    if len(used_fact_ids) != len(raw_fact_ids) or not used_fact_ids <= allowed_fact_ids:
        raise GroundedPostDraftError("generated_fact_out_of_bounds")
    return {
        "author_agent_id": author_agent_id,
        "content": content.strip(),
        "used_fact_ids": sorted(used_fact_ids),
    }


def select_grounded_post_draft(
    publication: Mapping[str, Any],
    *,
    author_agent_id: int,
    language: str,
    generator: DraftGenerator | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    """Return a validated draft, falling back to authored text on any LLM fault."""

    facts = dict(publication.get("facts") or {})
    allowed_fact_ids = set(facts)
    generation_mode = str(publication.get("generation_mode") or "static_fallback")
    fallback_reason: str | None = None
    if generation_mode == "llm_with_fallback" and generator is not None:
        try:
            generated = generator({
                "author_agent_id": author_agent_id,
                "allowed_facts": facts,
                "publication_id": publication.get("publication_id"),
                "language": language,
            })
            return (
                validate_grounded_post_draft(
                    generated,
                    author_agent_id=author_agent_id,
                    allowed_fact_ids=allowed_fact_ids,
                ),
                "llm",
                None,
            )
        except Exception as exc:  # adapters are deliberately isolated from runtime
            preserve_stop(exc)
            fallback_reason = (
                str(exc) if isinstance(exc, GroundedPostDraftError) else "generation_failed"
            )
    elif generation_mode == "llm_with_fallback":
        fallback_reason = "generator_unavailable"

    template = next(
        (
            dict(item)
            for item in publication.get("templates", ())
            if int(item.get("author_agent_id", 0)) == author_agent_id
        ),
        None,
    )
    if template is None:
        raise GroundedPostDraftError("fallback_template_missing")
    localized = dict(template.get("content") or {})
    content = str(localized.get(language) or localized.get("en") or "").strip()
    if not content:
        raise GroundedPostDraftError("fallback_content_missing")
    return (
        {
            "author_agent_id": author_agent_id,
            "content": content,
            "localized_content": localized,
            "used_fact_ids": sorted(allowed_fact_ids),
        },
        "static_fallback",
        fallback_reason,
    )


def evaluate_event_social_publications(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    spec: WorldSpec,
    source_action: WorldAction,
    event: WorldEventInstance,
    generator: DraftGenerator | None = None,
) -> list[UserPost]:
    """Evaluate, audit, and materialize resident posts for one completed event."""

    if event.status != "completed":
        return []
    event_metadata = _json_object(event.metadata_json)
    event_definition_id = event_metadata.get("declarative_event_id")
    definition = spec.event_specs.get(str(event_definition_id))
    if definition is None or not definition.social_publications:
        return []

    created: list[UserPost] = []
    for raw_publication in definition.social_publications:
        publication = dict(raw_publication)
        publication_id = str(publication["publication_id"])
        templates = [dict(item) for item in publication.get("templates", ())]
        candidates: list[tuple[int, dict[str, Any]]] = []
        trigger_outcomes = set(publication.get("trigger_outcomes", ()))
        for template in templates:
            author_agent_id = int(template["author_agent_id"])
            reason = _candidate_block_reason(
                db,
                session=session,
                world=world,
                event=event,
                publication=publication,
                author_agent_id=author_agent_id,
                outcome_allowed=event.outcome_code in trigger_outcomes,
            )
            if reason is None:
                candidates.append((author_agent_id, template))
            else:
                _audit(
                    db,
                    session=session,
                    source_action=source_action,
                    event=event,
                    publication_id=publication_id,
                    author_agent_id=author_agent_id,
                    outcome="blocked",
                    reason_code=reason,
                    rank=0,
                    world=world,
                )

        candidates.sort(
            key=lambda item: _stable_rank(
                session.simulation_seed,
                event.id,
                publication_id,
                item[0],
            )
        )
        remaining = max(0, int(publication.get("max_posts", 1)))
        already_created = (
            db.query(UserPost)
            .filter(
                UserPost.session_id == session.id,
                UserPost.source_type == "world_event",
                UserPost.source_id == event.id,
            )
            .count()
        )
        remaining = max(0, remaining - already_created)
        for rank, (author_agent_id, _template) in enumerate(candidates, start=1):
            if remaining <= 0:
                _audit(
                    db,
                    session=session,
                    source_action=source_action,
                    event=event,
                    publication_id=publication_id,
                    author_agent_id=author_agent_id,
                    outcome="blocked",
                    reason_code="publication_limit_reached",
                    rank=rank,
                    world=world,
                )
                continue
            draft, generation_mode, fallback_reason = select_grounded_post_draft(
                publication,
                author_agent_id=author_agent_id,
                language=source_action.language,
                generator=generator,
            )
            post_action = WorldAction(
                session_id=session.id,
                idempotency_key=f"social:event:{event.id}:{publication_id}:{author_agent_id}",
                actor_type="resident",
                actor_agent_id=author_agent_id,
                policy_id=SOCIAL_POLICY_ID,
                policy_version=SOCIAL_POLICY_VERSION,
                decision_reason_code="eligible_grounded_event_fact",
                action_type="create_post",
                target_location_id=event.location_id,
                event_instance_id=event.id,
                language=source_action.language,
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
                metadata_json=json.dumps({
                    "publication_id": publication_id,
                    "source_event_definition_id": definition.event_id,
                    "source_participant_action_id": source_action.id,
                    "used_fact_ids": draft["used_fact_ids"],
                    "generation_mode": generation_mode,
                    "fallback_reason": fallback_reason,
                }),
            )
            db.add(post_action)
            db.flush()
            resident = spec.residents[author_agent_id]
            post = UserPost(
                feed_post_id=0,
                session_id=session.id,
                day=world.current_day,
                author_alias=resident.name,
                content=draft["content"],
                language=source_action.language,
                simulated_time=_minutes_to_time(world.current_time_minutes),
                world_time_minutes=world.current_time_minutes,
                author_type="resident",
                author_agent_id=author_agent_id,
                post_type=str(publication.get("post_type") or "activity"),
                visibility=str(publication.get("visibility") or "island_public"),
                source_type="world_event",
                source_id=event.id,
                location_id=event.location_id,
                facts_json=json.dumps(dict(publication.get("facts") or {}), ensure_ascii=False),
                metadata_json=json.dumps({
                    "publication_id": publication_id,
                    "event_definition_id": definition.event_id,
                    "event_outcome_code": event.outcome_code,
                    "source_action_id": source_action.id,
                    "post_action_id": post_action.id,
                    "generation_mode": generation_mode,
                    "fallback_reason": fallback_reason,
                    "used_fact_ids": draft["used_fact_ids"],
                    "localized_content": draft.get("localized_content", {}),
                    "allow_comments": bool(publication.get("allow_comments", True)),
                }, ensure_ascii=False),
                idempotency_key=post_action.idempotency_key,
            )
            db.add(post)
            db.flush()
            post.feed_post_id = USER_POST_ID_OFFSET + post.id
            db.add(Notification(
                session_id=session.id,
                day=world.current_day,
                agent_id=author_agent_id,
                post_id=post.feed_post_id,
                notification_type=f"resident_post_{post.id}",
                content_en=f"{resident.name} shared a new island update.",
                content_zh_cn=f"{resident.name} 分享了一条新的岛内动态。",
                world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,
            ))
            _audit(
                db,
                session=session,
                source_action=source_action,
                event=event,
                publication_id=publication_id,
                author_agent_id=author_agent_id,
                outcome="selected",
                reason_code="eligible_grounded_event_fact",
                rank=rank,
                world=world,
            )
            created.append(post)
            remaining -= 1
    return created


def _candidate_block_reason(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    event: WorldEventInstance,
    publication: Mapping[str, Any],
    author_agent_id: int,
    outcome_allowed: bool,
) -> str | None:
    if not outcome_allowed:
        return "event_outcome_not_publishable"
    if author_agent_id not in set(publication.get("witness_agent_ids", ())):
        return "author_did_not_witness_event"
    publication_id = str(publication.get("publication_id"))
    existing = (
        db.query(UserPost)
        .filter(
            UserPost.session_id == session.id,
            UserPost.idempotency_key == f"social:event:{event.id}:{publication_id}:{author_agent_id}",
        )
        .first()
    )
    if existing is not None:
        return "already_published"
    cooldown = int(publication.get("cooldown_minutes", 0))
    if cooldown <= 0:
        return None
    current_absolute = (world.current_day - 1) * 1440 + world.current_time_minutes
    previous_posts = (
        db.query(UserPost)
        .filter(
            UserPost.session_id == session.id,
            UserPost.author_agent_id == author_agent_id,
            UserPost.author_type == "resident",
        )
        .order_by(UserPost.day.desc(), UserPost.world_time_minutes.desc())
        .all()
    )
    for post in previous_posts:
        metadata = _json_object(post.metadata_json)
        if metadata.get("publication_id") != publication_id:
            continue
        previous_absolute = (post.day - 1) * 1440 + int(post.world_time_minutes or 0)
        if current_absolute - previous_absolute < cooldown:
            return "publication_cooldown_active"
        break
    return None


def _audit(
    db: DBSession,
    *,
    session: UserSession,
    source_action: WorldAction,
    event: WorldEventInstance,
    publication_id: str,
    author_agent_id: int,
    outcome: str,
    reason_code: str,
    rank: int,
    world: WorldState,
) -> None:
    db.add(WorldEmergenceDecision(
        session_id=session.id,
        source_action_id=source_action.id,
        candidate_type="social_publication",
        candidate_id=f"{publication_id}:{author_agent_id}",
        outcome=outcome,
        reason_code=reason_code,
        rank=rank,
        simulation_seed=session.simulation_seed,
        policy_id=SOCIAL_POLICY_ID,
        policy_version=SOCIAL_POLICY_VERSION,
        snapshot_json=json.dumps({
            "event_instance_id": event.id,
            "event_outcome_code": event.outcome_code,
            "world_day": world.current_day,
            "world_time_minutes": world.current_time_minutes,
            "location_id": event.location_id,
        }),
    ))


def _stable_rank(seed: int, event_id: int, publication_id: str, author_id: int) -> str:
    return hashlib.sha256(
        f"{seed}:{event_id}:{publication_id}:{author_id}".encode("utf-8")
    ).hexdigest()


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _minutes_to_time(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"
