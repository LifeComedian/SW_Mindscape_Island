"""Resident conversations with separate generation and commit steps."""

from __future__ import annotations
from agents.output_safety import preserve_stop

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session as DBSession

from agents import AgentRequest, AgentService
from agents.safety import check_user_comment_safety
from models import (
    CharacterState,
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldConversation,
    WorldConversationParticipant,
    WorldConversationTurn,
    WorldEventInstance,
    WorldInteractionPrompt,
    WorldMemory,
    WorldState,
    RelationshipState,
)
from services.world_memory_service import record_memory
from world.registry import get_world_spec
from world.specs import WorldSpec


SOCIAL_POLICY_ID = "bounded-ambient-social"
SOCIAL_POLICY_VERSION = "v2"
SOCIAL_AUDIT_VERSION = "resident-social-audit-v2"
SOCIAL_COOLDOWN_MINUTES = 30
PARTICIPANT_FOCUS_MINUTES = 15
MIN_AMBIENT_TURNS = 2
MAX_AMBIENT_TURNS = 6
MAX_ACTIVE_AMBIENT_CONVERSATIONS = 3
MAX_PUBLIC_LINE_LENGTH = 500
AMBIENT_LINE_KINDS = (
    "greeting",
    "shared_activity",
    "location_comment",
    "follow_up_memory",
    "leave",
)


class ResidentSocialError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class AmbientConversationPlan:
    plan_type: Literal["start", "reply", "end", "noop"]
    session_id: int
    trigger_action_id: int
    world_version: str
    day: int
    minute: int
    location_id: str
    initiator_agent_id: int | None
    speaker_agent_id: int | None
    target_agent_id: int | None
    conversation_id: int | None
    language: str
    reason_code: str
    candidate_pairs: tuple[tuple[int, int, str], ...] = ()
    source_pulse_id: int | None = None
    conversation_goal: str = "ordinary_public_contact"
    line_kind: str = "greeting"
    target_turn_count: int = MIN_AMBIENT_TURNS
    eligible_memory_ids: tuple[int, ...] = ()
    relationship_summary: tuple[tuple[str, int], ...] = ()

    @property
    def idempotency_key(self) -> str:
        return f"ambient:trigger:{self.trigger_action_id}"


@dataclass(frozen=True)
class AmbientLine:
    content: str
    generation_mode: str
    model_provider: str | None
    model_name: str | None
    prompt_version: str
    safety_flag: bool
    latency_ms: int
    metadata: dict[str, Any]


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


def _elapsed_minutes(*, from_day: int, from_minute: int, to_day: int, to_minute: int) -> int:
    return (to_day - from_day) * 1440 + to_minute - from_minute


def _is_resident_available(row: CharacterState) -> bool:
    state = _json_loads(row.state_json)
    flags = state.get("flags", {})
    return not (
        isinstance(flags, dict)
        and (
            flags.get("unavailable") is True
            or flags.get("social_available") is False
        )
    )


def _location_is_event_occupied(
    db: DBSession,
    *,
    session_id: int,
    location_id: str,
) -> bool:
    active_scenario = (
        db.query(ScenarioInstance.id)
        .filter(
            ScenarioInstance.session_id == session_id,
            ScenarioInstance.location_id == location_id,
            ScenarioInstance.status == "active",
        )
        .first()
    )
    active_event = (
        db.query(WorldEventInstance.id)
        .filter(
            WorldEventInstance.session_id == session_id,
            WorldEventInstance.location_id == location_id,
            WorldEventInstance.status == "active",
        )
        .first()
    )
    return active_scenario is not None or active_event is not None


def _conversation_members(
    db: DBSession,
    conversation: WorldConversation,
) -> tuple[int, ...]:
    rows = (
        db.query(WorldConversationParticipant.agent_id)
        .filter(
            WorldConversationParticipant.conversation_id == conversation.id,
            WorldConversationParticipant.session_id == conversation.session_id,
            WorldConversationParticipant.member_type == "resident",
            WorldConversationParticipant.agent_id.is_not(None),
            WorldConversationParticipant.left_at.is_(None),
        )
        .order_by(WorldConversationParticipant.agent_id.asc())
        .all()
    )
    if rows:
        return tuple(int(row[0]) for row in rows)
    # Compatibility for an early additive row without participant records.
    values = [conversation.initiator_agent_id, conversation.agent_id]
    return tuple(sorted({int(value) for value in values if value is not None}))


def _active_participant_conversation_agent_ids(
    db: DBSession,
    session_id: int,
) -> set[int]:
    rows = (
        db.query(WorldConversation.agent_id)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .all()
    )
    return {int(row[0]) for row in rows}


def _recently_approached_agent_ids(
    db: DBSession,
    *,
    session_id: int,
    day: int,
    minute: int,
) -> set[int]:
    rows = (
        db.query(
            WorldAction.target_agent_id,
            WorldAction.world_day,
            WorldAction.world_time_minutes,
        )
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.action_type == "approach",
            WorldAction.target_agent_id.is_not(None),
        )
        .order_by(WorldAction.id.desc())
        .limit(20)
        .all()
    )
    return {
        int(target_agent_id)
        for target_agent_id, action_day, action_minute in rows
        if 0
        <= _elapsed_minutes(
            from_day=int(action_day),
            from_minute=int(action_minute),
            to_day=day,
            to_minute=minute,
        )
        <= PARTICIPANT_FOCUS_MINUTES
    }


def _within_cooldown(
    db: DBSession,
    *,
    session_id: int,
    agent_id: int,
    day: int,
    minute: int,
) -> bool:
    recent = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.conversation_kind == "resident_resident",
            (
                (WorldConversation.initiator_agent_id == agent_id)
                | (WorldConversation.agent_id == agent_id)
            ),
        )
        .order_by(WorldConversation.id.desc())
        .first()
    )
    if recent is None:
        return False
    metadata = _json_loads(recent.metadata_json)
    started_day = int(metadata.get("started_day", day))
    started_minute = int(metadata.get("started_time_minutes", minute))
    elapsed = _elapsed_minutes(
        from_day=started_day,
        from_minute=started_minute,
        to_day=day,
        to_minute=minute,
    )
    return 0 <= elapsed < SOCIAL_COOLDOWN_MINUTES


