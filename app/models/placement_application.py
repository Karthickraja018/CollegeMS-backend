from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base

if TYPE_CHECKING:
    from .student import Student
    from .placement_drive import PlacementDrive
    from .college import College

class PlacementApplication(Base):
    __tablename__ = "placement_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    drive_id: Mapped[int] = mapped_column(ForeignKey("placement_drives.id", ondelete="CASCADE"), nullable=False)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    applied_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    offer_ctc_lpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    offer_letter_url: Mapped[str | None] = mapped_column(String(500))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped["Student"] = relationship(back_populates="placement_applications")
    drive: Mapped["PlacementDrive"] = relationship(back_populates="applications")
    college: Mapped["College"] = relationship(back_populates="placement_applications")
