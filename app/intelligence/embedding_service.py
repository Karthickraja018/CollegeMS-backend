"""
Embedding Service — Multi-Provider Abstraction.

Supports:
  - gemini   : google.generativeai text-embedding-004 (768-dim)
  - groq     : Groq API nomic-embed-text (768-dim)
  - openai   : OpenAI text-embedding-3-small (1536-dim → truncated to 768)
  - nvidia   : NVIDIA NIM NV-Embed-v2 (4096-dim → projected to 768)

Provider is selected via EMBEDDING_PROVIDER env var.
Model can be overridden via EMBEDDING_MODEL env var.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Base
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingProviderBase(ABC):
    """Abstract embedding provider — all implementations must return list[float]."""

    VECTOR_DIM: int = 768

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts (default: sequential)."""
        results = []
        for text in texts:
            results.append(await self.embed(text))
        return results

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider identifier string."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier being used."""

    def _normalize_to_768(self, vec: list[float]) -> list[float]:
        """Truncate or pad vector to 768 dimensions."""
        if len(vec) >= self.VECTOR_DIM:
            return vec[:self.VECTOR_DIM]
        return vec + [0.0] * (self.VECTOR_DIM - len(vec))


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Provider
# ─────────────────────────────────────────────────────────────────────────────