def _stable_choice_index(
    *,
    simulation_seed: int,
    world_version: str,
    day: int,
    minute: int,
    values: tuple[Any, ...],
) -> int:
    raw = f"{simulation_seed}:{world_version}:{day}:{minute}:{values!r}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _source_pulse_id(action: WorldAction) -> int | None:
    metadata = _json_loads(action.metadata_json)
    autonomy = metadata.get("resident_autonomy", {})
    if not isinstance(autonomy, dict):
        return None
    value = autonomy.get("source_pulse_id")
    return int(value) if isinstance(value, int) and value > 0 else None


def _active_ambient_member_ids(db: DBSession, session_id: int) -> set[int]:
    rows = (
        db.query(WorldConversationParticipant.agent_id)
        .join(
            WorldConversation,
            WorldConversation.id == WorldConversationParticipant.conversation_id,
        )
        .filter(
            WorldConversationParticipant.session_id == session_id,
            WorldConversationParticipant.member_type == "resident",
            WorldConversationParticipant.agent_id.is_not(None),
            WorldConversationParticipant.left_at.is_(None),
            WorldConversation.conversation_kind == "resident_resident",
            WorldConversation.status == "active",
        )
        .all()
    )
    return {int(row[0]) for row in rows}


def _qualified_public_memory_ids(
    db: DBSession,
    *,
    session_id: int,
    speaker_agent_id: int,
    target_agent_id: int,
    location_id: str,
) -> tuple[int, ...]:
    """Return IDs only for ordinary resident/public memories, never participant text."""

    memories = (
        db.query(WorldMemory)
        .filter(
            WorldMemory.session_id == session_id,
            WorldMemory.owner_agent_id == speaker_agent_id,
            WorldMemory.privacy_category == "ordinary",
        )
        .order_by(WorldMemory.id.desc())
        .limit(8)
        .all()
    )
    eligible: list[int] = []
    for memory in memories:
        metadata = _json_loads(memory.metadata_json)
        if metadata.get("source_event_type") not in {
            "resident_conversation",
            "resident_inspect_object",
        }:
            continue
        if metadata.get("location_id") != location_id:
            continue
        raw_related = metadata.get("related_agent_ids", [])
        related = {
            int(value)
            for value in raw_related
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
        }
        if related and target_agent_id not in related:
            continue
        eligible.append(memory.id)
    return tuple(eligible[:3])


def _public_relationship_summary(
    db: DBSession,
    *,
    session_id: int,
    speaker_agent_id: int,
    target_agent_id: int,
) -> tuple[tuple[str, int], ...]:
    relationship = (
        db.query(RelationshipState)
        .filter(
            RelationshipState.session_id == session_id,
            RelationshipState.source_agent_id == speaker_agent_id,
            RelationshipState.target_key == f"resident:{target_agent_id}",
        )
        .first()
    )
    if relationship is None:
        return ()
    return (
        ("familiarity", relationship.familiarity),
        ("trust", relationship.trust),
        ("warmth", relationship.warmth),
        ("tension", relationship.tension),
    )


def _target_turn_count(
    *,
    simulation_seed: int,
    world_version: str,
    day: int,
    minute: int,
    first_id: int,
    second_id: int,
    location_id: str,
) -> int:
    span = MAX_AMBIENT_TURNS - MIN_AMBIENT_TURNS + 1
    return MIN_AMBIENT_TURNS + (
        _stable_choice_index(
            simulation_seed=simulation_seed,
            world_version=world_version,
            day=day,
            minute=minute,
            values=("target_turn_count", first_id, second_id, location_id),
        )
        % span
    )


def _line_kind(
    *,
    plan_type: str,
    turn_count: int,
    target_turn_count: int,
    eligible_memory_ids: tuple[int, ...],
    simulation_seed: int,
    world_version: str,
    day: int,
    minute: int,
    speaker_agent_id: int,
    target_agent_id: int,
) -> str:
    if turn_count + 1 >= target_turn_count:
        return "leave"
    if plan_type == "start":
        choices = ("greeting", "shared_activity", "location_comment")
    else:
        choices = (
            ("follow_up_memory", "shared_activity", "location_comment")
            if eligible_memory_ids
            else ("shared_activity", "location_comment")
        )
    return choices[
        _stable_choice_index(
            simulation_seed=simulation_seed,
            world_version=world_version,
            day=day,
            minute=minute,
            values=("line_kind", turn_count, speaker_agent_id, target_agent_id),
        )
        % len(choices)
    ]


def _noop_plan(
    *,
    session_id: int,
    trigger_action_id: int,
    world: WorldState,
    language: str,
    reason_code: str,
    candidate_pairs: tuple[tuple[int, int, str], ...] = (),
) -> AmbientConversationPlan:
    return AmbientConversationPlan(
        plan_type="noop",
        session_id=session_id,
        trigger_action_id=trigger_action_id,
        world_version=world.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        location_id=world.participant_location_id,
        initiator_agent_id=None,
        speaker_agent_id=None,
        target_agent_id=None,
        conversation_id=None,
        language=language,
        reason_code=reason_code,
        candidate_pairs=candidate_pairs,
    )


