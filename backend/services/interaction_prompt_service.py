"""Resident invitations, expiry, cooldowns, and responses."""

from __future__ import annotations
from agents.output_safety import preserve_stop

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

import schemas
from models import (
    CharacterState,
    ResidentIntentState,
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldConversation,
    WorldConversationParticipant,
    WorldConversationTurn,
    WorldEventInstance,
    WorldInteractionPrompt,
    WorldSimulationPulse,
    WorldState,
)
from world.registry import get_world_spec


PROMPT_POLICY_ID = "resident-participant-invitation"
PROMPT_POLICY_VERSION = "v1"
PROMPT_SCHEMA_VERSION = "world-interaction-prompt-v1"
PROMPT_OPENING_VERSION = "resident-greeting-rule-v1"
PROMPT_EXPIRY_MINUTES = 15
LATER_COOLDOWN_MINUTES = 30
DECLINE_COOLDOWN_MINUTES = 120
EXPIRED_COOLDOWN_MINUTES = 15
ALLOWED_RESPONSES = ("accept", "later", "decline")


class InteractionPromptError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _localized(value: dict[str, str], language: str) -> str:
    return value.get(language) or value.get("en") or next(iter(value.values()), "")


def _absolute_minutes(day: int, minute: int) -> int:
    return (day - 1) * 1440 + minute


def _add_world_minutes(day: int, minute: int, amount: int) -> tuple[int, int]:
    absolute = _absolute_minutes(day, minute) + amount
    return absolute // 1440 + 1, absolute % 1440


def serialize_interaction_prompt(
    prompt: WorldInteractionPrompt,
    *,
    language: str = "en",
) -> dict[str, Any]:
    opening = _json_loads(prompt.opening_text_json, {})
    if not isinstance(opening, dict):
        opening = {}
    return {
        "prompt_id": prompt.id,
        "initiator_agent_id": prompt.initiator_agent_id,
        "location_id": prompt.location_id,
        "prompt_kind": prompt.prompt_kind,
        "status": prompt.status,
        "opening_text": opening,
        "display_opening_text": opening.get(language) or opening.get("en") or "",
        "allowed_responses": _json_loads(prompt.allowed_responses_json, []),
        "created_day": prompt.created_day,
        "created_time_minutes": prompt.created_time_minutes,
        "expiry_day": prompt.expiry_day,
        "expiry_time_minutes": prompt.expiry_time_minutes,
        "resolved_day": prompt.resolved_day,
        "resolved_time_minutes": prompt.resolved_time_minutes,
        "response_code": prompt.response_code,
        "source_intent_id": prompt.source_intent_id,
        "source_pulse_id": prompt.source_pulse_id,
        "source_action_id": prompt.source_action_id,
        "response_action_id": prompt.response_action_id,
        "cooldown_key": prompt.cooldown_key,
        "cooldown_until_day": prompt.cooldown_until_day,
        "cooldown_until_time_minutes": prompt.cooldown_until_time_minutes,
        "reason_code": prompt.reason_code,
        "policy_id": prompt.policy_id,
        "policy_version": prompt.policy_version,
        "metadata": _json_loads(prompt.metadata_json, {}),
        "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
        "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
    }


def _resident_in_active_conversation(
    db: DBSession,
    *,
    session_id: int,
    agent_id: int,
) -> bool:
    direct = (
        db.query(WorldConversation.id)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
            WorldConversation.agent_id == agent_id,
        )
        .first()
    )
    if direct is not None:
        return True
    member = (
        db.query(WorldConversationParticipant.id)
        .join(
            WorldConversation,
            WorldConversation.id == WorldConversationParticipant.conversation_id,
        )
        .filter(
            WorldConversationParticipant.session_id == session_id,
            WorldConversationParticipant.member_type == "resident",
            WorldConversationParticipant.agent_id == agent_id,
            WorldConversationParticipant.left_at.is_(None),
            WorldConversation.status == "active",
        )
        .first()
    )
    return member is not None


