import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import AiMessage, AiSession
from app.routers.ai_categorize import (
    _build_ai_chat_context,
    _find_matching_location,
    _resolve_location_and_create_reel,
    _run_turn,
)
from app.routers.categories import get_taxonomy
from app.routers.map import render_map_html
from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context
from app.web import templates

router = APIRouter(prefix="/ui/ai/multi", tags=["ai-multi"])

logger = logging.getLogger("app.ai")

MAX_PLACES = 15


def _seed_message(original_message: str, place_name: str) -> str:
    return (
        f"{original_message}\n\n"
        f"Concentrati SOLO su questo luogo specifico menzionato nel testo, ignorando gli altri: {place_name}"
    )


def _read_latest_result(session: Session, session_id: str) -> Optional[dict]:
    messages = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == session_id, AiMessage.role == "assistant")
        .order_by(AiMessage.created_at)
    ).all()
    if not messages:
        return None
    return json.loads(messages[-1].content)


def _build_multi_context(session: Session, session_ids: list[str], link: str) -> dict:
    # Defensive dedup: the rendered page never produces duplicate ids in a
    # real submission (the confirm form and each clarify form are sibling,
    # non-nested <form> elements, so a browser only ever submits one form's
    # own inputs). This guards only against a malformed/crafted request.
    seen: set[str] = set()
    session_ids = [sid for sid in session_ids if not (sid in seen or seen.add(sid))]

    rows = []
    for session_id in session_ids:
        result = _read_latest_result(session, session_id)
        if result is None:
            continue
        matched_location_id = _find_matching_location(session, result.get("place_name", ""))
        resolved = result.get("question") is None
        place_payload = {
            "place_name": result.get("place_name", ""),
            "near_hub": result.get("near_hub") or "",
            "types": result.get("types", []),
            "note": result.get("note", ""),
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "matched_location_id": matched_location_id or "",
            "confidence": result.get("confidence"),
        }
        rows.append(
            {
                "session_id": session_id,
                "result": result,
                "resolved": resolved,
                "place_json": json.dumps(place_payload),
            }
        )

    return {
        "link": link or "",
        "session_ids": session_ids,
        "rows": rows,
        "taxonomy": get_taxonomy(session),
    }


def start_multi_place_batch(
    request: Request, session: Session, original_message: str, link: str, place_names: list[str]
):
    session_ids = []
    for place_name in place_names[:MAX_PLACES]:
        ai_session, _, _ = _run_turn(session, None, _seed_message(original_message, place_name))
        session_ids.append(ai_session.id)

    context = _build_multi_context(session, session_ids, link)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/message")
def ui_ai_multi_message(
    request: Request,
    link: str = Form(""),
    session_ids: list[str] = Form([]),
    clarify_session_id: str = Form(""),
    clarify_text: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if clarify_session_id and clarify_text:
        _run_turn(session, clarify_session_id, clarify_text)

    context = _build_multi_context(session, session_ids, link)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/confirm")
def ui_ai_multi_confirm(
    request: Request,
    link: str = Form(...),
    session_ids: list[str] = Form([]),
    place_json: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    for raw in place_json:
        try:
            place = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry")
            continue
        _resolve_location_and_create_reel(
            session,
            link,
            place["place_name"],
            place.get("near_hub", ""),
            place.get("types", []),
            place.get("note", ""),
            place.get("lat"),
            place.get("lon"),
            place.get("matched_location_id", ""),
            place.get("confidence"),
        )

    for session_id in session_ids:
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
