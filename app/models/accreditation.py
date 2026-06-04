from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class AccreditationDocument(Base):
    __tablename__ = "accreditation_documents"

    id = Column(Integer, primary_key=True, index=True)
    college_id = Column(Integer, ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    is_required = Column(Boolean, default=True, nullable=False)
    is_uploaded = Column(Boolean, default=False, nullable=False)
    uploaded_at = Column(DateTime, nullable=True)
    
    college = relationship("College")
