"""
LLM Provider Abstraction Layer.
All providers implement BaseLLMProvider so agents never touch SDK-specific code.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        """Generate a complete response (non-streaming)."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Stream response tokens one chunk at a time."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier used for API calls."""
        ...
