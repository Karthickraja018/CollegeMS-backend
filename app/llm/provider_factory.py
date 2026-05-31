"""
Provider Factory — reads LLM_PROVIDER from config and returns the correct implementation.
To add a new provider: create a new file in llm/, then add one entry here.
"""
from functools import lru_cache
from app.llm.base import BaseLLMProvider
from app.config import get_settings


@lru_cache
def get_llm_provider() -> BaseLLMProvider:
    """Return the configured LLM provider instance (singleton via lru_cache)."""
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        from app.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
    elif provider == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif provider == "claude":
        from app.llm.claude_provider import ClaudeProvider
        return ClaudeProvider()
    elif provider == "nvidia":
        from app.llm.nvidia_provider import NvidiaProvider
        return NvidiaProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            "Set LLM_PROVIDER to one of: gemini, openai, claude"
        )
