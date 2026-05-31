from sqlalchemy import String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, default=4)

    # Relationships
    department: Mapped["Department"] = relationship(back_populates="subjects")  # type: ignore[name-defined]
    attendance_records: Mapped[list["Attendance"]] = relationship(back_populates="subject")  # type: ignore[name-defined]
    marks_records: Mapped[list["Marks"]] = relationship(back_populates="subject")  # type: ignore[name-defined]
