# Design — Japan Reel Organizer (Python rewrite)

Status: approved by user, ready for implementation planning.
Source brief: `docs/japan-reel-organizer-specifiche.md`

## 1. Goal

Rewrite the existing single-file HTML/JS prototype as a Python app that organizes Instagram reels saved for a Japan trip: categorize by location (hub city/region → nearby day trip) and content type, display on a schematic railway-map-style SVG, and assist categorization via a generative AI chat flow.

## 2. Stack

- **Backend**: Python 3.11+, FastAPI
- **Persistence**: SQLite via SQLModel
- **Frontend**: Jinja2 server-rendered templates + HTMX for interactivity, responsive mobile-first CSS, vanilla JS only for the SVG map. No PWA for now.
- **AI**: Anthropic Python SDK, model `claude-haiku-4-5` (cost-effective, sufficient for short-text classification). Structured output enforced via `output_config.format` (JSON Schema) on `messages.create` — not tool-use, not plain-text parsing.
- **Execution**: Dockerized (`Dockerfile` + `uvicorn` entrypoint). `docker run` locally for now; all config (Anthropic API key, DB path) via environment variables so a future remote deploy (Render/Fly.io) is a config change, not a code change.

## 3. Project structure

```
japan-reel-organizer/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── models.py            # SQLModel: Location, Reel, ReelType, AiSession, AiMessage
│   ├── db.py                # engine + session
│   ├── seed.py               # default hubs + sample satellites
│   ├── routers/
│   │   ├── locations.py     # CRUD locations
│   │   ├── reels.py         # CRUD reels + filters
│   │   └── ai_categorize.py # AI chat endpoint
│   ├── ai/
│   │   ├── client.py        # Anthropic SDK wrapper
│   │   └── prompts.py       # system prompt, JSON schema
│   ├── templates/           # Jinja2: index.html, partials/*
│   └── static/               # css, map JS
├── data/
│   └── japan_reels.db       # SQLite file (gitignored, Docker volume)
├── Dockerfile
├── pyproject.toml
└── README.md
```

## 4. Data model

### Location
| field     | type              | notes |
|-----------|-------------------|-------|
| id        | str (uuid/slug)   | PK |
| name      | str               | e.g. "Kyoto - Osaka / Kansai" |
| is_hub    | bool              | True = main station, False = day-trip satellite |
| parent_id | str, nullable     | set only when `is_hub=False`; FK to a hub Location |
| x, y      | float, nullable   | SVG coordinates (hubs only; satellites computed radially at runtime) |

### Reel
| field       | type          | notes |
|-------------|---------------|-------|
| id          | str (uuid)    | PK |
| link        | str           | Instagram reel URL |
| location_id | str, FK       | → Location |
| note        | str, nullable | short memo |
| created_at  | datetime      | default now |

### ReelType (join table)
| field   | type | notes |
|---------|------|-------|
| reel_id | str, FK | → Reel |
| type    | str     | one of the fixed taxonomy values |

Taxonomy (fixed constant, not in DB): `food` 🍜, `culture` ⛩️, `nature` 🌸, `shopping` 🛍️, `stay` 🏨, `transport` 🚄, `experience` 🎡 — each with Italian label, icon, UI color.

### AiSession / AiMessage (conversation persistence)
| table     | fields |
|-----------|--------|
| AiSession | id, created_at, updated_at |
| AiMessage | id, session_id (FK), role (`user`/`assistant`), content, created_at |

Persisted on DB (not in-memory) so a categorization conversation survives a server restart — relevant once the app may run on a remote host that can sleep/restart.

### Seed data
Hubs: Sapporo/Hokkaido, Sendai/Tohoku, Tokyo/Kanto, Nagoya/Chubu, Kyoto-Osaka/Kansai, Hiroshima/Chugoku, Matsuyama/Shikoku, Fukuoka/Kyushu, Okinawa.
Sample satellites: Nikko, Kamakura, Hakone, Kawagoe (→ Tokyo); Nara, Uji, Himeji (→ Kansai); Miyajima (→ Hiroshima); Otaru (→ Sapporo); Dazaifu (→ Fukuoka).

## 5. Core features

### 5.1 Map
- Endpoint returns all Locations with reel counts.
- Radial layout of satellites around their hub, computed server-side.
- SVG rendering: circle-stations sized by reel count, dashed hub→satellite lines, click shows a panel with that stop's reels.
- Type filter: clickable chips dim stations with no reels of the selected type.

### 5.2 Manual reel CRUD
- Add-reel form: link, location (dropdown grouped by hub + satellites, "create new location" option), type (multi-select), note.
- Create a new location on the fly, as a new hub or as a satellite of an existing hub.
- Delete a reel.

