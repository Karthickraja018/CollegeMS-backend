import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey, SmallInteger, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class SubjectType(str, enum.Enum):
    theory = 'theory'
    practical = 'practical'
    theory_cum_practical = 'theory_cum_practical'
    project = 'project'
    seminar = 'seminar'
    internship = 'internship'
    mooc = 'mooc'
    audit_course = 'audit_course'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .department import Department
    from .program import Program
    from .attendance import AttendanceRecord
    from .marks import MarksRecord


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SubjectType] = mapped_column(SAEnum(SubjectType), default=SubjectType.theory, nullable=False)
    semester_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    credits: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    lecture_hours: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    tutorial_hours: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    practical_hours: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    # total_hours and is_lab are generated in DB
    is_elective: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    regulations: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    department: Mapped["Department"] = relationship(back_populates="subjects")
    program: Mapped["Program"] = relationship(back_populates="subjects")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="subject")
    marks_records: Mapped[list["MarksRecord"]] = relationship(back_populates="subject")
