"""
NVIDIA NIM LLM Provider — Uses the OpenAI SDK configured for NVIDIA endpoints.
"""
from typing import AsyncIterator
from openai import AsyncOpenAI
import asyncio

from app.llm.base import BaseLLMProvider
from app.config import get_settings


class NvidiaProvider(BaseLLMProvider):
    def __init__(self):
        settings = get_settings()
        self._model_name = settings.nvidia_model
        
        # NVIDIA NIM API requires OpenAI client configured with their base_url
        self._client = AsyncOpenAI(
            api_key=settings.nvidia_api_key or "empty",
            base_url="https://integrate.api.nvidia.com/v1"
        )

    @property
    def provider_name(self) -> str:
        return "nvidia"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
            
        for msg in messages:
            role = msg.get("role", "user")
            formatted_messages.append({"role": role, "content": msg.get("content", "")})

        response = await self._client.chat.completions.create(
            model=self._model_name,
            messages=formatted_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
            
        for msg in messages:
            role = msg.get("role", "user")
            formatted_messages.append({"role": role, "content": msg.get("content", "")})

        stream_response = await self._client.chat.completions.create(
            model=self._model_name,
            messages=formatted_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )
        
        async for chunk in stream_response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
