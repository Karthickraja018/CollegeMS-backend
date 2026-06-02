"""
Agent Context Bus — Shared singleton for all agents.

The AgentContextBus is the single entry point for all agents to:
  1. Retrieve semantic context before generating SQL/reports/analysis
  2. Record feedback after query execution
  3. Store successful queries into query memory

Usage:
    bus = get_context_bus()
    ctx = await bus.get_context(question, db, agent_type="query")
    # ctx["schema_summary"] → inject into LLM prompt
    # ctx["terminology"]    → use for term resolution
    # ctx["entities"]       → validate tables/columns
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.context_retrieval import ContextRetrievalService
from app.intelligence.context_assembler import ContextAssembler

logger = logging.getLogger(__name__)


class AgentContextBus:
    """
    Shared intelligence context bus.
    All agents call this instead of querying the database schema directly.
    """

    def __init__(self):
        self._retrieval_svc = ContextRetrievalService()
        self._assembler = ContextAssembler()

    async def get_context(
        self,
        question: str,
        db: AsyncSession,
        agent_type: str = "query",
    ) -> dict[str, Any]:
        """
        Full context pipeline:
        1. Retrieve relevant entities, terminology, query examples via pgvector
        2. Fetch join relationships for matched entities
        3. Assemble structured context dict
        4. Return to agent

        Returns:
            dict with keys: entities, join_paths, terminology, query_examples,
                           business_rules, schema_summary, meta
        """
        t0 = time.monotonic()
        try:
            retrieval = await self._retrieval_svc.retrieve(
                question=question,
                db=db,
                agent_type=agent_type,
            )
            context = self._assembler.assemble(retrieval, agent_type=agent_type)
            elapsed = (time.monotonic() - t0) * 1000
            context["meta"]["total_ms"] = round(elapsed, 1)
            logger.info(
                f"[AgentContextBus] {agent_type} context ready in {elapsed:.0f}ms "
                f"— {len(context['entities'])} entities, "
                f"{len(context['terminology'])} terms, "
                f"{len(context['query_examples'])} query examples"
            )
            return context
        except Exception as e:
            logger.error(f"[AgentContextBus] Context retrieval failed: {e}", exc_info=True)
            # Return a safe empty context — agents will still function with rule-based fallback
            return self._empty_context(question, agent_type, str(e))

    def _empty_context(
        self, question: str, agent_type: str, error: str = ""
    ) -> dict[str, Any]:
        """Return an empty context structure when retrieval fails."""
        return {
            "entities": [],
            "join_paths": [],
            "terminology": {},
            "query_examples": [],
            "business_rules": [],
            "schema_summary": "",
            "meta": {
                "question": question,
                "agent_type": agent_type,
                "error": error,
                "entities_found": 0,
                "terms_found": 0,
                "queries_found": 0,
            }
        }

    async def record_feedback(
        self,
        *,
        original_question: str,
        generated_sql: Optional[str],
        exec_time_ms: Optional[int],
        success: bool,
        error_message: Optional[str] = None,
        user_rating: Optional[int] = None,
        agent_used: str = "query",
        user_role: Optional[str] = None,
        db: AsyncSession,
    ) -> Optional[int]:
        """
        Store query execution feedback in query_feedback table.
        Returns the feedback record ID.
        """
        try:
            result = await db.execute(
                text("""
                    INSERT INTO query_feedback
                        (original_question, generated_sql, exec_time_ms,
                         success, error_message, user_rating, agent_used, user_role)
                    VALUES
                        (:q, :sql, :ms, :ok, :err, :rating, :agent, :role)
                    RETURNING id
                """),
                {
                    "q": original_question,
                    "sql": generated_sql,
                    "ms": exec_time_ms,
                    "ok": success,
                    "err": error_message,
                    "rating": user_rating,
                    "agent": agent_used,
                    "role": user_role,
                }
            )
            row = result.fetchone()
            await db.commit()
            return row.id if row else None
        except Exception as e:
            logger.warning(f"Failed to record query feedback: {e}")
            return None

    async def store_successful_query(
        self,
        *,
        question: str,
        generated_sql: str,
        result_summary: str,
        entities_used: list[str],
        tables_used: list[str],
        metrics_used: list[str] = None,
        agent_used: str = "query",
        query_type: str = "descriptive",
        exec_time_ms: Optional[int] = None,
        db: AsyncSession,
    ) -> Optional[int]:
        """
        Store a successful query into query_examples for future retrieval.
        Automatically generates embedding for the question.
        Returns the query_example ID.
        """
        try:
            result = await db.execute(
                text("""
                    INSERT INTO query_examples
                        (question, generated_sql, result_summary,
                         entities_used, metrics_used, tables_used,
                         agent_used, query_type, feedback_score, success,
                         exec_time_ms, source)
                    VALUES
                        (:q, :sql, :summary,
                         :entities::jsonb, :metrics::jsonb, :tables::jsonb,
                         :agent, :qtype, 0.8, TRUE,
                         :ms, 'runtime')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                {
                    "q": question,
                    "sql": generated_sql.strip(),
                    "summary": result_summary,
                    "entities": json.dumps(entities_used),
                    "metrics": json.dumps(metrics_used or []),
                    "tables": json.dumps(tables_used),
                    "agent": agent_used,
                    "qtype": query_type,
                    "ms": exec_time_ms,
                }
            )
            row = result.fetchone()
            await db.commit()

            if row:
                qid = row.id
                # Generate embedding asynchronously (non-blocking)
                asyncio.create_task(
                    self._embed_query_async(qid, question, db)
                )
                return qid
            return None
        except Exception as e:
            logger.warning(f"Failed to store successful query: {e}")
            return None

    async def _embed_query_async(
        self, query_id: int, question: str, db: AsyncSession
    ) -> None:
        """Background task: generate embedding for a newly stored query."""
        try:
            from app.intelligence.embedding_service import get_embedding_service
            svc = get_embedding_service()
            await svc.update_query_embedding(query_id, question, db)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to embed query {query_id}: {e}")

    async def get_intelligence_status(self, db: AsyncSession) -> dict[str, Any]:
        """Return counts from the knowledge store for monitoring."""
        try:
            result = await db.execute(text("SELECT metric, value FROM get_intelligence_status()"))
            rows = result.fetchall()
            status = {row.metric: row.value for row in rows}
            status["healthy"] = all(v > 0 for v in status.values())
            return status
        except Exception as e:
            logger.warning(f"Failed to get intelligence status: {e}")
            return {"healthy": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_context_bus: Optional[AgentContextBus] = None


def get_context_bus() -> AgentContextBus:
    """Return the singleton AgentContextBus instance."""
    global _context_bus
    if _context_bus is None:
        _context_bus = AgentContextBus()
    return _context_bus
