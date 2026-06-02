from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Date, func, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base

if TYPE_CHECKING:
    from .student import Student
    from .college import College
    from .fee_transaction import FeeTransaction

class FeeAccount(Base):
    __tablename__ = "fee_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    paid_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped["Student"] = relationship(back_populates="fee_accounts")
    college: Mapped["College"] = relationship(back_populates="fee_accounts")
    transactions: Mapped[list["FeeTransaction"]] = relationship(back_populates="fee_account")
