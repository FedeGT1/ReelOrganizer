import json
import logging
from typing import Optional

from app.ai.providers.base import AIProviderError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.location_matching import NEW_HUB_SENTINEL, resolve_place
from app.models import AiMessage, AiSession, Location, Reel, ReelType
from app.reel_links import find_duplicate_reel
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
    """Shared post-AI-call bookkeeping: type filtering, location resolution,
    and the missing-coordinates safety net. Mutates `result` in place and
    returns the auto-matched place location id (None if ambiguous/new).
    DB reads only -- callers own commit()."""
    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    valid_type_keys = get_valid_type_keys(session)
    result["types"] = [t for t in result.get("types", []) if t in valid_type_keys]

    resolution = resolve_place(
        session, result["place_name"], result.get("near_hub"), result.get("lat"), result.get("lon")
    )
    logger.debug("session=%s resolution=%s", ai_session.id, resolution)

    if (
        resolution.place_tier == "ambiguous"
        and result.get("question") is None
        and not result.get("candidates")
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        if resolution.hub_tier == "auto":
            hub = session.get(Location, resolution.hub_id)
            result["lat"] = hub.lat
            result["lon"] = hub.lon

        if result.get("lat") is None or result.get("lon") is None:
            result["question"] = MISSING_COORDINATES_QUESTION

    logger.debug("session=%s final result=%s", ai_session.id, result)
    return resolution.place_location_id


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
    session: Session,
    ai_session_id: Optional[str],
    link: str,
    notice: Optional[str] = None,
    caption: str = "",
    transcript: str = "",
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

    resolution = (
        resolve_place(
            session,
            latest_result["place_name"],
            latest_result.get("near_hub"),
            latest_result.get("lat"),
            latest_result.get("lon"),
        )
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
        "caption": caption or "",
        "transcript": transcript or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "resolution": resolution,
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
    caption: str = Form(""),
    transcript: str = Form(""),
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

            return start_multi_place_batch(
                request, session, combined_message, link, place_names, caption, transcript
            )
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
        request,
        "partials/ai_chat.html",
        _build_ai_chat_context(session, ai_session.id, link, caption=caption, transcript=transcript),
    )


def _resolve_location_and_create_reel(
    session: Session,
    link: str,
    place_name: str,
    types: list[str],
    note: str,
    lat,
    lon,
    resolution_location_id: str,
    resolution_hub_id: str = "",
    confidence: Optional[str] = None,
    caption: str = "",
    transcript: str = "",
) -> Reel:
    if resolution_location_id:
        location_id = resolution_location_id
    else:
        if not lat or not lon:
            raise HTTPException(
                status_code=400, detail="lat/lon are required to create a new location"
            )
        if not resolution_hub_id:
            raise HTTPException(
                status_code=400, detail="a hub choice is required to create a new location"
            )

        is_hub = resolution_hub_id == NEW_HUB_SENTINEL
        new_location = Location(
            name=place_name,
            is_hub=is_hub,
            parent_id=None if is_hub else resolution_hub_id,
            lat=float(lat),
            lon=float(lon),
            geocode_confidence=confidence or None,
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel = Reel(
        link=link,
        location_id=location_id,
        note=note or None,
        caption=caption or None,
        transcript=transcript or None,
    )
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
    types: list[str] = Form([]),
    note: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    resolution_location_id: str = Form(""),
    resolution_hub_id: str = Form(""),
    confidence: str = Form(""),
    confirm_duplicate: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            warning_html = templates.get_template(
                "partials/_ai_confirm_duplicate_warning.html"
            ).render(
                existing_location_name=existing_location.name if existing_location else "?",
                existing_note=duplicate.note,
                session_id=session_id,
                link=link,
                place_name=place_name,
                types=types,
                note=note,
                lat=lat,
                lon=lon,
                resolution_location_id=resolution_location_id,
                resolution_hub_id=resolution_hub_id,
                confidence=confidence,
                caption=caption,
                transcript=transcript,
            )
            return HTMLResponse(warning_html)

    _resolve_location_and_create_reel(
        session,
        link,
        place_name,
        types,
        note,
        lat,
        lon,
        resolution_location_id,
        resolution_hub_id,
        confidence,
        caption,
        transcript,
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
