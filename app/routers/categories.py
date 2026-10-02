import re
import unicodedata

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, ReelType
from app.web import templates

router = APIRouter(prefix="/api/categories", tags=["categories"])
ui_router = APIRouter(prefix="/ui/categories", tags=["categories-ui"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session) -> dict[str, dict]:
    categories = session.exec(select(Category).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon} for c in categories}


def get_valid_type_keys(session: Session) -> set[str]:
    return set(session.exec(select(Category.key)).all())


def reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None:
    """None means "no filter". Otherwise the set of reel ids tagged with
    every type in `types` (AND across types)."""
    if not types:
        return None
    result: set[str] | None = None
    for type_value in types:
        ids = set(session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all())
        result = ids if result is None else result & ids
    return result


class CategoryPayload(BaseModel):
    label: str
    icon: str


def _create_category(session: Session, label: str, icon: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if session.get(Category, key):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(key=key, label=label, icon=icon)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, key: str, label: str, icon: str) -> Category:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
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
    return _create_category(session, payload.label, payload.icon)


@router.put("/{key}")
def update_category(key: str, payload: CategoryPayload, session: Session = Depends(get_session)):
    return _update_category(session, key, payload.label, payload.icon)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)


def _category_list_context(session: Session) -> dict:
    return {"categories": session.exec(select(Category).order_by(Category.created_at)).all()}


@ui_router.get("")
def ui_list_categories(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.post("")
def ui_create_category(
    request: Request,
    label: str = Form(...),
    icon: str = Form(...),
    session: Session = Depends(get_session),
):
    _create_category(session, label, icon)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.get("/{key}/edit")
def ui_edit_category_form(request: Request, key: str, session: Session = Depends(get_session)):
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse(request, "partials/category_edit_row.html", {"category": category})


@ui_router.post("/{key}")
def ui_update_category(
    request: Request,
    key: str,
    label: str = Form(...),
    icon: str = Form(...),
    session: Session = Depends(get_session),
):
    _update_category(session, key, label, icon)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.delete("/{key}")
def ui_delete_category(request: Request, key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))
