"""Event response provider interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence


def _freeze(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class NpcResponseRequest:
    npc_id: int
    session_id: int
    event_context: Mapping[str, Any]
    player_message: str
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    static_text: Mapping[str, str] = field(default_factory=dict)
    intent: str = "ordinary_reply"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_context", _freeze(self.event_context))
        object.__setattr__(
            self,
            "conversation_history",
            tuple(_freeze(item) for item in self.conversation_history),
        )
        object.__setattr__(self, "static_text", MappingProxyType(dict(self.static_text)))


@dataclass(frozen=True, slots=True)
class NpcResponse:
    provider: str
    npc_id: int
    text: Mapping[str, str]
    intent: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", MappingProxyType(dict(self.text)))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


class NpcResponseProvider(Protocol):
    provider_key: str

    def generate(self, request: NpcResponseRequest) -> NpcResponse:
        ...


class StaticNpcResponseProvider:
    provider_key = "static"

    def generate(self, request: NpcResponseRequest) -> NpcResponse:
        if not request.static_text:
            raise ValueError("Static NPC responses require localized static_text.")
        return NpcResponse(
            provider=self.provider_key,
            npc_id=request.npc_id,
            text=request.static_text,
            intent=request.intent,
            metadata={"replaceable_with_llm": True},
        )


def generate_npc_response(
    *,
    npc_id: int,
    session_id: int,
    event_context: Mapping[str, Any],
    player_message: str,
    conversation_history: Sequence[Mapping[str, Any]],
    static_text: Mapping[str, str],
    intent: str = "ordinary_reply",
    provider: NpcResponseProvider | None = None,
) -> NpcResponse:
    """Generate one event response through the replaceable provider boundary."""

    selected_provider = provider or StaticNpcResponseProvider()
    return selected_provider.generate(
        NpcResponseRequest(
            npc_id=npc_id,
            session_id=session_id,
            event_context=event_context,
            player_message=player_message,
            conversation_history=tuple(conversation_history),
            static_text=static_text,
            intent=intent,
        )
    )
