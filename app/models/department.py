from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    hod_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    students: Mapped[list["Student"]] = relationship(back_populates="department")  # type: ignore[name-defined]
    subjects: Mapped[list["Subject"]] = relationship(back_populates="department")  # type: ignore[name-defined]
