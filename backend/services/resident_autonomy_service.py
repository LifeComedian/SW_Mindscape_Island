"""Deterministic, bounded ordinary resident autonomy for foreground pulses."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.orm import Session as DBSession

from models import (
    CharacterState,
    RelationshipState,
    ResidentIntentState,
    ScenarioInstance,
    Session as UserSession,
    WorldAction,
    WorldConversation,
    WorldConversationParticipant,
    WorldEventInstance,
    WorldInteractionPrompt,
    WorldMemory,
    WorldSimulationPulse,
    WorldState,
)
from services.resident_runtime_service import (
    build_resident_perception,
    retrieve_resident_decision_memories,
)
from services.resident_social_service import end_ambient_conversations_for_resident
from services.world_memory_service import memory_metadata, record_memory
from world.graph import can_travel, object_exists
from world.resident_agents import CandidateIntent
from world.schedules import resolve_resident_schedule
from world.specs import ResidentSpec, ScheduleBlock, WorldSpec


AUTONOMY_POLICY_ID = "bounded-autonomy"
AUTONOMY_POLICY_VERSION = "v1"
AUTONOMY_AUDIT_VERSION = "resident-autonomy-audit-v1"
MAX_AUTONOMY_ACTIONS_PER_PULSE = 3
MAX_RESIDENT_ACTIONS_PER_PULSE = 8
AUTONOMY_INTENT_DURATION_MINUTES = 10
AUTONOMY_ACTION_TYPES = frozenset(
    {
        "resident_idle",
        "resident_inspect_object",
        "resident_socialize_intent",
        "resident_greet_participant_intent",
        "resident_visit_location",
        "resident_continue_intent",
        "resident_end_intent",
    }
)


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


def _localized(value: Mapping[str, str], language: str = "en") -> str:
    return value.get(language) or value.get("en") or next(iter(value.values()), "")


def _elapsed_minutes(
    *, from_day: int, from_minute: int, to_day: int, to_minute: int
) -> int:
    return (to_day - from_day) * 1440 + to_minute - from_minute


def _is_due(intent: ResidentIntentState, world: WorldState) -> bool:
    return (world.current_day, world.current_time_minutes) >= (
        intent.due_day,
        intent.due_time_minutes,
    )


def _flatten_profile(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, Mapping):
        return " ".join(_flatten_profile(item) for item in value.values())
    if isinstance(value, (tuple, list, set, frozenset)):
        return " ".join(_flatten_profile(item) for item in value)
    return ""


_PROFILE_TERMS = {
    "idle": ("quiet", "calm", "steady", "patient", "reserved"),
    "inspect_object": (
        "practical",
        "object",
        "organize",
        "repair",
        "book",
        "supply",
        "work",
    ),
    "socialize_resident": (
        "social",
        "share",
        "community",
        "conversation",
        "friendly",
        "gathering",
    ),
    "greet_participant": (
        "newcomer",
        "welcome",
        "help",
        "visitor",
        "attentive",
    ),
    "visit_adjacent_location": ("walk", "route", "path", "island", "changing"),
}


def _profile_affinity(resident_spec: ResidentSpec, intent_type: str) -> int:
    text = _flatten_profile(resident_spec.profile)
    return min(8, sum(text.count(term) for term in _PROFILE_TERMS[intent_type]))


def _current_goal_affinity(resident: CharacterState, intent_type: str) -> int:
    text = f"{resident.current_goal} {resident.current_activity}".lower()
    return min(5, sum(text.count(term) for term in _PROFILE_TERMS[intent_type]))


def _relationship_bonus(
    relationships: Mapping[str, RelationshipState],
    target_key: str | None,
) -> int:
    if target_key is None or target_key not in relationships:
        return 0
    row = relationships[target_key]
    value = (row.familiarity + row.trust + row.warmth - row.tension) // 25
    return max(-6, min(10, value))


def _memory_bonus(
    memories: Sequence[WorldMemory],
    *,
    intent_type: str,
    location_id: str,
    target_agent_id: int | None,
    target_object_id: str | None,
) -> int:
    bonus = 0
    expected_tags = {intent_type, "autonomy", "ordinary_activity"}
    for memory in memories:
        metadata = memory_metadata(memory)
        tags = {str(item) for item in metadata.get("tags", [])}
        related = {
            int(item)
            for item in metadata.get("related_agent_ids", [])
            if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
        }
        if tags.intersection(expected_tags):
            bonus += 1
        if metadata.get("location_id") == location_id:
            bonus += 1
        if target_agent_id is not None and target_agent_id in related:
            bonus += 2
        if target_object_id is not None and metadata.get("object_id") == target_object_id:
            bonus += 2
    return min(8, bonus)


def _intent_summary(
    *,
    intent_type: str,
    spec: WorldSpec,
    target_location_id: str | None = None,
    target_agent_id: int | None = None,
    target_object_id: str | None = None,
) -> dict[str, str]:
    if intent_type == "idle":
        return {"en": "taking a short pause", "zh-CN": "正在短暂停留"}
    if intent_type == "inspect_object":
        label_en = target_object_id or "a nearby object"
        label_zh = target_object_id or "附近的物件"
        if target_location_id in spec.locations:
            point = next(
                (
                    item
                    for item in spec.locations[target_location_id].interaction_points
                    if item.get("object_id") == target_object_id
                ),
                None,
            )
            if point is not None and isinstance(point.get("name"), Mapping):
                label_en = _localized(point["name"], "en")
                label_zh = _localized(point["name"], "zh-CN")
        return {
            "en": f"looking at {label_en}",
            "zh-CN": f"正在查看{label_zh}",
        }
    if intent_type == "socialize_resident" and target_agent_id in spec.residents:
        name = spec.residents[target_agent_id].name
        return {"en": f"looking for a moment to talk with {name}", "zh-CN": f"正准备和{name}聊几句"}
    if intent_type == "greet_participant":
        return {"en": "considering greeting the visiting islander", "zh-CN": "正准备向来访岛民打招呼"}
    if intent_type == "visit_adjacent_location" and target_location_id in spec.locations:
        location = spec.locations[target_location_id]
        return {
            "en": f"visiting {_localized(location.name, 'en')}",
            "zh-CN": f"正前往{_localized(location.name, 'zh-CN')}",
        }
    return {"en": "following the current plan", "zh-CN": "正在按当前计划行动"}


def _candidate(
    *,
    intent_id: str,
    intent_type: str,
    schedule_state_id: str,
    priority: int,
    weight: int,
    reason_tags: Iterable[str],
    target_location_id: str | None = None,
    target_resident_id: int | None = None,
    target_object_id: str | None = None,
) -> CandidateIntent:
    return CandidateIntent(
        intent_id=intent_id,
        intent_type=intent_type,
        priority=priority,
        proposed_by=AUTONOMY_POLICY_ID,
        schedule_state_id=schedule_state_id,
        target_location_id=target_location_id,
        target_resident_id=target_resident_id,
        target_object_id=target_object_id,
        weight=max(0, weight),
        reason_tags=tuple(sorted(set(reason_tags))),
    )


def _recent_autonomy_action(
    db: DBSession, *, session_id: int, agent_id: int
) -> WorldAction | None:
    return (
        db.query(WorldAction)
        .filter(
            WorldAction.session_id == session_id,
            WorldAction.actor_type == "resident",
            WorldAction.actor_agent_id == agent_id,
            WorldAction.policy_id == AUTONOMY_POLICY_ID,
        )
        .order_by(WorldAction.id.desc())
        .first()
    )


def _resident_unavailable(row: CharacterState) -> bool:
    flags = _json_loads(row.state_json).get("flags", {})
    return bool(
        isinstance(flags, dict)
        and (flags.get("unavailable") is True or flags.get("autonomy_available") is False)
    )


def _occupied_resident_ids(db: DBSession, session_id: int) -> set[int]:
    occupied = {
        int(agent_id)
        for (agent_id,) in db.query(WorldConversation.agent_id)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
        )
        .all()
        if agent_id is not None
    }
    occupied.update(
        int(agent_id)
        for (agent_id,) in db.query(WorldConversation.initiator_agent_id)
        .filter(
            WorldConversation.session_id == session_id,
            WorldConversation.status == "active",
            WorldConversation.initiator_agent_id.is_not(None),
        )
        .all()
        if agent_id is not None
    )
    occupied.update(
        int(agent_id)
        for (agent_id,) in db.query(WorldConversationParticipant.agent_id)
        .join(
            WorldConversation,
            WorldConversation.id == WorldConversationParticipant.conversation_id,
        )
        .filter(
            WorldConversationParticipant.session_id == session_id,
            WorldConversationParticipant.member_type == "resident",
            WorldConversationParticipant.agent_id.is_not(None),
            WorldConversationParticipant.left_at.is_(None),
            WorldConversation.status == "active",
        )
        .all()
        if agent_id is not None
    )
    occupied.update(
        int(agent_id)
        for (agent_id,) in db.query(WorldInteractionPrompt.initiator_agent_id)
        .filter(
            WorldInteractionPrompt.session_id == session_id,
            WorldInteractionPrompt.status == "pending",
        )
        .all()
    )
    return occupied


def _event_occupied_locations(db: DBSession, session_id: int) -> set[str]:
    locations = {
        location_id
        for (location_id,) in db.query(ScenarioInstance.location_id)
        .filter(
            ScenarioInstance.session_id == session_id,
            ScenarioInstance.status == "active",
        )
        .all()
    }
    locations.update(
        location_id
        for (location_id,) in db.query(WorldEventInstance.location_id)
        .filter(
            WorldEventInstance.session_id == session_id,
            WorldEventInstance.status == "active",
        )
        .all()
    )
    return locations


def _build_candidates(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
    intent: ResidentIntentState,
    schedule: ScheduleBlock,
    occupied_residents: set[int],
    reserved_targets: set[int],
) -> tuple[tuple[CandidateIntent, ...], list[WorldMemory]]:
    resident_spec = spec.residents[resident.agent_id]
    autonomy = resident_spec.autonomy
    if intent.intent_type != "follow_schedule" and intent.status == "active":
        intent_type = "end_intent" if _is_due(intent, world) else "continue_intent"
        candidate = _candidate(
            intent_id=f"autonomy:{resident.agent_id}:{intent_type}:{intent.id}",
            intent_type=intent_type,
            schedule_state_id=schedule.state_id,
            priority=100,
            weight=100,
            reason_tags=("committed_intent", "intent_due" if _is_due(intent, world) else "intent_active"),
            target_location_id=intent.target_location_id,
            target_resident_id=intent.target_agent_id,
            target_object_id=intent.target_object_id,
        )
        return (candidate,), []

    perception = build_resident_perception(
        db, spec=spec, world=world, resident=resident
    )
    memories = retrieve_resident_decision_memories(
        db,
        session_id=world.session_id,
        perception=perception,
    )
    relationships = {
        row.target_key: row
        for row in db.query(RelationshipState)
        .filter(
            RelationshipState.session_id == world.session_id,
            RelationshipState.source_agent_id == resident.agent_id,
        )
        .all()
    }
    candidates: list[CandidateIntent] = []

    def add_regular(
        intent_type: str,
        *,
        key: str,
        base_weight: int,
        target_location_id: str | None = None,
        target_agent_id: int | None = None,
        target_object_id: str | None = None,
    ) -> None:
        target_key = (
            "participant"
            if intent_type == "greet_participant"
            else f"resident:{target_agent_id}" if target_agent_id is not None else None
        )
        weight = (
            base_weight
            + _profile_affinity(resident_spec, intent_type)
            + _current_goal_affinity(resident, intent_type)
            + _relationship_bonus(relationships, target_key)
            + _memory_bonus(
                memories,
                intent_type=intent_type,
                location_id=resident.current_location_id,
                target_agent_id=target_agent_id,
                target_object_id=target_object_id,
            )
        )
        tags = [
            "allowed_by_content",
            "schedule_state_compatible",
            "current_goal_context",
        ]
        if target_key in relationships:
            tags.append("relationship_context")
        if memories:
            tags.append("ordinary_memory_context")
        candidates.append(
            _candidate(
                intent_id=f"autonomy:{resident.agent_id}:{intent_type}:{key}",
                intent_type=intent_type,
                schedule_state_id=schedule.state_id,
                priority=50 if intent_type != "idle" else 40,
                weight=weight,
                reason_tags=tags,
                target_location_id=target_location_id,
                target_resident_id=target_agent_id,
                target_object_id=target_object_id,
            )
        )

    allowed = set(autonomy.allowed_intents)
    if "idle" in allowed:
        add_regular(
            "idle",
            key=resident.current_location_id,
            base_weight=autonomy.idle_weight,
            target_location_id=resident.current_location_id,
        )
    if "inspect_object" in allowed:
        for object_id in perception.visible_object_ids:
            add_regular(
                "inspect_object",
                key=object_id,
                base_weight=autonomy.inspect_weight,
                target_location_id=resident.current_location_id,
                target_object_id=object_id,
            )
    if "socialize_resident" in allowed:
        for target_id in perception.visible_resident_ids:
            if target_id in occupied_residents or target_id in reserved_targets:
                continue
            add_regular(
                "socialize_resident",
                key=str(target_id),
                base_weight=autonomy.socialize_weight,
                target_location_id=resident.current_location_id,
                target_agent_id=target_id,
            )
    if "greet_participant" in allowed and perception.participant_present:
        add_regular(
            "greet_participant",
            key="participant",
            base_weight=autonomy.greet_weight,
            target_location_id=resident.current_location_id,
        )
    if (
        "visit_adjacent_location" in allowed
        and schedule.state_id in autonomy.free_time_state_ids
        # Make visits due before the schedule block ends so residents can return.
        and world.current_time_minutes + AUTONOMY_INTENT_DURATION_MINUTES
        < schedule.end_minute
    ):
        adjacent = sorted(spec.locations[resident.current_location_id].connected_location_ids)
        preferred = set(autonomy.preferred_location_ids)
        for target_location_id in adjacent:
            if not spec.locations[target_location_id].opening_hours.get("always_open", False):
                continue
            add_regular(
                "visit_adjacent_location",
                key=target_location_id,
                base_weight=autonomy.travel_weight + (8 if target_location_id in preferred else 0),
                target_location_id=target_location_id,
            )
    return tuple(candidates), memories


def _select_candidate(
    *,
    session: UserSession,
    world: WorldState,
    pulse: WorldSimulationPulse,
    resident: CharacterState,
    candidates: Sequence[CandidateIntent],
) -> tuple[CandidateIntent, int]:
    if not candidates:
        raise ValueError("Autonomy selection requires at least one candidate.")
    top_priority = max(candidate.priority for candidate in candidates)
    tier = tuple(
        sorted(
            (candidate for candidate in candidates if candidate.priority == top_priority),
            key=lambda item: item.intent_id,
        )
    )
    total_weight = sum(candidate.weight for candidate in tier)
    if total_weight <= 0:
        return tier[0], 0
    seed = (
        f"{session.simulation_seed}:{world.world_version}:{pulse.sequence}:"
        f"{world.current_day}:{world.current_time_minutes}:{resident.agent_id}"
    )
    roll = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16) % total_weight
    cursor = 0
    for candidate in tier:
        cursor += candidate.weight
        if roll < cursor:
            return candidate, roll
    return tier[-1], roll


def _candidate_payload(candidate: CandidateIntent) -> dict[str, Any]:
    return {
        "intent_id": candidate.intent_id,
        "intent_type": candidate.intent_type,
        "priority": candidate.priority,
        "weight": candidate.weight,
        "schedule_state_id": candidate.schedule_state_id,
        "target_location_id": candidate.target_location_id,
        "target_resident_id": candidate.target_resident_id,
        "target_object_id": candidate.target_object_id,
        "reason_tags": list(candidate.reason_tags),
    }


def _action_type(intent_type: str) -> str:
    mapping = {
        "idle": "resident_idle",
        "inspect_object": "resident_inspect_object",
        "socialize_resident": "resident_socialize_intent",
        "greet_participant": "resident_greet_participant_intent",
        "visit_adjacent_location": "resident_visit_location",
        "continue_intent": "resident_continue_intent",
        "end_intent": "resident_end_intent",
    }
    return mapping[intent_type]


def _revalidate(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    resident: CharacterState,
    schedule: ScheduleBlock,
    selected: CandidateIntent,
    occupied_locations: set[str],
    occupied_residents: set[int],
) -> bool:
    if resident.current_location_id in occupied_locations or _resident_unavailable(resident):
        return False
    if resident.schedule_state != schedule.state_id:
        return False
    if selected.intent_type == "inspect_object":
        return bool(
            selected.target_object_id
            and object_exists(spec, resident.current_location_id, selected.target_object_id)
        )
    if selected.intent_type == "socialize_resident":
        target = (
            db.query(CharacterState)
            .filter(
                CharacterState.session_id == world.session_id,
                CharacterState.agent_id == selected.target_resident_id,
                CharacterState.current_location_id == resident.current_location_id,
            )
            .first()
        )
        return target is not None and target.agent_id not in occupied_residents
    if selected.intent_type == "greet_participant":
        return world.participant_location_id == resident.current_location_id
    if selected.intent_type == "visit_adjacent_location":
        return bool(
            selected.target_location_id
            and schedule.state_id in spec.residents[resident.agent_id].autonomy.free_time_state_ids
            and can_travel(spec, resident.current_location_id, selected.target_location_id)
            and spec.locations[selected.target_location_id].opening_hours.get("always_open", False)
        )
    if selected.intent_type in {"continue_intent", "end_intent"}:
        intent = (
            db.query(ResidentIntentState)
            .filter(
                ResidentIntentState.session_id == world.session_id,
                ResidentIntentState.agent_id == resident.agent_id,
            )
            .first()
        )
        return intent is not None and intent.intent_type != "follow_schedule"
    return selected.intent_type == "idle"


def _end_resident_conversations(
    db: DBSession,
    *,
    world: WorldState,
    resident: CharacterState,
    location_id: str,
) -> None:
    for conversation in (
        db.query(WorldConversation)
        .filter(
            WorldConversation.session_id == world.session_id,
            WorldConversation.status == "active",
            WorldConversation.location_id == location_id,
            (
                (WorldConversation.agent_id == resident.agent_id)
                | (WorldConversation.initiator_agent_id == resident.agent_id)
            ),
        )
        .all()
    ):
        conversation.status = "ended"
        conversation.ended_reason_code = "resident_relocated"
        conversation.updated_at = utc_now()
    end_ambient_conversations_for_resident(
        db,
        world=world,
        agent_id=resident.agent_id,
        location_id=location_id,
        reason_code="resident_relocated",
    )


def _apply_selected_intent(
    db: DBSession,
    *,
    spec: WorldSpec,
    world: WorldState,
    pulse: WorldSimulationPulse,
    resident: CharacterState,
    intent: ResidentIntentState,
    schedule: ScheduleBlock,
    selected: CandidateIntent,
    candidates: Sequence[CandidateIntent],
    memories: Sequence[WorldMemory],
    roll: int,
) -> WorldAction:
    selected_type = selected.intent_type
    action_type = _action_type(selected_type)
    if action_type not in AUTONOMY_ACTION_TYPES:
        raise ValueError("Autonomy selected an action outside the allowlist.")
    summary = _intent_summary(
        intent_type=selected_type,
        spec=spec,
        target_location_id=selected.target_location_id,
        target_agent_id=selected.target_resident_id,
        target_object_id=selected.target_object_id,
    )
    if selected_type in {"continue_intent", "end_intent"}:
        original_summary = _json_loads(intent.summary_json)
        if original_summary:
            summary = {str(key): str(value) for key, value in original_summary.items()}

    metadata = {
        "resident_autonomy": {
            "schema_version": AUTONOMY_AUDIT_VERSION,
            "policy_id": AUTONOMY_POLICY_ID,
            "policy_version": AUTONOMY_POLICY_VERSION,
            "source_pulse_id": pulse.id,
            "source_pulse_sequence": pulse.sequence,
            "considered_candidates": [_candidate_payload(item) for item in candidates],
            "selected_intent": _candidate_payload(selected),
            "deterministic_roll": roll,
            "reason_code": (
                "revalidation_failed"
                if "revalidation_failed" in selected.reason_tags
                else "committed_intent_due"
                if selected_type == "end_intent"
                else "committed_intent_continues"
                if selected_type == "continue_intent"
                else "weighted_candidate_selected"
            ),
            "profile_version": spec.residents[resident.agent_id].profile_version,
            "world_version": spec.world_version,
            "content_pack_version": spec.content_pack_version,
            "recalled_memory_ids": [memory.id for memory in memories],
            "input_counts": {
                "candidate_count": len(candidates),
                "ordinary_memory_count": len(memories),
            },
            "validation_status": "applied",
        }
    }
    action = WorldAction(
        session_id=world.session_id,
        idempotency_key=f"autonomy:pulse:{pulse.id}:resident:{resident.agent_id}",
        actor_type="resident",
        actor_agent_id=resident.agent_id,
        policy_id=AUTONOMY_POLICY_ID,
        policy_version=AUTONOMY_POLICY_VERSION,
        decision_reason_code=metadata["resident_autonomy"]["reason_code"],
        action_type=action_type,
        target_location_id=selected.target_location_id,
        target_agent_id=selected.target_resident_id,
        target_object_id=selected.target_object_id,
        response_text="",
        language="en",
        world_day=world.current_day,
        world_time_minutes=world.current_time_minutes,
        metadata_json=_json_dumps(metadata),
    )
    db.add(action)
    db.flush()

    if selected_type == "end_intent":
        previous_location = resident.current_location_id
        resident.current_location_id = schedule.location_id
        resident.current_activity = _localized(schedule.activity, "en")
        resident.current_goal = _localized(schedule.goal, "en")
        state = _json_loads(resident.state_json)
        state.pop("autonomy_schedule_override_state", None)
        resident.state_json = _json_dumps(state)
        if previous_location != resident.current_location_id:
            _end_resident_conversations(
                db,
                world=world,
                resident=resident,
                location_id=previous_location,
            )
        intent.intent_type = "follow_schedule"
        intent.target_location_id = schedule.location_id
        intent.target_agent_id = None
        intent.target_object_id = None
        intent.due_day = world.current_day
        intent.due_time_minutes = schedule.end_minute
        intent.summary_json = _json_dumps(
            {
                "en": _localized(schedule.activity, "en"),
                "zh-CN": _localized(schedule.activity, "zh-CN"),
            }
        )
    elif selected_type == "continue_intent":
        pass
    else:
        previous_location = resident.current_location_id
        if selected_type == "visit_adjacent_location" and selected.target_location_id:
            resident.current_location_id = selected.target_location_id
            state = _json_loads(resident.state_json)
            state["autonomy_schedule_override_state"] = schedule.state_id
            resident.state_json = _json_dumps(state)
            if previous_location != resident.current_location_id:
                _end_resident_conversations(
                    db,
                    world=world,
                    resident=resident,
                    location_id=previous_location,
                )
        resident.current_activity = summary["en"]
        intent.intent_type = selected_type
        intent.target_location_id = selected.target_location_id
        intent.target_agent_id = selected.target_resident_id
        intent.target_object_id = selected.target_object_id
        intent.due_day = world.current_day
        intent.due_time_minutes = min(
            schedule.end_minute,
            world.current_time_minutes + AUTONOMY_INTENT_DURATION_MINUTES,
        )
        intent.summary_json = _json_dumps(summary)

    resident.updated_at = utc_now()
    intent.status = "active"
    intent.started_day = world.current_day
    intent.started_time_minutes = world.current_time_minutes
    intent.source_pulse_id = pulse.id
    intent.source_action_id = action.id
    intent.policy_id = AUTONOMY_POLICY_ID
    intent.policy_version = AUTONOMY_POLICY_VERSION
    intent.metadata_json = _json_dumps(
        {
            "schema_version": "resident-intent-state-v1",
            "schedule_state_id": schedule.state_id,
            "source": "foreground_pulse",
        }
    )
    intent.updated_at = utc_now()

    if selected_type == "inspect_object" and selected.target_object_id:
        record_memory(
            db,
            session_id=world.session_id,
            owner_agent_id=resident.agent_id,
            memory_type="episodic",
            content=f"Looked at {selected.target_object_id} during an ordinary island routine.",
            occurred_day=world.current_day,
            occurred_time_minutes=world.current_time_minutes,
            source_action_id=action.id,
            importance=1,
            location_id=resident.current_location_id,
            tags=("autonomy", "ordinary_activity", "inspect_object"),
            effect_key="inspect_object",
            metadata={"object_id": selected.target_object_id},
        )
    return action


def run_resident_autonomy_pulse(
    db: DBSession,
    *,
    spec: WorldSpec,
    session: UserSession,
    world: WorldState,
    pulse: WorldSimulationPulse,
    schedule_action_count: int,
) -> list[WorldAction]:
    """Run at most one action per selected resident and three per pulse."""

    if spec.map_spec is None:
        return []
    remaining = min(
        MAX_AUTONOMY_ACTIONS_PER_PULSE,
        max(0, MAX_RESIDENT_ACTIONS_PER_PULSE - schedule_action_count),
    )
    if remaining == 0:
        return []

    residents = (
        db.query(CharacterState)
        .filter(CharacterState.session_id == session.id)
        .order_by(CharacterState.agent_id.asc())
        .all()
    )
    intents_by_agent = {
        intent.agent_id: intent
        for intent in db.query(ResidentIntentState)
        .filter(ResidentIntentState.session_id == session.id)
        .all()
    }

    def resident_order_key(row: CharacterState) -> tuple[int, str]:
        intent = intents_by_agent.get(row.agent_id)
        due_committed_intent = (
            intent is not None
            and intent.intent_type != "follow_schedule"
            and intent.status == "active"
            and _is_due(intent, world)
        )
        deterministic_order = hashlib.sha256(
            f"{session.simulation_seed}:{pulse.sequence}:{row.agent_id}".encode("utf-8")
        ).hexdigest()
        return (0 if due_committed_intent else 1, deterministic_order)

    order = sorted(residents, key=resident_order_key)
    occupied_residents = _occupied_resident_ids(db, session.id)
    occupied_locations = _event_occupied_locations(db, session.id)
    reserved_targets: set[int] = set()
    actions: list[WorldAction] = []
    for resident in order:
        if spec.content_schema_version == "content-pack-v5":
            from services.plan_service import resident_is_in_active_plan

            if resident_is_in_active_plan(db, session_id=session.id, agent_id=resident.agent_id, location_id=resident.current_location_id):
                continue
        if len(actions) >= remaining:
            break
        resident_spec = spec.residents.get(resident.agent_id)
        if resident_spec is None or not resident_spec.autonomy.enabled:
            continue
        intent = intents_by_agent.get(resident.agent_id)
        if intent is None:
            continue
        must_finish_committed_intent = (
            intent.intent_type != "follow_schedule"
            and intent.status == "active"
            and _is_due(intent, world)
        )
        if (
            not must_finish_committed_intent
            and (
                resident.agent_id in occupied_residents
                or resident.current_location_id in occupied_locations
                or _resident_unavailable(resident)
            )
        ):
            continue
        schedule = resolve_resident_schedule(
            spec,
            resident.agent_id,
            world.current_day,
            world.current_time_minutes,
        )
        if resident.schedule_state != schedule.state_id:
            continue
        if intent.intent_type == "follow_schedule":
            recent = _recent_autonomy_action(
                db, session_id=session.id, agent_id=resident.agent_id
            )
            if recent is not None and _elapsed_minutes(
                from_day=recent.world_day,
                from_minute=recent.world_time_minutes,
                to_day=world.current_day,
                to_minute=world.current_time_minutes,
            ) < resident_spec.autonomy.action_cooldown_minutes:
                continue

        candidates, memories = _build_candidates(
            db,
            spec=spec,
            world=world,
            resident=resident,
            intent=intent,
            schedule=schedule,
            occupied_residents=occupied_residents,
            reserved_targets=reserved_targets,
        )
        if not candidates:
            continue
        selected, roll = _select_candidate(
            session=session,
            world=world,
            pulse=pulse,
            resident=resident,
            candidates=candidates,
        )
        if not _revalidate(
            db,
            spec=spec,
            world=world,
            resident=resident,
            schedule=schedule,
            selected=selected,
            occupied_locations=occupied_locations,
            occupied_residents=occupied_residents,
        ):
            selected = _candidate(
                intent_id=f"autonomy:{resident.agent_id}:safe-wait",
                intent_type="idle",
                schedule_state_id=schedule.state_id,
                priority=100,
                weight=1,
                reason_tags=("revalidation_failed", "safe_fallback"),
                target_location_id=resident.current_location_id,
            )
            candidates = (*candidates, selected)
            roll = 0
        action = _apply_selected_intent(
            db,
            spec=spec,
            world=world,
            pulse=pulse,
            resident=resident,
            intent=intent,
            schedule=schedule,
            selected=selected,
            candidates=candidates,
            memories=memories,
            roll=roll,
        )
        actions.append(action)
        if selected.target_resident_id is not None:
            reserved_targets.add(selected.target_resident_id)
    db.flush()
    return actions
