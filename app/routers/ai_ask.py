import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.ai.prompts import MAX_REELS_IN_CONTEXT
from app.ai.providers.base import AIProviderError
from app.db import get_session
from app.models import AskMessage, AskSession, Location, Reel, ReelType
from app.routers.categories import get_taxonomy
from app.routers.reels import _location_and_satellite_ids
from app.web import templates

ui_router = APIRouter(prefix="/ui/ask", tags=["ask-ui"])

logger = logging.getLogger("app.ai")

FALLBACK_ANSWER = "Errore nel contattare l'assistente, riprova."


def _scoped_reel_context(
    session: Session, location_id: Optional[str], category_key: Optional[str]
) -> tuple[list[dict], bool]:
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query.order_by(Reel.created_at)).all()

    if category_key is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == category_key)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    taxonomy = get_taxonomy(session)
    entries = []
    for r in reels:
        location = session.get(Location, r.location_id)
        type_keys = session.exec(select(ReelType.type).where(ReelType.reel_id == r.id)).all()
        entries.append({
            "place_name": location.name if location else "?",
            "categories": [taxonomy[t]["label"] for t in type_keys if t in taxonomy],
            "note": r.note or "",
            "link": r.link,
        })

    truncated = len(entries) > MAX_REELS_IN_CONTEXT
    return entries[:MAX_REELS_IN_CONTEXT], truncated


def _run_ask_turn(
    session: Session,
    session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    message: str,
) -> AskSession:
    if session_id:
        ask_session = session.get(AskSession, session_id)
        if ask_session is None:
            raise HTTPException(status_code=404, detail="Ask session not found")
        location_id = ask_session.location_id
        category_key = ask_session.category_key
    else:
        ask_session = AskSession(location_id=location_id, category_key=category_key)
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

    session.add(AskMessage(session_id=ask_session.id, role="user", content=message))
    session.commit()

    history = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    reels, truncated = _scoped_reel_context(session, location_id, category_key)
    location = session.get(Location, location_id) if location_id else None
    location_name = location.name if location else None
    taxonomy = get_taxonomy(session)
    category_label = taxonomy[category_key]["label"] if category_key and category_key in taxonomy else None

    try:
        result = ai_client.ask(reels, location_name, category_label, truncated, api_messages)
        answer = result["answer"]
    except (AIProviderError, RuntimeError):
        logger.exception("ask_session=%s ask call failed", ask_session.id)
        answer = FALLBACK_ANSWER

    session.add(AskMessage(session_id=ask_session.id, role="assistant", content=answer))
    ask_session.updated_at = datetime.utcnow()
    session.add(ask_session)
    session.commit()

    return ask_session


def _session_message_label(first_message: str, max_len: int = 60) -> str:
    text = (first_message or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _session_scope_label(location_name: Optional[str], category_label: Optional[str]) -> str:
    return f"{location_name or 'Tutte le città'} — {category_label or 'Tutte le categorie'}"


def _list_ask_sessions(session: Session) -> list[dict]:
    sessions = session.exec(select(AskSession).order_by(AskSession.updated_at.desc())).all()
    taxonomy = get_taxonomy(session)
    summaries = []
    for s in sessions:
        first_message = session.exec(
            select(AskMessage.content)
            .where(AskMessage.session_id == s.id, AskMessage.role == "user")
            .order_by(AskMessage.created_at)
        ).first()
        location = session.get(Location, s.location_id) if s.location_id else None
        category_label = (
            taxonomy[s.category_key]["label"] if s.category_key and s.category_key in taxonomy else None
        )
        summaries.append({
            "id": s.id,
            "message_label": _session_message_label(first_message or ""),
            "scope_label": _session_scope_label(location.name if location else None, category_label),
            "date_label": s.updated_at.strftime("%d/%m/%Y %H:%M"),
        })
    return summaries


def _build_ask_chat_context(
    session: Session,
    ask_session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    notice: Optional[str] = None,
) -> dict:
    history: list[dict] = []
    if ask_session_id:
        messages = session.exec(
            select(AskMessage).where(AskMessage.session_id == ask_session_id).order_by(AskMessage.created_at)
        ).all()
        history = [{"role": m.role, "text": m.content} for m in messages]

    hubs = session.exec(select(Location).where(Location.is_hub == True).order_by(Location.name)).all()
    return {
        "session_id": ask_session_id or "",
        "location_id": location_id or "",
        "category_key": category_key or "",
        "hubs": hubs,
        "taxonomy": get_taxonomy(session),
        "history": history,
        "notice": notice,
        "sessions": _list_ask_sessions(session),
    }


@ui_router.get("/panel")
def ui_ask_panel(
    request: Request,
    session_id: str = "",
    location_id: str = "",
    category_key: str = "",
    session: Session = Depends(get_session),
):
    if session_id:
        ask_session = session.get(AskSession, session_id)
        if ask_session is None:
            context = _build_ask_chat_context(
                session, None, None, None, notice="Conversazione non trovata, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        context = _build_ask_chat_context(
            session, ask_session.id, ask_session.location_id, ask_session.category_key
        )
        return templates.TemplateResponse(request, "partials/ask_chat.html", context)

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, None, location_id or None, category_key or None),
    )


@ui_router.post("/message")
def ui_ask_message(
    request: Request,
    session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    message: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        ask_session = _run_ask_turn(
            session, session_id or None, location_id or None, category_key or None, message
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ask_chat_context(
                session, None, location_id or None, category_key or None,
                notice="Sessione scaduta, ricomincia pure da qui.",
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        raise

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, ask_session.id, ask_session.location_id, ask_session.category_key),
    )


@ui_router.delete("/history/{session_id}")
def ui_ask_delete_history(
    request: Request,
    session_id: str,
    current_session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    session: Session = Depends(get_session),
):
    ask_session = session.get(AskSession, session_id)
    if ask_session is not None:
        for m in session.exec(select(AskMessage).where(AskMessage.session_id == session_id)).all():
            session.delete(m)
        session.delete(ask_session)
        session.commit()

    reopen_session_id = None if current_session_id == session_id else (current_session_id or None)
    context = _build_ask_chat_context(session, reopen_session_id, location_id or None, category_key or None)
    return templates.TemplateResponse(request, "partials/ask_chat.html", context)
