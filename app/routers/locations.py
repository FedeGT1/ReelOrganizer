from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel
from app.web import templates

router = APIRouter(prefix="/api/locations", tags=["locations"])
ui_router = APIRouter(prefix="/ui/locations", tags=["locations-ui"])


class LocationPayload(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: float
    lon: float


def _has_children(session: Session, location_id: str) -> bool:
    return (
        session.exec(select(Location).where(Location.parent_id == location_id)).first()
        is not None
    )


def _has_reels(session: Session, location_id: str) -> bool:
    return (
        session.exec(select(Reel).where(Reel.location_id == location_id)).first()
        is not None
    )


def _reel_counts(session: Session) -> dict:
    return dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
        ).all()
    )


def _serialize_location(location: Location, reel_count: int) -> dict:
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "lat": location.lat,
        "lon": location.lon,
        "reel_count": reel_count,
    }


def _create_location(
    session: Session, name: str, is_hub: bool, parent_id: Optional[str], lat: float, lon: float
) -> Location:
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    location = Location(
        name=name, is_hub=is_hub, parent_id=None if is_hub else parent_id, lat=lat, lon=lon
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def _update_location(
    session: Session,
    location_id: str,
    name: str,
    is_hub: bool,
    parent_id: Optional[str],
    lat: float,
    lon: float,
) -> Location:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    if not is_hub and _has_children(session, location_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot turn a location with child locations into a satellite; reassign or delete them first",
        )
    location.name = name
    location.is_hub = is_hub
    location.parent_id = None if is_hub else parent_id
    location.lat = lat
    location.lon = lon
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def _delete_location(session: Session, location_id: str) -> None:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if _has_children(session, location_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has child locations; reassign or delete them first",
        )
    if _has_reels(session, location_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has reels attached; move or delete them first",
        )
    session.delete(location)
    session.commit()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationPayload, session: Session = Depends(get_session)):
    location = _create_location(
        session, payload.name, payload.is_hub, payload.parent_id, payload.lat, payload.lon
    )
    return _serialize_location(location, 0)


@router.get("")
def list_locations(session: Session = Depends(get_session)):
    locations = session.exec(select(Location)).all()
    counts = _reel_counts(session)
    return [_serialize_location(loc, counts.get(loc.id, 0)) for loc in locations]


@router.put("/{location_id}")
def update_location(
    location_id: str, payload: LocationPayload, session: Session = Depends(get_session)
):
    location = _update_location(
        session,
        location_id,
        payload.name,
        payload.is_hub,
        payload.parent_id,
        payload.lat,
        payload.lon,
    )
    counts = _reel_counts(session)
    return _serialize_location(location, counts.get(location.id, 0))


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str, session: Session = Depends(get_session)):
    _delete_location(session, location_id)


def _location_list_context(session: Session, error: Optional[str] = None) -> dict:
    locations = session.exec(select(Location)).all()
    counts = _reel_counts(session)
    hubs = sorted((loc for loc in locations if loc.is_hub), key=lambda loc: loc.name)
    hubs_by_id = {loc.id: loc for loc in hubs}

    satellites_by_parent: dict = {}
    for loc in locations:
        if not loc.is_hub:
            satellites_by_parent.setdefault(loc.parent_id, []).append(loc)
    for satellites in satellites_by_parent.values():
        satellites.sort(key=lambda loc: loc.name)

    def _entry(loc: Location) -> dict:
        return {
            "id": loc.id,
            "name": loc.name,
            "is_hub": loc.is_hub,
            "parent_name": hubs_by_id[loc.parent_id].name
            if loc.parent_id in hubs_by_id
            else None,
            "lat": loc.lat,
            "lon": loc.lon,
            "reel_count": counts.get(loc.id, 0),
        }

    entries = []
    placed_ids = set()
    for hub in hubs:
        entries.append(_entry(hub))
        placed_ids.add(hub.id)
        for satellite in satellites_by_parent.get(hub.id, []):
            entries.append(_entry(satellite))
            placed_ids.add(satellite.id)

    for loc in locations:
        if loc.id not in placed_ids:
            entries.append(_entry(loc))

    return {
        "locations": entries,
        "hubs": hubs,
        "error": error,
    }


@ui_router.get("")
def ui_list_locations(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )


@ui_router.post("")
def ui_create_location(
    request: Request,
    name: str = Form(...),
    is_hub: str = Form(...),
    parent_id: str = Form(""),
    lat: float = Form(...),
    lon: float = Form(...),
    session: Session = Depends(get_session),
):
    try:
        _create_location(session, name, is_hub == "true", parent_id or None, lat, lon)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, error="Un satellite richiede una città padre."),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )


@ui_router.get("/{location_id}/edit")
def ui_edit_location_form(
    request: Request, location_id: str, session: Session = Depends(get_session)
):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    hubs = session.exec(
        select(Location).where(Location.is_hub == True, Location.id != location_id)
    ).all()
    return templates.TemplateResponse(
        request, "partials/location_edit_row.html", {"location": location, "hubs": hubs}
    )


@ui_router.post("/{location_id}")
def ui_update_location(
    request: Request,
    location_id: str,
    name: str = Form(...),
    is_hub: str = Form(...),
    parent_id: str = Form(""),
    lat: float = Form(...),
    lon: float = Form(...),
    session: Session = Depends(get_session),
):
    try:
        _update_location(session, location_id, name, is_hub == "true", parent_id or None, lat, lon)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        error = (
            "Un satellite richiede una città padre."
            if exc.status_code == 400
            else "Questa città ha città satellite collegate: riassegnale o eliminale prima."
        )
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, error=error),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )


@ui_router.delete("/{location_id}")
def ui_delete_location(
    request: Request, location_id: str, session: Session = Depends(get_session)
):
    try:
        _delete_location(session, location_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        if _has_children(session, location_id):
            error = "Questa città ha città satellite collegate: riassegnale o eliminale prima."
        else:
            error = "Questa città ha reel collegati: spostali o eliminali prima dalla lista reel."
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, error=error),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )
