"""Anthropic Claude provider stub."""
from typing import AsyncIterator
from app.llm.base import BaseLLMProvider


class ClaudeProvider(BaseLLMProvider):
    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return "claude-3-5-sonnet-20241022"

    async def generate(self, messages, system_prompt="", temperature=0.2, max_tokens=8192) -> str:
        raise NotImplementedError("Claude provider not yet configured. Set LLM_PROVIDER=gemini or implement this class.")

    async def stream(self, messages, system_prompt="", temperature=0.2, max_tokens=8192) -> AsyncIterator[str]:
        raise NotImplementedError("Claude provider not yet configured.")
        yield
