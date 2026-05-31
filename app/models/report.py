import enum
from datetime import datetime
from sqlalchemy import String, ForeignKey, Text, DateTime, func, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ReportType(str, enum.Enum):
    department_monthly = "department_monthly"
    semester_performance = "semester_performance"
    attendance_report = "attendance_report"
    academic_analysis = "academic_analysis"
    naac_criterion2 = "naac_criterion2"
    at_risk_students = "at_risk_students"


class ReportFormat(str, enum.Enum):
    pdf = "pdf"
    docx = "docx"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    report_type: Mapped[ReportType] = mapped_column(SAEnum(ReportType), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(SAEnum(ReportFormat), nullable=False, default=ReportFormat.pdf)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    generated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    generated_by_user: Mapped["User"] = relationship(back_populates="reports")  # type: ignore[name-defined]
