import enum
from datetime import date
from sqlalchemy import String, ForeignKey, Date, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent = "absent"
    late = "late"


class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        SAEnum(AttendanceStatus), nullable=False, default=AttendanceStatus.present
    )

    # Relationships
    student: Mapped["Student"] = relationship(back_populates="attendance_records")  # type: ignore[name-defined]
    subject: Mapped["Subject"] = relationship(back_populates="attendance_records")  # type: ignore[name-defined]
