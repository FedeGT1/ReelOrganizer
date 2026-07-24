import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    lat: Optional[float] = None
    lon: Optional[float] = None


class Reel(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    link: str
    location_id: str = Field(foreign_key="location.id")
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Category(SQLModel, table=True):
    key: str = Field(primary_key=True)
    label: str
    icon: str
    color: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReelType(SQLModel, table=True):
    reel_id: str = Field(foreign_key="reel.id", primary_key=True)
    type: str = Field(foreign_key="category.key", primary_key=True)


class AiSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AiMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    session_id: str = Field(foreign_key="aisession.id")
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
