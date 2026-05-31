from sqlalchemy import String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    roll_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    batch: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2022-2026"
    section: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Risk score (computed by Performance Agent, stored for caching)
    risk_score: Mapped[float | None] = mapped_column(nullable=True)

    # Relationships
    department: Mapped["Department"] = relationship(back_populates="students")  # type: ignore[name-defined]
    attendance_records: Mapped[list["Attendance"]] = relationship(back_populates="student")  # type: ignore[name-defined]
    marks_records: Mapped[list["Marks"]] = relationship(back_populates="student")  # type: ignore[name-defined]
