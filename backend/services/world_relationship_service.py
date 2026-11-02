"""Fictional relationship state and change records."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    RelationshipChange,
    RelationshipState,
    WorldAction,
    WorldConversation,
    WorldState,
)
from world.specs import WorldSpec


RELATIONSHIP_VERSION = "relationship-v1"
TARGET_PARTICIPANT = "participant"
ALLOWED_REASON_CODES = frozenset(
    {"conversation_first_exchange", "declarative_event"}
)


class RelationshipStateError(RuntimeError):
    """Raised when a relationship change cannot be safely applied."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def normalize_target_key(
    *,
    target_key: str | None = None,
    target_agent_id: int | None = None,
) -> str:
    """Return a canonical relationship target key."""

    if target_key is not None and target_agent_id is not None:
        raise RelationshipStateError(
            "Provide either target_key or target_agent_id, not both.",
            400,
        )
    if target_agent_id is not None:
        if isinstance(target_agent_id, bool) or target_agent_id < 1:
            raise RelationshipStateError("target_agent_id must be positive.", 400)
        return f"resident:{target_agent_id}"

    normalized = (target_key or TARGET_PARTICIPANT).strip()
    if normalized == TARGET_PARTICIPANT:
        return TARGET_PARTICIPANT
    if normalized.startswith("resident:"):
        raw_agent_id = normalized.split(":", 1)[1]
        if raw_agent_id.isdigit() and int(raw_agent_id) > 0:
            return f"resident:{int(raw_agent_id)}"
    raise RelationshipStateError(
        "target_key must be participant or resident:{agent_id}.",
        400,
    )


def _target_agent_id(target_key: str) -> int | None:
    if not target_key.startswith("resident:"):
        return None
    return int(target_key.split(":", 1)[1])


def _resident_exists(
    db: DBSession,
    *,
    session_id: int,
    spec: WorldSpec,
    agent_id: int,
) -> bool:
    return (
        agent_id in spec.residents
        and db.query(CharacterState.id)
        .filter(
            CharacterState.session_id == session_id,
            CharacterState.agent_id == agent_id,
        )
        .first()
        is not None
    )


def _validate_world_binding(spec: WorldSpec, world: WorldState) -> None:
    if world.world_version != spec.world_version:
        raise RelationshipStateError(
            "World version does not match the relationship service spec.",
            409,
        )
    if world.scenario_pack_version != spec.scenario_pack_version:
        raise RelationshipStateError(
            "Scenario pack version does not match the relationship service spec.",
            409,
        )


def _validate_participants(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    source_agent_id: int,
    target_key: str,
) -> None:
    if isinstance(source_agent_id, bool) or source_agent_id < 1:
        raise RelationshipStateError("source_agent_id must be positive.", 400)
    if not _resident_exists(
        db,
        session_id=world.session_id,
        spec=spec,
        agent_id=source_agent_id,
    ):
        raise RelationshipStateError(
            "Relationship source is not a resident in this session world.",
            409,
        )
    target_agent_id = _target_agent_id(target_key)
    if target_agent_id is not None and not _resident_exists(
        db,
        session_id=world.session_id,
        spec=spec,
        agent_id=target_agent_id,
    ):
        raise RelationshipStateError(
            "Relationship target is not a resident in this session world.",
            409,
        )


def get_or_create_relationship(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    source_agent_id: int,
    target_key: str | None = None,
    target_agent_id: int | None = None,
) -> RelationshipState:
    """Return the session-local relationship row for a source and target."""

    _validate_world_binding(spec, world)
    normalized_target_key = normalize_target_key(
        target_key=target_key,
        target_agent_id=target_agent_id,
    )
    _validate_participants(
        db,
        spec=spec,
        world=world,
        source_agent_id=source_agent_id,
        target_key=normalized_target_key,
    )
    existing = (
        db.query(RelationshipState)
        .filter(
            RelationshipState.session_id == world.session_id,
            RelationshipState.source_agent_id == source_agent_id,
            RelationshipState.target_key == normalized_target_key,
        )
        .first()
    )
    if existing is not None:
        return existing

    relationship = RelationshipState(
        session_id=world.session_id,
        source_agent_id=source_agent_id,
        target_key=normalized_target_key,
        familiarity=0,
        trust=0,
        warmth=0,
        tension=0,
        unresolved_context="",
        version=RELATIONSHIP_VERSION,
        updated_day=world.current_day,
        updated_time_minutes=world.current_time_minutes,
    )
    db.add(relationship)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(RelationshipState)
            .filter(
                RelationshipState.session_id == world.session_id,
                RelationshipState.source_agent_id == source_agent_id,
                RelationshipState.target_key == normalized_target_key,
            )
            .first()
        )
        if existing is None:
            raise
        return existing
    return relationship


