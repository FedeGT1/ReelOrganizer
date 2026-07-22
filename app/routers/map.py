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


@ui_router.get("/map")
def ui_map(request: Request, type: str = None, session: Session = Depends(get_session)):
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_type(session, type) if type else set()
    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "locations": locations,
            "hubs_by_id": hubs_by_id,
            "taxonomy": TAXONOMY,
            "active_type": type,
            "matching_location_ids": matching_location_ids,
            "coastline_paths": COASTLINE_PATHS,
            "view_width": round(VIEW_WIDTH),
            "view_height": round(VIEW_HEIGHT),
            "inset_box": INSET_BOX,
            "inset_marker": INSET_MARKER,
            "inset_label_pos": INSET_LABEL_POS,
        },
    )
