import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey, Enum as SAEnum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class ReportType(str, enum.Enum):
    department_monthly = 'department_monthly'
    department_semester = 'department_semester'
    attendance_summary = 'attendance_summary'
    marks_analysis = 'marks_analysis'
    at_risk_students = 'at_risk_students'
    naac_criterion_1 = 'naac_criterion_1'
    naac_criterion_2 = 'naac_criterion_2'
    naac_criterion_3 = 'naac_criterion_3'
    naac_criterion_4 = 'naac_criterion_4'
    naac_criterion_5 = 'naac_criterion_5'
    naac_criterion_6 = 'naac_criterion_6'
    naac_criterion_7 = 'naac_criterion_7'
    nba_sar = 'nba_sar'
    nirf = 'nirf'
    annual_report = 'annual_report'
    custom = 'custom'

class ReportFormat(str, enum.Enum):
    pdf = 'pdf'
    docx = 'docx'
    xlsx = 'xlsx'
    pptx = 'pptx'

class ReportStatus(str, enum.Enum):
    queued = 'queued'
    generating = 'generating'
    completed = 'completed'
    failed = 'failed'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False)
    generated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[ReportType] = mapped_column(SAEnum(ReportType), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(SAEnum(ReportFormat), default=ReportFormat.pdf, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500))
    file_size_kb: Mapped[int | None] = mapped_column(Integer)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(SAEnum(ReportStatus), default=ReportStatus.queued, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    validation_passed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    generated_by_user: Mapped["User"] = relationship(back_populates="reports_generated")
