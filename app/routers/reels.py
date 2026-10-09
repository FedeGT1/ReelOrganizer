from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, ReelType, User
from app.reel_links import find_duplicate_reel
from app.routers.categories import get_taxonomy, get_valid_type_keys, reel_ids_matching_types
from app.routers.locations import _create_location
from app.routers.map import render_map_html
from app.scoping import get_owned, user_query
from app.web import templates

router = APIRouter(prefix="/api/reels", tags=["reels"])
ui_router = APIRouter(prefix="/ui", tags=["reels-ui"])

NEW_LOCATION_SENTINEL = "__new__"


def _is_safe_link(link: str) -> bool:
    return urlparse(link).scheme.lower() in ("http", "https")


def _location_and_satellite_ids(session: Session, user_id: str, location_id: str) -> list[str]:
    satellite_ids = session.exec(
        user_query(Location, user_id).with_only_columns(Location.id).where(Location.parent_id == location_id)
    ).all()
    return [location_id, *satellite_ids]


def _filter_reels_by_types(session: Session, reels: list[Reel], type_values: list[str]) -> list[Reel]:
    type_ids = reel_ids_matching_types(session, type_values)
    if type_ids is None:
        return reels
    return [r for r in reels if r.id in type_ids]


def _filter_reels_by_text(session: Session, reels: list[Reel], q: Optional[str]) -> list[Reel]:
    if not q:
        return reels
    needle = q.strip().lower()
    if not needle:
        return reels

    location_names: dict[str, str] = {}

    def location_name(location_id: str) -> str:
        if location_id not in location_names:
            loc = session.get(Location, location_id)
            location_names[location_id] = loc.name if loc else ""
        return location_names[location_id]

    return [
        r
        for r in reels
        if needle in (r.note or "").lower() or needle in location_name(r.location_id).lower()
    ]


class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


def _maps_query(location: Optional[Location]) -> Optional[str]:
    if location is None:
        return None
    if location.geocode_confidence != "low" and location.name:
        return location.name
    if location.lat is not None and location.lon is not None:
        return f"{location.lat},{location.lon}"
    return None


