import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, User
from app.routers.ai_categorize import _categorize_new_session_message
from app.routers.categories import get_taxonomy
from app.routers.reels import _serialize_reel
from app.scoping import get_owned, user_query
from app.web import templates

ui_router = APIRouter(prefix="/ui/reels", tags=["note-regeneration"])

logger = logging.getLogger("app.ai")

# Mirrors the multi-place batch's concurrency cap: keeps bulk regeneration
# reasonably fast without firing unbounded parallel AI calls.
MAX_CONCURRENT_REGENERATE_CALLS = 5


def _regen_source_message(reel: Reel) -> Optional[str]:
    parts = []
    if reel.caption:
        parts.append(f"Didascalia: {reel.caption}")
    if reel.transcript:
        parts.append(f"Trascrizione audio: {reel.transcript}")
    if parts:
        return "\n\n".join(parts)
    if reel.note:
        return f"Nota attuale: {reel.note}"
    return None


def _hub_names_and_category_labels(session: Session, user_id: str) -> tuple[list[str], dict[str, str]]:
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}
    return hub_names, category_labels


def _regenerate_note(
    reel: Reel, hub_names: list[str], category_labels: dict[str, str]
) -> bool:
    source = _regen_source_message(reel)
    if source is None:
        return False
    message = f"Link: {reel.link}\nDescrizione: {source}"
    result = _categorize_new_session_message(message, hub_names, category_labels)
    if result.get("question") or not result.get("note"):
        return False
    reel.note = result["note"]
    return True


@ui_router.put("/{reel_id}/regenerate-note")
def ui_regenerate_reel_note(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    hub_names, category_labels = _hub_names_and_category_labels(session, current_user.id)
    updated = _regenerate_note(reel, hub_names, category_labels)
    if updated:
        session.add(reel)
    session.commit()
    session.refresh(reel)

    card_html = templates.get_template("partials/_reel_card.html").render(
        reel=_serialize_reel(session, reel),
        taxonomy=get_taxonomy(session, current_user.id),
        regen_error=None if updated else "Non sono riuscito a rigenerare la nota, riprova.",
    )
    return HTMLResponse(card_html)


@ui_router.post("/regenerate-notes")
def ui_regenerate_all_notes(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    reels = session.exec(user_query(Reel, current_user.id)).all()
    hub_names, category_labels = _hub_names_and_category_labels(session, current_user.id)

    regenerable = [r for r in reels if _regen_source_message(r) is not None]
    skipped = len(reels) - len(regenerable)
    messages = [
        f"Link: {r.link}\nDescrizione: {_regen_source_message(r)}" for r in regenerable
    ]

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REGENERATE_CALLS) as executor:
        results = list(
            executor.map(
                lambda m: _categorize_new_session_message(m, hub_names, category_labels),
                messages,
            )
        )

    updated = 0
    failed = 0
    for reel, result in zip(regenerable, results):
        if result.get("question") or not result.get("note"):
            failed += 1
            continue
        reel.note = result["note"]
        session.add(reel)
        updated += 1
    session.commit()

    summary = (
        f"{updated} nota/e aggiornata/e, {skipped} saltata/e (nessun testo disponibile), "
        f"{failed} fallita/e."
    )
    return HTMLResponse(f'<p class="ai-notice">{summary}</p>')
