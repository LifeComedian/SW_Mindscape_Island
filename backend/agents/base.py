from dataclasses import dataclass, field
from typing import Any, Protocol
from agents.role_prompt import WorldRoleContext


@dataclass(frozen=True)
class AgentRequest:
    session_id: int
    agent_id: int
    post_id: int
    post_content: str
    user_comment: str
    language: str = "en"
    recent_history: list[dict[str, Any]] = field(default_factory=list)
    agent_memory: dict[str, Any] = field(default_factory=dict)
    target_context: str = ""
    reply_target_author: str = ""
    post_author: str = ""
    post_intent: str = ""
    reply_relation: str = ""
    thread_history: list[dict[str, Any]] = field(default_factory=list)
    interaction_kind: str = "reply_to_agent"
    persona_role_context: str = ""
    persona_background_context: str = ""
    world_role_context: WorldRoleContext | None = None


@dataclass(frozen=True)
class AgentResult:
    reply_content: str
    generation_mode: str
    model_provider: str | None
    model_name: str | None
    prompt_version: str
    safety_flag: bool
    latency_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentGenerationError(RuntimeError):
    pass


class Agent(Protocol):
    async def generate_reply(self, request: AgentRequest) -> AgentResult:
        ...
