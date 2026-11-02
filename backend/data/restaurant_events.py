"""Restaurant event handlers for the v0.3 world."""

from __future__ import annotations

from typing import Any

from data.island import CONFLICT_VARIANTS, SEATING_FORMS, TEXT
from world.events import (
    EventActionDescriptor,
    EventContext,
    EventPresentation,
    EventTransition,
    ScheduledEvent,
)


RESTAURANT_SEATING_EVENT_TYPE = "restaurant_seating"
RESTAURANT_SEATING_VERSION = "restaurant-seating-v03-runtime-v1"
RESTAURANT_CONFLICT_EVENT_TYPE = "restaurant_conflict"
RESTAURANT_CONFLICT_VERSION = "restaurant-conflict-v03-runtime-v1"
RESTAURANT_FOLLOW_UP_EVENT_TYPE = "restaurant_conflict_follow_up"
RESTAURANT_FOLLOW_UP_VERSION = "restaurant-followup-v03-runtime-v1"


def _localized(value: dict[str, str], language: str = "en") -> str:
    return value.get(language) or value.get("en") or next(iter(value.values()), "")


def _option_ids(context: EventContext) -> list[str]:
    raw = context.state.get("options")
    if isinstance(raw, tuple):
        options = raw
    elif isinstance(raw, list):
        options = tuple(raw)
    else:
        form = str(context.state.get("form") or "layout_a")
        options = tuple(SEATING_FORMS.get(form, SEATING_FORMS["layout_a"]))
    ids: list[str] = []
    for item in options:
        if isinstance(item, dict):
            option_id = item.get("option_id")
        else:
            option_id = getattr(item, "get", lambda _key, _default=None: None)(
                "option_id"
            )
        if isinstance(option_id, str) and option_id:
            ids.append(option_id)
    return ids


def _options(context: EventContext) -> list[dict[str, Any]]:
    raw = context.state.get("options")
    if isinstance(raw, tuple):
        options = raw
    elif isinstance(raw, list):
        options = tuple(raw)
    else:
        form = str(context.state.get("form") or "layout_a")
        options = tuple(SEATING_FORMS.get(form, SEATING_FORMS["layout_a"]))
    return [dict(item) for item in options if isinstance(item, dict)]


def _viewed_ids(context: EventContext) -> list[str]:
    raw = context.state.get("viewed_option_ids")
    if not isinstance(raw, (tuple, list)):
        return []
    return [str(item) for item in raw if str(item)]


def _selected_id(context: EventContext) -> str | None:
    raw = context.state.get("selected_option_id")
    return raw if isinstance(raw, str) and raw else None


def _calendar_value(context: EventContext, key: str, fallback: int) -> int:
    calendar = context.metadata.get("calendar")
    raw = calendar.get(key) if hasattr(calendar, "get") else None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return fallback


def _schedule_follow_up(context: EventContext) -> tuple[ScheduledEvent, ...]:
    day_end = _calendar_value(context, "day_end_minute", 20 * 60)
    day_start = _calendar_value(context, "day_start_minute", 9 * 60)
    total_days = _calendar_value(context, "total_days", context.world_day)
    minutes_until_day_end = day_end - context.world_time_minutes
    if minutes_until_day_end < 30 and context.world_day >= total_days:
        return ()
    if context.world_time_minutes + 30 <= day_end:
        due_day = context.world_day
        due_minute = context.world_time_minutes + 30
    else:
        due_day = min(total_days, context.world_day + 1)
        due_minute = day_start + (30 - max(0, minutes_until_day_end))
    return (
        ScheduledEvent(
            event_type=RESTAURANT_FOLLOW_UP_EVENT_TYPE,
            version=RESTAURANT_FOLLOW_UP_VERSION,
            due_day=due_day,
            due_time_minutes=due_minute,
            deduplication_key=(
                f"restaurant_conflict:{context.event_instance_id}:follow_up"
            ),
            payload={
                "scenario_instance_id": context.state.get("scenario_instance_id"),
                "agent_id": context.state.get("assigned_agent_id"),
                "variant": context.state.get("variant"),
                "location_id": context.location_id,
            },
        ),
    )


