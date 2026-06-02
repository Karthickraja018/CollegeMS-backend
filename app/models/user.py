import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, ForeignKey, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class UserRole(str, enum.Enum):
    admin = 'admin'
    college_admin = 'college_admin'
    principal = 'principal'
    hod = 'hod'
    faculty = 'faculty'
    staff = 'staff'
    student = 'student'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .college import College
    from .department import Department
    from .report import Report
    from .fee_transaction import FeeTransaction
    from .placement_drive import PlacementDrive


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(100))
    qualification: Mapped[str | None] = mapped_column(String(255))
    experience_years: Mapped[int | None] = mapped_column(Integer)  # SmallInt in DB
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.faculty, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    college: Mapped["College"] = relationship(back_populates="users")
    department: Mapped["Department"] = relationship(back_populates="users", foreign_keys=[department_id])
    reports_generated: Mapped[list["Report"]] = relationship(back_populates="generated_by_user")
    fee_transactions_received: Mapped[list["FeeTransaction"]] = relationship(back_populates="receiver")
    placement_drives_created: Mapped[list["PlacementDrive"]] = relationship(back_populates="creator")
