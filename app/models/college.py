import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, Numeric, Date, Text, DateTime, func, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY
from app.database import Base

class AccreditationType(str, enum.Enum):
    naac = 'naac'
    nba = 'nba'
    nirf = 'nirf'
    aicte = 'aicte'
    ugc = 'ugc'
    autonomous = 'autonomous'
    none = 'none'

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .department import Department
    from .user import User
    from .student import Student
    from .fee_account import FeeAccount
    from .placement_drive import PlacementDrive
    from .placement_application import PlacementApplication


class College(Base):
    __tablename__ = "colleges"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    schema_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    accreditation_type: Mapped[AccreditationType] = mapped_column(SAEnum(AccreditationType), default=AccreditationType.none, nullable=False)
    naac_grade: Mapped[str | None] = mapped_column(String(5))
    naac_cgpa: Mapped[float | None] = mapped_column(Numeric(4, 2))
    naac_valid_until: Mapped[datetime | None] = mapped_column(Date)
    nba_programs: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    university_name: Mapped[str | None] = mapped_column(String(255))
    university_code: Mapped[str | None] = mapped_column(String(50))
    is_autonomous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    subscription_plan: Mapped[str] = mapped_column(String(50), default='mvp', nullable=False)
    onboarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    departments: Mapped[list["Department"]] = relationship(back_populates="college")
    users: Mapped[list["User"]] = relationship(back_populates="college")
    students: Mapped[list["Student"]] = relationship(back_populates="college")
    fee_accounts: Mapped[list["FeeAccount"]] = relationship(back_populates="college")
    placement_drives: Mapped[list["PlacementDrive"]] = relationship(back_populates="college")
    placement_applications: Mapped[list["PlacementApplication"]] = relationship(back_populates="college")