class GeminiEmbeddingProvider(EmbeddingProviderBase):
    """
    Google Gemini text-embedding-004.
    Native 768-dim output — no normalization needed.
    """

    DEFAULT_MODEL = "models/gemini-embedding-2"

    def __init__(self, api_key: str, model: str = ""):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self._genai = genai
        
        raw_model = model or self.DEFAULT_MODEL
        if not raw_model.startswith("models/") and not raw_model.startswith("tunedModels/"):
            raw_model = f"models/{raw_model}"
        self._model = raw_model

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        result = await asyncio.to_thread(
            self._genai.embed_content,
            model=self._model,
            content=text,
            task_type="retrieval_document",
        )
        return self._normalize_to_768(result["embedding"])

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Gemini supports batch embedding natively."""
        result = await asyncio.to_thread(
            self._genai.embed_content,
            model=self._model,
            content=texts,
            task_type="retrieval_document",
        )
        embeddings = result["embedding"]
        # Gemini returns list of lists for batch
        if isinstance(embeddings[0], list):
            return [self._normalize_to_768(vec) for vec in embeddings]
        # Single text returns flat list — wrap it
        return [self._normalize_to_768(embeddings)]


# ─────────────────────────────────────────────────────────────────────────────
# Groq Provider
# ─────────────────────────────────────────────────────────────────────────────

class GroqEmbeddingProvider(EmbeddingProviderBase):
    """
    Groq API embedding.
    Supports nomic-embed-text (768-dim).
    Uses the OpenAI-compatible embeddings endpoint via Groq.
    """

    DEFAULT_MODEL = "nomic-embed-text"

    def __init__(self, api_key: str, model: str = ""):
        from groq import AsyncGroq
        self._client = AsyncGroq(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return self._normalize_to_768(response.data[0].embedding)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [self._normalize_to_768(item.embedding) for item in response.data]


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI Provider
# ─────────────────────────────────────────────────────────────────────────────

class OpenAIEmbeddingProvider(EmbeddingProviderBase):
    """
    OpenAI Embeddings API.
    Uses text-embedding-3-small (1536-dim → truncated to 768).
    """

    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self, api_key: str, model: str = ""):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=768,  # text-embedding-3-small supports custom dimensions
        )
        return self._normalize_to_768(response.data[0].embedding)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=768,
        )
        return [self._normalize_to_768(item.embedding) for item in response.data]


# ─────────────────────────────────────────────────────────────────────────────
# NVIDIA NIM Provider
# ─────────────────────────────────────────────────────────────────────────────

class NvidiaEmbeddingProvider(EmbeddingProviderBase):
    """
    NVIDIA NIM Embedding API (OpenAI-compatible).
    Uses NV-Embed-v2 or baai/bge-m3.
    """

    DEFAULT_MODEL = "baai/bge-m3"
    BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(self, api_key: str, model: str = ""):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            base_url=self.BASE_URL,
            api_key=api_key,
        )
        self._model = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return "nvidia"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            encoding_format="float",
        )
        return self._normalize_to_768(response.data[0].embedding)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            encoding_format="float",
        )
        return [self._normalize_to_768(item.embedding) for item in response.data]


# ─────────────────────────────────────────────────────────────────────────────
# Provider Factory
# ─────────────────────────────────────────────────────────────────────────────

def _create_provider() -> EmbeddingProviderBase:
    """Read EMBEDDING_PROVIDER from settings and return the appropriate provider."""
    from app.config import get_settings
    settings = get_settings()

    provider_name = settings.embedding_provider.lower().strip()
    model_override = settings.embedding_model.strip()

    if provider_name == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is required for Groq embedding provider")
        model = model_override or settings.groq_embedding_model
        logger.info(f"Using Groq embedding provider: {model}")
        return GroqEmbeddingProvider(api_key=settings.groq_api_key, model=model)

    elif provider_name == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embedding provider")
        logger.info(f"Using OpenAI embedding provider: {model_override or 'text-embedding-3-small'}")
        return OpenAIEmbeddingProvider(api_key=settings.openai_api_key, model=model_override)

    elif provider_name == "nvidia":
        if not settings.nvidia_api_key:
            raise ValueError("NVIDIA_API_KEY is required for NVIDIA embedding provider")
        logger.info(f"Using NVIDIA NIM embedding provider: {model_override or 'baai/bge-m3'}")
        return NvidiaEmbeddingProvider(api_key=settings.nvidia_api_key, model=model_override)

    else:
        # Default: Gemini
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini embedding provider")
        logger.info(f"Using Gemini embedding provider: {model_override or 'models/text-embedding-004'}")
        return GeminiEmbeddingProvider(api_key=settings.gemini_api_key, model=model_override)


# ─────────────────────────────────────────────────────────────────────────────
# EmbeddingService — Main Interface
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingService:
    """
    High-level embedding service used by the intelligence layer.
    Delegates to the configured provider (Gemini / Groq / OpenAI / NVIDIA).
    """

    def __init__(self, provider: Optional[EmbeddingProviderBase] = None):
        self._provider = provider or _create_provider()

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    async def generate(self, text: str) -> list[float]:
        """Generate a single embedding vector for the given text."""
        try:
            return await self._provider.embed(text.strip())
        except Exception as e:
            logger.error(f"Embedding generation failed ({self.provider_name}): {e}")
            raise

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        try:
            cleaned = [t.strip() for t in texts if t.strip()]
            return await self._provider.embed_batch(cleaned)
        except Exception as e:
            logger.error(f"Batch embedding failed ({self.provider_name}): {e}")
            # Fall back to sequential on batch failure
            logger.warning("Falling back to sequential embedding for batch")
            return [await self.generate(t) for t in texts if t.strip()]

    async def update_entity_embedding(
        self, entity_id: int, embedding_text: str, db
    ) -> None:
        """Regenerate and store embedding for a single entity."""
        from sqlalchemy import text as sql_text
        vec = await self.generate(embedding_text)
        await db.execute(
            sql_text("""
                INSERT INTO entity_embeddings (entity_id, embedding, model_version, embedding_text, updated_at)
                VALUES (:eid, :emb, :model, :txt, NOW())
                ON CONFLICT (entity_id) DO UPDATE
                  SET embedding = EXCLUDED.embedding,
                      model_version = EXCLUDED.model_version,
                      embedding_text = EXCLUDED.embedding_text,
                      updated_at = NOW()
            """),
            {"eid": entity_id, "emb": str(vec), "model": self.model_name, "txt": embedding_text},
        )

    async def update_term_embedding(
        self, term_id: int, embedding_text: str, db
    ) -> None:
        """Regenerate and store embedding for a single terminology entry."""
        from sqlalchemy import text as sql_text
        vec = await self.generate(embedding_text)
        await db.execute(
            sql_text("""
                INSERT INTO terminology_embeddings (term_id, embedding, model_version, embedding_text, updated_at)
                VALUES (:tid, :emb, :model, :txt, NOW())
                ON CONFLICT (term_id) DO UPDATE
                  SET embedding = EXCLUDED.embedding,
                      model_version = EXCLUDED.model_version,
                      embedding_text = EXCLUDED.embedding_text,
                      updated_at = NOW()
            """),
            {"tid": term_id, "emb": str(vec), "model": self.model_name, "txt": embedding_text},
        )

    async def update_query_embedding(
        self, query_id: int, embedding_text: str, db
    ) -> None:
        """Regenerate and store embedding for a query example."""
        from sqlalchemy import text as sql_text
        vec = await self.generate(embedding_text)
        await db.execute(
            sql_text("""
                INSERT INTO query_embeddings (query_id, embedding, model_version, embedding_text, updated_at)
                VALUES (:qid, :emb, :model, :txt, NOW())
                ON CONFLICT (query_id) DO UPDATE
                  SET embedding = EXCLUDED.embedding,
                      model_version = EXCLUDED.model_version,
                      embedding_text = EXCLUDED.embedding_text,
                      updated_at = NOW()
            """),
            {"qid": query_id, "emb": str(vec), "model": self.model_name, "txt": embedding_text},
        )

    async def update_all_embeddings(self, db) -> dict:
        """
        Full re-embedding pass for all entities, terms, and query examples.
        Called by KnowledgeSeeder after initial data load.
        Returns summary counts.
        """
        from sqlalchemy import text as sql_text

        counts = {"entities": 0, "terms": 0, "queries": 0, "errors": 0}

        # ── Entities ────────────────────────────────────────────────────────
        result = await db.execute(sql_text(
            "SELECT id, entity_name, description, aliases FROM semantic_entities WHERE is_active = TRUE"
        ))
        entities = result.fetchall()
        for row in entities:
            try:
                text_to_embed = (
                    f"Entity: {row.entity_name}. "
                    f"Description: {row.description}. "
                    f"Also known as: {', '.join(row.aliases or [])}."
                )
                await self.update_entity_embedding(row.id, text_to_embed, db)
                counts["entities"] += 1
            except Exception as e:
                logger.warning(f"Failed to embed entity {row.entity_name}: {e}")
                counts["errors"] += 1

        # ── Terminology ─────────────────────────────────────────────────────
        result = await db.execute(sql_text(
            "SELECT id, term, full_form, definition, aliases FROM academic_terminology WHERE is_active = TRUE"
        ))
        terms = result.fetchall()
        for row in terms:
            try:
                full_form_str = f" ({row.full_form})" if row.full_form else ""
                aliases_str = f" Also: {', '.join(row.aliases or [])}." if row.aliases else ""
                text_to_embed = (
                    f"Term: {row.term}{full_form_str}. "
                    f"Definition: {row.definition}.{aliases_str}"
                )
                await self.update_term_embedding(row.id, text_to_embed, db)
                counts["terms"] += 1
            except Exception as e:
                logger.warning(f"Failed to embed term {row.term}: {e}")
                counts["errors"] += 1

        # ── Query Examples ───────────────────────────────────────────────────
        result = await db.execute(sql_text(
            "SELECT id, question FROM query_examples WHERE success = TRUE"
        ))
        queries = result.fetchall()
        for row in queries:
            try:
                await self.update_query_embedding(row.id, row.question, db)
                counts["queries"] += 1
            except Exception as e:
                logger.warning(f"Failed to embed query {row.id}: {e}")
                counts["errors"] += 1

        await db.commit()

        # ── Create ivfflat indexes after data is loaded ─────────────────────
        await self._create_vector_indexes(db, counts)

        logger.info(
            f"Embedding update complete: {counts['entities']} entities, "
            f"{counts['terms']} terms, {counts['queries']} queries, "
            f"{counts['errors']} errors"
        )
        return counts

    async def _create_vector_indexes(self, db, counts: dict) -> None:
        """Create ivfflat indexes after rows exist (required by ivfflat)."""
        from sqlalchemy import text as sql_text
        try:
            if counts["entities"] > 0:
                await db.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_entity_emb_cosine "
                    "ON entity_embeddings USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 50)"
                ))
            if counts["terms"] > 0:
                await db.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_term_emb_cosine "
                    "ON terminology_embeddings USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 30)"
                ))
            if counts["queries"] > 0:
                await db.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_query_emb_cosine "
                    "ON query_embeddings USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 20)"
                ))
            await db.commit()
        except Exception as e:
            logger.warning(f"Could not create ivfflat indexes (may already exist): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Return the singleton EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
