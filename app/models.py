import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    x: Optional[float] = None
    y: Optional[float] = None
