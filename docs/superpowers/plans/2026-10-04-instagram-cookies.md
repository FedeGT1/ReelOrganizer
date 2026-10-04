# Instagram Authenticated Cookies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `yt-dlp` use an uploaded Instagram session cookies file when fetching reels, falling back to today's anonymous behavior when none is present, with a login-protected in-app page to upload/replace that file.

**Architecture:** `app/ingest/instagram.py` reads a cookies file path from `INSTAGRAM_COOKIES_PATH` and passes it to yt-dlp as `cookiefile` only if the file exists and is non-empty. A new router (`app/routers/instagram_cookies.py`) exposes a status+upload partial, wired into a new `/instagram-cookies` page following the exact pattern of the existing `/categories`/`/locations` pages.

**Tech Stack:** FastAPI, Jinja2 + htmx (existing patterns), yt-dlp, pytest + `TestClient`.

## Global Constraints

- `INSTAGRAM_COOKIES_PATH` env var, default `/data/instagram_cookies.txt` in Docker (set via `Dockerfile` `ENV`, same pattern as `REEL_DB_PATH`/`WHISPER_MODEL_CACHE_DIR`/`AI_DEBUG_LOG_PATH`).
- No cookie-format validation beyond "non-empty" — trusted single-user app, already behind the global `AuthMiddleware`.
- Any downstream import failure (expired cookies or otherwise) keeps today's existing generic fallback notice — no new notice text.
- New routes need no auth code of their own — `AuthMiddleware` in `app/main.py` protects every path by default already.

---

### Task 1: Cookie-aware `instagram.fetch()`

**Files:**
- Modify: `app/ingest/instagram.py`
- Test: `tests/test_ingest_instagram.py`

**Interfaces:**
- Produces: `app.ingest.instagram._cookies_path() -> Path` (reads `INSTAGRAM_COOKIES_PATH` env var, falling back to the module constant `DEFAULT_COOKIES_PATH = "/data/instagram_cookies.txt"`) — Task 2's router imports and reuses `_cookies_path()` directly, so the "file present and non-empty" check stays in one place.
- `fetch(url: str, download_dir: Path) -> FetchResult` signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Open `tests/test_ingest_instagram.py`. Add a new fake class right after `NoCaptionYoutubeDL` (after line 41, before the blank lines preceding `test_fetch_returns_caption_and_video_path`):

```python
class CapturingYoutubeDL(FakeYoutubeDL):
    captured_opts: dict | None = None

    def __init__(self, opts):
        super().__init__(opts)
        type(self).captured_opts = opts
```

Then add these three tests at the end of the file:

```python
def test_fetch_passes_cookiefile_when_cookies_file_exists_and_nonempty(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_file))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert CapturingYoutubeDL.captured_opts["cookiefile"] == str(cookies_file)


def test_fetch_omits_cookiefile_when_cookies_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(tmp_path / "does-not-exist.txt"))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert "cookiefile" not in CapturingYoutubeDL.captured_opts


def test_fetch_omits_cookiefile_when_cookies_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_file))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert "cookiefile" not in CapturingYoutubeDL.captured_opts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_instagram.py -v`
Expected: the three new tests FAIL with `AttributeError: 'NoneType' object is not subscriptable` or `KeyError: 'cookiefile'` (since `CapturingYoutubeDL.captured_opts` isn't populated / `cookiefile` isn't in `opts` yet — `fetch()` doesn't call `YoutubeDL` with that key).

- [ ] **Step 3: Implement cookie support in `app/ingest/instagram.py`**

Replace the full file content with:

```python
import os
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

YoutubeDL = yt_dlp.YoutubeDL
DownloadError = yt_dlp.utils.DownloadError

DEFAULT_COOKIES_PATH = "/data/instagram_cookies.txt"


class InstagramFetchError(Exception):
    pass


@dataclass
class FetchResult:
    caption: str
    video_path: Path


def _cookies_path() -> Path:
    return Path(os.environ.get("INSTAGRAM_COOKIES_PATH", DEFAULT_COOKIES_PATH))


def fetch(url: str, download_dir: Path) -> FetchResult:
    ydl_opts = {
        "outtmpl": str(download_dir / "reel.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "format": "mp4/best",
    }
    cookies_path = _cookies_path()
    if cookies_path.exists() and cookies_path.stat().st_size > 0:
        ydl_opts["cookiefile"] = str(cookies_path)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise InstagramFetchError(str(exc)) from exc

    matches = list(download_dir.glob("reel.*"))
    if not matches:
        raise InstagramFetchError("download completed but no output file was found")

    caption = (info or {}).get("description") or ""
    return FetchResult(caption=caption, video_path=matches[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_instagram.py -v`
Expected: all tests PASS (the 4 pre-existing ones plus the 3 new ones — 7 total).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest -q`
Expected: all tests PASS (no existing test sets `INSTAGRAM_COOKIES_PATH`, so they all take the default path, which doesn't exist on the dev/test machine — `cookiefile` stays omitted, identical to today's behavior).

- [ ] **Step 6: Commit**

```bash
git add app/ingest/instagram.py tests/test_ingest_instagram.py
git commit -m "feat: let yt-dlp use an Instagram cookies file when present"
```

---

### Task 2: Instagram cookies upload page

**Files:**
- Create: `app/routers/instagram_cookies.py`
- Create: `app/templates/instagram_cookies.html`
- Create: `app/templates/partials/instagram_cookies_status.html`
- Modify: `app/main.py`
- Modify: `app/templates/base.html`
- Test: `tests/test_instagram_cookies.py`

**Interfaces:**
- Consumes: `app.ingest.instagram.DEFAULT_COOKIES_PATH` and `app.ingest.instagram._cookies_path()` from Task 1.
- Produces: `ui_router` (`APIRouter`, prefix `/ui/instagram-cookies`) in `app.routers.instagram_cookies`, with `GET ""` and `POST ""`. Page route `GET /instagram-cookies` in `app.main`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_instagram_cookies.py`:

```python
def test_ui_instagram_cookies_status_shows_absent_when_no_file(client, monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(tmp_path / "missing.txt"))

    response = client.get("/ui/instagram-cookies")

    assert response.status_code == 200
    assert "Nessun cookie caricato" in response.text


def test_ui_instagram_cookies_upload_saves_file_and_shows_present(client, monkeypatch, tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_path))

    response = client.post(
        "/ui/instagram-cookies",
        files={"cookies_file": ("cookies.txt", b"# Netscape HTTP Cookie File\n", "text/plain")},
    )

    assert response.status_code == 200
    assert cookies_path.read_bytes() == b"# Netscape HTTP Cookie File\n"
    assert "ultimo aggiornamento" in response.text.lower()


def test_ui_instagram_cookies_upload_rejects_empty_file(client, monkeypatch, tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("existing content")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_path))

    response = client.post(
        "/ui/instagram-cookies",
        files={"cookies_file": ("cookies.txt", b"", "text/plain")},
    )

    assert response.status_code == 200
    assert "vuoto" in response.text.lower()
    assert cookies_path.read_text() == "existing content"


def test_instagram_cookies_page_renders(client):
    response = client.get("/instagram-cookies")

    assert response.status_code == 200
    assert 'hx-get="/ui/instagram-cookies"' in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_instagram_cookies.py -v`
Expected: all 4 FAIL with `404 Not Found` (neither the page route nor the `ui_router` exist yet).

- [ ] **Step 3: Create the router**

Create `app/routers/instagram_cookies.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, File, Request, UploadFile

from app.ingest.instagram import _cookies_path
from app.web import templates

ui_router = APIRouter(prefix="/ui/instagram-cookies", tags=["instagram-cookies-ui"])


def _status_context(error: str | None = None) -> dict:
    path = _cookies_path()
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
    path = _cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return templates.TemplateResponse(request, "partials/instagram_cookies_status.html", _status_context())
```

- [ ] **Step 4: Create the page shell template**

Create `app/templates/instagram_cookies.html`:

```html
{% extends "base.html" %}
{% block content %}
<section id="instagram-cookies-status" hx-get="/ui/instagram-cookies" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento stato cookie...</p>
</section>
{% endblock %}
```

- [ ] **Step 5: Create the status+upload partial**

Create `app/templates/partials/instagram_cookies_status.html`:

```html
{% if error %}
<p class="error">{{ error }}</p>
{% endif %}
{% if cookies_present %}
<p>Cookie Instagram caricati — ultimo aggiornamento: {{ updated_at.strftime("%Y-%m-%d %H:%M UTC") }}</p>
{% else %}
<p>Nessun cookie caricato — l'import prova in anonimo (può fallire su IP datacenter).</p>
{% endif %}
<form hx-post="/ui/instagram-cookies" hx-target="#instagram-cookies-status" hx-swap="innerHTML" hx-encoding="multipart/form-data">
    <input type="file" name="cookies_file" accept=".txt" required>
    <button type="submit">Carica cookie</button>
</form>
```

- [ ] **Step 6: Wire the router and page route into `app/main.py`**

In `app/main.py`, change the import on line 13 from:

```python
from app.routers import ai_ask, ai_categorize, ai_multi_categorize, auth, categories, instagram_import, locations, map as map_router, reels
```

to:

```python
from app.routers import ai_ask, ai_categorize, ai_multi_categorize, auth, categories, instagram_cookies, instagram_import, locations, map as map_router, reels
```

Add this line after `app.include_router(locations.ui_router)` (currently line 61):

```python
app.include_router(instagram_cookies.ui_router)
```

Add this page route after `locations_page` (currently lines 76-78):

```python
@app.get("/instagram-cookies")
async def instagram_cookies_page(request: Request):
    return templates.TemplateResponse(request, "instagram_cookies.html", {})
```

- [ ] **Step 7: Add the nav link**

In `app/templates/base.html`, change:

```html
            <a href="/locations">Gestisci hub</a>
            <a href="/ask">Chiedi all'AI</a>
```

to:

```html
            <a href="/locations">Gestisci hub</a>
            <a href="/instagram-cookies">Cookie Instagram</a>
            <a href="/ask">Chiedi all'AI</a>
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_instagram_cookies.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 9: Run the full suite to check for regressions**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add app/routers/instagram_cookies.py app/templates/instagram_cookies.html app/templates/partials/instagram_cookies_status.html app/main.py app/templates/base.html tests/test_instagram_cookies.py
git commit -m "feat: add login-protected page to upload Instagram cookies for yt-dlp"
```

---

### Task 3: Docs

**Files:**
- Modify: `Dockerfile`
- Modify: `README.md`

**Interfaces:** None (docs only).

- [ ] **Step 1: Add the Docker env default**

In `Dockerfile`, change:

```dockerfile
ENV REEL_DB_PATH=/data/japan_reels.db
ENV WHISPER_MODEL_CACHE_DIR=/data/whisper_models
ENV AI_DEBUG_LOG_PATH=/data/ai_debug.log
VOLUME ["/data"]
```

to:

```dockerfile
ENV REEL_DB_PATH=/data/japan_reels.db
ENV WHISPER_MODEL_CACHE_DIR=/data/whisper_models
ENV AI_DEBUG_LOG_PATH=/data/ai_debug.log
ENV INSTAGRAM_COOKIES_PATH=/data/instagram_cookies.txt
VOLUME ["/data"]
```

- [ ] **Step 2: Document it in `README.md`**

In `README.md`, insert a new section right before `## Persistence`:

```markdown
## Instagram authenticated cookies (optional)

Instagram applies much stricter limits to anonymous (cookie-less) requests
from datacenter/hosting IPs, which is what most VPS providers use — the
Instagram auto-import feature may work fine from one VPS and fail
consistently on another for this reason alone, regardless of configuration.
If anonymous imports are failing, upload a cookies.txt file from a real,
already-logged-in Instagram session at `/instagram-cookies` (login-protected,
same as the rest of the app): export it from a browser extension (e.g.
["YT-DLP Cookie Exporter"](https://addons.mozilla.org/en-US/android/addon/yt-dlp-cookie-exporter/)
on Firefox for Android works entirely from a phone), then upload the file
through that page. It's saved to `INSTAGRAM_COOKIES_PATH` (defaults to
`/data/instagram_cookies.txt` in Docker, so it persists across rebuilds on
the `/data` volume); `yt-dlp` uses it automatically whenever it's present
and non-empty, and falls back to today's anonymous behavior otherwise.
Export a fresh cookies.txt and re-upload whenever imports start failing
again — session cookies expire eventually (typically weeks to months).

Running locally outside Docker, point `INSTAGRAM_COOKIES_PATH` at a local,
writable file (same reasoning as `WHISPER_MODEL_CACHE_DIR` above) if you
want to test this without the Docker volume.
```

- [ ] **Step 3: Verify the inserted text**

Run: `grep -n "INSTAGRAM_COOKIES_PATH" Dockerfile README.md`
Expected: one match in `Dockerfile`, two matches in `README.md`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile README.md
git commit -m "docs: document the Instagram cookies upload page and INSTAGRAM_COOKIES_PATH"
```