### 5.3 AI-assisted categorization

**Constraint**: no Instagram scraping/browsing — the model only sees text the user pastes (link + caption, or free-form description).

Flow (session persisted in `AiSession`/`AiMessage`):

1. User sends link + caption/description (new or continuing session).
2. Backend loads message history from `AiMessage`, builds `system` (task description, list of existing hubs for matching, JSON schema) + `messages` (full history, not just the latest turn).
3. Call `client.messages.create(model="claude-haiku-4-5", output_config={"format": {"type": "json_schema", "schema": ...}}, system=..., messages=...)`. The schema enforces:
   ```json
   {
     "place_name": "string",
     "near_hub": "string | null",
     "types": ["food", "..."],
     "note": "string (max 20 words)",
     "confidence": "high | medium | low",
     "question": "string | null"
   }
   ```
4. If `question` is set, show it as an AI message, save the turn, wait for the user's reply, call again with updated history.
5. On user acceptance ("use this suggestion"):
   - match an existing Location by `place_name` (case-insensitive, substring both directions);
   - else if `near_hub` matches an existing hub, create a satellite under it named `place_name`;
   - else if `near_hub` is null and no match, create a new hub;
   - precompile the manual form (link, location, types, note) for user review — **never auto-save without confirmation**.
6. Filter `types` returned by the model against the valid taxonomy (drop unrecognized values).

### 5.4 AI session persistence
Stored in `AiSession`/`AiMessage` tables (decided — DB-backed, not in-memory), so a conversation survives a server restart mid-flow.

## 6. API (draft)

| Method | Path                             | Description |
|--------|-----------------------------------|-------------|
| GET    | `/api/locations`                  | list locations with reel counts |
| POST   | `/api/locations`                  | create location (hub or satellite) |
| DELETE | `/api/locations/{id}`             | delete location (cascade on linked reels — decide in implementation) |
| GET    | `/api/reels?location_id=&type=`   | filtered reel list |
| POST   | `/api/reels`                       | create reel |
| DELETE | `/api/reels/{id}`                  | delete reel |
| POST   | `/api/ai/categorize`              | send link+caption or follow-up answer; returns AI proposal (manages session) |

## 7. Visual direction

Inspiration: Japanese railway maps + ukiyo-e/hanko print aesthetic.
- Colors: warm-grey washi paper background (`#E3E1D4`), deep indigo ink (`#1F2C47`), medium indigo for stations/lines (`#35496B`), hanko-stamp red as the sole accent for CTAs/confirmation badges (`#A63A2E`), muted gold for details (`#B08D57`).
- Typography: display serif with Japanese influence (e.g. Shippori Mincho) for titles, geometric sans (e.g. Zen Kaku Gothic New) for body, monospace for tags/counters.
- The map is schematic, not geographically accurate — legibility of the hub→satellite system is the goal.
- The existing HTML prototype can be used as a direct reference for markup/CSS to adapt into Jinja2 templates.

Frontend is otherwise responsive/mobile-first per §2, since the app should also be usable from a phone in Japan.

## 8. Out of scope (for now)

- Multi-user / authentication
- Automatic import of saved Instagram reels (no reliable/permitted way to do this)
- Native mobile app
- Cloud sync beyond a future single-instance remote deploy (SQLite stays local/on a volume)

## 9. Suggested implementation order

1. Scaffold FastAPI + SQLModel + SQLite, `Location`/`Reel`/`ReelType` models, seed data.
2. Location and reel CRUD (no AI), minimal Jinja2 UI to verify the data model.
3. SVG map rendering with radial layout and type filters.
4. Full add/delete reel form.
5. AI integration: `AiSession`/`AiMessage` models, `/api/ai/categorize` endpoint, conversational session handling, structured-output JSON parsing.
6. Dockerize (Dockerfile, env-based config).
7. Visual polish per §7.

## 10. Resolved decisions (previously open questions)

- **Deploy**: Docker locally now; environment-variable-driven config in anticipation of future remote hosting.
- **Reel types**: relational join table (`ReelType`), not a JSON column — filtering by type is a core feature (§5.1).
- **AI session persistence**: DB-backed (`AiSession`/`AiMessage`), not in-memory — survives server restarts on a future remote host.
- **Frontend stack**: Jinja2 + HTMX + responsive CSS, no PWA for now (decided by Claude at user's request — user has no frontend expertise).
- **AI model**: `claude-haiku-4-5` — cost-effective and sufficient for short-text classification in a personal hobby app.
- **Structured output**: `output_config.format` with a JSON Schema (via the Messages API), not tool-use or plain-text parsing — guarantees valid JSON matching the schema in §5.3.
