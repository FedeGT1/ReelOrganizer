# Japan Reel Organizer

A small FastAPI app for organizing Instagram reels saved while planning a trip to Japan. Reels are categorized by location (a hub city/region, optionally with nearby day-trip satellites) and by content type (food, culture, nature, etc. — user-editable from the "Gestisci categorie" page), then displayed on an interactive map (Leaflet + OpenStreetMap). A generative AI chat flow helps categorize new reels: paste a link and a caption, and it proposes a place, category tags, and coordinates, asking clarifying questions when it doesn't have enough information, and never saving anything without confirmation.

## Stack

- **Backend**: Python 3.11+, FastAPI
- **Persistence**: SQLite via SQLModel (single file, created fresh at startup)
- **Frontend**: Jinja2 server-rendered templates + HTMX for interactivity, Leaflet + vanilla JS for the interactive map
- **AI**: Anthropic Python SDK (`claude-haiku-4-5`) with structured JSON output for categorization

## Running locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv sync
uv run uvicorn app.main:app --reload
```

The app is served at `http://localhost:8000`.

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
docker run --rm -d -p 8000:8000 -v "$(pwd)/data:/data" -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --name reel-organizer japan-reel-organizer
```

Check it's up: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

## Persistence

There are no migrations: the app creates a single fresh SQLite database at startup (path configurable via `REEL_DB_PATH`) and seeds it with default hubs and default categories if empty (both seeded independently, so clearing one doesn't require re-seeding the other). If you have an existing local `data/*.db` from before a schema change, delete it (`rm data/*.db`) so it gets recreated with the current schema — there is no migration path for schema changes.

## AI debug log

Every request/response exchanged with Claude during categorization, plus the safety-net decisions around it (missing-coordinates fallback, matched-location resolution), is logged to `data/ai_debug.log` (path configurable via `AI_DEBUG_LOG_PATH`) for troubleshooting. It's gitignored and grows unbounded — delete it freely.
