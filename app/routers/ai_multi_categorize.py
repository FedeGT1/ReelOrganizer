import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.location_matching import resolve_place
from app.models import AiMessage, AiSession, Location, User
from app.reel_links import find_duplicate_reel
from app.routers.ai_categorize import (
    _build_ai_chat_context,
    _categorize_new_session_message,
    _persist_categorize_result,
    _resolve_location_and_create_reel,
    _run_turn,
)
from app.routers.categories import get_taxonomy
from app.routers.map import render_map_html
from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context
from app.scoping import get_owned, user_query
from app.web import templates

router = APIRouter(prefix="/ui/ai/multi", tags=["ai-multi"])

logger = logging.getLogger("app.ai")

MAX_PLACES = 15
# Bounds how many categorize() calls run at once for one batch. Keeps the
# parallel speedup (vs. one-at-a-time) while avoiding firing all MAX_PLACES
# requests at the provider in one burst.
MAX_CONCURRENT_CATEGORIZE_CALLS = 5


def _seed_message(original_message: str, place_name: str) -> str:
    return (
        f"{original_message}\n\n"
        f"Concentrati SOLO su questo luogo specifico menzionato nel testo, ignorando gli altri: {place_name}"
    )


def _read_latest_result(session: Session, user_id: str, session_id: str) -> Optional[dict]:
    ai_session = get_owned(session, AiSession, session_id, user_id)
    if ai_session is None:
        return None
    messages = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == session_id, AiMessage.role == "assistant")
        .order_by(AiMessage.created_at)
    ).all()
    if not messages:
        return None
    return json.loads(messages[-1].content)


def _build_multi_context(
    session: Session, user_id: str, session_ids: list[str], link: str, caption: str = "", transcript: str = ""
) -> dict:
    # Defensive dedup: the rendered page never produces duplicate ids in a
    # real submission (the confirm form and each clarify form are sibling,
    # non-nested <form> elements, so a browser only ever submits one form's
    # own inputs). This guards only against a malformed/crafted request.
    seen: set[str] = set()
    session_ids = [sid for sid in session_ids if not (sid in seen or seen.add(sid))]

    rows = []
    for session_id in session_ids:
        result = _read_latest_result(session, user_id, session_id)
        if result is None:
            continue
        resolution = resolve_place(
            session, result.get("place_name", ""), result.get("near_hub"), result.get("lat"), result.get("lon"), user_id
        )
        resolved = result.get("question") is None
        place_payload = {
            "place_name": result.get("place_name", ""),
            "types": result.get("types", []),
            "note": result.get("note", ""),
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "resolution_location_id": resolution.place_location_id or "",
            "resolution_hub_id": resolution.hub_id or "",
            "confidence": result.get("confidence"),
        }
        rows.append(
            {
                "session_id": session_id,
                "result": result,
                "resolved": resolved,
                "resolution": resolution,
                "place_json": json.dumps(place_payload),
            }
        )

    return {
        "link": link or "",
        "caption": caption or "",
        "transcript": transcript or "",
        "session_ids": session_ids,
        "rows": rows,
        "taxonomy": get_taxonomy(session, user_id),
    }


def start_multi_place_batch(
    request: Request,
    session: Session,
    user_id: str,
    original_message: str,
    link: str,
    place_names: list[str],
    caption: str = "",
    transcript: str = "",
):
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    seeded_messages = [
        _seed_message(original_message, place_name) for place_name in place_names[:MAX_PLACES]
    ]

    # The slow part -- the AI calls -- runs concurrently, DB-free. Results
    # come back in the same order as seeded_messages regardless of which
    # call actually finished first (concurrent.futures.Executor.map
    # guarantee), so pairing with the right place is preserved.
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CATEGORIZE_CALLS) as executor:
        results = list(
            executor.map(
                lambda m: _categorize_new_session_message(m, hub_names, category_labels),
                seeded_messages,
            )
        )

    session_ids = []
    for message, result in zip(seeded_messages, results):
        ai_session, _, _ = _persist_categorize_result(session, user_id, message, result)
        session_ids.append(ai_session.id)

    context = _build_multi_context(session, user_id, session_ids, link, caption, transcript)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/message")
def ui_ai_multi_message(
    request: Request,
    link: str = Form(""),
    session_ids: list[str] = Form([]),
    clarify_session_id: str = Form(""),
    clarify_text: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if clarify_session_id and clarify_text:
        if get_owned(session, AiSession, clarify_session_id, current_user.id) is None:
            raise HTTPException(status_code=404, detail="AI session not found")
        _run_turn(session, current_user.id, clarify_session_id, clarify_text)

    context = _build_multi_context(session, current_user.id, session_ids, link, caption, transcript)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/confirm")
def ui_ai_multi_confirm(
    request: Request,
    link: str = Form(...),
    session_ids: list[str] = Form([]),
    place_json: list[str] = Form([]),
    confirm_duplicate: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            warning_html = templates.get_template(
                "partials/_ai_multi_confirm_duplicate_warning.html"
            ).render(
                existing_location_name=existing_location.name if existing_location else "?",
                existing_note=duplicate.note,
                link=link,
                session_ids=session_ids,
                place_json=place_json,
                caption=caption,
                transcript=transcript,
            )
            return HTMLResponse(warning_html)

    places = []
    for raw in place_json:
        try:
            places.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry")
            continue

    # Validate every checked place BEFORE creating any of them. Each call to
    # _resolve_location_and_create_reel commits internally, so doing this
    # validation one place at a time inside the creation loop below would let
    # earlier places in the batch get committed before a later place's 400 --
    # a partial commit that duplicates reels if the user fixes and resubmits.
    # These two conditions must mirror _resolve_location_and_create_reel's
    # own checks exactly.
    for place in places:
        if not place.get("resolution_location_id", ""):
            if not place.get("lat") or not place.get("lon"):
                raise HTTPException(
                    status_code=400, detail="lat/lon are required to create a new location"
                )
            if not place.get("resolution_hub_id", ""):
                raise HTTPException(
                    status_code=400, detail="a hub choice is required to create a new location"
                )

    for place in places:
        _resolve_location_and_create_reel(
            session,
            current_user.id,
            link,
            place["place_name"],
            place.get("types", []),
            place.get("note", ""),
            place.get("lat"),
            place.get("lon"),
            place.get("resolution_location_id", ""),
            place.get("resolution_hub_id", ""),
            place.get("confidence"),
            caption,
            transcript,
        )

    for session_id in session_ids:
        stale_ai_session = get_owned(session, AiSession, session_id, current_user.id)
        if stale_ai_session is not None:
            for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
                session.delete(msg)
            session.delete(stale_ai_session)
            session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, current_user.id, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
