"""LLM client abstraction layer"""
from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Abstract LLM client interface"""

    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """
        Generate completion from LLM

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions

        Returns:
            Raw LLM response text
        """
        pass


class ClaudeClient(LLMClient):
    """Claude API client"""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """Call Claude API"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        # Extract text content from response
        if response.content:
            for block in response.content:
                if hasattr(block, 'text'):
                    return block.text

        return ""


class VLLMClient(LLMClient):
    """vLLM client using OpenAI-compatible API"""

    def __init__(self, base_url: str, model: str = "Qwen2.5-7B-Instruct", api_key: str = "EMPTY"):
        import openai
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key
        )
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """Call vLLM via OpenAI-compatible API"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)

        if response.choices:
            return response.choices[0].message.content or ""

        return ""
