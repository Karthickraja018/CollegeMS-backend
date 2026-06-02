"""
Embedding Worker — Processes background embedding generation tasks.

This worker polls the `embedding_jobs` table to process changes 
triggered by the Database Triggers (Phase 6).
"""
import asyncio
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """Background worker to process embedding jobs."""

    def __init__(self, batch_size: int = 50):
        self.batch_size = batch_size
        self._embedding_service = get_embedding_service()

    async def process_pending_jobs(self, db: AsyncSession) -> int:
        """
        Poll the database for pending jobs and process them.
        Returns the number of jobs processed.
        """
        # Lock jobs for processing to prevent concurrent workers from picking them up
        query = text("""
            WITH locked_jobs AS (
                SELECT id
                FROM embedding_jobs
                WHERE status = 'PENDING'
                ORDER BY created_at ASC
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            )
            UPDATE embedding_jobs
            SET status = 'PROCESSING', updated_at = NOW()
            WHERE id IN (SELECT id FROM locked_jobs)
            RETURNING id, entity_type, entity_id, job_type
        """)
        
        result = await db.execute(query, {"batch_size": self.batch_size})
        jobs = result.fetchall()
        
        if not jobs:
            return 0
            
        logger.info(f"Processing {len(jobs)} embedding jobs...")
        
        processed_count = 0
        for job in jobs:
            success = await self._process_job(db, job)
            status = 'COMPLETED' if success else 'FAILED'
            
            await db.execute(text("""
                UPDATE embedding_jobs
                SET status = :status, updated_at = NOW(),
                    attempts = attempts + 1
                WHERE id = :job_id
            """), {"status": status, "job_id": job.id})
            
            if success:
                processed_count += 1
                
        await db.commit()
        return processed_count

    async def _process_job(self, db: AsyncSession, job: Any) -> bool:
        """Process a single job."""
        try:
            if job.job_type == 'DELETE':
                # Remove embeddings for deleted entities
                await self._handle_delete(db, job)
                return True
                
            # For INSERT/UPDATE, we need to fetch the entity and re-embed
            if job.entity_type == 'entity':
                await self._embedding_service.update_all_embeddings(db) # We can optimize this to only update the specific entity later
                return True
            elif job.entity_type == 'terminology':
                await self._embedding_service.update_all_embeddings(db)
                return True
            elif job.entity_type == 'query':
                # Re-embed query
                row = await db.execute(text("SELECT question FROM query_examples WHERE id = :id"), {"id": job.entity_id})
                query_row = row.fetchone()
                if query_row:
                    await self._embedding_service.update_query_embedding(job.entity_id, query_row.question, db)
                return True
            elif job.entity_type == 'metric':
                # Metric embeddings are not implemented yet, but placeholders
                return True
                
            return False
        except Exception as e:
            logger.error(f"Failed to process job {job.id}: {e}")
            return False

    async def _handle_delete(self, db: AsyncSession, job: Any) -> None:
        """Handle deletion of embeddings."""
        if job.entity_type == 'entity':
            await db.execute(text("DELETE FROM entity_embeddings WHERE entity_id = :id"), {"id": job.entity_id})
        elif job.entity_type == 'terminology':
            await db.execute(text("DELETE FROM terminology_embeddings WHERE term_id = :id"), {"id": job.entity_id})
        elif job.entity_type == 'query':
            await db.execute(text("DELETE FROM query_embeddings WHERE query_id = :id"), {"id": job.entity_id})


async def run_worker_loop(get_db_session_func, poll_interval_seconds: int = 60):
    """Run the worker in a continuous background loop."""
    logger.info("Starting embedding background worker loop...")
    worker = EmbeddingWorker()
    
    while True:
        try:
            async with get_db_session_func() as db:
                processed = await worker.process_pending_jobs(db)
                if processed > 0:
                    logger.info(f"Processed {processed} embedding jobs.")
        except Exception as e:
            logger.error(f"Embedding worker loop error: {e}")
            
        await asyncio.sleep(poll_interval_seconds)
