import logging
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session

from app.db import get_session
from app.ingest import instagram, transcribe
from app.routers.ai_categorize import _build_ai_chat_context
from app.web import templates

router = APIRouter(prefix="/ui/ai", tags=["ai-import"])

logger = logging.getLogger("app.ingest")

IMPORT_TIMEOUT_SECONDS = 180

FETCH_FAILED_NOTICE = (
    "Non sono riuscito a importare in automatico questo reel — "
    "inserisci la didascalia a mano qui sotto."
)
TIMEOUT_NOTICE = "L'importazione ha impiegato troppo tempo — inserisci la didascalia a mano qui sotto."
NOT_INSTAGRAM_NOTICE = "Il link deve essere un reel Instagram (instagram.com)."


class _ImportTimeout(Exception):
    pass


def _is_instagram_link(link: str) -> bool:
    try:
        parsed = urlparse(link)
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https") and parsed.hostname in (
        "instagram.com",
        "www.instagram.com",
    )


@dataclass
class ImportResult:
    caption: Optional[str]
    transcript: Optional[str]


def _build_prefill_message(result: ImportResult) -> str:
    parts = []
    if result.caption:
        parts.append(f"Didascalia: {result.caption}")
    if result.transcript:
        parts.append(f"Trascrizione audio: {result.transcript}")
    elif result.transcript is None:
        parts.append("(trascrizione non disponibile)")
    return "\n\n".join(parts)


def _run_import(link: str) -> ImportResult:
    with tempfile.TemporaryDirectory() as tmp:
        result = instagram.fetch(link, Path(tmp))
        try:
            transcript = transcribe.transcribe(result.video_path)
        except Exception:
            logger.exception("transcription failed for link=%s", link)
            transcript = None

    return ImportResult(caption=result.caption, transcript=transcript)


def _run_import_with_timeout(link: str, timeout_seconds: float) -> ImportResult:
    outcome: dict = {}

    def worker():
        try:
            outcome["value"] = _run_import(link)
        except Exception as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise _ImportTimeout()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


@router.post("/import")
def ui_ai_import(request: Request, link: str = Form(...), session: Session = Depends(get_session)):
    if not _is_instagram_link(link):
        context = _build_ai_chat_context(session, None, link, notice=NOT_INSTAGRAM_NOTICE)
        return templates.TemplateResponse(request, "partials/ai_chat.html", context)

    prefill_message = ""
    import_caption = ""
    import_transcript = ""
    notice = None
    try:
        result = _run_import_with_timeout(link, IMPORT_TIMEOUT_SECONDS)
        prefill_message = _build_prefill_message(result)
        import_caption = result.caption or ""
        import_transcript = result.transcript or ""
    except instagram.InstagramFetchError:
        logger.exception("instagram fetch failed for link=%s", link)
        notice = FETCH_FAILED_NOTICE
    except _ImportTimeout:
        logger.warning("instagram import timed out for link=%s", link)
        notice = TIMEOUT_NOTICE
    except Exception:
        logger.exception("unexpected error during instagram import for link=%s", link)
        notice = FETCH_FAILED_NOTICE

    context = _build_ai_chat_context(session, None, link, notice=notice)
    context["prefill_message"] = prefill_message
    context["caption"] = import_caption
    context["transcript"] = import_transcript
    return templates.TemplateResponse(request, "partials/ai_chat.html", context)