class RestaurantSeatingEvent:
    event_type = RESTAURANT_SEATING_EVENT_TYPE
    version = RESTAURANT_SEATING_VERSION

    def present(self, context: EventContext) -> EventPresentation:
        actions: list[EventActionDescriptor] = []
        for option_id in _option_ids(context):
            actions.append(
                EventActionDescriptor(
                    action_id=f"seat_view:{option_id}",
                    labels={"en": f"View {option_id}", "zh-CN": "查看座位"},
                    kind="inspect",
                    target_object_id=option_id,
                )
            )
            actions.append(
                EventActionDescriptor(
                    action_id=f"seat_select:{option_id}",
                    labels={"en": f"Choose {option_id}", "zh-CN": "选择座位"},
                    kind="choice",
                    target_object_id=option_id,
                )
            )
        actions.extend(
            [
                EventActionDescriptor(
                    action_id="skip",
                    labels={"en": "Skip", "zh-CN": "跳过"},
                    kind="skip",
                ),
                EventActionDescriptor(
                    action_id="technical_failure",
                    labels={"en": "Technical failure", "zh-CN": "技术中断"},
                    kind="system",
                ),
                EventActionDescriptor(
                    action_id="depart",
                    labels={"en": "Leave", "zh-CN": "离开"},
                    kind="leave",
                ),
            ]
        )
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key="legacy_restaurant_seating",
            titles={"en": "Restaurant seating", "zh-CN": "餐厅选座"},
            stimuli=TEXT["seating_stimulus"],
            actions=tuple(actions),
            metadata={
                "legacy_scenario_bridge": True,
                "scenario_instance_id": context.state.get("scenario_instance_id"),
                "form": context.state.get("form"),
            },
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        if action_id.startswith("seat_view:"):
            option_id = action_id.split(":", 1)[1]
            if option_id not in _option_ids(context):
                raise ValueError("Unknown seat option.")
            viewed = _viewed_ids(context)
            if option_id not in viewed:
                viewed.append(option_id)
            return EventTransition(
                next_state="viewing",
                status="active",
                outcome_code="seat_viewed",
                state_patch={"viewed_option_ids": viewed},
            )
        if action_id.startswith("seat_select:"):
            option_id = action_id.split(":", 1)[1]
            if option_id not in _option_ids(context):
                raise ValueError("Unknown seat option.")
            return EventTransition(
                next_state="selected",
                status="completed",
                outcome_code="seat_recorded",
                state_patch={"selected_option_id": option_id},
            )
        if action_id == "skip":
            return EventTransition(
                next_state="skipped",
                status="completed",
                outcome_code="skipped_without_penalty",
            )
        if action_id == "technical_failure":
            return EventTransition(
                next_state="interrupted",
                status="cancelled",
                outcome_code="interrupted_technical",
            )
        if action_id == "depart":
            return EventTransition(
                next_state="left",
                status="completed",
                outcome_code="left_scene",
            )
        raise ValueError("Unsupported seating event action.")


