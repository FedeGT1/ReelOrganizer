from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("")
def list_locations(session: Session = Depends(get_session)):
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
            "x": loc.x,
            "y": loc.y,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]
