from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Reel, ReelType
from app.taxonomy import VALID_TYPES

router = APIRouter(prefix="/api/reels", tags=["reels"])


class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


def _serialize_reel(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "id": reel.id,
        "link": reel.link,
        "location_id": reel.location_id,
        "note": reel.note,
        "created_at": reel.created_at.isoformat(),
        "types": [t.type for t in types],
    }


@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id == location_id)
    reels = session.exec(query).all()

    if type is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == type)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    return [_serialize_reel(session, r) for r in reels]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(payload: ReelCreate, session: Session = Depends(get_session)):
    reel = Reel(link=payload.link, location_id=payload.location_id, note=payload.note)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    for type_value in payload.types:
        if type_value in VALID_TYPES:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)
