from sqlalchemy import Column, String, DateTime
from app.database import Base

class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti = Column(String(36), primary_key=True, index=True)
    expires_at = Column(DateTime, nullable=False)
