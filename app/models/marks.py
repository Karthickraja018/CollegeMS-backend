import enum
from sqlalchemy import String, ForeignKey, Integer, Float, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ExamType(str, enum.Enum):
    internal1 = "internal1"
    internal2 = "internal2"
    internal3 = "internal3"
    semester_end = "semester_end"
    assignment = "assignment"
    practical = "practical"


class Marks(Base):
    __tablename__ = "marks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    exam_type: Mapped[ExamType] = mapped_column(SAEnum(ExamType), nullable=False)
    marks_obtained: Mapped[float] = mapped_column(Float, nullable=False)
    max_marks: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)

    # Relationships
    student: Mapped["Student"] = relationship(back_populates="marks_records")  # type: ignore[name-defined]
    subject: Mapped["Subject"] = relationship(back_populates="marks_records")  # type: ignore[name-defined]