def prepare_resident_social_tick(
    db: DBSession,
    *,
    session_id: int,
    trigger_action_id: int,
    language: str,
) -> AmbientConversationPlan | None:
    """Prepare one deterministic, bounded plan without changing the database."""

    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
    trigger = (
        db.query(WorldAction)
        .filter(
            WorldAction.id == trigger_action_id,
            WorldAction.session_id == session_id,
        )
        .first()
    )
    if session is None or world is None or trigger is None:
        raise ResidentSocialError("The social tick source is not in this session.", 404)
    spec = get_world_spec(world.world_version)
    if spec.map_spec is None or session.status != "active":
        return None
    if (
        db.query(WorldAction.id)
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.idempotency_key == f"ambient:trigger:{trigger_action_id}",
        )
        .first()
        is not None
    ):
        return None

    source_pulse_id = _source_pulse_id(trigger)
    active_ambient = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.conversation_kind == "resident_resident",
            WorldConversation.status == "active",
        )
        .order_by(WorldConversation.location_id.asc(), WorldConversation.id.asc())
        .all()
    )
    participant_busy_ids = _active_participant_conversation_agent_ids(db, session_id)
    participant_busy_ids.update(
        int(row[0])
        for row in db.query(WorldInteractionPrompt.initiator_agent_id)
        .filter(
            WorldInteractionPrompt.session_id == session_id,
            WorldInteractionPrompt.status == "pending",
        )
        .all()
    )
    participant_busy_ids.update(
        _recently_approached_agent_ids(
            db,
            session_id=session_id,
            day=world.current_day,
            minute=world.current_time_minutes,
        )
    )

    def plan_for_conversation(conversation: WorldConversation) -> AmbientConversationPlan:
        member_ids = _conversation_members(db, conversation)
        rows = (
            db.query(CharacterState)
            .filter(
                CharacterState.session_id == session_id,
                CharacterState.agent_id.in_(member_ids),
            )
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
        invalid_reason = None
        if len(member_ids) != 2 or len(rows) != 2:
            invalid_reason = "member_unavailable"
        elif any(row.current_location_id != conversation.location_id for row in rows):
            invalid_reason = "resident_relocated"
        elif any(not _is_resident_available(row) for row in rows):
            invalid_reason = "member_unavailable"
        elif participant_busy_ids.intersection(member_ids):
            invalid_reason = "participant_focus"
        elif _location_is_event_occupied(
            db, session_id=session_id, location_id=conversation.location_id
        ):
            invalid_reason = "event_priority"
        if invalid_reason is not None:
            return AmbientConversationPlan(
                plan_type="end",
                session_id=session_id,
                trigger_action_id=trigger_action_id,
                world_version=world.world_version,
                day=world.current_day,
                minute=world.current_time_minutes,
                location_id=conversation.location_id,
                initiator_agent_id=conversation.initiator_agent_id,
                speaker_agent_id=None,
                target_agent_id=conversation.agent_id,
                conversation_id=conversation.id,
                language=language,
                reason_code=invalid_reason,
                source_pulse_id=source_pulse_id,
            )
        metadata = _json_loads(conversation.metadata_json)
        turn_count = int(metadata.get("turn_count", 0))
        target_turn_count = int(
            metadata.get(
                "target_turn_count",
                _target_turn_count(
                    simulation_seed=session.simulation_seed,
                    world_version=world.world_version,
                    day=int(metadata.get("started_day", world.current_day)),
                    minute=int(
                        metadata.get("started_time_minutes", world.current_time_minutes)
                    ),
                    first_id=member_ids[0],
                    second_id=member_ids[1],
                    location_id=conversation.location_id,
                ),
            )
        )
        target_turn_count = max(
            MIN_AMBIENT_TURNS, min(MAX_AMBIENT_TURNS, target_turn_count)
        )
        if turn_count >= target_turn_count:
            return AmbientConversationPlan(
                plan_type="end",
                session_id=session_id,
                trigger_action_id=trigger_action_id,
                world_version=world.world_version,
                day=world.current_day,
                minute=world.current_time_minutes,
                location_id=conversation.location_id,
                initiator_agent_id=conversation.initiator_agent_id,
                speaker_agent_id=None,
                target_agent_id=conversation.agent_id,
                conversation_id=conversation.id,
                language=language,
                reason_code="goal_completed",
                source_pulse_id=source_pulse_id,
                target_turn_count=target_turn_count,
            )
        last_turn = (
            db.query(WorldConversationTurn)
            .filter(WorldConversationTurn.conversation_id == conversation.id)
            .order_by(WorldConversationTurn.id.desc())
            .first()
        )
        last_speaker = last_turn.speaker_id if last_turn is not None else None
        speaker_id = next(
            (agent_id for agent_id in member_ids if agent_id != last_speaker),
            member_ids[0],
        )
        target_id = next(agent_id for agent_id in member_ids if agent_id != speaker_id)
        memory_ids = _qualified_public_memory_ids(
            db,
            session_id=session_id,
            speaker_agent_id=speaker_id,
            target_agent_id=target_id,
            location_id=conversation.location_id,
        )
        return AmbientConversationPlan(
            plan_type="reply",
            session_id=session_id,
            trigger_action_id=trigger_action_id,
            world_version=world.world_version,
            day=world.current_day,
            minute=world.current_time_minutes,
            location_id=conversation.location_id,
            initiator_agent_id=conversation.initiator_agent_id,
            speaker_agent_id=speaker_id,
            target_agent_id=target_id,
            conversation_id=conversation.id,
            language=language,
            reason_code="public_reply_due",
            source_pulse_id=source_pulse_id,
            conversation_goal=str(
                metadata.get("conversation_goal", "ordinary_public_contact")
            ),
            line_kind=_line_kind(
                plan_type="reply",
                turn_count=turn_count,
                target_turn_count=target_turn_count,
                eligible_memory_ids=memory_ids,
                simulation_seed=session.simulation_seed,
                world_version=world.world_version,
                day=world.current_day,
                minute=world.current_time_minutes,
                speaker_agent_id=speaker_id,
                target_agent_id=target_id,
            ),
            target_turn_count=target_turn_count,
            eligible_memory_ids=memory_ids,
            relationship_summary=_public_relationship_summary(
                db,
                session_id=session_id,
                speaker_agent_id=speaker_id,
                target_agent_id=target_id,
            ),
        )

    # Invalid conversations end before any new one is admitted.
    for conversation in active_ambient:
        candidate = plan_for_conversation(conversation)
        if candidate.plan_type == "end" and candidate.reason_code != "goal_completed":
            return candidate

    active_members = _active_ambient_member_ids(db, session_id)
    active_by_location = {item.location_id: item for item in active_ambient}
    exact_social_intent = (
        trigger.action_type == "resident_socialize_intent"
        and trigger.actor_agent_id is not None
        and trigger.target_agent_id is not None
    )
    if exact_social_intent:
        initiator_id = int(trigger.actor_agent_id)
        target_id = int(trigger.target_agent_id)
        rows = (
            db.query(CharacterState)
            .filter(
                CharacterState.session_id == session_id,
                CharacterState.agent_id.in_((initiator_id, target_id)),
            )
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
        location_id = trigger.target_location_id or (
            rows[0].current_location_id if rows else world.participant_location_id
        )
        existing_at_location = active_by_location.get(location_id)
        if existing_at_location is not None:
            members = set(_conversation_members(db, existing_at_location))
            if members == {initiator_id, target_id}:
                metadata = _json_loads(existing_at_location.metadata_json)
                if source_pulse_id is None or metadata.get("last_source_pulse_id") != source_pulse_id:
                    return plan_for_conversation(existing_at_location)
            return _noop_plan(
                session_id=session_id,
                trigger_action_id=trigger_action_id,
                world=world,
                language=language,
                reason_code="location_conversation_limit",
            )
        valid_rows = (
            len(rows) == 2
            and all(row.current_location_id == location_id for row in rows)
            and all(_is_resident_available(row) for row in rows)
            and not {initiator_id, target_id}.intersection(
                participant_busy_ids | active_members
            )
            and not _location_is_event_occupied(
                db, session_id=session_id, location_id=location_id
            )
            and not _within_cooldown(
                db,
                session_id=session_id,
                agent_id=initiator_id,
                day=world.current_day,
                minute=world.current_time_minutes,
            )
        )
        if valid_rows and len(active_ambient) < MAX_ACTIVE_AMBIENT_CONVERSATIONS:
            target_turn_count = _target_turn_count(
                simulation_seed=session.simulation_seed,
                world_version=world.world_version,
                day=world.current_day,
                minute=world.current_time_minutes,
                first_id=initiator_id,
                second_id=target_id,
                location_id=location_id,
            )
            return AmbientConversationPlan(
                plan_type="start",
                session_id=session_id,
                trigger_action_id=trigger_action_id,
                world_version=world.world_version,
                day=world.current_day,
                minute=world.current_time_minutes,
                location_id=location_id,
                initiator_agent_id=initiator_id,
                speaker_agent_id=initiator_id,
                target_agent_id=target_id,
                conversation_id=None,
                language=language,
                reason_code="autonomy_social_intent",
                candidate_pairs=((initiator_id, target_id, location_id),),
                source_pulse_id=source_pulse_id,
                line_kind=_line_kind(
                    plan_type="start",
                    turn_count=0,
                    target_turn_count=target_turn_count,
                    eligible_memory_ids=(),
                    simulation_seed=session.simulation_seed,
                    world_version=world.world_version,
                    day=world.current_day,
                    minute=world.current_time_minutes,
                    speaker_agent_id=initiator_id,
                    target_agent_id=target_id,
                ),
                target_turn_count=target_turn_count,
                relationship_summary=_public_relationship_summary(
                    db,
                    session_id=session_id,
                    speaker_agent_id=initiator_id,
                    target_agent_id=target_id,
                ),
            )

    # Continue a different active conversation at most once for this source pulse.
    available_active = [
        item
        for item in active_ambient
        if source_pulse_id is None
        or _json_loads(item.metadata_json).get("last_source_pulse_id") != source_pulse_id
    ]
    if available_active:
        index = _stable_choice_index(
            simulation_seed=session.simulation_seed,
            world_version=world.world_version,
            day=world.current_day,
            minute=world.current_time_minutes,
            values=("active_conversation", trigger_action_id, tuple(item.id for item in available_active)),
        ) % len(available_active)
        return plan_for_conversation(available_active[index])

    # Pulse-driven starts require an explicit committed socialize intent.
    if source_pulse_id is not None:
        return _noop_plan(
            session_id=session_id,
            trigger_action_id=trigger_action_id,
            world=world,
            language=language,
            reason_code=(
                "global_conversation_limit"
                if len(active_ambient) >= MAX_ACTIVE_AMBIENT_CONVERSATIONS
                else "no_explicit_social_intent"
            ),
        )

    busy_ids = participant_busy_ids | active_members
    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == session_id)
        .order_by(CharacterState.current_location_id.asc(), CharacterState.agent_id.asc())
        .all()
    )
    eligible_by_location: dict[str, list[int]] = {}
    for resident in residents:
        if resident.agent_id not in spec.residents:
            continue
        if resident.agent_id in busy_ids or not _is_resident_available(resident):
            continue
        if _within_cooldown(
            db,
            session_id=session_id,
            agent_id=resident.agent_id,
            day=world.current_day,
            minute=world.current_time_minutes,
        ):
            continue
        eligible_by_location.setdefault(resident.current_location_id, []).append(
            resident.agent_id
        )
    pairs: list[tuple[int, int, str]] = []
    for location_id, agent_ids in sorted(eligible_by_location.items()):
        if (
            location_id in active_by_location
            or len(agent_ids) < 2
            or _location_is_event_occupied(
                db, session_id=session_id, location_id=location_id
            )
        ):
            continue
        for index, first_id in enumerate(agent_ids):
            for second_id in agent_ids[index + 1 :]:
                pairs.append((first_id, second_id, location_id))
    candidate_pairs = tuple(pairs)
    if not candidate_pairs or len(active_ambient) >= MAX_ACTIVE_AMBIENT_CONVERSATIONS:
        return _noop_plan(
            session_id=session_id,
            trigger_action_id=trigger_action_id,
            world=world,
            language=language,
            reason_code=(
                "global_conversation_limit"
                if len(active_ambient) >= MAX_ACTIVE_AMBIENT_CONVERSATIONS
                else "no_eligible_pair"
            ),
        )
    pair_index = _stable_choice_index(
        simulation_seed=session.simulation_seed,
        world_version=world.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        values=candidate_pairs,
    ) % len(candidate_pairs)
    first_id, second_id, location_id = candidate_pairs[pair_index]
    direction_index = _stable_choice_index(
        simulation_seed=session.simulation_seed,
        world_version=world.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        values=("direction", first_id, second_id, location_id),
    ) % 2
    initiator_id, target_id = (
        (first_id, second_id) if direction_index == 0 else (second_id, first_id)
    )
    # Preserve the pre-M3-C participant-action compatibility tick at two turns;
    # pulse-owned conversations use the bounded deterministic 2..6 target above.
    target_turn_count = MIN_AMBIENT_TURNS
    return AmbientConversationPlan(
        plan_type="start",
        session_id=session_id,
        trigger_action_id=trigger_action_id,
        world_version=world.world_version,
        day=world.current_day,
        minute=world.current_time_minutes,
        location_id=location_id,
        initiator_agent_id=initiator_id,
        speaker_agent_id=initiator_id,
        target_agent_id=target_id,
        conversation_id=None,
        language=language,
        reason_code="deterministic_same_location_pair",
        candidate_pairs=candidate_pairs,
        target_turn_count=target_turn_count,
        line_kind=_line_kind(
            plan_type="start",
            turn_count=0,
            target_turn_count=target_turn_count,
            eligible_memory_ids=(),
            simulation_seed=session.simulation_seed,
            world_version=world.world_version,
            day=world.current_day,
            minute=world.current_time_minutes,
            speaker_agent_id=initiator_id,
            target_agent_id=target_id,
        ),
        relationship_summary=_public_relationship_summary(
            db,
            session_id=session_id,
            speaker_agent_id=initiator_id,
            target_agent_id=target_id,
        ),
    )


