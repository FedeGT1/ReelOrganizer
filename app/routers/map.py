from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.layout import radial_positions
from app.models import Location, Reel

router = APIRouter(prefix="/api/map", tags=["map"])


def compute_map(session: Session) -> list[dict]:
    locations = session.exec(select(Location)).all()
    counts = dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
        ).all()
    )

    hubs = [loc for loc in locations if loc.is_hub]
    satellites_by_hub: dict[str, list[Location]] = {}
    for loc in locations:
        if not loc.is_hub and loc.parent_id is not None:
            satellites_by_hub.setdefault(loc.parent_id, []).append(loc)

    result = []
    for hub in hubs:
        result.append(
            {
                "id": hub.id,
                "name": hub.name,
                "is_hub": True,
                "parent_id": None,
                "x": hub.x,
                "y": hub.y,
                "reel_count": counts.get(hub.id, 0),
            }
        )
        satellites = satellites_by_hub.get(hub.id, [])
        positions = radial_positions(hub.x or 0.0, hub.y or 0.0, len(satellites))
        for satellite, (sx, sy) in zip(satellites, positions):
            result.append(
                {
                    "id": satellite.id,
                    "name": satellite.name,
                    "is_hub": False,
                    "parent_id": hub.id,
                    "x": sx,
                    "y": sy,
                    "reel_count": counts.get(satellite.id, 0),
                }
            )
    return result


@router.get("")
def get_map(session: Session = Depends(get_session)):
    return compute_map(session)
