from sqlalchemy import Column, Integer, String, Numeric, Date, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class InstitutionMetric(Base):
    __tablename__ = "institution_metrics"

    id = Column(Integer, primary_key=True, index=True)
    college_id = Column(Integer, ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    academic_health = Column(Numeric(5, 2))
    attendance_rate = Column(Numeric(5, 2))
    pass_rate = Column(Numeric(5, 2))
    placement_rate = Column(Numeric(5, 2))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    college = relationship("College")


class DepartmentMetric(Base):
    __tablename__ = "department_metrics"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    attendance_rate = Column(Numeric(5, 2))
    pass_rate = Column(Numeric(5, 2))
    health_score = Column(Numeric(5, 2))
    risk_students_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    department = relationship("Department")


class StudentRiskScore(Base):
    __tablename__ = "student_risk_scores"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    risk_score = Column(Numeric(5, 2))
    risk_level = Column(String(20)) # critical, high, medium, low
    dropout_probability = Column(Numeric(4, 2))
    arrear_probability = Column(Numeric(4, 2))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    student = relationship("Student")


class AccreditationMetric(Base):
    __tablename__ = "accreditation_metrics"

    id = Column(Integer, primary_key=True, index=True)
    college_id = Column(Integer, ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    nba_score = Column(Numeric(5, 2))
    naac_score = Column(Numeric(5, 2))
    documentation_score = Column(Numeric(5, 2))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    college = relationship("College")


class ExecutiveInsight(Base):
    __tablename__ = "executive_insights"

    id = Column(Integer, primary_key=True, index=True)
    college_id = Column(Integer, ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    summary = Column(Text, nullable=False)
    recommendation = Column(Text)
    priority = Column(String(20)) # high, medium, low
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    college = relationship("College")
