from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Date, func, ForeignKey, Numeric, Text, SmallInteger
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base

if TYPE_CHECKING:
    from .college import College
    from .user import User
    from .placement_application import PlacementApplication

class PlacementDrive(Base):
    __tablename__ = "placement_drives"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_sector: Mapped[str | None] = mapped_column(String(100))
    drive_type: Mapped[str | None] = mapped_column(String(50))
    drive_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    registration_deadline: Mapped[datetime | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(100))
    ctc_lpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    stipend_monthly: Mapped[float | None] = mapped_column(Numeric(10, 2))
    bond_years: Mapped[int | None] = mapped_column(SmallInteger)
    eligible_departments: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    min_cgpa: Mapped[float | None] = mapped_column(Numeric(4, 2))
    min_attendance_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    no_active_arrears: Mapped[bool | None] = mapped_column(Boolean)
    job_role: Mapped[str | None] = mapped_column(String(255))
    job_location: Mapped[str | None] = mapped_column(String(255))
    headcount: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    college: Mapped["College"] = relationship(back_populates="placement_drives")
    creator: Mapped["User"] = relationship(back_populates="placement_drives_created")
    applications: Mapped[list["PlacementApplication"]] = relationship(back_populates="drive")
