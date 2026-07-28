# Japan Reel Organizer

A small FastAPI app for organizing Instagram reels saved while planning a trip to Japan. Reels are categorized by location (a hub city/region, optionally with nearby day-trip satellites — both fully manageable from the "Gestisci hub" page) and by content type (food, culture, nature, etc. — user-editable from the "Gestisci categorie" page), then displayed on an interactive map. A generative AI chat flow helps categorize new reels: paste a link and a caption, and it proposes a place, category tags, and coordinates, falling back to a web search when its own knowledge isn't enough to place the location, presenting a clickable list to disambiguate if search finds more than one plausible match, and never saving anything without confirmation. Saved reels can be edited afterwards (link, note, location, categories) or deleted. Login-protected (single fixed user) so it can be safely exposed on the internet for remote access.

## Stack

- **Backend**: Python 3.11+, FastAPI
- **Persistence**: SQLite via SQLModel (single file, created fresh at startup)
- **Frontend**: Jinja2 server-rendered templates + HTMX for interactivity, Leaflet (Esri World Street Map tiles) + vanilla JS for the interactive map
- **AI**: Anthropic Python SDK (`claude-haiku-4-5`) with structured JSON output and a web-search tool for categorization

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

The app is served at `http://localhost:8000`.

**Note:** the session cookie is marked `Secure` (HTTPS-only), so the login form won't actually work over plain `http://localhost:8000` — the browser will refuse to send the cookie back and you'll bounce back to `/login`. This is intentional for the real deployment (see [`docs/deployment-nginx-tls.md`](docs/deployment-nginx-tls.md), which puts nginx with TLS in front of the app); to exercise login locally you need HTTPS too, e.g. via a local self-signed cert passed to uvicorn (`--ssl-keyfile`/`--ssl-certfile`) or by testing against a real TLS-terminated deployment instead.

## Running the tests

```bash
uv run pytest -v
```

## Docker

Build the image:

```bash
docker build -t japan-reel-organizer .
```

Run it with a mounted data volume so the SQLite database persists across container restarts:

```bash
docker run --rm -d \
  -p 127.0.0.1:8000:8000 \
  -v "$(pwd)/data:/data" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e AUTH_USERNAME="$AUTH_USERNAME" \
  -e AUTH_PASSWORD="$AUTH_PASSWORD" \
  -e SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
  --name reel-organizer japan-reel-organizer
```

Binding to `127.0.0.1:8000` instead of `8000` means the container is only reachable from the VM itself, never directly from the internet — see [`docs/deployment-nginx-tls.md`](docs/deployment-nginx-tls.md) for putting nginx with TLS in front of it so it can be reached remotely.

Check it's up: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

## Persistence

There are no migrations: the app creates a single fresh SQLite database at startup (path configurable via `REEL_DB_PATH`) and seeds it with default hubs and default categories if empty (both seeded independently, so clearing one doesn't require re-seeding the other). If you have an existing local `data/*.db` from before a schema change, delete it (`rm data/*.db`) so it gets recreated with the current schema — there is no migration path for schema changes.

## AI debug log

Every request/response exchanged with Claude during categorization, plus the safety-net decisions around it (missing-coordinates fallback, matched-location resolution), is logged to `data/ai_debug.log` (path configurable via `AI_DEBUG_LOG_PATH`) for troubleshooting. It's gitignored and grows unbounded — delete it freely.