def _rule_line(plan: AmbientConversationPlan, spec: WorldSpec) -> str:
    target = spec.residents[int(plan.target_agent_id)]
    location = spec.locations[plan.location_id]
    location_name = location.name.get(plan.language, location.name["en"])
    templates_by_kind = (
        {
            "greeting": (
                f"{target.name}，在{location_name}见到你真好。今天过得怎么样？",
                f"嗨，{target.name}。我们正好都在{location_name}，要聊两句吗？",
            ),
            "shared_activity": (
                f"{target.name}，忙完手上的事以后，一起在这里歇一会儿怎么样？",
                "今天的日常安排还算顺利，能碰面聊两句也挺好。",
            ),
            "location_comment": (
                f"{location_name}今天很安静，待在这里让人觉得节奏慢了下来。",
                f"这里的气氛和往常有点不一样，你也注意到了吗，{target.name}？",
            ),
            "follow_up_memory": (
                f"{target.name}，我还记得我们上次在这里聊过的日常小事。后来还顺利吗？",
                "上次那段公开的闲聊我还记得，很高兴今天又碰到你。",
            ),
            "leave": (
                f"那我先继续今天的安排了，{target.name}。晚些时候见。",
                "聊得很开心，我该接着忙了。回头见。",
            ),
        }
        if plan.language == "zh-CN"
        else {
            "greeting": (
                f"Good to see you at {location_name}, {target.name}. How is your day going?",
                f"Hi, {target.name}. Since we're both at {location_name}, want to talk for a moment?",
            ),
            "shared_activity": (
                f"Once we're done with our tasks, {target.name}, perhaps we could take a short break here.",
                "The usual routine is going smoothly today. It is nice to pause and talk.",
            ),
            "location_comment": (
                f"{location_name} feels calm today. It makes the pace of everything seem slower.",
                f"The atmosphere here feels a little different today. Did you notice it too, {target.name}?",
            ),
            "follow_up_memory": (
                f"{target.name}, I remember our last public chat here. Did the rest of your day go well?",
                "I remember our last ordinary conversation. It is good to run into you again.",
            ),
            "leave": (
                f"I should get back to today's plans, {target.name}. See you later.",
                "It was good talking. I should keep moving, but I will see you around.",
            ),
        }
    )
    templates = templates_by_kind.get(plan.line_kind, templates_by_kind["greeting"])
    index = _stable_choice_index(
        simulation_seed=0,
        world_version=plan.world_version,
        day=plan.day,
        minute=plan.minute,
        values=(
            plan.plan_type,
            plan.line_kind,
            plan.speaker_agent_id,
            plan.target_agent_id,
            plan.conversation_id,
        ),
    ) % len(templates)
    return templates[index]


