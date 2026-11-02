"""Pure handlers for validated, data-only ordinary island events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from world.events import (
    EventActionDescriptor,
    EventContext,
    EventPresentation,
    EventTransition,
    ImmediateEvent,
    MemoryEffect,
    RelationshipEffect,
    ScheduledEvent,
    WorldStateEffect,
)
from world.clock import advance_clock
from world.npc_responses import generate_npc_response
from world.specs import (
    BehavioralEventActionContentSpec,
    BehavioralEventStageContentSpec,
    EventActionContentSpec,
    EventContentSpec,
    WorldSpec,
)


DECLARATIVE_RENDERER_KEY = "declarative_event"


def _next_follow_up_due(
    *,
    context: EventContext,
    target: EventContentSpec,
    world_spec: WorldSpec,
) -> tuple[int, int]:
    minimum_day = int(target.prerequisites.get("min_day", 1))
    maximum_day = int(
        target.prerequisites.get("max_day", world_spec.calendar.total_days)
    )
    window_start, window_end = target.time_window or (
        world_spec.calendar.day_start_minute,
        world_spec.calendar.day_end_minute,
    )
    for day in range(max(context.world_day, minimum_day), maximum_day + 1):
        if day == context.world_day:
            minute = max(window_start, context.world_time_minutes + 5)
        else:
            minute = window_start
        if minute <= window_end:
            return day, minute
    raise ValueError("The declared follow-up has no future eligible time.")


class DeclarativeEventHandler:
    """Interprets one fully validated EventContentSpec without executable content."""

    def __init__(self, event_spec: EventContentSpec, world_spec: WorldSpec) -> None:
        self.event_spec = event_spec
        self.world_spec = world_spec
        self.event_type = event_spec.event_type
        self.version = event_spec.version
        self._actions = {item.action_id: item for item in event_spec.actions}

    def present(self, context: EventContext) -> EventPresentation:
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key=self.event_spec.renderer_key or DECLARATIVE_RENDERER_KEY,
            titles=self.event_spec.title,
            stimuli=self.event_spec.stimulus,
            actions=tuple(
                EventActionDescriptor(
                    action_id=action.action_id,
                    labels=action.label,
                    kind="choice",
                    requires_text=action.requires_text,
                    metadata={"outcome_key": action.outcome_key},
                )
                for action in self.event_spec.actions
            ),
            metadata={
                "declarative": True,
                "event_id": self.event_spec.event_id,
            },
        )

    def _memory_effects(
        self,
        action: EventActionContentSpec,
    ) -> tuple[MemoryEffect, ...]:
        if action.outcome_key != "remember":
            return ()
        owner_agent_id = action.memory_owner_agent_id
        if owner_agent_id is None:
            return ()
        memory_text = action.memory_text or self.event_spec.stimulus
        content = memory_text.get("en") or next(iter(memory_text.values()), "")
        if not content:
            return ()
        return (
            MemoryEffect(
                owner_agent_id=owner_agent_id,
                memory_type="episodic",
                content=content,
                importance=1,
                privacy_category="ordinary",
                subject_type="ordinary_story_event",
                subject_id=self.event_spec.event_id,
                metadata={
                    "effect_key": f"{action.action_id}:story_memory",
                    "tags": ("declarative_event", self.event_spec.event_id),
                    "related_agent_ids": (owner_agent_id,),
                },
            ),
        )

    def _relationship_effects(
        self,
        action: EventActionContentSpec,
    ) -> tuple[RelationshipEffect, ...]:
        effect = action.relationship_effect
        if action.outcome_key != "relationship_delta" or not isinstance(effect, Mapping):
            return ()
        return (
            RelationshipEffect(
                source_agent_id=int(effect["target_agent_id"]),
                familiarity_delta=int(effect.get("familiarity_delta", 0)),
                trust_delta=int(effect.get("trust_delta", 0)),
                warmth_delta=int(effect.get("warmth_delta", 0)),
                tension_delta=int(effect.get("tension_delta", 0)),
                metadata={"effect_key": f"{action.action_id}:relationship"},
            ),
        )

    def _scheduled_events(
        self,
        context: EventContext,
        action: EventActionContentSpec,
    ) -> tuple[ScheduledEvent, ...]:
        if action.outcome_key != "schedule_follow_up" or not action.follow_up_event_id:
            return ()
        target = self.world_spec.event_specs[action.follow_up_event_id]
        due_day, due_minute = _next_follow_up_due(
            context=context,
            target=target,
            world_spec=self.world_spec,
        )
        return (
            ScheduledEvent(
                event_type=target.event_type,
                version=target.version,
                due_day=due_day,
                due_time_minutes=due_minute,
                deduplication_key=(
                    f"declarative:{context.event_instance_id}:"
                    f"{action.action_id}:{target.event_id}"
                ),
                payload={
                    "event_id": target.event_id,
                    "location_id": target.location_ids[0],
                    "state": {
                        "state": "presented",
                        "event_id": target.event_id,
                        "source_event_instance_id": context.event_instance_id,
                    },
                },
            ),
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        action = self._actions.get(action_id)
        if action is None:
            raise ValueError("Unsupported declarative event action.")
        if action.requires_text and not response_text.strip():
            raise ValueError("This declarative action requires text.")
        if not action.requires_text and response_text.strip():
            raise ValueError("This declarative action does not accept text.")
        outcome_code = {
            "complete": "completed",
            "leave": "left",
            "remember": "story_remembered",
            "relationship_delta": "relationship_updated",
            "schedule_follow_up": "follow_up_scheduled",
        }[action.outcome_key]
        return EventTransition(
            next_state=outcome_code,
            status="completed",
            outcome_code=outcome_code,
            state_patch={
                "last_action_id": action.action_id,
                "response_recorded": bool(response_text.strip()),
            },
            memory_effects=self._memory_effects(action),
            relationship_effects=self._relationship_effects(action),
            scheduled_events=self._scheduled_events(context, action),
            metadata={
                "declarative": True,
                "event_id": self.event_spec.event_id,
                "outcome_key": action.outcome_key,
            },
        )


class BehavioralEventHandler:
    """Pure interpreter for validated multi-stage behavioral event content."""

    def __init__(self, event_spec: EventContentSpec, world_spec: WorldSpec) -> None:
        if not event_spec.stages or not event_spec.initial_stage_id:
            raise ValueError("Behavioral event content requires an initial stage.")
        self.event_spec = event_spec
        self.world_spec = world_spec
        self.event_type = event_spec.event_type
        self.version = event_spec.version
        self._stages = {stage.stage_id: stage for stage in event_spec.stages}

    def _stage(self, context: EventContext) -> BehavioralEventStageContentSpec:
        raw_state = context.state.get("state")
        stage_id = (
            raw_state
            if isinstance(raw_state, str) and raw_state in self._stages
            else self.event_spec.initial_stage_id
        )
        return self._stages[str(stage_id)]

    @staticmethod
    def _action(
        stage: BehavioralEventStageContentSpec,
        action_id: str,
    ) -> BehavioralEventActionContentSpec | None:
        return next((item for item in stage.actions if item.action_id == action_id), None)

    def present(self, context: EventContext) -> EventPresentation:
        stage = self._stage(context)
        npc_response = context.state.get("npc_response")
        response_payload = dict(npc_response) if isinstance(npc_response, Mapping) else None
        return EventPresentation(
            event_type=self.event_type,
            version=self.version,
            renderer_key=self.event_spec.renderer_key,
            titles=stage.title,
            stimuli=stage.stimulus,
            actions=tuple(
                EventActionDescriptor(
                    action_id=action.action_id,
                    labels=action.label,
                    kind=action.action_type,
                    requires_text=action.requires_text,
                    target_object_id=action.target_id,
                    metadata={
                        "behavioral_action_type": action.action_type,
                        "target_type": action.target_type,
                        "target_agent_id": action.target_agent_id,
                        "target_location_id": action.target_location_id,
                        "terminal": action.terminal,
                    },
                )
                for action in stage.actions
            ),
            metadata={
                "declarative": True,
                "behavioral_event": True,
                "event_id": self.event_spec.event_id,
                "stage_id": stage.stage_id,
                "npc_response": response_payload,
            },
        )

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        stage = self._stage(context)
        action = self._action(stage, action_id)
        if action is None:
            raise ValueError("Unsupported behavioral event action.")
        normalized_response = response_text.strip()
        if action.requires_text and not normalized_response:
            raise ValueError("This behavioral event action requires text.")
        if not action.requires_text and normalized_response:
            raise ValueError("This behavioral event action does not accept text.")

        next_state = action.outcome_code if action.terminal else str(action.next_stage_id)
        state_patch: dict[str, Any] = {
            **dict(action.state_updates),
            "last_action_id": action.action_id,
            "last_stage_id": stage.stage_id,
            "response_recorded": bool(normalized_response),
            "npc_response": None,
        }
        response_metadata: dict[str, Any] = {}
        if action.npc_response is not None:
            response_config = dict(action.npc_response)
            npc_id = int(response_config["npc_id"])
            resident = self.world_spec.residents[npc_id]
            recent_history = context.state.get("conversation_history", ())
            safe_history = (
                tuple(item for item in recent_history if isinstance(item, Mapping))[-8:]
                if isinstance(recent_history, (tuple, list))
                else ()
            )
            generated = generate_npc_response(
                npc_id=npc_id,
                session_id=context.session_id,
                event_context={
                    "npc_name": resident.name,
                    "npc_identity": dict(resident.role),
                    "npc_personality": dict(resident.profile.get("personality", {})),
                    "npc_background": dict(resident.background),
                    "npc_communication_style": dict(
                        resident.profile.get("communication_style", {})
                    ),
                    "relationship_with_player": "runtime_relationship_context",
                    "event_id": self.event_spec.event_id,
                    "event_type": self.event_type,
                    "stage_id": stage.stage_id,
                    "location_id": context.location_id,
                    "world_day": context.world_day,
                    "world_time_minutes": context.world_time_minutes,
                    "event_facts": dict(self.event_spec.llm_context),
                    "current_goal": context.state.get("trigger_goals", {}),
                    "knowledge_boundary": self.event_spec.llm_context.get(
                        "knowledge_boundary", ()
                    ),
                },
                player_message=normalized_response,
                conversation_history=safe_history,
                static_text=dict(response_config["text"]),
                intent=str(response_config.get("intent", "ordinary_reply")),
            )
            state_patch["npc_response"] = {
                "provider": generated.provider,
                "npc_id": generated.npc_id,
                "text": dict(generated.text),
                "intent": generated.intent,
            }
            next_history = list(safe_history)
            if normalized_response:
                next_history.append(
                    {"speaker": "participant", "content": normalized_response}
                )
            next_history.append(
                {
                    "speaker": "npc",
                    "npc_id": generated.npc_id,
                    "content": dict(generated.text),
                }
            )
            state_patch["conversation_history"] = next_history[-8:]
            response_metadata = {
                "npc_response_provider": generated.provider,
                "npc_response_npc_id": generated.npc_id,
                "npc_response_intent": generated.intent,
            }

        world_effects: tuple[WorldStateEffect, ...] = ()
        if action.goal_effect is not None:
            goal = dict(action.goal_effect)
            world_effects = (
                WorldStateEffect(
                    effect_type="upsert_goal",
                    key=str(goal["goal_id"]),
                    payload=goal,
                ),
            )

        memory_effects: list[MemoryEffect] = []
        relationship_effects: list[RelationshipEffect] = []
        scheduled_events: list[ScheduledEvent] = []
        immediate_events: list[ImmediateEvent] = []
        typed_world_effects = list(world_effects)
        configured_minutes = action.action_minutes
        relocation_target = action.target_location_id
        public_messages: list[Mapping[str, str]] = []
        for effect_index, frozen_effect in enumerate(action.effects):
            effect = dict(frozen_effect)
            effect_type = str(effect["type"])
            if effect_type == "advance_time":
                configured_minutes = int(effect["minutes"])
            elif effect_type == "set_flag":
                typed_world_effects.append(
                    WorldStateEffect(
                        effect_type="set_flag",
                        key=str(effect["flag_id"]),
                        payload={"value": bool(effect.get("value", True))},
                    )
                )
            elif effect_type == "goal_update":
                payload = dict(effect["goal"])
                typed_world_effects.append(
                    WorldStateEffect(
                        effect_type="upsert_goal",
                        key=str(payload["goal_id"]),
                        payload=payload,
                    )
                )
            elif effect_type == "relationship_delta":
                relationship_effects.append(
                    RelationshipEffect(
                        source_agent_id=int(effect["target_agent_id"]),
                        familiarity_delta=int(effect.get("familiarity_delta", 0)),
                        trust_delta=int(effect.get("trust_delta", 0)),
                        warmth_delta=int(effect.get("warmth_delta", 0)),
                        tension_delta=int(effect.get("tension_delta", 0)),
                        reason_code="declarative_event",
                        metadata={"effect_key": f"{action.action_id}:{effect_index}"},
                    )
                )
            elif effect_type == "add_memory":
                text = effect["text"]
                content = text.get("en") or next(iter(text.values()))
                memory_effects.append(
                    MemoryEffect(
                        owner_agent_id=int(effect["owner_agent_id"]),
                        memory_type="episodic",
                        content=str(content),
                        metadata={
                            "effect_key": f"{action.action_id}:{effect_index}",
                            "tags": tuple(effect.get("tags", ())),
                        },
                    )
                )
            elif effect_type in {"start_event", "schedule_event"}:
                target = self.world_spec.event_specs[str(effect["event_id"])]
                payload = {"event_id": target.event_id, "state": target.initial_stage_id or "presented"}
                if effect_type == "start_event":
                    immediate_events.append(
                        ImmediateEvent(
                            event_type=target.event_type,
                            version=target.version,
                            trigger_key=f"flow:{context.event_instance_id}:{action.action_id}:{effect_index}",
                            location_id=context.location_id,
                            payload=payload,
                        )
                    )
                else:
                    due = advance_clock(
                        self.world_spec.calendar,
                        context.world_day,
                        context.world_time_minutes,
                        int(effect["delay_minutes"]),
                    ).after
                    scheduled_events.append(
                        ScheduledEvent(
                            event_type=target.event_type,
                            version=target.version,
                            due_day=due.day,
                            due_time_minutes=due.minute,
                            deduplication_key=f"flow:{context.event_instance_id}:{action.action_id}:{effect_index}",
                            payload=payload,
                        )
                    )
            elif effect_type == "move_participant":
                relocation_target = str(effect["location_id"])
            elif effect_type == "show_message":
                public_messages.append(effect["text"])
        if public_messages:
            state_patch["flow_messages"] = public_messages

        return EventTransition(
            next_state=next_state,
            status="completed" if action.terminal else "active",
            outcome_code=action.outcome_code,
            state_patch=state_patch,
            memory_effects=tuple(memory_effects),
            relationship_effects=tuple(relationship_effects),
            scheduled_events=tuple(scheduled_events),
            immediate_events=tuple(immediate_events),
            world_state_effects=tuple(typed_world_effects),
            metadata={
                "declarative": True,
                "behavioral_event": True,
                "event_id": self.event_spec.event_id,
                "stage_id": stage.stage_id,
                "behavioral_action_type": action.action_type,
                "event_action_minutes": configured_minutes,
                "target_type": action.target_type,
                "target_id": action.target_id,
                "target_agent_id": action.target_agent_id,
                "target_location_id": relocation_target,
                "relocate_participant": relocation_target is not None and any(dict(item).get("type") == "move_participant" for item in action.effects),
                "flow_effects": [dict(item) for item in action.effects],
                "action_metadata": dict(action.metadata),
                "goal_effect": dict(action.goal_effect) if action.goal_effect else None,
                **response_metadata,
            },
        )


def resolve_declarative_event_handler(
    world_spec: WorldSpec,
    *,
    event_type: str,
    event_version: str,
    event_id: str | None = None,
) -> DeclarativeEventHandler | None:
    if event_id is not None:
        candidate = world_spec.event_specs.get(event_id)
        if (
            candidate is not None
            and candidate.event_type == event_type
            and candidate.version == event_version
        ):
            return (
                BehavioralEventHandler(candidate, world_spec)
                if candidate.stages
                else DeclarativeEventHandler(candidate, world_spec)
            )
        return None
    matches = [
        item
        for item in world_spec.event_specs.values()
        if item.event_type == event_type and item.version == event_version
    ]
    if len(matches) != 1:
        return None
    candidate = matches[0]
    return (
        BehavioralEventHandler(candidate, world_spec)
        if candidate.stages
        else DeclarativeEventHandler(candidate, world_spec)
    )