def _serialize_reel(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    location = session.get(Location, reel.location_id)
    return {
        "id": reel.id,
        "link": reel.link,
        "location_id": reel.location_id,
        "location_name": location.name if location else None,
        "note": reel.note,
        "created_at": reel.created_at.isoformat(),
        "types": [t.type for t in types],
        "lat": location.lat if location else None,
        "lon": location.lon if location else None,
        "maps_query": _maps_query(location),
        "can_regenerate": bool(reel.caption or reel.transcript or reel.note),
    }


def _update_reel(
    session: Session,
    user_id: str,
    reel_id: str,
    link: str,
    location_id: str,
    note: Optional[str],
    types: list[str],
) -> Reel:
    reel = get_owned(session, Reel, reel_id, user_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    if get_owned(session, Location, location_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")

    reel.link = link
    reel.location_id = location_id
    reel.note = note
    session.add(reel)

    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.commit()

    valid_type_keys = get_valid_type_keys(session, user_id)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel


@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = user_query(Reel, current_user.id)
    if location_id is not None:
        query = query.where(
            Reel.location_id.in_(_location_and_satellite_ids(session, current_user.id, location_id))
        )
    reels = session.exec(query).all()

    reels = _filter_reels_by_types(session, reels, type)
    reels = _filter_reels_by_text(session, reels, q)

    return [_serialize_reel(session, r) for r in reels]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(
    payload: ReelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(payload.link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    if get_owned(session, Location, payload.location_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    reel = Reel(
        link=payload.link, location_id=payload.location_id, note=payload.note, user_id=current_user.id
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session, current_user.id)
    for type_value in payload.types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)


@router.put("/{reel_id}")
def update_reel(
    reel_id: str,
    payload: ReelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = _update_reel(
        session, current_user.id, reel_id, payload.link, payload.location_id, payload.note, payload.types
    )
    return _serialize_reel(session, reel)


@router.delete("/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reel(
    reel_id: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    for t in types:
        session.delete(t)
    session.delete(reel)
    session.commit()


def _reel_list_context(
    session: Session,
    user_id: str,
    location_id: Optional[str] = None,
    type_values: Optional[list[str]] = None,
    q: Optional[str] = None,
) -> dict:
    type_values = type_values or []
    query = user_query(Reel, user_id)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, user_id, location_id)))
    reels = session.exec(query).all()

    reels = _filter_reels_by_types(session, reels, type_values)
    reels = _filter_reels_by_text(session, reels, q)

    filtered_location = get_owned(session, Location, location_id, user_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "taxonomy": get_taxonomy(session, user_id),
        "filtered_location": filtered_location,
    }


def _reel_add_form_context(
    session: Session,
    user_id: str,
    error: Optional[str] = None,
    duplicate_warning: Optional[dict] = None,
) -> dict:
    locations = session.exec(user_query(Location, user_id)).all()
    return {
        "locations": locations,
        "hubs": [loc for loc in locations if loc.is_hub],
        "taxonomy": get_taxonomy(session, user_id),
        "error": error,
        "duplicate_warning": duplicate_warning,
    }


def _reel_edit_form_context(session: Session, user_id: str, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "reel": reel,
        "locations": session.exec(user_query(Location, user_id)).all(),
        "taxonomy": get_taxonomy(session, user_id),
        "reel_type_keys": {t.type for t in types},
    }


@ui_router.get("/reels/add-form")
def ui_reel_add_form(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/reel_add_form.html", _reel_add_form_context(session, current_user.id)
    )


@ui_router.get("/reels/{reel_id}/edit-form")
def ui_reel_edit_form(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return templates.TemplateResponse(
        request, "partials/reel_edit_form.html", _reel_edit_form_context(session, current_user.id, reel)
    )


@ui_router.put("/reels/{reel_id}")
def ui_update_reel(
    request: Request,
    reel_id: str,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _update_reel(session, current_user.id, reel_id, link, location_id, note, types)

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response


@ui_router.get("/reels")
def ui_list_reels(
    request: Request,
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, current_user.id, location_id, type, q)
    )


@ui_router.post("/reels")
def ui_create_reel(
    request: Request,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    new_location_name: str = Form(""),
    new_location_is_hub: str = Form("true"),
    new_location_parent_id: str = Form(""),
    new_location_lat: Optional[float] = Form(None),
    new_location_lon: Optional[float] = Form(None),
    confirm_duplicate: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            form_html = templates.get_template("partials/reel_add_form.html").render(
                _reel_add_form_context(
                    session,
                    current_user.id,
                    duplicate_warning={
                        "existing_location_name": existing_location.name if existing_location else "?",
                        "existing_note": duplicate.note,
                        "link": link,
                        "location_id": location_id,
                        "note": note or "",
                        "types": types,
                        "new_location_name": new_location_name,
                        "new_location_is_hub": new_location_is_hub,
                        "new_location_parent_id": new_location_parent_id,
                        "new_location_lat": new_location_lat if new_location_lat is not None else "",
                        "new_location_lon": new_location_lon if new_location_lon is not None else "",
                    },
                )
            )
            return HTMLResponse(form_html)

    if location_id == NEW_LOCATION_SENTINEL:
        try:
            new_location = _create_location(
                session,
                current_user.id,
                new_location_name,
                new_location_is_hub == "true",
                new_location_parent_id or None,
                new_location_lat,
                new_location_lon,
            )
        except HTTPException as exc:
            if exc.status_code != 400:
                raise
            form_html = templates.get_template("partials/reel_add_form.html").render(
                _reel_add_form_context(session, current_user.id, error="Un satellite richiede una città padre.")
            )
            return HTMLResponse(form_html)
        location_id = new_location.id
    elif get_owned(session, Location, location_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail="Location not found")

    reel = Reel(link=link, location_id=location_id, note=note, user_id=current_user.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    valid_type_keys = get_valid_type_keys(session, current_user.id)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response


@ui_router.delete("/reels/{reel_id}")
def ui_delete_reel(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.delete(reel)
    session.commit()
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, current_user.id)
    )