def _ambient_agent_request(
    plan: AmbientConversationPlan,
    spec: WorldSpec,
    fallback: str,
) -> AgentRequest:
    speaker = spec.residents[int(plan.speaker_agent_id)]
    target = spec.residents[int(plan.target_agent_id)]
    location = spec.locations[plan.location_id]
    instruction = (
        f"Write one brief, ordinary, public {plan.line_kind} line to {target.name}. "
        "Use one or two sentences. Do not introduce facts beyond the supplied public "
        "location, roles, and generic ordinary-memory signal. Reveal no private information."
    )
    return AgentRequest(
        session_id=plan.session_id,
        agent_id=int(plan.speaker_agent_id),
        post_id=0,
        post_content=(
            f"A public ambient conversation at {location.name['en']}. "
            f"Safe rule fallback: {fallback}"
        ),
        user_comment=instruction,
        language=plan.language,
        recent_history=[],
        agent_memory={
            "eligible_ordinary_memory_ids": list(plan.eligible_memory_ids),
            "relationship_summary": dict(plan.relationship_summary),
        },
        target_context=plan.conversation_goal,
        reply_target_author=target.name,
        post_author=speaker.name,
        post_intent=f"brief public resident-to-resident {plan.line_kind}",
        reply_relation="two residents speaking publicly in the same location",
        thread_history=[],
        interaction_kind="resident_ambient_conversation",
        persona_role_context=spec.residents[int(plan.speaker_agent_id)].role.get(
            plan.language,
            spec.residents[int(plan.speaker_agent_id)].role["en"],
        ),
        persona_background_context="Public role context only; no participant text or private memory.",
    )


async def generate_ambient_line(
    plan: AmbientConversationPlan,
    *,
    agent_service: AgentService,
) -> AmbientLine | None:
    if plan.plan_type not in {"start", "reply"}:
        return None
    spec = get_world_spec(plan.world_version)
    fallback = _rule_line(plan, spec)
    mode = agent_service.settings.agent_mode
    should_try_llm = mode == "llm" or (
        mode == "auto" and agent_service.settings.has_llm_config
    )
    if not should_try_llm:
        return AmbientLine(
            content=fallback,
            generation_mode="rule",
            model_provider=None,
            model_name=None,
            prompt_version="resident-ambient-rule-v1",
            safety_flag=False,
            latency_ms=0,
            metadata={"language": plan.language, "interaction_kind": "resident_ambient_conversation"},
        )

    try:
        result = await agent_service.llm_agent.generate_reply(
            _ambient_agent_request(plan, spec, fallback)
        )
        content = result.reply_content.strip()
        output_safety = check_user_comment_safety(content, plan.language)
        if (
            not content
            or len(content) > MAX_PUBLIC_LINE_LENGTH
            or result.safety_flag
            or output_safety.safety_flag
            or "<script" in content.lower()
        ):
            raise ValueError("provider returned an invalid public ambient line")
        return AmbientLine(
            content=content,
            generation_mode="llm",
            model_provider=result.model_provider,
            model_name=result.model_name,
            prompt_version=result.prompt_version,
            safety_flag=False,
            latency_ms=result.latency_ms,
            metadata={**result.metadata, "interaction_kind": "resident_ambient_conversation"},
        )
    except Exception as exc:
        preserve_stop(exc)
        return AmbientLine(
            content=fallback,
            generation_mode="rule_fallback",
            model_provider=None,
            model_name=None,
            prompt_version="resident-ambient-rule-v1",
            safety_flag=False,
            latency_ms=0,
            metadata={
                "language": plan.language,
                "interaction_kind": "resident_ambient_conversation",
                "fallback_reason": type(exc).__name__,
            },
        )


