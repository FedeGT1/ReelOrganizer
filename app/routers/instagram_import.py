import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session

from app.db import get_session
from app.ingest import instagram, transcribe
from app.routers.ai_categorize import _build_ai_chat_context
from app.web import templates

router = APIRouter(prefix="/ui/ai", tags=["ai-import"])

logger = logging.getLogger("app.ingest")

IMPORT_TIMEOUT_SECONDS = 60

FETCH_FAILED_NOTICE = (
    "Non sono riuscito a importare in automatico questo reel — "
    "inserisci la didascalia a mano qui sotto."
)
TIMEOUT_NOTICE = "L'importazione ha impiegato troppo tempo — inserisci la didascalia a mano qui sotto."
NOT_INSTAGRAM_NOTICE = "Il link deve essere un reel Instagram (instagram.com)."


def _is_instagram_link(link: str) -> bool:
    parsed = urlparse(link)
    return parsed.scheme.lower() in ("http", "https") and parsed.hostname in (
        "instagram.com",
        "www.instagram.com",
    )


def _run_import(link: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        result = instagram.fetch(link, Path(tmp))
        try:
            transcript = transcribe.transcribe(result.video_path)
        except Exception:
            logger.exception("transcription failed for link=%s", link)
            transcript = None

    parts = []
    if result.caption:
        parts.append(f"Didascalia: {result.caption}")
    if transcript:
        parts.append(f"Trascrizione audio: {transcript}")
    elif transcript is None:
        parts.append("(trascrizione non disponibile)")
    return "\n\n".join(parts)


@router.post("/import")
def ui_ai_import(request: Request, link: str = Form(...), session: Session = Depends(get_session)):
    if not _is_instagram_link(link):
        context = _build_ai_chat_context(session, None, link, notice=NOT_INSTAGRAM_NOTICE)
        return templates.TemplateResponse(request, "partials/ai_chat.html", context)

    prefill_message = ""
    notice = None
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_run_import, link)
        prefill_message = future.result(timeout=IMPORT_TIMEOUT_SECONDS)
    except instagram.InstagramFetchError:
        logger.exception("instagram fetch failed for link=%s", link)
        notice = FETCH_FAILED_NOTICE
    except FutureTimeoutError:
        logger.warning("instagram import timed out for link=%s", link)
        notice = TIMEOUT_NOTICE
    finally:
        executor.shutdown(wait=False)

    context = _build_ai_chat_context(session, None, link, notice=notice)
    context["prefill_message"] = prefill_message
    return templates.TemplateResponse(request, "partials/ai_chat.html", context)
