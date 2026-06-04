"""
Background task scheduler using APScheduler to periodically compute
and update the performance metrics for staff, departments, and students.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
from datetime import datetime
import logging

from app.database import AsyncSessionLocal
from sqlalchemy import text

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def compute_monthly_metrics():
    """Background task to compute monthly performance metrics."""
    logger.info(f"Starting monthly metrics computation at {datetime.now()}")
    async with AsyncSessionLocal() as db:
        try:
            # Monthly snapshot logic for staff_performance_metrics and hod_performance_metrics
            logger.info("Computing metrics... (placeholder for complex SQL aggregation)")
            # In a production setting, this would call complex CTEs or a stored procedure 
            # to aggregate attendance, marks, feedback, and populate the monthly metrics tables.
            pass
        except Exception as e:
            logger.error(f"Error computing metrics: {e}")
        finally:
            await db.commit()

def start_scheduler():
    """Initialize and start the background scheduler."""
    # Run at midnight on the 1st of every month
    scheduler.add_job(compute_monthly_metrics, "cron", day=1, hour=0, minute=0)
    scheduler.start()
    logger.info("APScheduler started")

def shutdown_scheduler():
    """Shutdown the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shutdown")
