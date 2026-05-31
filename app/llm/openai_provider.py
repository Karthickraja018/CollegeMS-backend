"""OpenAI provider stub — implement by installing openai and filling in the SDK calls."""
from typing import AsyncIterator
from app.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return "gpt-4o"

    async def generate(self, messages, system_prompt="", temperature=0.2, max_tokens=8192) -> str:
        raise NotImplementedError("OpenAI provider not yet configured. Set LLM_PROVIDER=gemini or implement this class.")

    async def stream(self, messages, system_prompt="", temperature=0.2, max_tokens=8192) -> AsyncIterator[str]:
        raise NotImplementedError("OpenAI provider not yet configured.")
        yield  # Make it a generator
