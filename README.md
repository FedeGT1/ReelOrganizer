# Japan Reel Organizer

A small FastAPI app for organizing Instagram reels saved while planning a trip to Japan. Reels are categorized by location (a hub city/region, optionally with nearby day-trip satellites — both fully manageable from the "Gestisci hub" page) and by content type (food, culture, nature, etc. — user-editable from the "Gestisci categorie" page), then displayed on an interactive map. Pasting a reel link can auto-import its caption and an audio transcript (via yt-dlp + a local Whisper speech-to-text model) instead of typing them by hand. A generative AI chat flow then categorizes the reel: it proposes a place, category tags, and coordinates, falling back to a web search when its own knowledge isn't enough to place the location, presenting a clickable list to disambiguate if search finds more than one plausible match, splitting a reel that lists several distinct places (e.g. "10 places to see in Kyoto") into a checklist of individually-resolved pins, and never saving anything without confirmation. Saved reels can be edited afterwards (link, note, location, categories) or deleted. Login-protected (single fixed user) so it can be safely exposed on the internet for remote access.

## Stack

- **Backend**: Python 3.11+, FastAPI
- **Persistence**: SQLite via SQLModel (single file, created fresh at startup)
- **Frontend**: Jinja2 server-rendered templates + HTMX for interactivity, Leaflet (Esri World Street Map tiles) + vanilla JS for the interactive map
- **AI**: configurable provider via `AI_PROVIDER` env var — Anthropic Python SDK (`claude-haiku-4-5`, default) or OpenAI Python SDK (`gpt-6-luna`); both use structured JSON output and a web-search tool for categorization
- **Reel import**: `yt-dlp` (caption + video download, anonymous) and `faster-whisper` (local CPU speech-to-text) for the auto-import feature — both require `ffmpeg`, already installed in the Docker image

## Running locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AUTH_USERNAME=your-username
export AUTH_PASSWORD=your-strong-password
export SESSION_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
uv sync
uv run uvicorn app.main:app --reload
```

`AUTH_USERNAME`/`AUTH_PASSWORD` gate every page and API route behind a login form. `SESSION_SECRET_KEY` signs the session cookie — generate it once and keep it stable across restarts (regenerating it invalidates every logged-in session). The app refuses to start if any of the three is missing.

By default the app uses Anthropic (`ANTHROPIC_API_KEY` required, as above). To use OpenAI's `gpt-6-luna` instead, set `AI_PROVIDER=openai` and `OPENAI_API_KEY=sk-...`; `AI_REASONING_EFFORT` (`none`/`low`/`medium`/`high`/`xhigh`/`max`, default `medium`) tunes its cost/latency/quality trade-off and is ignored when using Anthropic.

The app is served at `http://localhost:8000`.

**Note:** the Whisper speech-to-text model cache defaults to `/data/whisper_models` (`WHISPER_MODEL_CACHE_DIR`), an absolute path meant for the Docker deployment's mounted volume. Running locally outside Docker, `/data` usually doesn't exist or isn't writable, and the first reel transcription will fail with a read-only-filesystem error. Point it at a local, writable directory instead:

```bash
export WHISPER_MODEL_CACHE_DIR="$(pwd)/data/whisper_models"
mkdir -p "$WHISPER_MODEL_CACHE_DIR"
```

**Note:** the session cookie is marked `Secure` (HTTPS-only), so the login form won't actually work over plain `http://localhost:8000` — the browser will refuse to send the cookie back and you'll bounce back to `/login`. This is intentional for the real deployment (see [`docs/deployment-apache-tls.md`](docs/deployment-apache-tls.md) — or [`docs/deployment-nginx-tls.md`](docs/deployment-nginx-tls.md) if your VM uses nginx instead — for putting a reverse proxy with TLS in front of the app); to exercise login locally you need HTTPS too, e.g. via a local self-signed cert passed to uvicorn (`--ssl-keyfile`/`--ssl-certfile`) or by testing against a real TLS-terminated deployment instead.

## Running the tests

```bash
uv run pytest -v
```

## Docker

Build the image:

```bash
docker build -t reel-organizer .
```

Use the **same name** for the image tag and the container (`reel-organizer` for both, as below) — don't follow older examples that name them differently (e.g. image `japan-reel-organizer` / container `reel-organizer`). A mismatched name is exactly what let a stale image run silently after a rebuild once: the build succeeded, `/health` returned `{"status":"ok"}`, logs looked normal, but `docker run` referenced the old image tag by habit, so none of the new code was actually live. Using one consistent name removes that whole failure mode.

Credentials go in a `.env` file (copy `.env.example` and fill in real values) rather than individual `-e` flags — one file to manage instead of juggling shell variables on every `docker run`, and nothing sensitive lingers in shell history. Keep it **outside** the git working tree or confirm it's gitignored (it already is, as `.env`), and restrict its permissions (`chmod 600 .env`) since it holds plaintext secrets.

