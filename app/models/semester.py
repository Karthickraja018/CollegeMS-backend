import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Date, func, ForeignKey, SmallInteger, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class SemesterStatus(str, enum.Enum):
    upcoming = 'upcoming'
    ongoing = 'ongoing'
    completed = 'completed'
    results_published = 'results_published'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .academic_year import AcademicYear
    from .program import Program


class Semester(Base):
    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    semester_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    status: Mapped[SemesterStatus] = mapped_column(SAEnum(SemesterStatus), default=SemesterStatus.upcoming, nullable=False)
    working_days: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    academic_year: Mapped["AcademicYear"] = relationship(back_populates="semesters")
    program: Mapped["Program"] = relationship(back_populates="semesters")
