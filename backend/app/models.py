from sqlalchemy import Column, Integer, String, Text, ForeignKey
from app.db import Base
from pydantic import BaseModel
from typing import Optional


# SQLAlchemy ORM model
class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    zip_code = Column(String(20), nullable=False)
    country = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)


# Pydantic schema
class PropertySchema(BaseModel):
    id: Optional[int]
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    country: str
    description: Optional[str] = None
    owner_id: Optional[int] = None

    class Config:
        orm_mode = True
