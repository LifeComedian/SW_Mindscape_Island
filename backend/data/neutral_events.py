"""Event fixtures for runtime validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data.restaurant_events import (
    RestaurantConflictEvent,
    RestaurantConflictFollowUpEvent,
    RestaurantSeatingEvent,
)
from world.events import (
    EventActionDescriptor,
    EventContext,
    EventPresentation,
    EventRegistry,
    EventTransition,
    MemoryEffect,
    ScheduledEvent,
)


NEUTRAL_GREETING_EVENT_TYPE = "neutral_greeting"
NEUTRAL_GREETING_VERSION = "neutral-greeting-v1"


def _agent_id(context: EventContext) -> int:
    raw = context.state.get("agent_id") or context.metadata.get("agent_id")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    if context.visible_agent_ids:
        return context.visible_agent_ids[0]
    return 1


def _agent_name(context: EventContext) -> str:
    raw = context.metadata.get("agent_name") or context.state.get("agent_name")
    return raw if isinstance(raw, str) and raw.strip() else f"resident {_agent_id(context)}"


def _calendar_value(context: EventContext, key: str, fallback: int) -> int:
    calendar = context.metadata.get("calendar")
    if isinstance(calendar, Mapping):
        raw = calendar.get(key)
    else:
        raw = None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return fallback


class NeutralGreetingEvent:
    event_type = NEUTRAL_GREETING_EVENT_TYPE
    version = NEUTRAL_GREETING_VERSION

    def present(self, context: EventContext) -> EventPresentation:
        kind = str(context.state.get("kind") or "greeting")
        agent_name = _agent_name(context)
        if kind == "check_in":
            return EventPresentation(
                event_type=self.event_type,
                version=self.version,
                renderer_key="neutral_greeting_check_in",
                titles={
                    "en": "A brief check-in",
                    "zh-CN": "一次简短问候",
                },
                stimuli={
                    "en": (
                        f"{agent_name} notices you again and offers a simple, "
                        "ordinary hello."
                    ),
                    "zh-CN": f"{agent_name} 再次看见你，普通地打了个招呼。",
                },
                actions=(
                    EventActionDescriptor(
                        action_id="acknowledge",
                        labels={"en": "Acknowledge", "zh-CN": "回应一下"},
                    ),
                    EventActionDescriptor(
                        action_id="leave",
                        labels={"en": "Move on", "zh-CN": "先离开"},
                    ),
                ),
                metadata={"neutral_fixture": True, "agent_id": _agent_id(context)},
            )
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key="neutral_greeting",
            titles={
                "en": "An ordinary greeting",
                "zh-CN": "一次普通问候",
            },
            stimuli={
                "en": (
                    f"{agent_name} gives a small wave and offers a neutral "
                    "morning greeting."
                ),
                "zh-CN": f"{agent_name} 轻轻挥手，普通地向你问了声早。",
            },
            actions=(
                EventActionDescriptor(
                    action_id="reply",
                    labels={"en": "Reply", "zh-CN": "回复"},
                    requires_text=True,
                ),
                EventActionDescriptor(
                    action_id="leave",
                    labels={"en": "Move on", "zh-CN": "先离开"},
                ),
            ),
            metadata={"neutral_fixture": True, "agent_id": _agent_id(context)},
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        kind = str(context.state.get("kind") or "greeting")
        agent_id = _agent_id(context)
        agent_name = _agent_name(context)
        if action_id == "leave":
            return EventTransition(
                next_state="left",
                status="completed",
                outcome_code="left_without_response",
                state_patch={"last_action_id": action_id},
            )
        if kind == "check_in" and action_id == "acknowledge":
            return EventTransition(
                next_state="acknowledged",
                status="completed",
                outcome_code="check_in_acknowledged",
                state_patch={"last_action_id": action_id},
            )
        if kind != "check_in" and action_id == "reply":
            total_days = _calendar_value(context, "total_days", context.world_day)
            day_start = _calendar_value(context, "day_start_minute", 9 * 60)
            scheduled: tuple[ScheduledEvent, ...] = ()
            if context.world_day < total_days:
                scheduled = (
                    ScheduledEvent(
                        event_type=self.event_type,
                        version=self.version,
                        due_day=context.world_day + 1,
                        due_time_minutes=day_start + 30,
                        deduplication_key=(
                            f"neutral_greeting:{context.event_instance_id}:check_in"
                        ),
                        payload={
                            "kind": "check_in",
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "location_id": context.location_id,
                        },
                    ),
                )
            return EventTransition(
                next_state="replied",
                status="completed",
                outcome_code="participant_replied",
                state_patch={
                    "last_action_id": action_id,
                    "response_recorded": True,
                },
                memory_effects=(
                    MemoryEffect(
                        owner_agent_id=agent_id,
                        memory_type="episodic",
                        content=(
                            "The participant replied to an ordinary greeting "
                            f"from {agent_name}."
                        ),
                        importance=1,
                        privacy_category="ordinary",
                        subject_type="participant",
                        subject_id="participant",
                        metadata={
                            "effect_key": "reply_memory",
                            "tags": ("neutral_greeting", "ordinary_greeting"),
                            "related_agent_ids": (agent_id,),
                        },
                    ),
                ),
                scheduled_events=scheduled,
            )
        raise ValueError("Unsupported neutral greeting event action.")


EVENT_REGISTRY = EventRegistry()
EVENT_REGISTRY.register(NeutralGreetingEvent())
EVENT_REGISTRY.register(RestaurantSeatingEvent())
EVENT_REGISTRY.register(RestaurantConflictEvent())
EVENT_REGISTRY.register(RestaurantConflictFollowUpEvent())


def get_event_registry() -> EventRegistry:
    return EVENT_REGISTRY


def neutral_greeting_initial_state(
    *,
    agent_id: int,
    agent_name: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "state": "presented",
        "kind": "greeting",
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
    if extra:
        state.update(extra)
    return state
