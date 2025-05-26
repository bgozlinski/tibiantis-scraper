from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.models.base import Base
from app.db.models.character import Character
from datetime import datetime, UTC


class BedmageMonitor(Base):
    __tablename__ = "bedmage_monitors"

    id = Column(Integer, primary_key=True, index=True)
    character_name = Column(String, ForeignKey("characters.name"), index=True)
    start_time = Column(DateTime, default=datetime.now(UTC))
    is_active = Column(Boolean, default=True)
    is_notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    # Define relationship to a Character model
    character = relationship("Character", back_populates="bedmage_monitors")