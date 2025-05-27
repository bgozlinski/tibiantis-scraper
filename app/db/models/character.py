from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from app.db.models.base import Base
from datetime import datetime, UTC


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    sex = Column(String, nullable=True)
    vocation = Column(String, nullable=True)
    level = Column(Integer, nullable=True)
    world = Column(String, nullable=True)
    residence = Column(String, nullable=True)
    house = Column(String, nullable=True)
    guild_membership = Column(String, nullable=True)
    last_login = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    account_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    # Define relationship to BedmageMonitor model
    bedmages = relationship("Bedmage", back_populates="character")
