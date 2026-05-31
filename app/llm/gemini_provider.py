"""
Gemini LLM Provider — Primary implementation using google-generativeai SDK.
"""
import asyncio
from typing import AsyncIterator

import google.generativeai as genai

from app.llm.base import BaseLLMProvider
from app.config import get_settings


def _messages_to_gemini(messages: list[dict]) -> list[dict]:
    """Convert generic {role, content} format to Gemini's parts format."""
    result = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        result.append({"role": role, "parts": [msg["content"]]})
    return result


class GeminiProvider(BaseLLMProvider):
    def __init__(self):
        settings = get_settings()
        genai.configure(api_key=settings.gemini_api_key)
        self._model_name = settings.gemini_model
        self._model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

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
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_prompt or None,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        gemini_messages = _messages_to_gemini(messages)

        # Run in thread to avoid blocking the event loop
        response = await asyncio.to_thread(
            model.generate_content,
            gemini_messages,
        )
        return response.text

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_prompt or None,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        gemini_messages = _messages_to_gemini(messages)

        # Use sync streaming in a thread, yield chunks via queue
        import queue as queue_module
        q: queue_module.Queue = queue_module.Queue()
        SENTINEL = object()

        def _stream_sync():
            try:
                for chunk in model.generate_content(gemini_messages, stream=True):
                    if chunk.text:
                        q.put(chunk.text)
            finally:
                q.put(SENTINEL)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _stream_sync)

        while True:
            # Poll the queue without blocking the async loop
            try:
                item = q.get_nowait()
                if item is SENTINEL:
                    break
                yield item
            except queue_module.Empty:
                await asyncio.sleep(0.01)
