import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, ReelType

router = APIRouter(prefix="/api/categories", tags=["categories"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session) -> dict[str, dict]:
    categories = session.exec(select(Category).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon, "color": c.color} for c in categories}


def get_valid_type_keys(session: Session) -> set[str]:
    return set(session.exec(select(Category.key)).all())


class CategoryPayload(BaseModel):
    label: str
    icon: str
    color: str


def _create_category(session: Session, label: str, icon: str, color: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if session.get(Category, key):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(key=key, label=label, icon=icon, color=color)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, key: str, label: str, icon: str, color: str) -> Category:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
    category.color = color
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _delete_category(session: Session, key: str) -> None:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for rt in session.exec(select(ReelType).where(ReelType.type == key)).all():
        session.delete(rt)
    session.delete(category)
    session.commit()


@router.get("")
def list_categories(session: Session = Depends(get_session)):
    return session.exec(select(Category).order_by(Category.created_at)).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryPayload, session: Session = Depends(get_session)):
    return _create_category(session, payload.label, payload.icon, payload.color)


@router.put("/{key}")
def update_category(key: str, payload: CategoryPayload, session: Session = Depends(get_session)):
    return _update_category(session, key, payload.label, payload.icon, payload.color)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)
