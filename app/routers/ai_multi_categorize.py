import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select

from app.db import get_session
from app.models import AiMessage
from app.routers.ai_categorize import _find_matching_location, _run_turn
from app.routers.categories import get_taxonomy
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
    # The template repeats the `session_ids` hidden inputs in both the main
    # confirm form and in each unresolved row's clarify form, so a submission
    # from the rendered page can legitimately contain duplicate ids. Dedupe
    # here (preserving order) so a place doesn't get rendered as two rows.
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
    if clarify_session_id and clarify_text:
        _run_turn(session, clarify_session_id, clarify_text)

    context = _build_multi_context(session, session_ids, link)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)