def _social_audit(plan: AmbientConversationPlan) -> dict[str, Any]:
    return {
        "schema_version": SOCIAL_AUDIT_VERSION,
        "trigger_action_id": plan.trigger_action_id,
        "plan_type": plan.plan_type,
        "reason_code": plan.reason_code,
        "candidate_pairs": [
            {"first_agent_id": first, "second_agent_id": second, "location_id": location}
            for first, second, location in plan.candidate_pairs
        ],
        "selected": {
            "conversation_id": plan.conversation_id,
            "initiator_agent_id": plan.initiator_agent_id,
            "speaker_agent_id": plan.speaker_agent_id,
            "target_agent_id": plan.target_agent_id,
            "location_id": plan.location_id,
        },
        "source_pulse_id": plan.source_pulse_id,
        "conversation_goal": plan.conversation_goal,
        "line_kind": plan.line_kind,
        "target_turn_count": plan.target_turn_count,
        "eligible_ordinary_memory_ids": list(plan.eligible_memory_ids),
        "relationship_summary": dict(plan.relationship_summary),
        "world_version": plan.world_version,
        "day": plan.day,
        "time_minutes": plan.minute,
        "visibility": "public",
        "max_turns": MAX_AMBIENT_TURNS,
        "min_turns": MIN_AMBIENT_TURNS,
        "max_active_conversations": MAX_ACTIVE_AMBIENT_CONVERSATIONS,
        "cooldown_minutes": SOCIAL_COOLDOWN_MINUTES,
    }


