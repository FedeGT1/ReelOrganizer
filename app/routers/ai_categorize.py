import json
import logging
from typing import Optional

from app.ai.providers.base import AIProviderError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location, Reel, ReelType
from app.routers.categories import get_taxonomy, get_valid_type_keys
from app.routers.map import render_map_html
from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context
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
    candidates: Optional[list[str]] = None
    matched_location_id: Optional[str] = None


def _find_matching_location(session: Session, place_name: str) -> Optional[str]:
    place_name_lower = place_name.lower()
    if not place_name_lower:
        return None
    for loc in session.exec(select(Location)).all():
        loc_name_lower = loc.name.lower()
        if loc.is_hub:
            # Hub names are broad city/region labels (e.g. "Hakone") that
            # commonly appear as part of a much more specific new place's
            # name (e.g. "Hakone-Yumoto Eva Store"). Treating that as "the
            # same place" would wrongly collapse a brand-new satellite into
            # the hub itself, discarding its own estimated coordinates.
            # Only match a hub when the proposed name equals it, or is a
            # short label fully contained within the hub's name (e.g.
            # "Tokyo" inside "Tokyo / Kanto") -- never the other direction.
            if place_name_lower == loc_name_lower or place_name_lower in loc_name_lower:
                return loc.id
        else:
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
    if result.get("candidates"):
        return "Ho trovato piu' posti possibili: " + ", ".join(result["candidates"]) + ". Quale?"

    parts = [f"Luogo proposto: {result.get('place_name', '')}."]
    if result.get("near_hub"):
        parts.append(f"Vicino a: {result['near_hub']}.")
    if result.get("types"):
        parts.append(f"Tipo: {', '.join(result['types'])}.")
    if result.get("note"):
        parts.append(f"Nota: {result['note']}.")
    parts.append(f"Confidenza: {result.get('confidence', '')}.")
    return " ".join(parts)


def _apply_result_post_processing(session: Session, ai_session: AiSession, result: dict) -> Optional[str]:
    """Shared post-AI-call bookkeeping: type filtering, location matching,
    and the missing-coordinates safety net. Mutates `result` in place and
    returns matched_location_id. DB reads only -- callers own commit()."""
    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    valid_type_keys = get_valid_type_keys(session)
    result["types"] = [t for t in result.get("types", []) if t in valid_type_keys]

    matched_location_id = _find_matching_location(session, result["place_name"])
    logger.debug("session=%s matched_location_id=%s", ai_session.id, matched_location_id)

    if (
        matched_location_id is None
        and result.get("question") is None
        and not result.get("candidates")
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        logger.debug(
            "session=%s safety net condition met (unmatched place, no question, missing lat/lon)",
            ai_session.id,
        )
        if result.get("near_hub"):
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
    return matched_location_id


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

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    taxonomy = get_taxonomy(session)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    try:
        result = ai_client.categorize(hub_names, category_labels, api_messages)
    except (AIProviderError, RuntimeError):
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

    matched_location_id = _apply_result_post_processing(session, ai_session, result)

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


def _categorize_new_session_message(
    message: str, hub_names: list[str], category_labels: dict[str, str]
) -> dict:
    """The DB-free half of a fresh-session (no history) categorize turn --
    safe to call concurrently from multiple threads, since it never reads
    or writes a Session. Used by the multi-place batch to run the slow AI
    calls for several places in parallel before persisting any of them."""
    try:
        return ai_client.categorize(hub_names, category_labels, [{"role": "user", "content": message}])
    except (AIProviderError, RuntimeError):
        logger.exception("categorize call failed for new-session message")
        return {
            "place_name": "",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None,
            "lon": None,
        }


def _persist_categorize_result(
    session: Session, message: str, result: dict
) -> tuple[AiSession, dict, Optional[str]]:
    """The DB-only half: creates the session/messages and applies the same
    post-processing _run_turn does, for a result already computed by
    _categorize_new_session_message. Must run sequentially against a
    single shared Session -- not thread-safe."""
    ai_session = AiSession()
    session.add(ai_session)
    session.commit()
    session.refresh(ai_session)

    session.add(AiMessage(session_id=ai_session.id, role="user", content=message))

    matched_location_id = _apply_result_post_processing(session, ai_session, result)

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
    can_confirm = (
        latest_result is not None
        and latest_result.get("question") is None
        and not latest_result.get("candidates")
    )

    return {
        "session_id": ai_session_id or "",
        "link": link or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "matched_location_id": matched_location_id or "",
        "taxonomy": get_taxonomy(session),
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

        try:
            detection = ai_client.detect_places(combined_message)
        except (AIProviderError, RuntimeError, json.JSONDecodeError):
            logger.exception("detect_places call failed, treating as single-place")
            detection = {"is_multi_place": False, "place_names": None}

        place_names = detection.get("place_names") or []
        if detection.get("is_multi_place") and len(place_names) >= 2:
            # Deferred import: ai_multi_categorize imports helpers from this module,
            # so importing it at module load time would create a circular import.
            from app.routers.ai_multi_categorize import start_multi_place_batch

            return start_multi_place_batch(request, session, combined_message, link, place_names)
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


def _resolve_location_and_create_reel(
    session: Session,
    link: str,
    place_name: str,
    near_hub: str,
    types: list[str],
    note: str,
    lat,
    lon,
    matched_location_id: str,
    confidence: Optional[str] = None,
) -> Reel:
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
            geocode_confidence=confidence or None,
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel = Reel(link=link, location_id=location_id, note=note or None)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return reel


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
    confidence: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    _resolve_location_and_create_reel(
        session, link, place_name, near_hub, types, note, lat, lon, matched_location_id, confidence
    )

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
    map_html = render_map_html(session)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
