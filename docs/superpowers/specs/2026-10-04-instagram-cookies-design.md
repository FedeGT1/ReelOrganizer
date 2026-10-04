# Instagram authenticated cookies for yt-dlp — design

## Context

The Instagram auto-import feature (`app/routers/instagram_import.py` +
`app/ingest/instagram.py`) uses `yt-dlp` anonymously (no login), as
documented in `docs/superpowers/specs/2026-09-28-instagram-auto-import-design.md`:
anonymous scraping was an explicit scope choice, with a note that an
Instagram login was "a candidate for a later phase if anonymous scraping
proves too unreliable in practice."

After migrating to a new VPS (OVH), every import attempt now fails with
`yt_dlp.utils.ExtractorError: Instagram sent an empty media response`. The
same link succeeds immediately when fetched from a non-datacenter IP. This
matches a well-documented yt-dlp/Instagram pattern
([yt-dlp#17074](https://github.com/yt-dlp/yt-dlp/issues/17074)): Instagram
applies much stricter limits to anonymous (cookie-less) requests from
IPs recognized as datacenter/hosting ranges. The previous VPS likely
worked only because its IP hadn't been classified yet, not because of any
configuration difference. A real domain would not change this — Instagram
never resolves the app's hostname, it only sees the source IP of the
scraping request.

Ruled out during discussion:
- **A different/commercial VPN**: still a datacenter-class IP (often even
  more aggressively blocklisted than a random VPS provider), doesn't fix
  the underlying issue.
- **Residential proxy service or a home device as VPN exit**: would
  genuinely work (residential IP), but costs money (proxy) or requires
  always-on home hardware with its own reliability trade-offs — shelved,
  not needed for a first fix.
- **yt-dlp direct `--username`/`--password` login from the VPS**: known to
  be unreliable for Instagram even on recent yt-dlp builds, requires
  re-entering 2FA codes by hand on every re-login, and critically — the
  login itself would happen from the already-flagged datacenter IP, which
  risks tripping Instagram's account-security challenges on the user's
  real account. Rejected for this reason.

**Chosen approach**: authenticate yt-dlp with a cookies.txt file exported
from a real, already-logged-in Instagram session (so the *login* event
happens on an unremarkable residential/mobile IP, never on the VPS), fed to
yt-dlp as a `cookiefile`. Must work entirely from an Android phone (no
desktop access assumed): Firefox for Android supports extensions, and a
purpose-built one exists — ["YT-DLP Cookie
Exporter"](https://addons.mozilla.org/en-US/android/addon/yt-dlp-cookie-exporter/)
— so export is a few taps. The remaining friction (copying the exported
file to the VPS) is removed by adding an upload page to the app itself,
reusing its existing login-protected UI instead of scp/terminal.

## Scope

In scope:
- `yt-dlp` uses a cookies file when present; falls back to today's
  anonymous behavior when absent (e.g. local dev, or before first upload).
- A simple authenticated page in the app to upload/replace the cookies
  file, usable from a phone browser's file picker.
- Docs: README env var, Dockerfile default path.

Out of scope (unchanged from the original import feature's scope):
- Any form of server-side Instagram login (username/password, interactive
  challenge handling).
- Detecting "cookies expired" specifically and showing a distinct notice —
  any import failure (expired cookies or otherwise) shows today's existing
  generic fallback notice.
- Automating the cookie *export* step itself (still a manual phone action
  via the Firefox addon, repeated whenever the Instagram session expires —
  expected to be infrequent, sessions typically last weeks to months).
- Non-Instagram platforms, any other auth mechanism (residential proxy,
  home-device VPN exit) — noted as possible future fallback in
  `docs/nice-to-have.md` if cookies prove insufficient.

## Architecture

**`app/ingest/instagram.py`**: `fetch()` reads a cookies file path from
`INSTAGRAM_COOKIES_PATH` (env var, mirroring the existing
`REEL_DB_PATH`/`WHISPER_MODEL_CACHE_DIR`/`AI_DEBUG_LOG_PATH` pattern). If
the file exists and is non-empty, pass `cookiefile: <path>` in `ydl_opts`;
otherwise omit it, preserving today's anonymous behavior exactly.

**`app/routers/instagram_cookies.py`** (new): `ui_router` at prefix
`/ui/instagram-cookies`:
- `GET ""`: renders a partial showing current status — file present (with
  last-modified timestamp) or absent ("nessun cookie, l'import prova in
  anonimo") — plus the upload form.
- `POST ""`: accepts a multipart file upload, rejects empty uploads with
  an inline error, otherwise overwrites the configured path and
  re-renders the same partial with updated status. No cookie-format
  validation beyond non-empty — the uploader is trusted (single-user app,
  already behind login).

**`app/main.py`**: new `GET /instagram-cookies` page route, following the
exact pattern of the existing `/categories`/`/locations` pages — a shell
template that `hx-get`s the partial above on load.

**`app/templates/instagram_cookies.html`** (new) +
**`app/templates/partials/instagram_cookies_status.html`** (new): follow
the structure of `categories.html` / `partials/category_list.html`.

**`app/templates/base.html`**: add a "Cookie Instagram" nav link next to
"Gestisci hub" / "Gestisci categorie".

No new auth code needed — `AuthMiddleware` (`app/main.py`) already
protects every route globally, including the new ones.

**Dockerfile**: add `ENV INSTAGRAM_COOKIES_PATH=/data/instagram_cookies.txt`,
consistent with the other `/data`-rooted env defaults. Lives on the
already-mounted `/data` volume, so it survives container rebuilds/restarts
like the SQLite DB and Whisper model cache do.

## Data flow

1. User exports `cookies.txt` from a logged-in Instagram session in
   Firefox for Android (via the "YT-DLP Cookie Exporter" addon or
   equivalent) — a normal-looking login/browsing session from a mobile IP,
   nothing server-side involved yet.
2. User opens `/instagram-cookies` in the app (already logged in), picks
   the file, uploads it.
3. App overwrites `/data/instagram_cookies.txt` on the VPS.
4. Next Instagram import: `instagram.fetch()` sees the file, passes
   `cookiefile` to yt-dlp, which sends authenticated requests — expected
   to no longer trigger the anonymous-datacenter-IP restriction.
5. If the file is missing (never uploaded, or deleted), behavior is
   unchanged from today: anonymous fetch, same failure mode as currently
   observed until cookies are provided.

## Error handling

- Empty/missing file on upload: inline error in the partial, nothing
  written to disk, existing cookies file (if any) untouched.
- Any import failure downstream (expired cookies, other yt-dlp errors,
  anything): unchanged — existing `FETCH_FAILED_NOTICE`/`TIMEOUT_NOTICE`
  fallback to manual caption entry. No attempt to distinguish "cookie
  expired" from other failures in this phase.

## Testing

- `app/ingest/instagram.py`: unit test that `cookiefile` is included in
  `ydl_opts` when the configured path exists and is non-empty, and
  omitted when the file is missing — using `monkeypatch` + `tmp_path`,
  following the existing test style in `tests/test_ingest_instagram.py`.
- `app/routers/instagram_cookies.py`: route test (new
  `tests/test_instagram_cookies.py`, following
  `tests/test_instagram_import_ui.py`'s style) that POSTing a file writes
  it to the configured path (overwriting an existing one), that an empty
  upload is rejected without touching an existing file, and that GET
  reflects both the "present" and "absent" states correctly.

## Docs

- `README.md`: document `INSTAGRAM_COOKIES_PATH`, and briefly describe the
  upload page and the Firefox-for-Android export method.
- `Dockerfile`: add the new `ENV` default alongside the existing ones.
