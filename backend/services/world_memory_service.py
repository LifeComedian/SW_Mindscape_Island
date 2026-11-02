"""Store and retrieve session-scoped resident memories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session as DBSession

from models import CharacterState, WorldAction, WorldMemory


MEMORY_SCHEMA_VERSION = "world-memory-v1"
STORY_MEMORY_TYPES = frozenset({"episodic", "semantic", "relationship_event"})
ORDINARY_PRIVACY_CATEGORY = "ordinary"


class MemoryConflictError(ValueError):
    """A source event was reused for a different memory payload."""


@dataclass(frozen=True)
class MemoryQuery:
    session_id: int
    owner_agent_id: int
    current_day: int
    current_time_minutes: int
    location_id: str | None = None
    scenario_instance_id: int | None = None
    related_agent_ids: tuple[int, ...] = ()
    tags: tuple[str, ...] = ()
    memory_types: tuple[str, ...] = ()
    privacy_categories: tuple[str, ...] = (ORDINARY_PRIVACY_CATEGORY,)
    limit: int = 5
    include_private: bool = True


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def memory_metadata(memory: WorldMemory) -> dict[str, Any]:
    """Read both legacy metadata and the versioned v1 structure."""

    return _json_loads(memory.metadata_json)


def record_memory(
    db: DBSession,
    *,
    session_id: int,
    owner_agent_id: int,
    memory_type: str,
    content: str,
    occurred_day: int,
    occurred_time_minutes: int,
    source_action_id: int | None = None,
    source_event_type: str | None = None,
    source_event_id: int | str | None = None,
    importance: int = 1,
    privacy_category: str = ORDINARY_PRIVACY_CATEGORY,
    location_id: str | None = None,
    scenario_instance_id: int | None = None,
    source_response_id: int | None = None,
    related_agent_ids: Iterable[int] = (),
    tags: Iterable[str] = (),
    effect_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorldMemory:
    """Add one memory to the caller's transaction.

    ``effect_key`` lets one source produce multiple memories of the same type.
    The database transaction and source action/event remain the authoritative
    write boundary.
    """

    normalized_type = memory_type.strip()
    normalized_content = content.strip()
    normalized_privacy = privacy_category.strip()
    normalized_effect_key = effect_key.strip() if effect_key is not None else None
    if session_id < 1 or owner_agent_id < 1:
        raise ValueError("session_id and owner_agent_id must be positive.")
    if not normalized_type or len(normalized_type) > 30:
        raise ValueError("memory_type must contain 1 to 30 characters.")
    if normalized_type not in STORY_MEMORY_TYPES:
        raise ValueError(
            "memory_type must be one of: "
            + ", ".join(sorted(STORY_MEMORY_TYPES))
            + "."
        )
    if not normalized_content:
        raise ValueError("Memory content must not be empty.")
    if not normalized_privacy or len(normalized_privacy) > 30:
        raise ValueError("privacy_category must contain 1 to 30 characters.")
    if occurred_day < 1 or not 0 <= occurred_time_minutes <= 1439:
        raise ValueError("Memory virtual time is outside the supported range.")
    if not 1 <= importance <= 5:
        raise ValueError("Memory importance must be between 1 and 5.")
    if effect_key is not None and (
        not normalized_effect_key or len(normalized_effect_key) > 80
    ):
        raise ValueError("effect_key must contain 1 to 80 characters.")

    owner_exists = (
        db.query(CharacterState.id)
        .filter(
            CharacterState.session_id == session_id,
            CharacterState.agent_id == owner_agent_id,
        )
        .first()
        is not None
    )
    if not owner_exists:
        raise ValueError("Memory owner is not a resident in this session world.")
    if source_action_id is not None:
        action_exists = (
            db.query(WorldAction.id)
            .filter(
                WorldAction.id == source_action_id,
                WorldAction.session_id == session_id,
            )
            .first()
            is not None
        )
        if not action_exists:
            raise ValueError("source_action_id does not belong to this session.")

    resolved_event_type = source_event_type or (
        "world_action" if source_action_id is not None else "system"
    )
    resolved_event_id = (
        source_event_id if source_event_id is not None else source_action_id
    )
    payload = dict(metadata or {})
    payload["schema_version"] = MEMORY_SCHEMA_VERSION
    payload["source_event_type"] = resolved_event_type
    payload["source_event_id"] = resolved_event_id
    if normalized_effect_key is not None:
        payload["effect_key"] = normalized_effect_key
    if location_id is not None:
        payload["location_id"] = location_id
    if scenario_instance_id is not None:
        payload["scenario_instance_id"] = scenario_instance_id
    if source_response_id is not None:
        payload["source_response_id"] = source_response_id
    payload["related_agent_ids"] = sorted(
        {int(agent_id) for agent_id in related_agent_ids if int(agent_id) > 0}
    )
    payload["tags"] = sorted(
        {str(tag).strip() for tag in tags if str(tag).strip()}
    )

    existing: WorldMemory | None = None
    if source_action_id is not None or resolved_event_id is not None:
        candidates = (
            db.query(WorldMemory)
            .filter(
                WorldMemory.session_id == session_id,
                WorldMemory.owner_agent_id == owner_agent_id,
                WorldMemory.memory_type == normalized_type,
            )
            .all()
        )
        for candidate in candidates:
            candidate_metadata = memory_metadata(candidate)
            same_source = (
                candidate.source_action_id == source_action_id
                if source_action_id is not None
                else (
                    candidate_metadata.get("source_event_type")
                    == resolved_event_type
                    and candidate_metadata.get("source_event_id")
                    == resolved_event_id
                )
            )
            if (
                same_source
                and candidate_metadata.get("effect_key") == normalized_effect_key
            ):
                existing = candidate
                break
        if existing is not None:
            if (
                existing.content != normalized_content
                or existing.importance != importance
                or existing.privacy_category != normalized_privacy
                or existing.occurred_day != occurred_day
                or existing.occurred_time_minutes != occurred_time_minutes
                or memory_metadata(existing) != payload
            ):
                raise MemoryConflictError(
                    "The source effect already owns a different memory payload."
                )
            return existing

    memory = WorldMemory(
        session_id=session_id,
        owner_agent_id=owner_agent_id,
        memory_type=normalized_type,
        source_action_id=source_action_id,
        content=normalized_content,
        importance=importance,
        privacy_category=normalized_privacy,
        occurred_day=occurred_day,
        occurred_time_minutes=occurred_time_minutes,
        metadata_json=_json_dumps(payload),
    )
    db.add(memory)
    return memory


def _memory_rank(memory: WorldMemory, query: MemoryQuery) -> tuple[int, int, int, int]:
    metadata = memory_metadata(memory)
    context_score = 0
    if query.scenario_instance_id is not None:
        if metadata.get("scenario_instance_id") == query.scenario_instance_id:
            context_score += 4
    if query.location_id is not None and metadata.get("location_id") == query.location_id:
        context_score += 2

    related = {
        int(value)
        for value in metadata.get("related_agent_ids", [])
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    }
    context_score += len(related.intersection(query.related_agent_ids))
    memory_tags = {str(value) for value in metadata.get("tags", [])}
    context_score += len(memory_tags.intersection(query.tags))

    age_minutes = max(
        0,
        (query.current_day - memory.occurred_day) * 1440
        + query.current_time_minutes
        - memory.occurred_time_minutes,
    )
    return (
        context_score,
        memory.importance,
        -age_minutes,
        memory.id or 0,
    )


def retrieve_memories(db: DBSession, query: MemoryQuery) -> list[WorldMemory]:
    """Return deterministic, context-ranked memories for one resident.

    The default privacy filter is deliberately fail-closed: only ordinary story
    memory is eligible unless a trusted caller explicitly selects another class.
    """

    if query.session_id < 1 or query.owner_agent_id < 1:
        raise ValueError("session_id and owner_agent_id must be positive.")
    if query.current_day < 1 or not 0 <= query.current_time_minutes <= 1439:
        raise ValueError("Memory query virtual time is outside the supported range.")
    if not query.privacy_categories or query.limit <= 0:
        return []

    requested_types = set(query.memory_types)
    unsupported_types = requested_types.difference(STORY_MEMORY_TYPES)
    if unsupported_types:
        raise ValueError(
            "Resident memory queries cannot access non-story memory types: "
            + ", ".join(sorted(unsupported_types))
            + "."
        )

    db_query = db.query(WorldMemory).filter(
        WorldMemory.session_id == query.session_id,
        WorldMemory.owner_agent_id == query.owner_agent_id,
        WorldMemory.privacy_category.in_(query.privacy_categories),
        WorldMemory.memory_type.in_(
            tuple(sorted(requested_types or STORY_MEMORY_TYPES))
        ),
        or_(
            WorldMemory.occurred_day < query.current_day,
            and_(
                WorldMemory.occurred_day == query.current_day,
                WorldMemory.occurred_time_minutes <= query.current_time_minutes,
            ),
        ),
    )
    candidates = db_query.all()
    if not query.include_private:
        candidates=[m for m in candidates if not {'private_message','private_conversation'}.intersection(memory_metadata(m).get('tags',[]))]
    candidates.sort(key=lambda item: _memory_rank(item, query), reverse=True)
    return candidates[: min(query.limit, 100)]


def build_agent_memory_context(
    db: DBSession,
    *,
    session_id: int,
    owner_agent_id: int,
    current_day: int,
    current_time_minutes: int,
    location_id: str | None,
    limit: int = 5,
    include_private: bool = True,
) -> dict[str, Any]:
    """Build the backwards-compatible context consumed by AgentRequest."""

    episodic_query = db.query(WorldMemory).filter(
        WorldMemory.session_id == session_id,
        WorldMemory.owner_agent_id == owner_agent_id,
        WorldMemory.privacy_category == ORDINARY_PRIVACY_CATEGORY,
        WorldMemory.memory_type == "episodic",
    )
    episodic_count = episodic_query.count()
    episodic_rows = episodic_query.order_by(
        WorldMemory.occurred_day.desc(),
        WorldMemory.occurred_time_minutes.desc(),
        WorldMemory.id.desc(),
    ).all()
    if not include_private:
        episodic_rows=[m for m in episodic_rows if not {'private_message','private_conversation'}.intersection(memory_metadata(m).get('tags',[]))]
        episodic_count=len(episodic_rows)
    latest_episodic=episodic_rows[0] if episodic_rows else None
    memories = retrieve_memories(
        db,
        MemoryQuery(
            session_id=session_id,
            owner_agent_id=owner_agent_id,
            current_day=current_day,
            current_time_minutes=current_time_minutes,
            location_id=location_id,
            related_agent_ids=(owner_agent_id,),
            limit=limit,
            include_private=include_private,
        ),
    )
    if not memories:
        return {}

    latest_comment = latest_episodic.content if latest_episodic is not None else ""
    prefix = "The participant said: "
    if latest_comment.startswith(prefix):
        latest_comment = latest_comment[len(prefix) :]
    return {
        "comment_count": episodic_count,
        "last_day": latest_episodic.occurred_day if latest_episodic is not None else None,
        "last_user_comment": latest_comment,
        "memory_count": len(memories),
        "memory_schema_version": MEMORY_SCHEMA_VERSION,
        "recent_memories": [
            {
                "memory_id": item.id,
                "owner_agent_id": item.owner_agent_id,
                "session_id": item.session_id,
                "memory_type": item.memory_type,
                "content": item.content,
                "importance": item.importance,
                "occurred_day": item.occurred_day,
                "occurred_time_minutes": item.occurred_time_minutes,
                "metadata": memory_metadata(item),
            }
            for item in memories
        ],
    }