def _participant_has_blocking_interaction(
    db: DBSession,
    *,
    session_id: int,
    location_id: str,
) -> bool:
    if (
        db.query(WorldConversation.id)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
            WorldConversation.conversation_kind == "participant_resident",
        )
        .first()
        is not None
    ):
        return True
    if (
        db.query(ScenarioInstance.id)
        .filter(
            ScenarioInstance.session_id == session_id,
            ScenarioInstance.status == "active",
            ScenarioInstance.location_id == location_id,
        )
        .first()
        is not None
    ):
        return True
    return (
        db.query(WorldEventInstance.id)
        .filter(
            WorldEventInstance.session_id == session_id,
            WorldEventInstance.status == "active",
            WorldEventInstance.location_id == location_id,
        )
        .first()
        is not None
    )


def _prompt_invalid_reason(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    prompt: WorldInteractionPrompt,
    check_agent_busy: bool = True,
) -> str | None:
    if session.status != "active":
        return "session_finished"
    now = _absolute_minutes(world.current_day, world.current_time_minutes)
    expiry = _absolute_minutes(prompt.expiry_day, prompt.expiry_time_minutes)
    if now >= expiry:
        return "expired"
    if world.participant_location_id != prompt.location_id:
        return "participant_relocated"
    resident = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == session.id,
            CharacterState.agent_id == prompt.initiator_agent_id,
        )
        .first()
    )
    if resident is None or resident.current_location_id != prompt.location_id:
        return "resident_relocated"
    if _participant_has_blocking_interaction(
        db, session_id=session.id, location_id=prompt.location_id
    ):
        return "participant_busy"
    if check_agent_busy and _resident_in_active_conversation(
        db, session_id=session.id, agent_id=prompt.initiator_agent_id
    ):
        return "resident_busy"
    return None


def _resolve_prompt(
    prompt: WorldInteractionPrompt,
    *,
    world: WorldState,
    status: str,
    reason_code: str,
    response_code: str | None = None,
    cooldown_minutes: int = 0,
) -> None:
    prompt.status = status
    prompt.reason_code = reason_code
    prompt.response_code = response_code
    prompt.resolved_day = world.current_day
    prompt.resolved_time_minutes = world.current_time_minutes
    if cooldown_minutes:
        (
            prompt.cooldown_until_day,
            prompt.cooldown_until_time_minutes,
        ) = _add_world_minutes(
            world.current_day,
            world.current_time_minutes,
            cooldown_minutes,
        )
    prompt.updated_at = utc_now()


def close_invalid_interaction_prompts(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
) -> list[WorldInteractionPrompt]:
    """Resolve pending prompts made stale by time or authoritative world state."""

    closed: list[WorldInteractionPrompt] = []
    prompts = (
        db.query(WorldInteractionPrompt)
        .filter(
            WorldInteractionPrompt.session_id == session.id,
            WorldInteractionPrompt.status == "pending",
        )
        .order_by(WorldInteractionPrompt.id.asc())
        .all()
    )
    for prompt in prompts:
        reason = _prompt_invalid_reason(
            db,
            session=session,
            world=world,
            prompt=prompt,
            check_agent_busy=True,
        )
        if reason is None:
            continue
        _resolve_prompt(
            prompt,
            world=world,
            status="expired" if reason == "expired" else "closed",
            reason_code=reason,
            cooldown_minutes=(EXPIRED_COOLDOWN_MINUTES if reason == "expired" else 0),
        )
        closed.append(prompt)
    return closed


def invalidate_pending_interaction_prompts(
    db: DBSession,
    *,
    world: WorldState,
    reason_code: str,
) -> None:
    for prompt in (
        db.query(WorldInteractionPrompt)
        .filter(
            WorldInteractionPrompt.session_id == world.session_id,
            WorldInteractionPrompt.status == "pending",
        )
        .all()
    ):
        _resolve_prompt(
            prompt,
            world=world,
            status="closed",
            reason_code=reason_code,
        )


def _cooldown_active(
    db: DBSession,
    *,
    session_id: int,
    cooldown_key: str,
    day: int,
    minute: int,
) -> bool:
    prompts = (
        db.query(WorldInteractionPrompt)
        .filter(
            WorldInteractionPrompt.session_id == session_id,
            WorldInteractionPrompt.cooldown_key == cooldown_key,
            WorldInteractionPrompt.cooldown_until_day.is_not(None),
        )
        .order_by(WorldInteractionPrompt.id.desc())
        .limit(10)
        .all()
    )
    now = _absolute_minutes(day, minute)
    return any(
        prompt.cooldown_until_day is not None
        and prompt.cooldown_until_time_minutes is not None
        and now
        < _absolute_minutes(
            prompt.cooldown_until_day,
            prompt.cooldown_until_time_minutes,
        )
        for prompt in prompts
    )


