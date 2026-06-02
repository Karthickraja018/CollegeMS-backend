import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey, SmallInteger, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class ProgramType(str, enum.Enum):
    ug = 'ug'
    pg = 'pg'
    diploma = 'diploma'
    certificate = 'certificate'
    phd = 'phd'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .department import Department
    from .semester import Semester
    from .student import Student
    from .subject import Subject


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[ProgramType] = mapped_column(SAEnum(ProgramType), nullable=False)
    duration_years: Mapped[int] = mapped_column(SmallInteger, default=4, nullable=False)
    total_semesters: Mapped[int] = mapped_column(SmallInteger, default=8, nullable=False)
    total_credits: Mapped[int] = mapped_column(SmallInteger, default=160, nullable=False)
    intake_capacity: Mapped[int | None] = mapped_column(SmallInteger)
    is_nba_accredited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    department: Mapped["Department"] = relationship(back_populates="programs")
    semesters: Mapped[list["Semester"]] = relationship(back_populates="program")
    students: Mapped[list["Student"]] = relationship(back_populates="program")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="program")
