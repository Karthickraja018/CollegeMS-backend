import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Date, func, ForeignKey, SmallInteger, Enum as SAEnum, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class AttendanceStatus(str, enum.Enum):
    present = 'present'
    absent = 'absent'
    od = 'od'
    medical_leave = 'medical_leave'
    duty_leave = 'duty_leave'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .student import Student
    from .subject import Subject


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"), nullable=False)
    marked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    period: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(SAEnum(AttendanceStatus), default=AttendanceStatus.present, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    student: Mapped["Student"] = relationship(back_populates="attendance_records")
    subject: Mapped["Subject"] = relationship(back_populates="attendance_records")