def _new_social_action(
    plan: AmbientConversationPlan,
    *,
    action_type: str,
    actor_type: str,
    actor_agent_id: int | None,
    target_agent_id: int | None,
    response_text: str = "",
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> WorldAction:
    return WorldAction(
        session_id=plan.session_id,
        idempotency_key=idempotency_key or plan.idempotency_key,
        actor_type=actor_type,
        actor_agent_id=actor_agent_id,
        policy_id=SOCIAL_POLICY_ID,
        policy_version=SOCIAL_POLICY_VERSION,
        decision_reason_code=plan.reason_code,
        action_type=action_type,
        target_location_id=plan.location_id,
        target_agent_id=target_agent_id,
        response_text=response_text,
        language=plan.language,
        world_day=plan.day,
        world_time_minutes=plan.minute,
        metadata_json=_json_dumps(metadata or {"resident_social": _social_audit(plan)}),
    )


def _close_conversation(
    db: DBSession,
    conversation: WorldConversation,
    *,
    reason_code: str,
) -> None:
    now = utc_now()
    conversation.status = "ended"
    conversation.ended_reason_code = reason_code
    conversation.updated_at = now
    for participant in conversation.participants:
        if participant.left_at is None:
            participant.left_at = now
            participant.leave_reason_code = reason_code


def _validate_plan_world(
    db: DBSession,
    plan: AmbientConversationPlan,
) -> tuple[UserSession, WorldState, WorldSpec] | None:
    session = db.query(UserSession).filter(UserSession.id == plan.session_id).first()
    world = db.query(WorldState).filter(WorldState.session_id == plan.session_id).first()
    if session is None or world is None or session.status != "active":
        return None
    if (
        world.world_version != plan.world_version
        or world.current_day != plan.day
        or world.current_time_minutes != plan.minute
    ):
        return None
    return session, world, get_world_spec(world.world_version)


def _turn_metadata(
    *,
    plan: AmbientConversationPlan,
    line: AmbientLine,
    spec: WorldSpec,
) -> dict[str, Any]:
    speaker_profile = spec.residents[int(plan.speaker_agent_id)]
    return {
        "schema_version": "resident-conversation-turn-v2",
        "visibility": "public",
        "language": plan.language,
        "listener_agent_id": plan.target_agent_id,
        "conversation_goal": plan.conversation_goal,
        "line_kind": plan.line_kind,
        "generation_mode": line.generation_mode,
        "prompt_version": line.prompt_version,
        "profile_version": speaker_profile.profile_version,
        "policy_id": SOCIAL_POLICY_ID,
        "policy_version": SOCIAL_POLICY_VERSION,
        "source_pulse_id": plan.source_pulse_id,
        "source_action_id": plan.trigger_action_id,
        "eligible_ordinary_memory_ids": list(plan.eligible_memory_ids),
        "relationship_summary": dict(plan.relationship_summary),
        "safety_result": "passed" if not line.safety_flag else "flagged",
        "generation": line.metadata,
    }


def persist_resident_social_plan(
    db: DBSession,
    *,
    plan: AmbientConversationPlan,
    line: AmbientLine | None,
) -> WorldAction | None:
    existing = (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == plan.session_id,
            WorldAction.idempotency_key == plan.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        return existing
    validated = _validate_plan_world(db, plan)
    if validated is None:
        return None
    _session, world, spec = validated

    if plan.plan_type == "noop":
        action = _new_social_action(
            plan,
            action_type="resident_social_noop",
            actor_type="system",
            actor_agent_id=None,
            target_agent_id=None,
        )
        db.add(action)
        db.flush()
        return action

    if plan.plan_type == "start":
        if line is None or plan.speaker_agent_id is None or plan.target_agent_id is None:
            raise ResidentSocialError("A social start requires a validated public line.")
        rows = (
            db.query(CharacterState)
            .filter(
                CharacterState.session_id == plan.session_id,
                CharacterState.agent_id.in_((plan.speaker_agent_id, plan.target_agent_id)),
            )
            .order_by(CharacterState.agent_id.asc())
            .all()
        )
        busy_ids = _active_participant_conversation_agent_ids(db, plan.session_id)
        active_ambient_count = (
            db.query(WorldConversation.id)
            .filter(
                WorldConversation.session_id == plan.session_id,
                WorldConversation.conversation_kind == "resident_resident",
                WorldConversation.status == "active",
            )
            .count()
        )
        active_at_location = (
            db.query(WorldConversation.id)
            .filter(
                WorldConversation.session_id == plan.session_id,
                WorldConversation.conversation_kind == "resident_resident",
                WorldConversation.status == "active",
                WorldConversation.location_id == plan.location_id,
            )
            .first()
            is not None
        )
        active_member_ids = _active_ambient_member_ids(db, plan.session_id)
        if (
            len(rows) != 2
            or any(row.current_location_id != plan.location_id for row in rows)
            or any(not _is_resident_available(row) for row in rows)
            or plan.speaker_agent_id in busy_ids
            or plan.target_agent_id in busy_ids
            or active_ambient_count >= MAX_ACTIVE_AMBIENT_CONVERSATIONS
            or active_at_location
            or plan.speaker_agent_id in active_member_ids
            or plan.target_agent_id in active_member_ids
            or _location_is_event_occupied(
                db, session_id=plan.session_id, location_id=plan.location_id
            )
        ):
            stale = _new_social_action(
                plan,
                action_type="resident_social_noop",
                actor_type="system",
                actor_agent_id=None,
                target_agent_id=None,
                metadata={
                    "resident_social": {
                        **_social_audit(plan),
                        "reason_code": "state_changed_before_persist",
                    }
                },
            )
            db.add(stale)
            db.flush()
            return stale
        conversation = WorldConversation(
            session_id=plan.session_id,
            agent_id=plan.target_agent_id,
            location_id=plan.location_id,
            status="active",
            conversation_kind="resident_resident",
            initiator_type="resident",
            initiator_agent_id=plan.speaker_agent_id,
            visibility="public",
            metadata_json=_json_dumps(
                {
                    "schema_version": "resident-conversation-v1",
                    "started_day": plan.day,
                    "started_time_minutes": plan.minute,
                    "turn_count": 1,
                    "target_turn_count": plan.target_turn_count,
                    "conversation_goal": plan.conversation_goal,
                    "last_source_pulse_id": plan.source_pulse_id,
                    "last_source_action_id": plan.trigger_action_id,
                    "trigger_action_id": plan.trigger_action_id,
                }
            ),
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=plan.session_id,
                    member_type="resident",
                    agent_id=plan.speaker_agent_id,
                    member_role="initiator",
                ),
                WorldConversationParticipant(
                    conversation_id=conversation.id,
                    session_id=plan.session_id,
                    member_type="resident",
                    agent_id=plan.target_agent_id,
                    member_role="target",
                ),
            ]
        )
        action = _new_social_action(
            plan,
            action_type="resident_conversation_start",
            actor_type="resident",
            actor_agent_id=plan.speaker_agent_id,
            target_agent_id=plan.target_agent_id,
            response_text=line.content,
            metadata={
                "resident_social": {
                    **_social_audit(plan),
                    "conversation_id": conversation.id,
                },
                "generation": line.metadata,
            },
        )
        db.add(action)
        db.flush()
        db.add(
            WorldConversationTurn(
                conversation_id=conversation.id,
                session_id=plan.session_id,
                source_action_id=action.id,
                speaker_type="resident",
                speaker_id=plan.speaker_agent_id,
                content=line.content,
                world_day=plan.day,
                world_time_minutes=plan.minute,
                response_latency_ms=line.latency_ms,
                generation_mode=line.generation_mode,
                model_provider=line.model_provider,
                model_name=line.model_name,
                prompt_version=line.prompt_version,
                safety_flag=line.safety_flag,
                metadata_json=_json_dumps(
                    _turn_metadata(plan=plan, line=line, spec=spec)
                ),
            )
        )
        record_memory(
            db,
            session_id=plan.session_id,
            owner_agent_id=plan.speaker_agent_id,
            memory_type="episodic",
            source_action_id=action.id,
            source_event_type="resident_conversation",
            source_event_id=conversation.id,
            effect_key="ambient_start",
            content=(
                f"I started a brief public conversation with {spec.residents[plan.target_agent_id].name}."
            ),
            importance=1,
            privacy_category="ordinary",
            occurred_day=plan.day,
            occurred_time_minutes=plan.minute,
            location_id=plan.location_id,
            related_agent_ids=(plan.speaker_agent_id, plan.target_agent_id),
            tags=("resident_dialogue", "public_ambient"),
        )
        return action

    conversation = (
        db.query(WorldConversation)
        .filter(
            WorldConversation.id == plan.conversation_id,
            WorldConversation.session_id == plan.session_id,
            WorldConversation.conversation_kind == "resident_resident",
            WorldConversation.status == "active",
        )
        .first()
    )
    if conversation is None:
        return None
    member_ids = _conversation_members(db, conversation)
    rows = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == plan.session_id,
            CharacterState.agent_id.in_(member_ids),
        )
        .all()
    )
    valid_members = (
        len(member_ids) == 2
        and len(rows) == 2
        and all(row.current_location_id == conversation.location_id for row in rows)
        and all(_is_resident_available(row) for row in rows)
        and not _active_participant_conversation_agent_ids(
            db, plan.session_id
        ).intersection(member_ids)
        and not _recently_approached_agent_ids(
            db,
            session_id=plan.session_id,
            day=plan.day,
            minute=plan.minute,
        ).intersection(member_ids)
        and not _location_is_event_occupied(
            db,
            session_id=plan.session_id,
            location_id=conversation.location_id,
        )
        and (
            plan.source_pulse_id is None
            or _json_loads(conversation.metadata_json).get("last_source_pulse_id")
            != plan.source_pulse_id
        )
    )
    if plan.plan_type == "reply" and valid_members and line is not None:
        action = _new_social_action(
            plan,
            action_type="resident_conversation_reply",
            actor_type="resident",
            actor_agent_id=plan.speaker_agent_id,
            target_agent_id=plan.target_agent_id,
            response_text=line.content,
            metadata={
                "resident_social": _social_audit(plan),
                "generation": line.metadata,
            },
        )
        db.add(action)
        db.flush()
        db.add(
            WorldConversationTurn(
                conversation_id=conversation.id,
                session_id=plan.session_id,
                source_action_id=action.id,
                speaker_type="resident",
                speaker_id=plan.speaker_agent_id,
                content=line.content,
                world_day=plan.day,
                world_time_minutes=plan.minute,
                response_latency_ms=line.latency_ms,
                generation_mode=line.generation_mode,
                model_provider=line.model_provider,
                model_name=line.model_name,
                prompt_version=line.prompt_version,
                safety_flag=line.safety_flag,
                metadata_json=_json_dumps(
                    _turn_metadata(plan=plan, line=line, spec=spec)
                ),
            )
        )
        metadata = _json_loads(conversation.metadata_json)
        new_turn_count = int(metadata.get("turn_count", 1)) + 1
        metadata["turn_count"] = new_turn_count
        metadata["target_turn_count"] = plan.target_turn_count
        metadata["conversation_goal"] = plan.conversation_goal
        metadata["last_source_pulse_id"] = plan.source_pulse_id
        metadata["last_source_action_id"] = plan.trigger_action_id
        conversation.metadata_json = _json_dumps(metadata)
        conversation.updated_at = utc_now()
        if new_turn_count >= plan.target_turn_count or plan.line_kind == "leave":
            end_reason = (
                "turn_limit_reached"
                if plan.source_pulse_id is None
                else "goal_completed"
            )
            _close_conversation(db, conversation, reason_code=end_reason)
            end_action = _new_social_action(
                plan,
                action_type="resident_conversation_end",
                actor_type="system",
                actor_agent_id=None,
                target_agent_id=None,
                idempotency_key=(
                    f"ambient:end:{conversation.id}:goal:{plan.trigger_action_id}"
                ),
                metadata={
                    "resident_social": {
                        **_social_audit(plan),
                        "reason_code": end_reason,
                    }
                },
            )
            db.add(end_action)
        record_memory(
            db,
            session_id=plan.session_id,
            owner_agent_id=int(plan.speaker_agent_id),
            memory_type="episodic",
            source_action_id=action.id,
            source_event_type="resident_conversation",
            source_event_id=conversation.id,
            effect_key="ambient_reply",
            content=(
                f"I exchanged a brief public reply with {spec.residents[int(plan.target_agent_id)].name}."
            ),
            importance=1,
            privacy_category="ordinary",
            occurred_day=plan.day,
            occurred_time_minutes=plan.minute,
            location_id=plan.location_id,
            related_agent_ids=(int(plan.speaker_agent_id), int(plan.target_agent_id)),
            tags=("resident_dialogue", "public_ambient"),
        )
        return action

    reason = plan.reason_code if plan.plan_type == "end" else "state_changed_before_persist"
    _close_conversation(db, conversation, reason_code=reason)
    action = _new_social_action(
        plan,
        action_type="resident_conversation_end",
        actor_type="system",
        actor_agent_id=None,
        target_agent_id=None,
        metadata={
            "resident_social": {**_social_audit(plan), "reason_code": reason}
        },
    )
    db.add(action)
    db.flush()
    return action


