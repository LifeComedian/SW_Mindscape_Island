"""World event contracts and declarative effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol


def _freeze(value: Any) -> Any:
    """Recursively copy common containers into read-only equivalents."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = _freeze(value)
    if not isinstance(frozen, Mapping):  # Defensive; the public input is a Mapping.
        raise TypeError("Expected a mapping.")
    return frozen


@dataclass(frozen=True, slots=True)
class EventContext:
    """Read-only world snapshot supplied to an event handler."""

    session_id: int
    world_day: int
    world_time_minutes: int
    location_id: str
    simulation_seed: int
    event_instance_id: int | str | None = None
    visible_agent_ids: tuple[int, ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "visible_agent_ids", tuple(self.visible_agent_ids))
        object.__setattr__(self, "state", _frozen_mapping(self.state))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class EventActionDescriptor:
    """One action that the current event presentation permits."""

    action_id: str
    labels: Mapping[str, str]
    kind: str = "choice"
    enabled: bool = True
    requires_text: bool = False
    target_object_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", _frozen_mapping(self.labels))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class EventPresentation:
    """Participant-visible event content produced from an EventContext."""

    event_type: str
    version: str
    renderer_key: str
    titles: Mapping[str, str]
    stimuli: Mapping[str, str]
    actions: tuple[EventActionDescriptor, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "titles", _frozen_mapping(self.titles))
        object.__setattr__(self, "stimuli", _frozen_mapping(self.stimuli))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class MemoryEffect:
    """A requested memory write for the world runtime to validate and persist."""

    owner_agent_id: int
    memory_type: str
    content: str
    importance: int = 1
    privacy_category: str = "ordinary"
    subject_type: str | None = None
    subject_id: int | str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """A future event request; scheduling and idempotency belong to the runtime."""

    event_type: str
    version: str
    due_day: int
    due_time_minutes: int
    deduplication_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class ImmediateEvent:
    """A validated event that starts after the current flow action completes."""

    event_type: str
    version: str
    trigger_key: str
    location_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class RelationshipEffect:
    """A small, audited resident-to-participant narrative relationship change."""

    source_agent_id: int
    familiarity_delta: int = 0
    trust_delta: int = 0
    warmth_delta: int = 0
    tension_delta: int = 0
    reason_code: str = "declarative_event"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class WorldStateEffect:
    """A bounded request to update an ordinary piece of world state."""

    effect_type: str
    key: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effect_type not in {"upsert_goal", "set_flag"}:
            raise ValueError("Unsupported world-state effect type.")
        if not self.key.strip():
            raise ValueError("World-state effect key cannot be empty.")
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class EventTransition:
    """Declarative effects returned by an event handler.

    A transition does not execute writes.  The future world runtime must validate
    the state patch and effects, attach their source event, and persist them.
    """

    next_state: str
    status: str
    outcome_code: str
    state_patch: Mapping[str, Any] = field(default_factory=dict)
    memory_effects: tuple[MemoryEffect, ...] = ()
    relationship_effects: tuple[RelationshipEffect, ...] = ()
    scheduled_events: tuple[ScheduledEvent, ...] = ()
    immediate_events: tuple[ImmediateEvent, ...] = ()
    world_state_effects: tuple[WorldStateEffect, ...] = ()
    presentation: EventPresentation | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_patch", _frozen_mapping(self.state_patch))
        object.__setattr__(self, "memory_effects", tuple(self.memory_effects))
        object.__setattr__(
            self,
            "relationship_effects",
            tuple(self.relationship_effects),
        )
        object.__setattr__(self, "scheduled_events", tuple(self.scheduled_events))
        object.__setattr__(self, "immediate_events", tuple(self.immediate_events))
        object.__setattr__(
            self,
            "world_state_effects",
            tuple(self.world_state_effects),
        )
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


class WorldEventHandler(Protocol):
    """Interface implemented by a versioned, database-agnostic world event."""

    event_type: str
    version: str

    def present(self, context: EventContext) -> EventPresentation:
        """Build the currently visible event presentation."""

        ...

    def handle_action(
        self,
        context: EventContext,
        action_id: str,
        response_text: str = "",
    ) -> EventTransition:
        """Return requested effects for one allowed participant action."""

        ...


class DuplicateEventHandlerError(ValueError):
    """Raised when an event type/version key is registered more than once."""


class UnknownEventHandlerError(LookupError):
    """Raised when no handler is registered for an exact event version."""


class EventRegistry:
    """Registry that resolves handlers by exact ``(event_type, version)`` keys."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], WorldEventHandler] = {}

    def register(self, handler: WorldEventHandler) -> None:
        event_type = getattr(handler, "event_type", "")
        version = getattr(handler, "version", "")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Event handler event_type must be a non-empty string.")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Event handler version must be a non-empty string.")
        if not callable(getattr(handler, "present", None)) or not callable(
            getattr(handler, "handle_action", None)
        ):
            raise TypeError("Event handler must implement present and handle_action.")

        key = (event_type, version)
        if key in self._handlers:
            raise DuplicateEventHandlerError(
                f"Handler already registered for event_type={event_type!r}, "
                f"version={version!r}."
            )
        self._handlers[key] = handler

    def resolve(self, event_type: str, version: str) -> WorldEventHandler:
        """Resolve one exact version; the registry never guesses a latest version."""

        key = (event_type, version)
        try:
            return self._handlers[key]
        except KeyError as exc:
            available = self.registered_versions(event_type)
            suffix = f" Available versions: {', '.join(available)}." if available else ""
            raise UnknownEventHandlerError(
                f"No handler registered for event_type={event_type!r}, "
                f"version={version!r}.{suffix}"
            ) from exc

    def registered_versions(self, event_type: str) -> tuple[str, ...]:
        """Return deterministic diagnostic output without applying version semantics."""

        return tuple(
            sorted(version for kind, version in self._handlers if kind == event_type)
        )
