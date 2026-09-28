# Instagram Auto-Import (Caption + Speech-to-Text) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click "Importa da Instagram" action to the existing AI-assisted add-reel flow that downloads a reel, extracts its caption, transcribes its audio via speech-to-text, and prefills the existing (editable) description textarea — so the user no longer has to retype the caption by hand.

**Architecture:** A new `app/ingest/` package wraps two external tools behind small, mockable functions: `instagram.py` (yt-dlp — downloads the video and reads its caption from metadata) and `transcribe.py` (faster-whisper — transcribes the downloaded video's audio). A new router, `app/routers/instagram_import.py`, ties them together behind `POST /ui/ai/import`, reusing the existing `_build_ai_chat_context` helper from `app/routers/ai_categorize.py` so the response is the same `partials/ai_chat.html` panel the rest of the AI flow already renders — just with the message textarea prefilled. No changes to `app/ai/client.py`, `app/ai/prompts.py`, or the categorization logic itself.

**Tech Stack:** FastAPI (sync endpoints, already thread-pooled), yt-dlp, faster-whisper, HTMX (existing panel-swap pattern), pytest with `monkeypatch`-based test doubles (matching the existing `app/ai/client.py` mocking pattern).

## Global Constraints

- Instagram only, anonymous scraping only (no login) — this phase.
- Explicit "Importa" button with a loading state — never auto-triggered just by pasting/typing a link.
- Any failure (invalid link, private/removed reel, transcription failure, timeout) falls back to the existing manual-entry experience — never a dead end.
- Whisper model size: `base`. Cached on disk under a path inside the mounted `/data` volume, configurable via `WHISPER_MODEL_CACHE_DIR` (default `/data/whisper_models`) and `WHISPER_MODEL_SIZE` (default `base`) env vars, following the existing `REEL_DB_PATH`/`AI_DEBUG_LOG_PATH` convention.
- `ffmpeg` is a new required system dependency (needed by both yt-dlp and faster-whisper's audio decoding).
- Overall import operation (download + transcribe) has a 60-second timeout; on timeout, fall back to manual entry exactly like any other failure.
- Never save a reel without explicit user confirmation — this existing app-wide invariant is untouched; auto-import only prefills a textarea the user still reviews and submits themselves.
- Explicitly out of scope for this phase: PWA `share_target` (native phone share), an Instagram login for scraping, and other platforms (TikTok, YouTube Shorts).

---

## Task 1: Instagram fetch module (`app/ingest/instagram.py`)

**Files:**
- Create: `app/ingest/__init__.py`
- Create: `app/ingest/instagram.py`
- Modify: `pyproject.toml` (add `yt-dlp` dependency)
- Test: `tests/test_ingest_instagram.py`

**Interfaces:**
- Produces: `InstagramFetchError(Exception)`; `FetchResult` (dataclass with `caption: str`, `video_path: Path`); `fetch(url: str, download_dir: Path) -> FetchResult`; module-level `YoutubeDL` and `DownloadError` attributes (monkeypatchable in tests, mirroring `app/ai/client.py`'s `get_client()` pattern).

- [ ] **Step 1: Add the `yt-dlp` dependency**

Edit `pyproject.toml`'s `dependencies` list to add `"yt-dlp>=2024.12.0",` after `"anthropic>=0.69.0",`, then run:

```bash
uv sync
```

Expected: `uv.lock` updates and `yt-dlp` installs without errors.

- [ ] **Step 2: Create the empty package init**

Create `app/ingest/__init__.py` with empty content (just a blank file, matching how `app/ai/__init__.py` and `app/routers/__init__.py` are empty).

- [ ] **Step 3: Write the failing tests**

Create `tests/test_ingest_instagram.py`:

```python
from pathlib import Path

import pytest

from app.ingest import instagram


class FakeYoutubeDL:
    should_fail = False
    description = "Una gita a Kyoto"
    write_file = True

    def __init__(self, opts):
        self.opts = opts
        self.download_dir = Path(opts["outtmpl"]).parent

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if type(self).should_fail:
            raise instagram.DownloadError("simulated failure")
        if type(self).write_file:
            (self.download_dir / "reel.mp4").write_bytes(b"fake video bytes")
        return {"description": type(self).description}


class FailingYoutubeDL(FakeYoutubeDL):
    should_fail = True


class NoFileYoutubeDL(FakeYoutubeDL):
    write_file = False


class NoCaptionYoutubeDL(FakeYoutubeDL):
    description = None


def test_fetch_returns_caption_and_video_path(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", FakeYoutubeDL)

    result = instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert result.caption == "Una gita a Kyoto"
    assert result.video_path == tmp_path / "reel.mp4"
    assert result.video_path.exists()


def test_fetch_raises_instagram_fetch_error_on_download_error(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", FailingYoutubeDL)

    with pytest.raises(instagram.InstagramFetchError):
        instagram.fetch("https://instagram.com/reel/private", tmp_path)


def test_fetch_raises_when_no_output_file_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", NoFileYoutubeDL)

    with pytest.raises(instagram.InstagramFetchError):
        instagram.fetch("https://instagram.com/reel/abc", tmp_path)


def test_fetch_defaults_caption_to_empty_string_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", NoCaptionYoutubeDL)

    result = instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert result.caption == ""
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest_instagram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingest.instagram'` (or `ImportError`).

- [ ] **Step 5: Implement `app/ingest/instagram.py`**

```python
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

YoutubeDL = yt_dlp.YoutubeDL
DownloadError = yt_dlp.utils.DownloadError


class InstagramFetchError(Exception):
    pass


@dataclass
class FetchResult:
    caption: str
    video_path: Path


def fetch(url: str, download_dir: Path) -> FetchResult:
    ydl_opts = {
        "outtmpl": str(download_dir / "reel.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "format": "mp4/best",
    }
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

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest_instagram.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/ingest/__init__.py app/ingest/instagram.py tests/test_ingest_instagram.py
git commit -m "feat: add Instagram reel fetch module (yt-dlp wrapper)"
```

---

## Task 2: Transcription module (`app/ingest/transcribe.py`)

**Files:**
- Create: `app/ingest/transcribe.py`
- Modify: `pyproject.toml` (add `faster-whisper` dependency)
- Modify: `Dockerfile` (install `ffmpeg`, add `WHISPER_MODEL_CACHE_DIR` env var)
- Test: `tests/test_ingest_transcribe.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent module).
- Produces: `get_model() -> WhisperModel` (module-level `_model` cache, monkeypatchable, mirrors `app/ai/client.py`'s `get_client()`); `transcribe(video_path: Path) -> str`.

- [ ] **Step 1: Add the `faster-whisper` dependency**

Edit `pyproject.toml`'s `dependencies` list to add `"faster-whisper>=1.0.0",` after the `yt-dlp` line added in Task 1, then run:

```bash
uv sync
```

Expected: `uv.lock` updates and `faster-whisper` (and its `ctranslate2` dependency) install without errors.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ingest_transcribe.py`:

```python
from pathlib import Path
from types import SimpleNamespace

from app.ingest import transcribe


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, path):
        return iter(self._segments), SimpleNamespace(language="it")


def test_transcribe_joins_segment_texts(monkeypatch):
    monkeypatch.setattr(
        transcribe, "get_model", lambda: FakeModel([FakeSegment(" Ciao "), FakeSegment("da Kyoto ")])
    )

    result = transcribe.transcribe(Path("/tmp/fake.mp4"))

    assert result == "Ciao da Kyoto"


def test_transcribe_returns_empty_string_for_no_segments(monkeypatch):
    monkeypatch.setattr(transcribe, "get_model", lambda: FakeModel([]))

    result = transcribe.transcribe(Path("/tmp/fake.mp4"))

    assert result == ""


def test_get_model_reads_env_vars_and_caches_instance(monkeypatch):
    captured = {}

    class RecordingWhisperModel:
        def __init__(self, model_size, device, compute_type, download_root):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type
            captured["download_root"] = download_root

    monkeypatch.setattr(transcribe, "WhisperModel", RecordingWhisperModel)
    monkeypatch.setattr(transcribe, "_model", None)
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")
    monkeypatch.setenv("WHISPER_MODEL_CACHE_DIR", "/tmp/whisper-cache")

    first = transcribe.get_model()
    second = transcribe.get_model()

    assert captured == {
        "model_size": "small",
        "device": "cpu",
        "compute_type": "int8",
        "download_root": "/tmp/whisper-cache",
    }
    assert first is second
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingest.transcribe'`.

- [ ] **Step 4: Implement `app/ingest/transcribe.py`**

```python
import os
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

_model: Optional[WhisperModel] = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        model_size = os.environ.get("WHISPER_MODEL_SIZE", "base")
        download_root = os.environ.get("WHISPER_MODEL_CACHE_DIR", "/data/whisper_models")
        _model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=download_root)
    return _model


def transcribe(video_path: Path) -> str:
    model = get_model()
    segments, _info = model.transcribe(str(video_path))
    return " ".join(segment.text.strip() for segment in segments).strip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest_transcribe.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Update the Dockerfile for `ffmpeg` and the model cache path**

Edit `Dockerfile` — add `ffmpeg` installation before the `uv sync` step and set the new env var alongside the existing `REEL_DB_PATH`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app ./app

ENV REEL_DB_PATH=/data/japan_reels.db
ENV WHISPER_MODEL_CACHE_DIR=/data/whisper_models
VOLUME ["/data"]

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile app/ingest/transcribe.py tests/test_ingest_transcribe.py
git commit -m "feat: add Whisper transcription module (faster-whisper wrapper)"
```

---

## Task 3: Import endpoint + UI wiring

**Files:**
- Create: `app/routers/instagram_import.py`
- Modify: `app/main.py` (register the new router)
- Modify: `app/templates/partials/ai_chat.html` (import button, loading indicator, prefilled textarea, retained link value)
- Modify: `app/static/css/style.css` (htmx-indicator visibility rules)
- Modify: `docs/deployment-nginx-tls.md` (note on `proxy_read_timeout`)
- Test: `tests/test_instagram_import_ui.py`

**Interfaces:**
- Consumes: `app.ingest.instagram.fetch`, `app.ingest.instagram.InstagramFetchError`, `app.ingest.instagram.FetchResult` (Task 1); `app.ingest.transcribe.transcribe` (Task 2); `app.routers.ai_categorize._build_ai_chat_context(session, ai_session_id, link, notice=None) -> dict` (existing).
- Produces: `router: APIRouter` with `POST /ui/ai/import`; `_is_instagram_link(link: str) -> bool`.

- [ ] **Step 1: Update the template first, so the endpoint's tests can assert on real markup**

Edit `app/templates/partials/ai_chat.html`, replacing the pre-session branch of the bottom form (currently lines 53-63):

```html
<form hx-post="/ui/ai/message" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-input-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    {% if not session_id %}
    <input type="url" name="link" id="ai-import-link" placeholder="Link Instagram" required value="{{ link }}">
    <button type="button" class="btn-import"
            hx-post="/ui/ai/import"
            hx-include="#ai-import-link"
            hx-target="#ai-chat-panel"
            hx-swap="innerHTML"
            hx-indicator="#ai-import-indicator">Importa da Instagram</button>
    <span id="ai-import-indicator" class="htmx-indicator">Scarico e trascrivo…</span>
    <textarea name="message" placeholder="Descrizione o didascalia del reel" required>{{ prefill_message|default('') }}</textarea>
    {% else %}
    <input type="hidden" name="link" value="{{ link }}">
    <textarea name="message" placeholder="Scrivi..." required></textarea>
    {% endif %}
    <button type="submit">Invia</button>
</form>
```

- [ ] **Step 2: Add the loading-indicator CSS**

Append to `app/static/css/style.css`:

```css
.htmx-indicator {
    display: none;
}

.htmx-request .htmx-indicator,
.htmx-request.htmx-indicator {
    display: inline;
}
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_instagram_import_ui.py`:

```python
from app.ingest import instagram, transcribe


def test_ui_ai_panel_shows_import_button_before_any_session(client):
    response = client.get("/ui/ai/panel")

    assert response.status_code == 200
    assert 'id="ai-import-link"' in response.text
    assert 'hx-post="/ui/ai/import"' in response.text


def test_ui_ai_import_prefills_caption_and_transcript(client, session, monkeypatch):
    def fake_fetch(url, download_dir):
        video_path = download_dir / "reel.mp4"
        video_path.write_bytes(b"fake")
        return instagram.FetchResult(caption="Ramen a Tokyo", video_path=video_path)

    monkeypatch.setattr(instagram, "fetch", fake_fetch)
    monkeypatch.setattr(transcribe, "transcribe", lambda video_path: "Questo e' il miglior ramen di Tokyo")

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/abc"})

    assert response.status_code == 200
    assert "Ramen a Tokyo" in response.text
    assert "miglior ramen di Tokyo" in response.text
    assert 'value="https://instagram.com/reel/abc"' in response.text


def test_ui_ai_import_rejects_non_instagram_link(client, session):
    response = client.post("/ui/ai/import", data={"link": "https://tiktok.com/reel/abc"})

    assert response.status_code == 200
    assert "reel Instagram" in response.text


def test_ui_ai_import_falls_back_to_manual_entry_on_fetch_error(client, session, monkeypatch):
    def failing_fetch(url, download_dir):
        raise instagram.InstagramFetchError("private reel")

    monkeypatch.setattr(instagram, "fetch", failing_fetch)

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/private"})

    assert response.status_code == 200
    assert "Non sono riuscito a importare" in response.text
    assert 'name="message" placeholder="Descrizione o didascalia del reel" required></textarea>' in response.text


def test_ui_ai_import_proceeds_with_caption_only_when_transcription_fails(client, session, monkeypatch):
    def fake_fetch(url, download_dir):
        video_path = download_dir / "reel.mp4"
        video_path.write_bytes(b"fake")
        return instagram.FetchResult(caption="Tempio a Kyoto", video_path=video_path)

    def failing_transcribe(video_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(instagram, "fetch", fake_fetch)
    monkeypatch.setattr(transcribe, "transcribe", failing_transcribe)

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/abc"})

    assert response.status_code == 200
    assert "Tempio a Kyoto" in response.text
    assert "trascrizione non disponibile" in response.text
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_instagram_import_ui.py -v`
Expected: FAIL — `404 Not Found` for `/ui/ai/import` (route doesn't exist yet), and the first test fails because `ai_chat.html` doesn't yet reference `prefill_message`/the import button until Step 1 is applied (Step 1 above already applies the template change, so only the router-dependent assertions should fail at this point: `test_ui_ai_import_*` tests fail with 404; `test_ui_ai_panel_shows_import_button_before_any_session` should already PASS since the template edit from Step 1 is already in place).

- [ ] **Step 5: Implement `app/routers/instagram_import.py`**

```python
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
```

- [ ] **Step 6: Register the router in `app/main.py`**

Change the router import line:

```python
from app.routers import ai_categorize, auth, categories, instagram_import, locations, map as map_router, reels
```

Add, next to the other `ai_categorize` router includes:

```python
app.include_router(instagram_import.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_instagram_import_ui.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Run the full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: PASS (all existing tests plus the new ones — no regressions in `test_ai_ui.py`, `test_reels_api.py`, etc.).

- [ ] **Step 9: Add the nginx timeout note**

Edit `docs/deployment-nginx-tls.md`, inserting this paragraph right after the `## 2. Create a minimal HTTP server block for the new domain` section's closing code block (after the `sudo systemctl reload nginx` line, before `## 3. Get a TLS certificate with certbot`):

```markdown

The Instagram auto-import feature (`POST /ui/ai/import`) can take up to 60
seconds to download and transcribe a reel. nginx's default
`proxy_read_timeout` is also 60s, which is right at the edge — raise it
explicitly inside the `location /` block above to avoid spurious 504s:

\```nginx
proxy_read_timeout 75s;
\```
```

- [ ] **Step 10: Commit**

```bash
git add app/routers/instagram_import.py app/main.py app/templates/partials/ai_chat.html app/static/css/style.css tests/test_instagram_import_ui.py docs/deployment-nginx-tls.md
git commit -m "feat: add Instagram auto-import endpoint and UI wiring"
```

---

## Manual Verification (not automated — requires a live reel and real network access)

The plan's automated tests all mock `instagram.fetch` and `transcribe.transcribe`, so none of them exercise the real yt-dlp/faster-whisper integration end-to-end. Before considering this feature done, manually verify against the running app (`uv run uvicorn app.main:app --reload`, with `ffmpeg` installed locally):

1. Paste a real, public Instagram reel link into the AI panel and click "Importa da Instagram" — confirm the textarea fills with a plausible caption and transcript within roughly 30 seconds.
2. Paste a private or deleted reel's link — confirm the fallback notice appears and the textarea is left empty for manual typing.
3. Paste a non-Instagram link (e.g. a YouTube URL) — confirm the "must be an Instagram reel" notice appears without attempting a download.
4. Confirm no leftover files remain in the system temp directory after a few imports (the `tempfile.TemporaryDirectory()` context manager should clean up automatically).
