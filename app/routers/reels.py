from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType
from app.routers.categories import get_taxonomy, get_valid_type_keys
from app.routers.map import render_map_html
from app.web import templates

router = APIRouter(prefix="/api/reels", tags=["reels"])
ui_router = APIRouter(prefix="/ui", tags=["reels-ui"])


def _is_safe_link(link: str) -> bool:
    return urlparse(link).scheme.lower() in ("http", "https")


def _location_and_satellite_ids(session: Session, location_id: str) -> list[str]:
    satellite_ids = session.exec(
        select(Location.id).where(Location.parent_id == location_id)
    ).all()
    return [location_id, *satellite_ids]


class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


def _serialize_reel(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    location = session.get(Location, reel.location_id)
    return {
        "id": reel.id,
        "link": reel.link,
        "location_id": reel.location_id,
        "note": reel.note,
        "created_at": reel.created_at.isoformat(),
        "types": [t.type for t in types],
        "lat": location.lat if location else None,
        "lon": location.lon if location else None,
    }


def _update_reel(
    session: Session, reel_id: str, link: str, location_id: str, note: Optional[str], types: list[str]
) -> Reel:
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    reel.link = link
    reel.location_id = location_id
    reel.note = note
    session.add(reel)

    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.commit()

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel


@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query).all()

    if type is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == type)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    return [_serialize_reel(session, r) for r in reels]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(payload: ReelCreate, session: Session = Depends(get_session)):
    if not _is_safe_link(payload.link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    reel = Reel(link=payload.link, location_id=payload.location_id, note=payload.note)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session)
    for type_value in payload.types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)


@router.put("/{reel_id}")
def update_reel(reel_id: str, payload: ReelCreate, session: Session = Depends(get_session)):
    reel = _update_reel(session, reel_id, payload.link, payload.location_id, payload.note, payload.types)
    return _serialize_reel(session, reel)


@router.delete("/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reel(reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    for t in types:
        session.delete(t)
    session.delete(reel)
    session.commit()


def _reel_list_context(
    session: Session, location_id: Optional[str] = None, type_value: Optional[str] = None
) -> dict:
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query).all()

    if type_value is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    filtered_location = session.get(Location, location_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "taxonomy": get_taxonomy(session),
        "filtered_location": filtered_location,
    }


def _reel_add_form_context(session: Session) -> dict:
    return {
        "locations": session.exec(select(Location)).all(),
        "taxonomy": get_taxonomy(session),
    }


def _reel_edit_form_context(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "reel": reel,
        "locations": session.exec(select(Location)).all(),
        "taxonomy": get_taxonomy(session),
        "reel_type_keys": {t.type for t in types},
    }


@ui_router.get("/reels/add-form")
def ui_reel_add_form(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/reel_add_form.html", _reel_add_form_context(session))


@ui_router.get("/reels/{reel_id}/edit-form")
def ui_reel_edit_form(request: Request, reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return templates.TemplateResponse(
        request, "partials/reel_edit_form.html", _reel_edit_form_context(session, reel)
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
):
    _update_reel(session, reel_id, link, location_id, note, types)

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)

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
    type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, location_id, type)
    )


@ui_router.post("/reels")
def ui_create_reel(
    request: Request,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    reel = Reel(link=link, location_id=location_id, note=note)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response


@ui_router.delete("/reels/{reel_id}")
def ui_delete_reel(request: Request, reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.delete(reel)
    session.commit()
    return templates.TemplateResponse(request, "partials/reel_list.html", _reel_list_context(session))