Run it with a mounted data volume so the SQLite database persists across container restarts. Use an **absolute path** for the volume mount, not `$(pwd)/data` — if you (or a script) ever run the `docker run` command from a different working directory, `$(pwd)` silently resolves to wherever you happen to be, mounting an unrelated empty directory instead of your real data and making it look like all your reels vanished. `--restart unless-stopped` (not `--rm`) makes the container survive a VM reboot:

```bash
docker run -d \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/reelorganizer/data:/data" \
  --env-file /absolute/path/to/.env \
  --name reel-organizer reel-organizer
```

Binding to `127.0.0.1:8000` instead of `8000` means the container is only reachable from the VM itself, never directly from the internet — see [`docs/deployment-apache-tls.md`](docs/deployment-apache-tls.md) — or [`docs/deployment-nginx-tls.md`](docs/deployment-nginx-tls.md) if your VM uses nginx instead — for putting a reverse proxy with TLS in front of it so it can be reached remotely. That guide also covers a required reverse-proxy read-timeout bump (180s) — without it, the auto-import and multi-place-reel features can hit a 504 on a slow/long reel.

To run with the OpenAI provider instead, set `AI_PROVIDER=openai` and `OPENAI_API_KEY=sk-...` in `.env` (optionally `AI_REASONING_EFFORT` and `OPENAI_TIMEOUT` — see `.env.example`); no change needed to the `docker run` command since it already reads everything from `--env-file`.

**No domain yet?** [sslip.io](https://sslip.io) gives you a working public hostname for free, no registration or DNS propagation wait: `<ip-with-dashes>.sslip.io` (e.g. `203-0-113-42.sslip.io` for IP `203.0.113.42`) resolves instantly to that IP, and Let's Encrypt/certbot will happily issue a real certificate for it. Handy for testing a deployment end-to-end (including real HTTPS login) before you have a real domain pointed at the VM.

Check it's up: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

The first-ever Instagram auto-import also downloads the ~140MB Whisper speech-to-text model into the `/data` volume — it's cached there afterwards, so this only happens once (not on every container restart), but that first import will be noticeably slower than later ones. Triggering one import manually right after deploying warms the cache ahead of real use.

### Updating after a code change

`docker restart` reuses the existing container's already-loaded image — it never picks up new code, no matter how you got the new code onto the VM. Rebuild and recreate the container instead:

```bash
git pull   # or however you get the updated code onto the VM

docker build -t reel-organizer .   # add --no-cache if you suspect a stale cached layer (see below)

docker stop reel-organizer
docker rm reel-organizer

docker run -d \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/reelorganizer/data:/data" \
  --env-file /absolute/path/to/.env \
  --name reel-organizer reel-organizer
```

Then verify the running container is actually on the image you just built — `/health` returning `{"status":"ok"}` only proves the server started, not that it's running your latest code:

```bash
docker images reel-organizer                        # note the freshest IMAGE ID
docker inspect -f '{{.Image}}' reel-organizer        # must match that IMAGE ID
```

If they don't match, the `docker run` above referenced the wrong image name/tag (double-check for typos or an old tag like `japan-reel-organizer` lingering in a saved command) — fix the image name and re-run.

If `docker build` reports `Using cache` on the `COPY app ./app` step right after you know the code changed, rebuild with `docker build --no-cache -t reel-organizer .` to force every layer to actually re-run, then repeat the stop/rm/run/verify above.

Once confirmed, old images pile up fast (each is ~1GB) and this VM's disk is small — list them and remove the ones no container references:

```bash
docker images
docker rmi <old-image-id-or-tag> [<old-image-id-or-tag> ...]
docker df   # or: df -h /
```

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

## Persistence

There are no migrations: the app creates a single fresh SQLite database at startup (path configurable via `REEL_DB_PATH`) and seeds it with default hubs and default categories if empty (both seeded independently, so clearing one doesn't require re-seeding the other). If you have an existing local `data/*.db` from before a schema *or seed data* change, delete it (`rm data/*.db`) so it gets recreated with the current schema/seed — there is no migration path for schema or seed-data changes. The downloaded Whisper model is cached separately (path configurable via `WHISPER_MODEL_CACHE_DIR`, defaults to `/data/whisper_models` in Docker) and isn't affected by resetting the database.

## AI debug log

Every request/response exchanged with Claude during categorization, plus the safety-net decisions around it (missing-coordinates fallback, matched-location resolution), is logged to `data/ai_debug.log` (path configurable via `AI_DEBUG_LOG_PATH`) for troubleshooting. It's gitignored and grows unbounded — delete it freely.
