from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.models.base import Base


class Bedmage(Base):
    __tablename__ = "bedmages"

    id = Column(Integer, primary_key=True, index=True)
    character_name = Column(String, ForeignKey("characters.name"), index=True)

    # Define relationship to a Character model
    character = relationship("Character", back_populates="bedmages")
