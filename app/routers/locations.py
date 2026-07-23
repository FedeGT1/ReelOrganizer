from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType

router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationCreate(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: float
    lon: float


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, session: Session = Depends(get_session)):
    if not payload.is_hub and not payload.parent_id:
        raise HTTPException(
            status_code=400, detail="A satellite location requires a parent_id"
        )
    location = Location(**payload.model_dump())
    session.add(location)
    session.commit()
    session.refresh(location)
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "lat": location.lat,
        "lon": location.lon,
        "reel_count": 0,
    }


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
            "lat": loc.lat,
            "lon": loc.lon,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    children = session.exec(
        select(Location).where(Location.parent_id == location_id)
    ).all()
    if children:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has child locations; reassign or delete them first",
        )

    reels = session.exec(select(Reel).where(Reel.location_id == location_id)).all()
    for reel in reels:
        types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
        for t in types:
            session.delete(t)
        session.delete(reel)

    session.delete(location)
    session.commit()