class RestaurantConflictEvent:
    event_type = RESTAURANT_CONFLICT_EVENT_TYPE
    version = RESTAURANT_CONFLICT_VERSION

    def present(self, context: EventContext) -> EventPresentation:
        actions: list[EventActionDescriptor] = []
        selected = _selected_id(context)
        for option_id in _option_ids(context):
            actions.append(
                EventActionDescriptor(
                    action_id=f"seat_change:{option_id}",
                    labels={"en": f"Change to {option_id}", "zh-CN": "更换座位"},
                    kind="choice",
                    target_object_id=option_id,
                )
            )
        for response_id in ("clarify", "negotiate", "leave"):
            actions.append(
                EventActionDescriptor(
                    action_id=f"respond:{response_id}",
                    labels={"en": response_id, "zh-CN": response_id},
                    kind="choice",
                )
            )
        actions.append(
            EventActionDescriptor(
                action_id="respond:free_text",
                labels={"en": "Free text", "zh-CN": "自由回应"},
                kind="text",
                requires_text=True,
            )
        )
        actions.extend(
            [
                EventActionDescriptor(
                    action_id="skip",
                    labels={"en": "Skip", "zh-CN": "跳过"},
                    kind="skip",
                ),
                EventActionDescriptor(
                    action_id="technical_failure",
                    labels={"en": "Technical failure", "zh-CN": "技术中断"},
                    kind="system",
                ),
                EventActionDescriptor(
                    action_id="depart",
                    labels={"en": "Leave", "zh-CN": "离开"},
                    kind="leave",
                ),
            ]
        )
        variant = str(context.state.get("variant") or CONFLICT_VARIANTS[0])
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key="legacy_restaurant_conflict",
            titles={"en": "Community misunderstanding", "zh-CN": "社区误会"},
            stimuli=TEXT.get(f"conflict_{variant}", TEXT["conflict_ambiguous"]),
            actions=tuple(actions),
            metadata={
                "legacy_scenario_bridge": True,
                "scenario_instance_id": context.state.get("scenario_instance_id"),
                "variant": variant,
            },
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        if action_id.startswith("seat_change:"):
            option_id = action_id.split(":", 1)[1]
            if option_id not in _option_ids(context):
                raise ValueError("Unknown seat option.")
            previous = _selected_id(context)
            return EventTransition(
                next_state="active",
                status="active",
                outcome_code="seat_changed",
                state_patch={
                    "selected_option_id": option_id,
                    "previous_option_id": previous,
                },
            )
        if action_id.startswith("respond:"):
            response_type = action_id.split(":", 1)[1]
            if response_type == "free_text" and not response_text.strip():
                raise ValueError("Free-text response requires response_text.")
            scheduled = _schedule_follow_up(context)
            state_patch: dict[str, Any] = {
                "response_type": response_type,
                "follow_up_status": "scheduled"
                if scheduled
                else "not_delivered_day_ended",
            }
            return EventTransition(
                next_state="responded",
                status="completed",
                outcome_code="conflict_response_recorded",
                state_patch=state_patch,
                scheduled_events=scheduled,
            )
        if action_id == "depart":
            scheduled = _schedule_follow_up(context)
            return EventTransition(
                next_state="left",
                status="completed",
                outcome_code="left_scene",
                state_patch={
                    "response_type": "leave",
                    "follow_up_status": "scheduled"
                    if scheduled
                    else "not_delivered_day_ended",
                },
                scheduled_events=scheduled,
            )
        if action_id == "skip":
            return EventTransition(
                next_state="skipped",
                status="completed",
                outcome_code="skipped_without_penalty",
            )
        if action_id == "technical_failure":
            return EventTransition(
                next_state="interrupted",
                status="cancelled",
                outcome_code="interrupted_technical",
            )
        raise ValueError("Unsupported conflict event action.")


class RestaurantConflictFollowUpEvent:
    event_type = RESTAURANT_FOLLOW_UP_EVENT_TYPE
    version = RESTAURANT_FOLLOW_UP_VERSION

    def present(self, context: EventContext) -> EventPresentation:
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key="legacy_restaurant_follow_up",
            titles={"en": "Restaurant follow-up", "zh-CN": "餐厅回访"},
            stimuli=TEXT["follow_up"],
            actions=(),
            metadata={
                "legacy_scenario_bridge": True,
                "scenario_instance_id": context.state.get("scenario_instance_id"),
                "variant": context.state.get("variant"),
            },
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        raise ValueError("Restaurant follow-up is delivered by the runtime.")


def seating_event_state(
    *,
    scenario_instance_id: int,
    form: str,
    selected_option_id: str | None = None,
    viewed_option_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "state": "presented",
        "scenario_instance_id": scenario_instance_id,
        "form": form,
        "options": SEATING_FORMS[form],
        "selected_option_id": selected_option_id,
        "viewed_option_ids": list(viewed_option_ids or []),
    }


def conflict_event_state(
    *,
    scenario_instance_id: int,
    variant: str,
    selected_option_id: str | None,
    options: list[dict[str, Any]],
    assigned_agent_id: int | None,
) -> dict[str, Any]:
    return {
        "state": "presented",
        "scenario_instance_id": scenario_instance_id,
        "form": "booking_mixup",
        "variant": variant,
        "options": options,
        "selected_option_id": selected_option_id,
        "assigned_agent_id": assigned_agent_id,
    }
