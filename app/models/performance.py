"""
Performance tracking models for faculty and HOD monthly KPI snapshots.
Used by the Principal Intelligence Platform to monitor staff performance over time.
"""
from sqlalchemy import Column, Integer, Numeric, Date, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class StaffPerformanceMetric(Base):
    """Monthly performance snapshot for a faculty member."""
    __tablename__ = "staff_performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    month = Column(Date, nullable=False)  # first day of month (e.g. 2025-12-01)

    # Compliance metrics
    attendance_submission_pct = Column(Numeric(5, 2))   # % attendance submitted on time
    marks_submission_pct = Column(Numeric(5, 2))        # % marks submitted on time

    # Academic outcomes
    student_pass_rate = Column(Numeric(5, 2))           # avg pass rate of taught students
    avg_student_attendance = Column(Numeric(5, 2))      # avg attendance in their classes

    # Engagement
    feedback_score = Column(Numeric(3, 1))              # student feedback 1.0–5.0
    classes_conducted = Column(Integer, default=0)      # total classes taken
    ai_usage_count = Column(Integer, default=0)         # AI queries made in platform
    report_count = Column(Integer, default=0)           # reports generated

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    department = relationship("Department")


class HodPerformanceMetric(Base):
    """Monthly performance snapshot for an HOD's department leadership."""
    __tablename__ = "hod_performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    month = Column(Date, nullable=False)  # first day of month

    # Department health
    dept_health_score = Column(Numeric(5, 2))            # composite health score
    faculty_compliance_rate = Column(Numeric(5, 2))      # % faculty submitting on time
    student_risk_count = Column(Integer, default=0)      # at-risk students in dept

    # Academic
    pass_rate = Column(Numeric(5, 2))
    attendance_rate = Column(Numeric(5, 2))

    # Leadership
    review_meetings_held = Column(Integer, default=0)    # meetings scheduled & held
    faculty_feedback_avg = Column(Numeric(3, 1))         # faculty satisfaction with HOD

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    department = relationship("Department")