def create_prompt_from_greeting_action(
    db: DBSession,
    *,
    session: UserSession,
    world: WorldState,
    pulse: WorldSimulationPulse,
    action: WorldAction,
    language: str,
) -> WorldInteractionPrompt | None:
    """Create at most one participant-facing prompt from a committed greet intent."""

    if action.action_type != "resident_greet_participant_intent":
        return None
    if action.actor_agent_id is None:
        return None
    key = f"prompt:greet:action:{action.id}"
    existing = (
        db.query(WorldInteractionPrompt)
        .filter(
            WorldInteractionPrompt.session_id == session.id,
            WorldInteractionPrompt.idempotency_key == key,
        )
        .first()
    )
    if existing is not None:
        return existing
    close_invalid_interaction_prompts(db, session=session, world=world)
    if (
        db.query(WorldInteractionPrompt.id)
        .filter(
            WorldInteractionPrompt.session_id == session.id,
            WorldInteractionPrompt.status == "pending",
        )
        .first()
        is not None
    ):
        return None
    agent_id = int(action.actor_agent_id)
    location_id = action.target_location_id or world.participant_location_id
    if location_id != world.participant_location_id:
        return None
    resident = (
        db.query(CharacterState)
        .filter(
            CharacterState.session_id == session.id,
            CharacterState.agent_id == agent_id,
        )
        .first()
    )
    if resident is None or resident.current_location_id != location_id:
        return None
    if _participant_has_blocking_interaction(
        db, session_id=session.id, location_id=location_id
    ) or _resident_in_active_conversation(
        db, session_id=session.id, agent_id=agent_id
    ):
        return None
    cooldown_key = f"participant-contact:resident:{agent_id}"
    if _cooldown_active(
        db,
        session_id=session.id,
        cooldown_key=cooldown_key,
        day=world.current_day,
        minute=world.current_time_minutes,
    ):
        return None
    spec = get_world_spec(world.world_version)
    from services.interaction_time_service import policy_for, conversation_slot
    policy = policy_for(world)
    if policy:
        previous = db.query(WorldInteractionPrompt).filter_by(session_id=session.id).all()
        from services.contact_budget_service import daily_contacts, pending_fixed_recipes
        reserved = len(pending_fixed_recipes(db, world, spec))
        if daily_contacts(db, world) >= max(0, policy.max_contacts_per_day - reserved):
            return None
        now = _absolute_minutes(world.current_day, world.current_time_minutes)
        if any(p.initiator_agent_id == agent_id and now - _absolute_minutes(p.created_day, p.created_time_minutes) < policy.contact_cooldown_minutes for p in previous):
            return None
        try:
            conversation_slot(db, world, spec, agent_id, policy.conversation_minutes)
        except Exception as exc:
            preserve_stop(exc)
            from services.world_service import WorldStateError
            if not isinstance(exc, WorldStateError):
                raise
            return None
    resident_spec = spec.residents.get(agent_id)
    location = spec.locations.get(location_id)
    if resident_spec is None or location is None:
        return None
    location_en = _localized(location.name, "en")
    location_zh = _localized(location.name, "zh-CN")
    opening = {
        "en": f"Hi, I'm {resident_spec.name}. Since we're both at {location_en}, would you like to talk for a moment?",
        "zh-CN": f"你好，我是{resident_spec.name}。我们正好都在{location_zh}，愿意聊一会儿吗？",
    }
    expiry_day, expiry_minute = _add_world_minutes(
        world.current_day,
        world.current_time_minutes,
        PROMPT_EXPIRY_MINUTES,
    )
    intent = (
        db.query(ResidentIntentState)
        .filter(
            ResidentIntentState.session_id == session.id,
            ResidentIntentState.source_action_id == action.id,
        )
        .first()
    )
    prompt = WorldInteractionPrompt(
        session_id=session.id,
        initiator_agent_id=agent_id,
        location_id=location_id,
        prompt_kind="resident_greeting",
        status="pending",
        opening_text_json=_json_dumps(opening),
        allowed_responses_json=_json_dumps(list(ALLOWED_RESPONSES)),
        created_day=world.current_day,
        created_time_minutes=world.current_time_minutes,
        expiry_day=expiry_day,
        expiry_time_minutes=expiry_minute,
        source_intent_id=intent.id if intent is not None else None,
        source_pulse_id=pulse.id,
        source_action_id=action.id,
        idempotency_key=key,
        cooldown_key=cooldown_key,
        reason_code="awaiting_participant",
        policy_id=PROMPT_POLICY_ID,
        policy_version=PROMPT_POLICY_VERSION,
        metadata_json=_json_dumps(
            {
                "schema_version": PROMPT_SCHEMA_VERSION,
                "opening_version": PROMPT_OPENING_VERSION,
                "language_requested": language,
                "world_version": world.world_version,
                "profile_version": resident_spec.profile_version,
                "source_pulse_sequence": pulse.sequence,
            }
        ),
    )
    db.add(prompt)
    db.flush()
    return prompt


