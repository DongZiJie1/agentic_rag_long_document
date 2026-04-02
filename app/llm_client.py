"""LLM client abstraction layer"""
from abc import ABC, abstractmethod
from typing import Any


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
