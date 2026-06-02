import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey, Enum as SAEnum, Text, BigInteger, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class ExamTypeEnum(str, enum.Enum):
    cia1 = 'cia1'
    cia2 = 'cia2'
    cia3 = 'cia3'
    model = 'model'
    semester_end = 'semester_end'
    practical = 'practical'
    viva = 'viva'
    assignment = 'assignment'
    quiz = 'quiz'
    project_review = 'project_review'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .student import Student
    from .subject import Subject


class MarksRecord(Base):
    __tablename__ = "marks_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"), nullable=False)
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    exam_type: Mapped[ExamTypeEnum] = mapped_column(SAEnum(ExamTypeEnum), nullable=False)
    marks_obtained: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    max_marks: Mapped[float] = mapped_column(Numeric(6, 2), default=100, nullable=False)
    grade_points: Mapped[float | None] = mapped_column(Numeric(4, 2))
    grade: Mapped[str | None] = mapped_column(String(5))
    is_absent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_withheld: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped["Student"] = relationship(back_populates="marks_records")
    subject: Mapped["Subject"] = relationship(back_populates="marks_records")