def get_relationship_snapshot(relationship: RelationshipState) -> dict[str, Any]:
    """Return the compact state used in before/after audit payloads."""

    return {
        "relationship_id": relationship.id,
        "session_id": relationship.session_id,
        "source_agent_id": relationship.source_agent_id,
        "target_key": relationship.target_key,
        "familiarity": relationship.familiarity,
        "trust": relationship.trust,
        "warmth": relationship.warmth,
        "tension": relationship.tension,
        "unresolved_context": relationship.unresolved_context,
        "version": relationship.version,
        "updated_day": relationship.updated_day,
        "updated_time_minutes": relationship.updated_time_minutes,
    }


def serialize_relationship(relationship: RelationshipState) -> dict[str, Any]:
    return {
        **get_relationship_snapshot(relationship),
        "updated_at": (
            relationship.updated_at.isoformat() if relationship.updated_at else None
        ),
    }


def serialize_relationship_change(change: RelationshipChange) -> dict[str, Any]:
    return {
        "relationship_change_id": change.id,
        "session_id": change.session_id,
        "relationship_id": change.relationship_id,
        "idempotency_key": change.idempotency_key,
        "source_action_id": change.source_action_id,
        "source_event_type": change.source_event_type,
        "source_event_id": change.source_event_id,
        "effect_key": change.effect_key,
        "familiarity_delta": change.familiarity_delta,
        "trust_delta": change.trust_delta,
        "warmth_delta": change.warmth_delta,
        "tension_delta": change.tension_delta,
        "reason_code": change.reason_code,
        "before": _json_loads(change.before_json),
        "after": _json_loads(change.after_json),
        "world_day": change.world_day,
        "world_time_minutes": change.world_time_minutes,
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }


