# Instagram Auto-Import (Caption + Speech-to-Text) — Design

## Goal

Today, adding a reel via the AI-assisted flow requires the user to paste the Instagram link *and* manually retype the caption/description into a textarea before Claude can categorize it. This replaces that manual retyping step with an optional one-click import: paste the link, press "Importa da Instagram", and the app downloads the reel, extracts its caption, transcribes its audio (speech-to-text), and prefills the same textarea — still editable, still requiring confirmation before saving, same as every other AI-assisted step in this app.

Scope for this phase: Instagram only, anonymous (no login) scraping, explicit button with a loading state, full fallback to today's manual-typing flow on any failure. Native phone share (PWA `share_target`), an Instagram login for scraping, and other platforms (TikTok, YouTube Shorts) are explicitly out of scope — candidates for a later phase if anonymous scraping proves too unreliable in practice.

## Architecture

New `app/ingest/` package, separate from `app/ai/` because it talks to Instagram/ffmpeg/whisper, not Claude:

- **`app/ingest/instagram.py`** — wraps `yt-dlp`. Given a reel URL, downloads the video and metadata into a temp directory and returns `{caption: str, video_path: Path}`. yt-dlp exposes the post's description in its metadata, so one tool covers both the video and the caption — no separate scraper needed. Raises `InstagramFetchError` for anything unfetchable (private, removed, blocked, invalid URL).
- **`app/ingest/transcribe.py`** — wraps `faster-whisper`. Extracts audio from the downloaded video (via ffmpeg) and transcribes it with the `base` model, chosen for the 2 vCPU / 8GB RAM VM. The model is loaded once per process (not per request) and cached on disk under a path inside the mounted `/data` volume (configurable via env var, following the existing `REEL_DB_PATH`/`AI_DEBUG_LOG_PATH` convention) so it survives container restarts instead of re-downloading (~140MB) every deploy. Returns an empty string if the audio is silent/unreadable rather than raising.
- Both modules delete their temp video/audio files immediately after use — the video itself is never persisted, only the extracted text.

New router **`app/routers/instagram_import.py`** with `POST /ui/ai/import`:
1. Validates `link` is `http(s)` and hostname is `instagram.com`/`www.instagram.com` (reusing the domain-safety pattern of `reels._is_safe_link`) before touching yt-dlp at all.
2. Calls `instagram.fetch()` then `transcribe.run()`, wrapped in an overall timeout (60s) so an anomalous reel can't hang the request indefinitely.
3. Renders `partials/ai_chat.html` in its pre-session state (same as `GET /ui/ai/panel` today) but with the link field retained and the message textarea prefilled with the combined caption+transcript — or, on any failure (`InstagramFetchError`, timeout), the same panel with `link` retained, the textarea empty, and a `notice` explaining the import failed and asking for manual entry (reusing the `notice` mechanism `ui_ai_message` already uses for expired sessions).

No changes to `app/ai/client.py` or `app/ai/prompts.py` — the combined text still flows into `ui_ai_message` → `_run_turn` exactly as today (`Link: ...\nDescrizione: ...`), so the categorization logic is untouched.

## UI Changes

`app/templates/partials/ai_chat.html`'s pre-session form (the `{% if not session_id %}` branch) gets one addition: an "Importa da Instagram" button next to the link input, `hx-post="/ui/ai/import" hx-target="#ai-chat-panel" hx-swap="innerHTML" hx-include="[name='link']"`, with an `hx-indicator` showing a "Scarico e trascrivo…" state while the request is in flight. The link `<input>` gains a `value="{{ link }}"` so it isn't lost across the round-trip, and the `<textarea name="message">` gains prefilled content (`{{ prefill_message }}`) when the import succeeds.

The textarea remains freely editable and the existing "Invia" button/flow is unchanged — import is additive, not a replacement path. A user can still type the caption by hand and skip the button entirely, exactly as today.

## Data Flow

1. User opens the AI panel, pastes the reel link.
2. User clicks "Importa da Instagram" → `POST /ui/ai/import` with the link.
3. Server downloads the reel (yt-dlp), extracts the caption, extracts and transcribes the audio (faster-whisper), deletes the temp files, and returns the panel with the textarea prefilled with:
   ```
   Didascalia: <caption>

   Trascrizione audio: <transcript>
   ```
4. User reviews/edits the prefilled text (fixing any mistranscribed words, trimming irrelevant parts) and clicks "Invia", same as the manual flow today.
5. From here the flow is unchanged: Claude proposes place/types/note via `ui_ai_message` → `_run_turn`, the user answers any clarifying questions, and nothing is saved until "Conferma e salva" is pressed.

## Error Handling

- **Invalid link or non-Instagram domain**: rejected before any fetch attempt, same style as the existing `_is_safe_link` 400.
- **Private/removed/blocked reel** (`InstagramFetchError`): panel re-rendered with `notice` = "Non sono riuscito a importare in automatico questo reel — inserisci la didascalia a mano qui sotto", link retained, textarea empty and ready for manual typing. Not a hard failure — the user can still proceed exactly as before this feature existed.
- **Video downloaded but transcription fails or audio is empty**: proceed with caption-only prefill (if a caption was found), appending a short note like "(trascrizione non disponibile)" instead of blocking the whole import.
- **Overall timeout (60s)**: treated identically to a fetch failure — falls back to the manual-entry notice.
- In every failure case the degraded experience is exactly today's behavior (type the caption yourself); there is no dead end.

## Dependencies and Deployment

- **New Python dependencies** (`pyproject.toml`): `yt-dlp`, `faster-whisper`.
- **New system dependency**: `ffmpeg`, added to the `Dockerfile` (`apt-get install ffmpeg`) — required by both yt-dlp and audio extraction.
- **Whisper model cache**: the `base` model is downloaded once and cached under a directory inside the mounted `/data` volume (new env var, default e.g. `/data/whisper_models`), so it isn't re-downloaded on every container restart.
- **Docker image size**: `faster-whisper` and its dependencies (ctranslate2, etc.) will noticeably increase image size — expected, not a blocker.
- **nginx**: the reverse proxy in front of the app likely has a default `proxy_read_timeout` (~60s); since import can take up to the full 60s timeout budget, this should be raised explicitly for this route (or globally) to avoid spurious 504s on slower reels.
- **VM resources**: 2 vCPU / 8GB RAM, shared with two existing WordPress sites on the same VM. The `base` model on CPU is a reasonable speed/accuracy tradeoff for occasional use; back-to-back imports could transiently slow the other sites, but this is a single-user personal app so that's an acceptable tradeoff, not something to engineer around now.

## Testing

- `app/ingest/instagram.py` and `app/ingest/transcribe.py` expose plain, mockable functions (same pattern as `app/ai/client.py`), so router tests mock fetch and transcription rather than hitting the network or actually running whisper.
- Cases to cover in `tests/`:
  - Valid Instagram link → import succeeds, textarea prefilled with caption + transcript, link retained.
  - Non-Instagram or malformed link → rejected before fetch, 400.
  - Private/removed reel (mocked `InstagramFetchError`) → panel returns with the fallback notice and an empty, manually-editable textarea.
  - Video with no usable audio → caption-only prefill, no hard failure.
- No test actually downloads from Instagram or runs real whisper inference — too slow/fragile for CI. Real-world verification (actually pasting a live reel link and checking the import) is manual, done by the user against the running app.
