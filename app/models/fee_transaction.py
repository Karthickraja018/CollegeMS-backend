from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Date, func, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base

if TYPE_CHECKING:
    from .fee_account import FeeAccount
    from .user import User

class FeeTransaction(Base):
    __tablename__ = "fee_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fee_account_id: Mapped[int] = mapped_column(ForeignKey("fee_accounts.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_ref: Mapped[str | None] = mapped_column(String(100))
    payment_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    fee_account: Mapped["FeeAccount"] = relationship(back_populates="transactions")
    receiver: Mapped["User"] = relationship(back_populates="fee_transactions_received")
