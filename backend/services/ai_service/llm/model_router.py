"""
LLM model router — routes requests to the appropriate model via vLLM or Ollama.
Provides a unified interface for all services.
"""
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from openai import AsyncOpenAI

from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_used: int
    finish_reason: str


class ModelRouter:
    """
    Routes AI requests to local models.
    Uses vLLM in production, falls back to Ollama for dev.
    """

    def __init__(self):
        # vLLM uses OpenAI-compatible API
        self._vllm = AsyncOpenAI(
            base_url=settings.VLLM_BASE_URL,
            api_key=settings.VLLM_API_KEY,
        )
        # Ollama also supports OpenAI-compatible API
        self._ollama = AsyncOpenAI(
            base_url=f"{settings.OLLAMA_BASE_URL}/v1",
            api_key="ollama",
        )

    def _get_client(self) -> AsyncOpenAI:
        """Use vLLM in production, Ollama in development."""
        return self._vllm if settings.is_production else self._ollama

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        model = model or settings.LLM_PRIMARY_MODEL
        temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        max_tokens = max_tokens or settings.LLM_MAX_TOKENS

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as exc:
            logger.error(f"LLM generation failed model={model}: {exc}")
            raise

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        model = model or settings.LLM_PRIMARY_MODEL
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        client = self._get_client()
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature or settings.LLM_TEMPERATURE,
            stream=True,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def embed(self, texts: list[str] | str, model: str | None = None) -> list[list[float]]:
        """Generate embeddings using the embedding model."""
        model = model or settings.LLM_EMBEDDING_MODEL
        if isinstance(texts, str):
            texts = [texts]
        client = self._get_client()
        response = await client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    async def embed_single(self, text: str) -> list[float]:
        embeddings = await self.embed([text])
        return embeddings[0]


# Singleton
llm = ModelRouter()
