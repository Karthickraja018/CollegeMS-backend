"""
Context Retrieval Service — Semantic search over the knowledge store.

Input : User question (natural language)
Output: RetrievalResult with ranked entities, terminology, query examples
Uses  : pgvector RPC functions via Supabase
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievedEntity:
    entity_id: int
    entity_name: str
    description: str
    primary_table: str
    join_key: Optional[str]
    aliases: list[str]
    attributes: list[str]
    business_rules: list[str]
    similarity: float


@dataclass
class RetrievedTerm:
    term_id: int
    term: str
    full_form: Optional[str]
    definition: str
    category: Optional[str]
    db_mapping: Optional[str]
    db_table: Optional[str]
    aliases: list[str]
    similarity: float


@dataclass
class RetrievedQuery:
    query_id: int
    question: str
    generated_sql: str
    result_summary: Optional[str]
    entities_used: list[str]
    metrics_used: list[str]
    tables_used: list[str]
    agent_used: Optional[str]
    query_type: Optional[str]
    feedback_score: Optional[float]
    similarity: float


@dataclass
class EntityRelationship:
    from_entity: str
    relationship: str
    to_entity: str
    join_sql: str
    description: Optional[str]
    confidence: float


@dataclass
class RetrievalResult:
    """Complete retrieval result returned to the ContextAssembler."""
    question: str
    entities: list[RetrievedEntity] = field(default_factory=list)
    terminology: list[RetrievedTerm] = field(default_factory=list)
    query_examples: list[RetrievedQuery] = field(default_factory=list)
    relationships: list[EntityRelationship] = field(default_factory=list)
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Context Retrieval Service
# ─────────────────────────────────────────────────────────────────────────────

class ContextRetrievalService:
    """
    Semantic retrieval engine for the Agent Intelligence Layer.
    Embeds the user question and searches entity/terminology/query stores.
    """

    def __init__(
        self,
        top_k_entities: int = 10,
        top_k_terms: int = 8,
        top_k_queries: int = 5,
        score_threshold: float = 0.60,
    ):
        self._top_k_entities = top_k_entities
        self._top_k_terms = top_k_terms
        self._top_k_queries = top_k_queries
        self._score_threshold = score_threshold

    async def retrieve(
        self,
        question: str,
        db: AsyncSession,
        agent_type: str = "query",
    ) -> RetrievalResult:
        """
        Full retrieval pipeline:
        1. Generate question embedding
        2. Search entities, terminology, query examples in parallel
        3. Fetch relationships for matched entities
        4. Return merged RetrievalResult
        """
        t_start = time.monotonic()

        result = RetrievalResult(question=question)

        # ── Step 1: Generate embedding ────────────────────────────────────
        embed_start = time.monotonic()
        try:
            svc = get_embedding_service()
            query_vec = await svc.generate(question)
        except Exception as e:
            logger.error(f"Failed to embed question: {e}")
            # Return empty result — agents will fall back to rule-based context
            result.retrieval_ms = (time.monotonic() - t_start) * 1000
            return result
        result.embedding_ms = (time.monotonic() - embed_start) * 1000

        # Load per-agent config from context_registry if available
        top_k_e, top_k_t, top_k_q, threshold = await self._load_agent_config(
            db, agent_type
        )

        # ── Step 2: Parallel semantic search ─────────────────────────────
        import asyncio
        entities_task = self._search_entities(db, query_vec, top_k_e, threshold)
        terms_task    = self._search_terminology(db, query_vec, top_k_t, threshold - 0.05)
        queries_task  = self._search_queries(db, query_vec, top_k_q, threshold)

        entities, terms, queries = await asyncio.gather(
            entities_task, terms_task, queries_task,
            return_exceptions=True
        )

        result.entities    = entities    if isinstance(entities, list)    else []
        result.terminology = terms       if isinstance(terms, list)       else []
        result.query_examples = queries  if isinstance(queries, list)     else []

        # ── Step 3: Fetch relationships for matched entities ──────────────
        if result.entities:
            entity_names = [e.entity_name for e in result.entities]
            result.relationships = await self._get_relationships(db, entity_names)

        result.retrieval_ms = (time.monotonic() - t_start) * 1000
        logger.debug(
            f"Retrieval complete in {result.retrieval_ms:.0f}ms "
            f"({len(result.entities)} entities, {len(result.terminology)} terms, "
            f"{len(result.query_examples)} query examples)"
        )
        return result

    async def _load_agent_config(
        self, db: AsyncSession, agent_type: str
    ) -> tuple[int, int, int, float]:
        """Load per-agent retrieval config from context_registry."""
        try:
            row = await db.execute(
                text("""
                    SELECT top_k_entities, top_k_terms, top_k_queries, score_threshold
                    FROM context_registry
                    WHERE agent_type = :agent AND is_active = TRUE
                """),
                {"agent": agent_type},
            )
            cfg = row.fetchone()
            if cfg:
                return cfg.top_k_entities, cfg.top_k_terms, cfg.top_k_queries, float(cfg.score_threshold)
        except Exception:
            pass
        return self._top_k_entities, self._top_k_terms, self._top_k_queries, self._score_threshold

    async def _search_entities(
        self, db: AsyncSession, query_vec: list[float], top_k: int, threshold: float
    ) -> list[RetrievedEntity]:
        """Call search_entities RPC and return typed results."""
        try:
            vec_str = f"[{','.join(str(x) for x in query_vec)}]"
            result = await db.execute(
                text("SELECT * FROM search_entities(:vec::vector, :k, :t)"),
                {"vec": vec_str, "k": top_k, "t": threshold},
            )
            rows = result.fetchall()
            return [
                RetrievedEntity(
                    entity_id=row.entity_id,
                    entity_name=row.entity_name,
                    description=row.description,
                    primary_table=row.primary_table,
                    join_key=row.join_key,
                    aliases=row.aliases or [],
                    attributes=row.attributes or [],
                    business_rules=row.business_rules or [],
                    similarity=float(row.similarity),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Entity search failed: {e}")
            return []

    async def _search_terminology(
        self, db: AsyncSession, query_vec: list[float], top_k: int, threshold: float
    ) -> list[RetrievedTerm]:
        """Call search_terminology RPC and return typed results."""
        try:
            vec_str = f"[{','.join(str(x) for x in query_vec)}]"
            result = await db.execute(
                text("SELECT * FROM search_terminology(:vec::vector, :k, :t)"),
                {"vec": vec_str, "k": top_k, "t": max(threshold, 0.45)},
            )
            rows = result.fetchall()
            return [
                RetrievedTerm(
                    term_id=row.term_id,
                    term=row.term,
                    full_form=row.full_form,
                    definition=row.definition,
                    category=row.category,
                    db_mapping=row.db_mapping,
                    db_table=row.db_table,
                    aliases=row.aliases or [],
                    similarity=float(row.similarity),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Terminology search failed: {e}")
            return []

    async def _search_queries(
        self, db: AsyncSession, query_vec: list[float], top_k: int, threshold: float
    ) -> list[RetrievedQuery]:
        """Call search_query_examples RPC and return typed results."""
        try:
            vec_str = f"[{','.join(str(x) for x in query_vec)}]"
            result = await db.execute(
                text("SELECT * FROM search_query_examples(:vec::vector, :k, :t, TRUE)"),
                {"vec": vec_str, "k": top_k, "t": threshold},
            )
            rows = result.fetchall()
            return [
                RetrievedQuery(
                    query_id=row.query_id,
                    question=row.question,
                    generated_sql=row.generated_sql,
                    result_summary=row.result_summary,
                    entities_used=row.entities_used or [],
                    metrics_used=row.metrics_used or [],
                    tables_used=row.tables_used or [],
                    agent_used=row.agent_used,
                    query_type=row.query_type,
                    feedback_score=float(row.feedback_score) if row.feedback_score else None,
                    similarity=float(row.similarity),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Query example search failed: {e}")
            return []

    async def _get_relationships(
        self, db: AsyncSession, entity_names: list[str]
    ) -> list[EntityRelationship]:
        """Fetch join relationships for retrieved entity names."""
        try:
            import json
            result = await db.execute(
                text("SELECT * FROM get_entity_relationships(:names::text[])"),
                {"names": entity_names},
            )
            rows = result.fetchall()
            return [
                EntityRelationship(
                    from_entity=row.from_entity,
                    relationship=row.relationship,
                    to_entity=row.to_entity,
                    join_sql=row.join_sql,
                    description=row.description,
                    confidence=float(row.confidence),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Relationship fetch failed: {e}")
            return []
