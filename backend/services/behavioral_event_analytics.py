"""Derive read-only timelines and features from world action records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from models import (
    Session as UserSession,
    WorldAction,
    WorldEventInstance,
    WorldEventTriggerEvaluation,
    WorldState,
)
from world.registry import get_world_spec


BEHAVIORAL_TIMELINE_VERSION = "behavioral-event-timeline-v1"
BEHAVIORAL_FEATURE_VERSION = "behavioral-event-features-v1"


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


def _world_elapsed_minutes(
    start_day: int,
    start_minute: int,
    end_day: int | None,
    end_minute: int | None,
) -> int | None:
    if end_day is None or end_minute is None:
        return None
    return max(0, (end_day - start_day) * 1440 + end_minute - start_minute)


def _action_metadata(action: WorldAction) -> dict[str, Any]:
    value = _json_loads(action.metadata_json, {})
    return value if isinstance(value, dict) else {}


def _behavior_metadata(action: WorldAction) -> dict[str, Any]:
    metadata = _action_metadata(action)
    nested = metadata.get("action_metadata")
    result = dict(nested) if isinstance(nested, Mapping) else {}
    for key in (
        "behavioral_action_type",
        "target_type",
        "target_id",
        "target_agent_id",
        "target_location_id",
        "goal_effect",
        "npc_response_provider",
        "npc_response_npc_id",
        "npc_response_intent",
    ):
        if key in metadata:
            result[key] = metadata[key]
    return result


def serialize_raw_action(action: WorldAction, *, location_id: str) -> dict[str, Any]:
    metadata = _action_metadata(action)
    behavior = _behavior_metadata(action)
    response_text = action.response_text or ""
    return {
        "action_id": action.id,
        "event_instance_id": action.event_instance_id,
        "timestamp": _iso(action.created_at),
        "action_type": behavior.get("behavioral_action_type", action.action_type),
        "runtime_action_type": action.action_type,
        "location": location_id,
        "target_type": behavior.get("target_type"),
        "target_id": behavior.get("target_id", action.target_object_id),
        "target_agent_id": action.target_agent_id,
        "target_location_id": action.target_location_id,
        "response_text": response_text,
        "message_length": len(response_text),
        "response_latency_ms": action.response_latency_ms,
        "world_day": action.world_day,
        "world_time_minutes": action.world_time_minutes,
        "metadata": behavior,
        "runtime_metadata": metadata,
    }


def _source_action_row(
    db: DBSession,
    *,
    event: WorldEventInstance,
) -> WorldAction | None:
    evaluation = (
        db.query(WorldEventTriggerEvaluation)
        .filter(WorldEventTriggerEvaluation.selected_event_instance_id == event.id)
        .first()
    )
    if evaluation is None:
        return None
    return db.query(WorldAction).filter(WorldAction.id == evaluation.source_action_id).first()


def _entry_action(source: WorldAction | None, *, event: WorldEventInstance) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "action_id": source.id,
        "event_instance_id": event.id,
        "timestamp": _iso(source.created_at),
        "action_type": "enter_location" if source.action_type == "move" else "event_trigger_action",
        "runtime_action_type": source.action_type,
        "location": event.location_id,
        "target_type": "location",
        "target_id": event.location_id,
        "target_agent_id": None,
        "target_location_id": event.location_id,
        "response_text": "",
        "message_length": 0,
        "response_latency_ms": None,
        "world_day": source.world_day,
        "world_time_minutes": source.world_time_minutes,
        "metadata": {"trigger_source": True},
        "runtime_metadata": _action_metadata(source),
    }


def _first(actions: list[dict[str, Any]], action_types: set[str]) -> dict[str, Any] | None:
    return next((item for item in actions if item["action_type"] in action_types), None)


def _last(actions: list[dict[str, Any]], action_types: set[str]) -> dict[str, Any] | None:
    return next((item for item in reversed(actions) if item["action_type"] in action_types), None)


def _metadata_true(actions: list[dict[str, Any]], key: str) -> bool:
    return any(item["metadata"].get(key) is True for item in actions)


def _restaurant_features(
    event: WorldEventInstance,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    inspections = [item for item in actions if item["action_type"] == "inspect_object"]
    selections = [item for item in actions if item["action_type"] == "select_seat"]
    selected = selections[-1] if selections else None
    first_selected = selections[0] if selections else None
    conversation_actions = [
        item
        for item in actions
        if item["action_type"] in {"start_conversation", "send_message", "continue_conversation"}
    ]
    player_messages = [item for item in conversation_actions if item["message_length"] > 0]
    npc_response_actions = [
        item for item in actions if item["metadata"].get("npc_response_provider")
    ]
    npc_interactions = [
        item
        for item in actions
        if item["target_agent_id"] is not None
        or item["metadata"].get("npc_response_npc_id") is not None
    ]
    message_total = sum(item["message_length"] for item in player_messages)
    first_conversation = next(
        (
            item
            for item in actions
            if item in conversation_actions
            or item["metadata"].get("npc_initiated_conversation") is True
            or item["metadata"].get("initiated_conversation") is True
        ),
        None,
    )
    final_metadata = actions[-1]["metadata"] if actions else {}
    return {
        "selected_seat_id": selected["target_id"] if selected else None,
        "selected_seat_type": selected["metadata"].get("seat_type") if selected else None,
        "selected_seat_social_density": selected["metadata"].get("social_density") if selected else None,
        "distance_to_nearest_npc": selected["metadata"].get("distance_to_nearest_npc") if selected else None,
        "decision_latency_ms": first_selected["response_latency_ms"] if first_selected else None,
        "decision_latency_wall_ms": (
            _elapsed_ms(event.started_at, _parse_timestamp(first_selected["timestamp"]))
            if first_selected
            else None
        ),
        "number_of_seats_inspected": len({item["target_id"] for item in inspections}),
        "number_of_position_changes_before_selection": max(0, len(selections) - 1),
        "initiated_conversation": _metadata_true(actions, "initiated_conversation") or bool(player_messages),
        "npc_initiated_conversation": _metadata_true(actions, "npc_initiated_conversation"),
        "number_of_npc_interactions": len(npc_interactions),
        "conversation_turn_count": len(player_messages) + len(npc_response_actions),
        "player_message_count": len(player_messages),
        "player_total_message_length": message_total,
        "player_average_message_length": (
            round(message_total / len(player_messages), 3) if player_messages else 0.0
        ),
        "conversation_start_latency_ms": (
            first_conversation["response_latency_ms"] if first_conversation else None
        ),
        "early_exit": _metadata_true(actions, "early_exit") or event.outcome_code in {"left_before_selection", "left_restaurant_early"},
        "changed_seat_after_sitting": _metadata_true(actions, "changed_seat_after_sitting") or len(selections) > 1,
        "time_spent_in_restaurant_ms": _elapsed_ms(event.started_at, event.completed_at),
        "time_spent_in_restaurant_world_minutes": _world_elapsed_minutes(
            event.started_day,
            event.started_time_minutes,
            event.completed_day,
            event.completed_time_minutes,
        ),
        "event_completed": bool(final_metadata.get("event_completed", event.outcome_code not in {"left_before_selection", "left_restaurant_early"})),
    }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _ferry_features(
    event: WorldEventInstance,
    actions: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    first_action = actions[0] if actions else None
    information_actions = [item for item in actions if item["metadata"].get("information_request") is True]
    contacted = {
        item["target_agent_id"]
        for item in actions
        if item["target_agent_id"] is not None
        and item["action_type"] in {"ask_information", "contact_npc", "send_message"}
    }
    waits = [item for item in actions if item["action_type"] == "wait"]
    player_messages = [item for item in actions if item["message_length"] > 0]
    npc_response_actions = [
        item for item in actions if item["metadata"].get("npc_response_provider")
    ]
    trigger_goal = state.get("trigger_goals", {}).get("north_island_meeting", {})
    switches = sum(
        1
        for previous, current in zip(actions, actions[1:])
        if previous["action_type"] != current["action_type"]
    )
    alternative_goal = next(
        (
            item["metadata"].get("alternative_goal")
            for item in reversed(actions)
            if item["metadata"].get("alternative_goal")
        ),
        None,
    )
    final_metadata = actions[-1]["metadata"] if actions else {}
    return {
        "original_goal": trigger_goal or None,
        "goal_created_timestamp": trigger_goal.get("updated_at") or trigger_goal.get("created_at"),
        "ferry_cancellation_timestamp": _iso(event.started_at),
        "first_action_after_cancellation": first_action["action_type"] if first_action else None,
        "decision_latency_after_cancellation_ms": first_action["response_latency_ms"] if first_action else None,
        "decision_latency_after_cancellation_wall_ms": (
            _elapsed_ms(event.started_at, _parse_timestamp(first_action["timestamp"]))
            if first_action
            else None
        ),
        "number_of_information_requests": len(information_actions),
        "number_of_npcs_contacted": len(contacted),
        "asked_sailor": _metadata_true(actions, "asked_sailor"),
        "contacted_anna": _metadata_true(actions, "contacted_anna"),
        "checked_map": _metadata_true(actions, "checked_map"),
        "searched_alternative_route": _metadata_true(actions, "searched_alternative_route"),
        "waited_at_harbor": bool(waits),
        "wait_duration": sum(int(item["metadata"].get("wait_duration", 0)) for item in waits),
        "changed_plan": _metadata_true(actions, "changed_plan"),
        "abandoned_original_goal": _metadata_true(actions, "abandoned_original_goal"),
        "returned_home": _metadata_true(actions, "returned_home"),
        "alternative_goal_selected": alternative_goal,
        "number_of_action_switches": switches,
        "number_of_location_changes": len(
            {
                item["target_location_id"]
                for item in actions
                if item["target_location_id"]
                and item["target_location_id"] != event.location_id
            }
        ),
        "conversation_turn_count": len(player_messages) + len(npc_response_actions),
        "player_message_count": len(player_messages),
        "player_total_message_length": sum(item["message_length"] for item in player_messages),
        "time_until_resolution_ms": _elapsed_ms(event.started_at, event.completed_at),
        "time_until_resolution_world_minutes": _world_elapsed_minutes(
            event.started_day,
            event.started_time_minutes,
            event.completed_day,
            event.completed_time_minutes,
        ),
        "resolution_type": state.get("resolution_type") or event.outcome_code or "unresolved",
        "event_completed": bool(final_metadata.get("event_completed", event.outcome_code != "unresolved")),
    }


def build_behavioral_event_records(
    db: DBSession,
    session: UserSession,
) -> list[dict[str, Any]]:
    world = db.query(WorldState).filter(WorldState.session_id == session.id).first()
    if world is None:
        return []
    spec = get_world_spec(world.world_version)
    behavioral_ids = {
        event_id for event_id, event_spec in spec.event_specs.items() if event_spec.stages
    }
    events = (
        db.query(WorldEventInstance)
        .filter(WorldEventInstance.session_id == session.id)
        .order_by(WorldEventInstance.id.asc())
        .all()
    )
    result: list[dict[str, Any]] = []
    for event in events:
        instance_metadata = _json_loads(event.metadata_json, {})
        event_definition_id = instance_metadata.get("declarative_event_id")
        if event_definition_id not in behavioral_ids:
            continue
        event_actions = (
            db.query(WorldAction)
            .filter(WorldAction.event_instance_id == event.id)
            .order_by(WorldAction.id.asc())
            .all()
        )
        raw_actions = [
            serialize_raw_action(action, location_id=event.location_id)
            for action in event_actions
        ]
        source = _source_action_row(db, event=event)
        entry = _entry_action(source, event=event)
        state = _json_loads(event.state_json, {})
        derived: dict[str, Any] = {}
        if event.event_type == "restaurant_seating_behavior":
            derived = _restaurant_features(event, raw_actions)
        elif event.event_type == "ferry_cancellation_behavior":
            derived = _ferry_features(event, raw_actions, state)
        result.append(
            {
                "timeline_version": BEHAVIORAL_TIMELINE_VERSION,
                "feature_version": BEHAVIORAL_FEATURE_VERSION,
                "event_instance": {
                    "event_instance_id": event.id,
                    "event_definition_id": event_definition_id,
                    "event_type": event.event_type,
                    "session_id": event.session_id,
                    "player_id": session.user_alias or f"session:{session.id}",
                    "location_id": event.location_id,
                    "start_time": _iso(event.started_at),
                    "end_time": _iso(event.completed_at),
                    "entry_timestamp": entry["timestamp"] if entry else None,
                    "status": event.status,
                    "resolution": event.outcome_code or None,
                    "state": state,
                },
                "raw_actions": ([entry] if entry else []) + raw_actions,
                "derived_features": derived,
            }
        )
    return result
