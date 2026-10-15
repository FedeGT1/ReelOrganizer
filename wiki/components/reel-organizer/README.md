---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-15"
tags:
  - kind/component
  - component/reel-organizer
  - status/authoritative
connected files: ["01-why-a-full-login-instead-of-basic-auth", "02-the-ai-categorization-flow", "03-the-multiuser-retrofit", "hub-satellite-location", "category-taxonomy", "get-owned", "ai-session-vs-ask-session", "additive-schema-migration"]
---

# ReelOrganizer

> Lets a self-hoster save Instagram reels found while trip-planning, have an AI propose
> where/what-type they are, and browse them on a map — multiple private accounts on one
> shared deployment.

| | |
|---|---|
| Repo | this repo, root = app root (no monorepo split) |
| Stack | Python 3.11+, FastAPI, SQLModel/SQLite, Jinja2 + HTMX, Leaflet |
| Listens on | `:8000` inside the container; bound to `127.0.0.1:8000` on the host, reverse-proxied for TLS |
| Entrypoint | `main.py` → `app.main:app`; `uv run uvicorn app.main:app` |
| Tests | `uv run pytest -v`, ~40 files under `tests/` |

Add a row for anything that would mislead: `app/ingest/instagram.py` also handles
non-Instagram URLs today only in name — see [[tiktok-import]] for the gap between the
module name and the (not yet broadened) hostname check in
`app/routers/instagram_import.py`.

## Role in the system

Everything: there is one deployable process. It owns the HTTP server, the SQLite
database, the AI calls, and the reel-import pipeline. It does **not** own:

- Instagram/TikTok itself — it never scrapes a page, only downloads via `yt-dlp` with
  whatever metadata that returns (`app/ingest/instagram.py`).
- The AI model — it calls out to Anthropic or OpenAI per-request; no model is bundled.
  See `app/ai/client.py::get_provider`.
- TLS termination — that's the reverse proxy in front of it (`docs/deployment-apache-tls.md`
  / `docs/deployment-nginx-tls.md`), not this app.

## Interface

- **Browser UI** (Jinja2 + HTMX partials) — the actual product surface: add/edit/delete
  reels, manage hubs/categories, the map, the two AI chat panels, the audit tool,
  Markdown export (`app/routers/export.py::build_export_markdown`). Routed from `app/main.py` and `app/routers/*`.
- **`/api/ai/categorize`** and the `/ui/ai/*`, `/ui/ask/*` HTMX endpoints — the
  conversational AI flows. See [[02-the-ai-categorization-flow]] and
  [[ai-session-vs-ask-session]].
- **`/health`** — unauthenticated liveness check, returns `{"status":"ok"}`. Does not
  prove the running container is on the latest image — see the repo `README.md`'s
  "Updating after a code change" section for the actual verification steps.
- **`scripts/create_user.py`** (CLI, run via `docker exec`) — the only way to create an
  account; there's no self-service signup. See [[03-the-multiuser-retrofit]].

## Talks to

| Dependency | Setting | Failure mode |
|---|---|---|
| Anthropic or OpenAI API | `AI_PROVIDER`, `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` | Not fatal to the app — `app/routers/ai_categorize.py::_run_turn` and `app/routers/ai_ask.py::_run_ask_turn` both catch `AIProviderError`/`RuntimeError` and degrade to a friendly in-chat error message instead of a 500 |
| Instagram (anonymous or cookie-authenticated via `yt-dlp`) | `INSTAGRAM_COOKIES_PATH` | Not fatal — surfaces as an import error to the user; datacenter IPs are rate-limited more aggressively than residential ones (operator-observed, see root `README.md`) |
| Local Whisper model (`faster-whisper`, CPU) | `WHISPER_MODEL_SIZE`, `WHISPER_MODEL_CACHE_DIR` | Not fatal — transcript just stays empty if it errors; first run downloads ~140MB and is markedly slower |
| SQLite file | `REEL_DB_PATH` | Fatal — this is the only datastore; see [[additive-schema-migration]] for how its schema evolves without a destructive reset |

## Where the authoritative detail lives

This page is the map, not the territory. The root `README.md` stays the reference for
every env var, the exact Docker commands, and the Instagram-cookie upload workflow —
link to it, don't copy it. `docs/deployment-apache-tls.md` / `docs/deployment-nginx-tls.md`
own the reverse-proxy configuration.

## See also

- [[01-why-a-full-login-instead-of-basic-auth]]
- [[02-the-ai-categorization-flow]]
- [[03-the-multiuser-retrofit]]
- [[hub-satellite-location]]
- [[category-taxonomy]]