def _response_matches(action: WorldAction, prompt_id: int, request: Any) -> bool:
    metadata = _json_loads(action.metadata_json, {})
    return (
        action.action_type == "interaction_prompt_response"
        and action.response_text == request.response
        and action.response_latency_ms == request.response_latency_ms
        and action.language == request.language
        and isinstance(metadata, dict)
        and metadata.get("prompt_id") == prompt_id
        and metadata.get("response") == request.response
    )


def respond_to_interaction_prompt(
    db: DBSession,
    *,
    session_id: int,
    prompt_id: int,
    request: schemas.WorldInteractionPromptResponseRequest,
) -> dict[str, Any]:
    """Resolve one prompt idempotently and create the formal conversation on accept."""

    from services.world_service import build_world_payload, session_write_lock

    with session_write_lock(session_id):
        db.rollback()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session is None:
            raise InteractionPromptError("Session not found.", 404)
        world = db.query(WorldState).filter(WorldState.session_id == session_id).first()
        if world is None:
            raise InteractionPromptError("Island world is not initialized.", 409)
        prompt = (
            db.query(WorldInteractionPrompt)
            .filter(
                WorldInteractionPrompt.id == prompt_id,
                WorldInteractionPrompt.session_id == session_id,
            )
            .first()
        )
        if prompt is None:
            raise InteractionPromptError("Interaction prompt not found.", 404)
        existing = (
            db.query(WorldAction)
            .filter(
                WorldAction.session_id == session_id,
                WorldAction.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if not _response_matches(existing, prompt_id, request):
                raise InteractionPromptError(
                    "The idempotency key was already used with another prompt response.",
                    409,
                )
            conversation_id = _json_loads(existing.metadata_json, {}).get(
                "conversation_id"
            )
            return {
                "status": "duplicate",
                "action_id": existing.id,
                "conversation_id": conversation_id,
                "prompt": serialize_interaction_prompt(
                    prompt, language=request.language
                ),
                "world": build_world_payload(db, session, request.language),
            }

        invalid_reason = _prompt_invalid_reason(
            db,
            session=session,
            world=world,
            prompt=prompt,
            check_agent_busy=True,
        )
        if invalid_reason is not None and prompt.status == "pending":
            _resolve_prompt(
                prompt,
                world=world,
                status="expired" if invalid_reason == "expired" else "closed",
                reason_code=invalid_reason,
                cooldown_minutes=(
                    EXPIRED_COOLDOWN_MINUTES if invalid_reason == "expired" else 0
                ),
            )
            db.commit()
            raise InteractionPromptError(
                f"The interaction prompt is no longer available: {invalid_reason}.",
                409,
            )
        if prompt.status != "pending":
            raise InteractionPromptError("The interaction prompt is already resolved.", 409)
        allowed = _json_loads(prompt.allowed_responses_json, [])
        if request.response not in allowed:
            raise InteractionPromptError("Unsupported interaction prompt response.", 400)

        action = WorldAction(
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            actor_type="participant",
            actor_agent_id=None,
            policy_id=PROMPT_POLICY_ID,
            policy_version=PROMPT_POLICY_VERSION,
            decision_reason_code=f"participant_{request.response}",
            action_type="interaction_prompt_response",
            target_location_id=prompt.location_id,
            target_agent_id=prompt.initiator_agent_id,
            response_text=request.response,
            response_latency_ms=request.response_latency_ms,
            language=request.language,
            world_day=world.current_day,
            world_time_minutes=world.current_time_minutes,
            metadata_json="{}",
        )
        db.add(action)
        db.flush()
        conversation_id: int | None = None
        if request.response == "accept":
            from services.interaction_time_service import conversation_slot
            slot = conversation_slot(db, world, get_world_spec(world.world_version), prompt.initiator_agent_id, 10)
            conversation = WorldConversation(
                session_id=session_id,
                agent_id=prompt.initiator_agent_id,
                location_id=prompt.location_id,
                status="active",
                conversation_kind="participant_resident",
                initiator_type="resident",
                initiator_agent_id=prompt.initiator_agent_id,
                visibility="session_private",
                metadata_json=_json_dumps(
                    {
                        "schema_version": "participant-conversation-v1",
                        "source_prompt_id": prompt.id,
                        "conversation_goal": "ordinary_participant_contact",
                        **slot,
                    }
                ),
            )
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id
            db.add_all(
                [
                    WorldConversationParticipant(
                        conversation_id=conversation.id,
                        session_id=session_id,
                        member_type="resident",
                        agent_id=prompt.initiator_agent_id,
                        member_role="initiator",
                    ),
                    WorldConversationParticipant(
                        conversation_id=conversation.id,
                        session_id=session_id,
                        member_type="participant",
                        agent_id=None,
                        member_role="target",
                    ),
                    WorldConversationTurn(
                        conversation_id=conversation.id,
                        session_id=session_id,
                        source_action_id=action.id,
                        speaker_type="agent",
                        speaker_id=prompt.initiator_agent_id,
                        content=serialize_interaction_prompt(
                            prompt, language=request.language
                        )["display_opening_text"],
                        world_day=world.current_day,
                        world_time_minutes=world.current_time_minutes,
                        response_latency_ms=0,
                        generation_mode="rule",
                        prompt_version=PROMPT_OPENING_VERSION,
                        safety_flag=False,
                        metadata_json=_json_dumps(
                            {
                                "visibility": "session_private",
                                "listener_type": "participant",
                                "conversation_goal": "ordinary_participant_contact",
                                "source_prompt_id": prompt.id,
                                "source_pulse_id": prompt.source_pulse_id,
                                "source_action_id": prompt.source_action_id,
                                "policy_id": PROMPT_POLICY_ID,
                                "policy_version": PROMPT_POLICY_VERSION,
                                "safety_result": "passed",
                            }
                        ),
                    ),
                ]
            )
            _resolve_prompt(
                prompt,
                world=world,
                status="accepted",
                reason_code="participant_accepted",
                response_code="accept",
            )
        elif request.response == "later":
            _resolve_prompt(
                prompt,
                world=world,
                status="later",
                reason_code="participant_later",
                response_code="later",
                cooldown_minutes=LATER_COOLDOWN_MINUTES,
            )
        else:
            _resolve_prompt(
                prompt,
                world=world,
                status="declined",
                reason_code="participant_declined",
                response_code="decline",
                cooldown_minutes=DECLINE_COOLDOWN_MINUTES,
            )
        prompt.response_action_id = action.id
        action.metadata_json = _json_dumps(
            {
                "schema_version": "interaction-prompt-response-v1",
                "prompt_id": prompt.id,
                "response": request.response,
                "conversation_id": conversation_id,
                "source_pulse_id": prompt.source_pulse_id,
                "source_action_id": prompt.source_action_id,
            }
        )
        db.commit()
        db.refresh(prompt)
        db.refresh(action)
        return {
            "status": "accepted" if request.response == "accept" else "resolved",
            "action_id": action.id,
            "conversation_id": conversation_id,
            "prompt": serialize_interaction_prompt(prompt, language=request.language),
            "world": build_world_payload(db, session, request.language),
        }
