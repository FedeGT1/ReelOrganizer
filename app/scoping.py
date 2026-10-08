from typing import Optional, Type, TypeVar

from sqlmodel import Session, SQLModel, select

from app.models import Category

ModelT = TypeVar("ModelT", bound=SQLModel)


def user_query(Model: Type[ModelT], user_id: str):
    return select(Model).where(Model.user_id == user_id)


def get_owned(session: Session, Model: Type[ModelT], id_: str, user_id: str) -> Optional[ModelT]:
    row = session.get(Model, id_)
    if row is None or row.user_id != user_id:
        return None
    return row


def get_owned_category(session: Session, key: str, user_id: str) -> Optional[Category]:
    return session.get(Category, (user_id, key))