def _validate_delta(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RelationshipStateError(f"{name} must be an integer delta.", 400)
    return value


def _validate_change_request(
    *,
    idempotency_key: str,
    effect_key: str,
    reason_code: str,
    familiarity_delta: int,
    trust_delta: int,
    warmth_delta: int,
    tension_delta: int,
) -> tuple[int, int, int, int]:
    if not idempotency_key.strip() or len(idempotency_key) > 120:
        raise RelationshipStateError(
            "idempotency_key must contain 1 to 120 characters.",
            400,
        )
    if not effect_key.strip() or len(effect_key) > 80:
        raise RelationshipStateError(
            "effect_key must contain 1 to 80 characters.",
            400,
        )
    if reason_code not in ALLOWED_REASON_CODES:
        raise RelationshipStateError("Unsupported relationship reason_code.", 400)
    deltas = (
        _validate_delta("familiarity_delta", familiarity_delta),
        _validate_delta("trust_delta", trust_delta),
        _validate_delta("warmth_delta", warmth_delta),
        _validate_delta("tension_delta", tension_delta),
    )
    if not any(deltas):
        raise RelationshipStateError(
            "At least one relationship delta must be non-zero.",
            400,
        )
    return deltas


def _source_action_belongs_to_session(
    db: DBSession,
    *,
    session_id: int,
    source_action_id: int,
) -> bool:
    return (
        db.query(WorldAction.id)
        .filter(
            WorldAction.id == source_action_id,
            WorldAction.session_id == session_id,
        )
        .first()
        is not None
    )


def _existing_change_matches(
    change: RelationshipChange,
    *,
    source_agent_id: int,
    target_key: str,
    source_action_id: int | None,
    source_event_type: str | None,
    source_event_id: str | None,
    effect_key: str,
    familiarity_delta: int,
    trust_delta: int,
    warmth_delta: int,
    tension_delta: int,
    reason_code: str,
) -> bool:
    relationship = change.relationship
    return (
        relationship.source_agent_id == source_agent_id
        and relationship.target_key == target_key
        and change.source_action_id == source_action_id
        and change.source_event_type == source_event_type
        and change.source_event_id == source_event_id
        and change.effect_key == effect_key
        and change.familiarity_delta == familiarity_delta
        and change.trust_delta == trust_delta
        and change.warmth_delta == warmth_delta
        and change.tension_delta == tension_delta
        and change.reason_code == reason_code
    )


def apply_relationship_change(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    source_agent_id: int,
    target_key: str | None = TARGET_PARTICIPANT,
    target_agent_id: int | None = None,
    idempotency_key: str,
    effect_key: str,
    reason_code: str,
    familiarity_delta: int = 0,
    trust_delta: int = 0,
    warmth_delta: int = 0,
    tension_delta: int = 0,
    source_action_id: int | None = None,
    source_event_type: str | None = None,
    source_event_id: int | str | None = None,
) -> RelationshipChange:
    """Apply one audited delta, clamping final values server-side."""

    _validate_world_binding(spec, world)
    normalized_target_key = normalize_target_key(
        target_key=target_key,
        target_agent_id=target_agent_id,
    )
    deltas = _validate_change_request(
        idempotency_key=idempotency_key,
        effect_key=effect_key,
        reason_code=reason_code,
        familiarity_delta=familiarity_delta,
        trust_delta=trust_delta,
        warmth_delta=warmth_delta,
        tension_delta=tension_delta,
    )
    (
        familiarity_delta,
        trust_delta,
        warmth_delta,
        tension_delta,
    ) = deltas
    normalized_source_event_id = (
        str(source_event_id) if source_event_id is not None else None
    )
    normalized_source_event_type = (
        source_event_type.strip() if source_event_type else None
    )
    normalized_effect_key = effect_key.strip()
    normalized_key = idempotency_key.strip()

    existing_change = (
        db.query(RelationshipChange)
        .filter(
            RelationshipChange.session_id == world.session_id,
            RelationshipChange.idempotency_key == normalized_key,
        )
        .first()
    )
    if existing_change is not None:
        if _existing_change_matches(
            existing_change,
            source_agent_id=source_agent_id,
            target_key=normalized_target_key,
            source_action_id=source_action_id,
            source_event_type=normalized_source_event_type,
            source_event_id=normalized_source_event_id,
            effect_key=normalized_effect_key,
            familiarity_delta=familiarity_delta,
            trust_delta=trust_delta,
            warmth_delta=warmth_delta,
            tension_delta=tension_delta,
            reason_code=reason_code,
        ):
            return existing_change
        raise RelationshipStateError(
            "Relationship idempotency key already has a different payload.",
            409,
        )

    _validate_participants(
        db,
        spec=spec,
        world=world,
        source_agent_id=source_agent_id,
        target_key=normalized_target_key,
    )
    if source_action_id is not None and not _source_action_belongs_to_session(
        db,
        session_id=world.session_id,
        source_action_id=source_action_id,
    ):
        raise RelationshipStateError(
            "source_action_id does not belong to this session.",
            409,
        )

    relationship = get_or_create_relationship(
        db,
        spec=spec,
        world=world,
        source_agent_id=source_agent_id,
        target_key=normalized_target_key,
    )
    before = get_relationship_snapshot(relationship)
    relationship.familiarity = _clamp(
        relationship.familiarity + familiarity_delta,
        0,
        100,
    )
    relationship.trust = _clamp(relationship.trust + trust_delta, -100, 100)
    relationship.warmth = _clamp(relationship.warmth + warmth_delta, -100, 100)
    relationship.tension = _clamp(relationship.tension + tension_delta, 0, 100)
    relationship.version = RELATIONSHIP_VERSION
    relationship.updated_day = world.current_day
    relationship.updated_time_minutes = world.current_time_minutes
    relationship.updated_at = utc_now()
    after = get_relationship_snapshot(relationship)

    change = RelationshipChange(
        session_id=world.session_id,
        relationship_id=relationship.id,
        idempotency_key=normalized_key,
        source_action_id=source_action_id,
        source_event_type=normalized_source_event_type,
        source_event_id=normalized_source_event_id,
        effect_key=normalized_effect_key,
        familiarity_delta=familiarity_delta,
        trust_delta=trust_delta,
        warmth_delta=warmth_delta,
        tension_delta=tension_delta,
        reason_code=reason_code,
        before_json=_json_dumps(before),
        after_json=_json_dumps(after),
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
    )
    db.add(change)
    try:
        db.flush()
    except IntegrityError as exc:
        raise RelationshipStateError(
            "Relationship idempotency key was reused concurrently.",
            409,
        ) from exc
    return change


def apply_conversation_first_exchange(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    conversation: WorldConversation,
    action: WorldAction,
) -> RelationshipChange:
    """Apply the sole M2-B live rule: first ordinary exchange +1 familiarity."""

    if conversation.session_id != world.session_id or action.session_id != world.session_id:
        raise RelationshipStateError(
            "Conversation relationship source belongs to another session.",
            409,
        )
    if action.action_type != "conversation_message":
        raise RelationshipStateError(
            "Conversation relationship source must be a conversation action.",
            409,
        )
    if conversation.agent_id != action.target_agent_id:
        raise RelationshipStateError(
            "Conversation action target does not match the relationship source.",
            409,
        )
    return apply_relationship_change(
        db,
        spec=spec,
        world=world,
        source_agent_id=conversation.agent_id,
        target_key=TARGET_PARTICIPANT,
        idempotency_key=f"conversation:{conversation.id}:first_exchange",
        effect_key="first_exchange",
        reason_code="conversation_first_exchange",
        familiarity_delta=1,
        source_action_id=action.id,
        source_event_type="conversation_message",
        source_event_id=conversation.id,
    )
