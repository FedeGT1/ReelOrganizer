from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.geo import COASTLINE_PATHS, INSET_BOX, INSET_LABEL_POS, INSET_MARKER, VIEW_HEIGHT, VIEW_WIDTH, project
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

    result = []
    for loc in locations:
        if loc.map_inset:
            x, y = None, None
        else:
            x, y = project(loc.lat or 0.0, loc.lon or 0.0)
        result.append(
            {
                "id": loc.id,
                "name": loc.name,
                "is_hub": loc.is_hub,
                "parent_id": loc.parent_id,
                "lat": loc.lat,
                "lon": loc.lon,
                "map_inset": loc.map_inset,
                "x": x,
                "y": y,
                "reel_count": counts.get(loc.id, 0),
            }
        )
    return result


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
    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "locations": locations,
            "hubs_by_id": hubs_by_id,
            "taxonomy": TAXONOMY,
            "active_type": type,
            "matching_location_ids": matching_location_ids,
            "visible_ids": visible_ids,
            "anchor_hub_ids": anchor_hub_ids,
            "hide_empty": hide_empty,
            "coastline_paths": COASTLINE_PATHS,
            "view_width": round(VIEW_WIDTH),
            "view_height": round(VIEW_HEIGHT),
            "inset_box": INSET_BOX,
            "inset_marker": INSET_MARKER,
            "inset_label_pos": INSET_LABEL_POS,
        },
    )
