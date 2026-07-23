import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType
from app.taxonomy import TAXONOMY
from app.web import templates

router = APIRouter(prefix="/api/map", tags=["map"])
ui_router = APIRouter(prefix="/ui", tags=["map-ui"])


def compute_map(session: Session) -> list[dict]:
    locations = session.exec(select(Location)).all()
    counts = dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
        ).all()
    )

    return [
        {
            "id": loc.id,
            "name": loc.name,
            "is_hub": loc.is_hub,
            "parent_id": loc.parent_id,
            "lat": loc.lat,
            "lon": loc.lon,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]


@router.get("")
def get_map(session: Session = Depends(get_session)):
    return compute_map(session)


def locations_with_type(session: Session, type_value: str) -> set[str]:
    reel_ids = set(
        session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all()
    )
    if not reel_ids:
        return set()
    return set(
        session.exec(select(Reel.location_id).where(Reel.id.in_(reel_ids))).all()
    )


def visible_location_ids(
    session: Session,
    locations: list[dict],
    type_value: str | None,
    hide_empty: bool,
) -> tuple[set[str] | None, set[str]]:
    """(visible_ids, anchor_hub_ids). visible_ids is None when hide_empty is
    False (no filtering - show everything). anchor_hub_ids is always a
    subset of visible_ids: hubs that qualify only because a child satellite
    qualifies, not because they have reels of their own."""
    if not hide_empty:
        return None, set()

    if type_value:
        qualifying = locations_with_type(session, type_value)
    else:
        qualifying = {loc["id"] for loc in locations if loc["reel_count"] > 0}

    anchor_hubs = {
        loc["id"]
        for loc in locations
        if loc["is_hub"]
        and loc["id"] not in qualifying
        and any(
            sat["parent_id"] == loc["id"] and sat["id"] in qualifying
            for sat in locations
        )
    }
    return qualifying | anchor_hubs, anchor_hubs


@ui_router.get("/map")
def ui_map(
    request: Request,
    type: str = None,
    hide_empty: bool = False,
    session: Session = Depends(get_session),
):
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_type(session, type) if type else set()
    visible_ids, anchor_hub_ids = visible_location_ids(session, locations, type, hide_empty)

    map_locations = []
    for loc in locations:
        if visible_ids is not None and loc["id"] not in visible_ids:
            continue
        if loc["lat"] is None or loc["lon"] is None:
            continue

        entry = {
            "id": loc["id"],
            "name": loc["name"],
            "is_hub": loc["is_hub"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "anchor": loc["id"] in anchor_hub_ids,
            "dimmed": bool(type) and loc["id"] not in matching_location_ids,
            "parent_lat": None,
            "parent_lon": None,
        }
        if not loc["is_hub"]:
            parent = hubs_by_id.get(loc["parent_id"])
            if parent is not None and parent["lat"] is not None and parent["lon"] is not None:
                entry["parent_lat"] = parent["lat"]
                entry["parent_lon"] = parent["lon"]
        map_locations.append(entry)

    map_locations_json = json.dumps(map_locations).replace("<", "\\u003c")

    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "map_locations_json": map_locations_json,
            "active_type": type,
            "taxonomy": TAXONOMY,
            "hide_empty": hide_empty,
        },
    )
