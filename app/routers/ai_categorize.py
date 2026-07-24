import json
import logging
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location, Reel, ReelType
from app.routers.reels import _is_safe_link, _reel_list_context
from app.taxonomy import TAXONOMY, VALID_TYPES
from app.web import templates

router = APIRouter(prefix="/api/ai", tags=["ai"])
ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])

logger = logging.getLogger("app.ai")

MISSING_COORDINATES_QUESTION = (
    "Non riesco a stimare le coordinate di questo posto: "
    "qual e' la citta' o zona piu' vicina?"
)


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
    if not place_name_lower:
        return None
    for loc in session.exec(select(Location)).all():
        loc_name_lower = loc.name.lower()
        if place_name_lower in loc_name_lower or loc_name_lower in place_name_lower:
            return loc.id
    return None


def _find_hub_by_name(session: Session, name: str) -> Optional[Location]:
    if not name:
        return None
    return session.exec(
        select(Location).where(Location.is_hub == True, func.lower(Location.name) == name.lower())
    ).first()


def _assistant_turn_text(result: dict) -> str:
    if result.get("question"):
        return result["question"]

    parts = [f"Luogo proposto: {result.get('place_name', '')}."]
    if result.get("near_hub"):
        parts.append(f"Vicino a: {result['near_hub']}.")
    if result.get("types"):
        parts.append(f"Tipo: {', '.join(result['types'])}.")
    if result.get("note"):
        parts.append(f"Nota: {result['note']}.")
    parts.append(f"Confidenza: {result.get('confidence', '')}.")
    return " ".join(parts)


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
    api_messages = [
        {
            "role": m.role,
            "content": _assistant_turn_text(json.loads(m.content)) if m.role == "assistant" else m.content,
        }
        for m in history
    ]

    previous_result = None
    for m in reversed(history[:-1]):
        if m.role == "assistant":
            previous_result = json.loads(m.content)
            break
    previous_safety_net_triggered = (
        previous_result is not None and previous_result.get("question") == MISSING_COORDINATES_QUESTION
    )
    logger.debug(
        "session=%s previous_safety_net_triggered=%s",
        ai_session.id, previous_safety_net_triggered,
    )

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    try:
        result = ai_client.categorize(hub_names, api_messages)
    except anthropic.AnthropicError:
        logger.exception("session=%s Anthropic call failed", ai_session.id)
        result = {
            "place_name": "",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None,
            "lon": None,
        }

    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])
    logger.debug("session=%s matched_location_id=%s", ai_session.id, matched_location_id)

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        logger.debug(
            "session=%s safety net condition met (unmatched place, no question, missing lat/lon)",
            ai_session.id,
        )
        if previous_safety_net_triggered and result.get("near_hub"):
            hub = _find_hub_by_name(session, result["near_hub"])
            logger.debug(
                "session=%s attempting hub fallback for near_hub=%r -> hub=%s",
                ai_session.id, result["near_hub"], hub.name if hub else None,
            )
            if hub is not None:
                result["lat"] = hub.lat
                result["lon"] = hub.lon

        if result.get("lat") is None or result.get("lon") is None:
            result["question"] = MISSING_COORDINATES_QUESTION

    logger.debug("session=%s final result=%s", ai_session.id, result)

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)


def _build_ai_chat_context(
    session: Session, ai_session_id: Optional[str], link: str, notice: Optional[str] = None
) -> dict:
    history: list[dict] = []
    latest_result: Optional[dict] = None

    if ai_session_id:
        messages = session.exec(
            select(AiMessage)
            .where(AiMessage.session_id == ai_session_id)
            .order_by(AiMessage.created_at)
        ).all()
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "text": m.content})
            else:
                result = json.loads(m.content)
                history.append({"role": "assistant", "result": result})
                latest_result = result

    matched_location_id = (
        _find_matching_location(session, latest_result["place_name"])
        if latest_result is not None
        else None
    )
    can_confirm = latest_result is not None and latest_result.get("question") is None

    return {
        "session_id": ai_session_id or "",
        "link": link or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "matched_location_id": matched_location_id or "",
        "taxonomy": TAXONOMY,
        "notice": notice,
    }


@ui_router.get("/panel")
def ui_ai_panel(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, None, "")
    )


@ui_router.post("/message")
def ui_ai_message(
    request: Request,
    session_id: str = Form(""),
    link: str = Form(""),
    message: str = Form(...),
    session: Session = Depends(get_session),
):
    if not session_id:
        if not _is_safe_link(link):
            raise HTTPException(status_code=400, detail="link must be an http(s) URL")
        combined_message = f"Link: {link}\nDescrizione: {message}"
    else:
        combined_message = message

    try:
        ai_session, _, _ = _run_turn(session, session_id or None, combined_message)
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ai_chat_context(
                session, None, "", notice="Sessione scaduta, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ai_chat.html", context)
        raise

    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, ai_session.id, link)
    )


@ui_router.post("/confirm")
def ui_ai_confirm(
    request: Request,
    session_id: str = Form(...),
    link: str = Form(...),
    place_name: str = Form(...),
    near_hub: str = Form(""),
    types: list[str] = Form([]),
    note: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    matched_location_id: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if matched_location_id:
        location_id = matched_location_id
    else:
        hub = _find_hub_by_name(session, near_hub)

        if not lat or not lon:
            raise HTTPException(
                status_code=400, detail="lat/lon are required to create a new location"
            )

        new_location = Location(
            name=place_name,
            is_hub=hub is None,
            parent_id=hub.id if hub else None,
            lat=float(lat),
            lon=float(lon),
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel = Reel(link=link, location_id=location_id, note=note or None)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    for type_value in types:
        if type_value in VALID_TYPES:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    stale_ai_session = session.get(AiSession, session_id)
    if stale_ai_session is not None:
        for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
            session.delete(msg)
        session.delete(stale_ai_session)
        session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )

    return HTMLResponse(
        ai_chat_html + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
    )
