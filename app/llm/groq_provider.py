"""
Groq LLM Provider implementation using the groq SDK.
"""
import asyncio
from typing import AsyncIterator
from groq import AsyncGroq

from app.llm.base import BaseLLMProvider
from app.config import get_settings


class GroqProvider(BaseLLMProvider):
    def __init__(self):
        settings = get_settings()
        self._model_name = settings.groq_model
        
        # Instantiate AsyncGroq client
        self._client = AsyncGroq(
            api_key=settings.groq_api_key or "empty",
            timeout=90.0,
        )

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model_name: str | None = None,
    ) -> str:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
            
        for msg in messages:
            role = msg.get("role", "user")
            formatted_messages.append({"role": role, "content": msg.get("content", "")})

        response = await self._client.chat.completions.create(
            model=model_name or self._model_name,
            messages=formatted_messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
        
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        model_name: str | None = None,
    ) -> AsyncIterator[str]:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
            
        for msg in messages:
            role = msg.get("role", "user")
            formatted_messages.append({"role": role, "content": msg.get("content", "")})

        stream_response = await self._client.chat.completions.create(
            model=model_name or self._model_name,
            messages=formatted_messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            stream=True
        )
        
        async for chunk in stream_response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
