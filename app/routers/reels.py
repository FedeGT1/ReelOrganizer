from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Reel, ReelType

router = APIRouter(prefix="/api/reels", tags=["reels"])


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
