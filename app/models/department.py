from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .college import College
    from .program import Program
    from .student import Student
    from .subject import Subject
    from .user import User


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    hod_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    phone_ext: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    established_year: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    college: Mapped["College"] = relationship(back_populates="departments")
    programs: Mapped[list["Program"]] = relationship(back_populates="department")
    students: Mapped[list["Student"]] = relationship(back_populates="department")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="department")
    users: Mapped[list["User"]] = relationship(back_populates="department", foreign_keys="User.department_id")
