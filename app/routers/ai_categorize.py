import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location
from app.taxonomy import VALID_TYPES

router = APIRouter(prefix="/api/ai", tags=["ai"])


class CategorizeRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class CategorizeResponse(BaseModel):
    session_id: str
    place_name: str
    near_hub: Optional[str]
    types: list[str]
    note: str
    confidence: str
    question: Optional[str]
    matched_location_id: Optional[str] = None


def _find_matching_location(session: Session, place_name: str) -> Optional[str]:
    place_name_lower = place_name.lower()
    for loc in session.exec(select(Location)).all():
        loc_name_lower = loc.name.lower()
        if place_name_lower in loc_name_lower or loc_name_lower in place_name_lower:
            return loc.id
    return None


def _run_turn(
    session: Session, session_id: Optional[str], message: str
) -> tuple[AiSession, dict, Optional[str]]:
    if session_id:
        ai_session = session.get(AiSession, session_id)
        if ai_session is None:
            raise HTTPException(status_code=404, detail="AI session not found")
    else:
        ai_session = AiSession()
        session.add(ai_session)
        session.commit()
        session.refresh(ai_session)

    session.add(AiMessage(session_id=ai_session.id, role="user", content=message))
    session.commit()

    history = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == ai_session.id)
        .order_by(AiMessage.created_at)
    ).all()
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    result = ai_client.categorize(hub_names, api_messages)
    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        result["question"] = (
            "Non riesco a stimare le coordinate di questo posto: "
            "qual e' la citta' o zona piu' vicina?"
        )

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)
