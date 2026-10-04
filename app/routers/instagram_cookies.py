import os
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, File, Request, UploadFile

from app.ingest.instagram import cookies_path
from app.web import templates

ui_router = APIRouter(prefix="/ui/instagram-cookies", tags=["instagram-cookies-ui"])


def _status_context(error: str | None = None) -> dict:
    path = cookies_path()
    if path.exists() and path.stat().st_size > 0:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return {"cookies_present": True, "updated_at": updated_at, "error": error}
    return {"cookies_present": False, "updated_at": None, "error": error}


@ui_router.get("")
def ui_instagram_cookies_status(request: Request):
    return templates.TemplateResponse(
        request, "partials/instagram_cookies_status.html", _status_context()
    )


@ui_router.post("")
async def ui_instagram_cookies_upload(request: Request, cookies_file: UploadFile = File(...)):
    content = await cookies_file.read()
    if not content:
        return templates.TemplateResponse(
            request,
            "partials/instagram_cookies_status.html",
            _status_context(error="Il file è vuoto."),
        )
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(content)
        os.replace(tmp_name, path)
    except Exception:
        os.unlink(tmp_name)
        raise
    return templates.TemplateResponse(request, "partials/instagram_cookies_status.html", _status_context())
