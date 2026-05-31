"""
FastAPI application entry point.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base

# Import all models so Alembic can detect them
import app.models  # noqa: F401

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (dev only — use Alembic in prod)."""
    os.makedirs(settings.reports_dir, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="CollegeMS API",
    description="AI-Powered College Management System — Single College MVP",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.analytics import router as analytics_router
from app.api.students import router as students_router
from app.api.upload import router as upload_router
from app.api.reports import router as reports_router

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(students_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(reports_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "CollegeMS API", "version": "1.0.0"}
