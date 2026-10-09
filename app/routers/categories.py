import re
import unicodedata

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Category, Reel, ReelType, User
from app.scoping import get_owned_category, user_query
from app.web import templates

router = APIRouter(prefix="/api/categories", tags=["categories"])
ui_router = APIRouter(prefix="/ui/categories", tags=["categories-ui"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session, user_id: str) -> dict[str, dict]:
    categories = session.exec(user_query(Category, user_id).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon} for c in categories}


def get_valid_type_keys(session: Session, user_id: str) -> set[str]:
    return {c.key for c in session.exec(user_query(Category, user_id)).all()}


def reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None:
    """None means "no filter". Otherwise the set of reel ids tagged with
    every type in `types` (AND across types). Callers must already have
    scoped the reel list they intersect this against -- this function
    itself does not filter by user."""
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


def _create_category(session: Session, user_id: str, label: str, icon: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if get_owned_category(session, key, user_id):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(user_id=user_id, key=key, label=label, icon=icon)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, user_id: str, key: str, label: str, icon: str) -> Category:
    category = get_owned_category(session, key, user_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _delete_category(session: Session, user_id: str, key: str) -> None:
    category = get_owned_category(session, key, user_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    owned_reel_ids = set(session.exec(user_query(Reel, user_id).with_only_columns(Reel.id)).all())
    for rt in session.exec(select(ReelType).where(ReelType.type == key)).all():
        if rt.reel_id in owned_reel_ids:
            session.delete(rt)
    session.delete(category)
    session.commit()


@router.get("")
def list_categories(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(user_query(Category, current_user.id).order_by(Category.created_at)).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _create_category(session, current_user.id, payload.label, payload.icon)


@router.put("/{key}")
def update_category(
    key: str,
    payload: CategoryPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _update_category(session, current_user.id, key, payload.label, payload.icon)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    key: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    _delete_category(session, current_user.id, key)


def _category_list_context(session: Session, user_id: str) -> dict:
    return {"categories": session.exec(user_query(Category, user_id).order_by(Category.created_at)).all()}


@ui_router.get("")
def ui_list_categories(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.post("")
def ui_create_category(
    request: Request,
    label: str = Form(...),
    icon: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _create_category(session, current_user.id, label, icon)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.get("/{key}/edit")
def ui_edit_category_form(
    request: Request,
    key: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    category = get_owned_category(session, key, current_user.id)
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
    current_user: User = Depends(get_current_user),
):
    _update_category(session, current_user.id, key, label, icon)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.delete("/{key}")
def ui_delete_category(
    request: Request,
    key: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _delete_category(session, current_user.id, key)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )
