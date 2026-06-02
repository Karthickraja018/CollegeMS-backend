"""
FastAPI application entry point — Academic Intelligence Platform.

Registered routers:
  Core:     auth, chat, analytics, students
  New:      dashboard (role-scoped), student-intelligence, department-intelligence, data-sync
  Admin:    dashboard, academic, users, students, attendance, exams, ai_ops, reports, settings, import
  Removed:  finance, placements (deprecated — not an ERP)
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base

# Import all models so SQLAlchemy can detect them
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
    title="Academic Intelligence Platform API",
    description="AI-Powered Academic Intelligence Platform — Role-Based, Data-Driven",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Core Routes ───────────────────────────────────────────────────────────────
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

# ── Role-Scoped Dashboard (NEW) ───────────────────────────────────────────────
from app.api.dashboard import router as dashboard_router
app.include_router(dashboard_router, prefix="/api")

# ── Intelligence APIs (NEW) ───────────────────────────────────────────────────
from app.api.student_intelligence import router as student_intel_router
from app.api.department_intelligence import router as dept_intel_router
app.include_router(student_intel_router, prefix="/api")
app.include_router(dept_intel_router, prefix="/api")

# ── Data Sync (NEW) ───────────────────────────────────────────────────────────
from app.api.data_sync import router as data_sync_router
app.include_router(data_sync_router, prefix="/api")

# ── Admin Module Routes — Phase 1 ─────────────────────────────────────────────
from app.api.admin.dashboard import router as admin_dashboard_router
from app.api.admin.academic import router as admin_academic_router
from app.api.admin.users import router as admin_users_router
from app.api.admin.students import router as admin_students_router

app.include_router(admin_dashboard_router, prefix="/api")
app.include_router(admin_academic_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(admin_students_router, prefix="/api")

# ── Admin Module Routes — Phase 2 ─────────────────────────────────────────────
from app.api.admin.attendance import router as admin_attendance_router
from app.api.admin.exams import router as admin_exams_router
# Finance and Placements removed — not part of Academic Intelligence Platform
from app.api.admin.notifications import router as admin_notifications_router
from app.api.admin.audit import router as admin_audit_router
from app.api.admin.ai_ops import router as admin_ai_ops_router
from app.api.admin.reports_settings import reports_router as admin_reports_router
from app.api.admin.reports_settings import settings_router as admin_settings_router

app.include_router(admin_attendance_router, prefix="/api")
app.include_router(admin_exams_router, prefix="/api")
app.include_router(admin_notifications_router, prefix="/api")
app.include_router(admin_audit_router, prefix="/api")
app.include_router(admin_ai_ops_router, prefix="/api")
app.include_router(admin_reports_router, prefix="/api")
app.include_router(admin_settings_router, prefix="/api")



# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Academic Intelligence Platform API",
        "version": "2.0.0",
        "roles": ["admin", "principal", "hod", "faculty"],
    }
