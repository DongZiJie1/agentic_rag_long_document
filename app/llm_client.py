"""LLM client abstraction layer"""
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.config import LLMConfig


class LLMClient(ABC):
    """Abstract LLM client interface"""

    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        """
        Generate completion from LLM

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions

        Returns:
            LLM response (包含 text 和 tool_calls 等信息)
        """
        pass


class ClaudeClient(LLMClient):
    """Claude API client"""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        """Call Claude API"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)
        return response  # 返回完整响应对象，包含 content 和 tool_use


class VLLMClient(LLMClient):
    """vLLM client using OpenAI-compatible API"""

    def __init__(self, base_url: str, model: str = "Qwen2.5-7B-Instruct", api_key: str = "EMPTY"):
        import openai
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key
        )
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        """Call vLLM via OpenAI-compatible API"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        return response  # 返回完整响应对象，包含 choices 和 tool_calls


# ══════════════════════════════════════════════════════════════════════════
#  Factory —— 根据配置创建 LLM 客户端
# ══════════════════════════════════════════════════════════════════════════

def _build_claude(config: LLMConfig, model_name: str | None) -> ClaudeClient:
    return ClaudeClient(
        api_key=config.anthropic_api_key,
        model=model_name or config.model_name or "claude-3-5-sonnet-20241022",
    )

def _build_vllm(config: LLMConfig, model_name: str | None) -> VLLMClient:
    return VLLMClient(
        base_url=config.vllm_base_url,
        model=model_name or config.model_name or "Qwen2.5-7B-Instruct",
        api_key=config.vllm_api_key or "EMPTY",
    )

_LLM_BUILDERS: dict[str, Callable[[LLMConfig, str | None], LLMClient]] = {
    "claude": _build_claude,
    "vllm": _build_vllm,
}


def create_llm(config: LLMConfig, model_name: str | None = None) -> LLMClient:
    """根据配置创建 LLM 客户端。model_name 可选，不传则用配置默认值。"""
    builder = _LLM_BUILDERS.get(config.backend)
    if not builder:
        raise ValueError(f"不支持的 LLM 后端: {config.backend}，可选: {list(_LLM_BUILDERS.keys())}")
    return builder(config, model_name)