async def process_resident_social_tick(
    db: DBSession,
    *,
    session_id: int,
    trigger_action_id: int,
    language: str,
    agent_service: AgentService,
) -> WorldAction | None:
    """Execute one social tick with provider work outside transactions and locks."""

    from services.interaction_time_service import policy_for
    bound = db.query(WorldState).filter_by(session_id=session_id).first()
    if bound is not None and policy_for(bound):
        db.rollback()
        return None
    plan = prepare_resident_social_tick(
        db,
        session_id=session_id,
        trigger_action_id=trigger_action_id,
        language=language,
    )
    db.rollback()
    if plan is None:
        return None
    line = await generate_ambient_line(plan, agent_service=agent_service)
    if db.in_transaction():
        raise ResidentSocialError("Provider generation opened a database transaction.", 500)

    # Imported lazily to avoid a module cycle at application startup.
    from services.world_service import session_write_lock

    with session_write_lock(session_id):
        db.rollback()
        action = persist_resident_social_plan(db, plan=plan, line=line)
        db.commit()
        if action is not None:
            db.refresh(action)
        return action


def end_ambient_conversations_for_resident(
    db: DBSession,
    *,
    world: WorldState,
    agent_id: int,
    location_id: str,
    reason_code: str,
) -> None:
    """End active public conversations when a resident becomes unavailable."""

    participant_rows = (
        db.query(WorldConversationParticipant)
        .join(
            WorldConversation,
            WorldConversation.id == WorldConversationParticipant.conversation_id,
        )
        .filter(
            WorldConversationParticipant.session_id == world.session_id,
            WorldConversationParticipant.member_type == "resident",
            WorldConversationParticipant.agent_id == agent_id,
            WorldConversationParticipant.left_at.is_(None),
            WorldConversation.conversation_kind == "resident_resident",
            WorldConversation.location_id == location_id,
            WorldConversation.status == "active",
        )
        .all()
    )
    for participant in participant_rows:
        conversation = participant.conversation
        _close_conversation(db, conversation, reason_code=reason_code)
        key = f"ambient:end:{conversation.id}:{reason_code}"
        if (
            db.query(WorldAction.id)
            .filter(
                WorldAction.session_id == world.session_id,
                WorldAction.idempotency_key == key,
            )
            .first()
            is None
        ):
            db.add(
                WorldAction(
                    session_id=world.session_id,
                    idempotency_key=key,
                    actor_type="system",
                    actor_agent_id=None,
                    policy_id=SOCIAL_POLICY_ID,
                    policy_version=SOCIAL_POLICY_VERSION,
                    decision_reason_code=reason_code,
                    action_type="resident_conversation_end",
                    target_location_id=location_id,
                    target_agent_id=agent_id,
                    response_text="",
                    language="en",
                    world_day=world.current_day,
                    world_time_minutes=world.current_time_minutes,
                    metadata_json=_json_dumps(
                        {
                            "resident_social": {
                                "schema_version": SOCIAL_AUDIT_VERSION,
                                "conversation_id": conversation.id,
                                "reason_code": reason_code,
                                "visibility": conversation.visibility,
                            }
                        }
                    ),
                )
            )
