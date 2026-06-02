import enum
from datetime import datetime
from sqlalchemy import Text, String, Integer, Boolean, DateTime, Date, func, ForeignKey, Enum as SAEnum, JSON, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class StudentStatus(str, enum.Enum):
    active = 'active'
    inactive = 'inactive'
    detained = 'detained'
    arrear = 'arrear'
    lateral_entry = 'lateral_entry'
    transferred_in = 'transferred_in'
    transferred_out = 'transferred_out'
    passed_out = 'passed_out'
    discontinued = 'discontinued'

class GenderEnum(str, enum.Enum):
    male = 'male'
    female = 'female'
    other = 'other'
    prefer_not_to_say = 'prefer_not_to_say'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .college import College
    from .department import Department
    from .program import Program
    from .attendance import AttendanceRecord
    from .marks import MarksRecord
    from .fee_account import FeeAccount
    from .placement_application import PlacementApplication


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), nullable=False)
    roll_number: Mapped[str] = mapped_column(String(30), nullable=False)
    register_number: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    parent_phone: Mapped[str | None] = mapped_column(String(20))
    dob: Mapped[datetime | None] = mapped_column(Date)
    gender: Mapped[GenderEnum | None] = mapped_column(SAEnum(GenderEnum))
    community: Mapped[str | None] = mapped_column(String(50))
    religion: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(10))
    current_semester: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    batch: Mapped[str] = mapped_column(String(20), nullable=False)
    section: Mapped[str | None] = mapped_column(String(10))
    lateral_entry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hosteller: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transport_route: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[StudentStatus] = mapped_column(SAEnum(StudentStatus), default=StudentStatus.active, nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 2), default=0)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    college: Mapped["College"] = relationship(back_populates="students")
    department: Mapped["Department"] = relationship(back_populates="students")
    program: Mapped["Program"] = relationship(back_populates="students")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="student")
    marks_records: Mapped[list["MarksRecord"]] = relationship(back_populates="student")
    fee_accounts: Mapped[list["FeeAccount"]] = relationship(back_populates="student")
    placement_applications: Mapped[list["PlacementApplication"]] = relationship(back_populates="student")
