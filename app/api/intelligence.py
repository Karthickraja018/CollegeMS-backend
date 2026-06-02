"""
Agent Intelligence Layer — Admin API.

Endpoints:
  GET  /api/intelligence/status   — knowledge store health and counts
  POST /api/intelligence/seed     — manually trigger knowledge seeding
  POST /api/intelligence/re-embed — regenerate all embeddings
  GET  /api/intelligence/search   — debug: test semantic search for a question
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.permissions import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence Layer"])


@router.get("/status")
async def get_intelligence_status(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(["admin", "college_admin", "principal"])),
):
    """
    Return health status of the Agent Intelligence Layer.
    Shows counts for entities, terminology, query examples, and embeddings.
    """
    from app.intelligence.agent_context_bus import get_context_bus
    bus = get_context_bus()
    status = await bus.get_intelligence_status(db)
    return {
        "status": "healthy" if status.get("healthy") else "degraded",
        "knowledge_store": status,
    }


@router.post("/seed")
async def seed_knowledge_store(
    force: bool = Query(default=False, description="Force re-seed even if data exists"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(["admin", "college_admin"])),
):
    """
    Manually trigger knowledge store seeding.
    Use force=true to re-seed even if data already exists.
    """
    from app.intelligence.knowledge_seeder import KnowledgeSeeder
    try:
        if force:
            counts = await KnowledgeSeeder.seed_all(db)
            return {"seeded": True, "forced": True, "counts": counts}
        else:
            seeded = await KnowledgeSeeder.seed_if_empty(db)
            return {"seeded": seeded, "forced": False}
    except Exception as e:
        logger.error(f"Knowledge seeding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Seeding failed: {str(e)}")


@router.post("/re-embed")
async def regenerate_embeddings(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(["admin", "college_admin"])),
):
    """
    Regenerate all vector embeddings for entities, terminology, and query examples.
    Use when switching embedding provider or upgrading the model.
    """
    from app.intelligence.embedding_service import get_embedding_service
    try:
        svc = get_embedding_service()
        counts = await svc.update_all_embeddings(db)
        return {
            "success": True,
            "provider": svc.provider_name,
            "model": svc.model_name,
            "counts": counts,
        }
    except Exception as e:
        logger.error(f"Re-embedding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Re-embedding failed: {str(e)}")


@router.get("/search")
async def debug_semantic_search(
    q: str = Query(..., description="Question to search for"),
    agent_type: str = Query(default="query", description="Agent type for config lookup"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(["admin", "college_admin", "principal"])),
):
    """
    Debug endpoint: perform a semantic search and return the full context.
    Useful for testing retrieval quality.
    """
    from app.intelligence.agent_context_bus import get_context_bus
    try:
        bus = get_context_bus()
        context = await bus.get_context(question=q, db=db, agent_type=agent_type)
        return {
            "question": q,
            "entities_found": len(context.get("entities", [])),
            "terms_found": len(context.get("terminology", {})),
            "queries_found": len(context.get("query_examples", [])),
            "retrieval_ms": context.get("meta", {}).get("total_ms"),
            "entities": context.get("entities", []),
            "terminology": context.get("terminology", {}),
            "query_examples": context.get("query_examples", []),
            "business_rules": context.get("business_rules", []),
            "schema_summary": context.get("schema_summary", ""),
        }
    except Exception as e:
        logger.error(f"Semantic search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/provider")
async def get_embedding_provider_info(
    _user=Depends(require_role(["admin", "college_admin"])),
):
    """Return the currently configured embedding provider info."""
    from app.intelligence.embedding_service import get_embedding_service
    try:
        svc = get_embedding_service()
        return {
            "provider": svc.provider_name,
            "model": svc.model_name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
