from agents.base import AgentGenerationError, AgentRequest, AgentResult
from agents.llm_agent import LLMAgent
from agents.rule_based import RuleBasedAgent
from config import Settings, settings


class AgentService:
    def __init__(self, runtime_settings: Settings = settings):
        self.settings = runtime_settings
        self.rule_agent = RuleBasedAgent()
        self.llm_agent = LLMAgent(runtime_settings=runtime_settings)

    async def generate_reply(self, request: AgentRequest) -> AgentResult:
        mode = self.settings.agent_mode
        if mode == "rule":
            return await self.rule_agent.generate_reply(request)

        should_try_llm = mode == "llm" or (
            mode == "auto"
            and self.settings.has_llm_config
        )

        if should_try_llm:
            try:
                return await self.llm_agent.generate_reply(request)
            except AgentGenerationError as exc:
                from agents.output_safety import ModelStop
                raise ModelStop('agent_generation_failure') from None

        return await self.rule_agent.generate_reply(request)
