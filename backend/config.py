import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


PROVIDER_DEFAULT_BASE_URLS = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.ai/v1",
    "moonshot": "https://api.moonshot.ai/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "tokenhub": "https://tokenhub.tencentmaas.com/v1",
    "qianfan": "https://qianfan.baidubce.com/v2",
    "baidu": "https://qianfan.baidubce.com/v2",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "ark": "https://ark.cn-beijing.volces.com/api/v3",
    "minimax": "https://api.minimax.io/v1",
}


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "")
        if value:
            return value
    return ""


@dataclass(frozen=True)
class Settings:
    agent_mode: str = os.getenv("AGENT_MODE", "auto").lower()
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai").lower()
    llm_api_key: str = _first_env(
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "ZHIPU_API_KEY",
        "BIGMODEL_API_KEY",
        "HUNYUAN_API_KEY",
        "QIANFAN_API_KEY",
        "ARK_API_KEY",
        "MINIMAX_API_KEY",
    )
    llm_base_url: str = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    llm_max_history_items: int = int(os.getenv("LLM_MAX_HISTORY_ITEMS", "6"))
    llm_network_mode: str = os.getenv("LLM_NETWORK_MODE", "direct")
    llm_proxy_url: str = os.getenv("LLM_PROXY_URL", "")
    llm_ca_bundle: str = os.getenv("LLM_CA_BUNDLE", "")
    llm_connect_timeout_seconds: float = float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "5"))
    llm_total_deadline_seconds: float = float(os.getenv("LLM_TOTAL_DEADLINE_SECONDS", "20"))
    llm_max_output_tokens: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512"))
    llm_max_input_bytes: int = int(os.getenv("LLM_MAX_INPUT_BYTES", "32768"))
    llm_transport_retries: int = int(os.getenv("LLM_TRANSPORT_RETRIES", "1"))
    llm_thinking: str = os.getenv("LLM_THINKING", "auto")
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "")
    llm_structured_mode: str = os.getenv("LLM_STRUCTURED_MODE", "json_object")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    @property
    def resolved_llm_base_url(self) -> str:
        return self.llm_base_url or PROVIDER_DEFAULT_BASE_URLS.get(self.llm_provider, "")

    @property
    def resolved_llm_api_key(self) -> str:
        return self.llm_api_key or self.openai_api_key

    @property
    def has_llm_config(self) -> bool:
        if not self.resolved_llm_api_key or not self.llm_model:
            return False
        if self.llm_provider == "openai":
            return True
        return bool(self.resolved_llm_base_url)


settings = Settings()
