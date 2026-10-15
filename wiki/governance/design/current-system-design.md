---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/design
  - status/draft
connected files: ["001-one-place-one-location", "002-client-side-reel-pagination", "components/reel-organizer/README", "hub-satellite-location", "get-owned", "additive-schema-migration", "group-reels-by-place", "BOOT-brownfield"]
posture: bootstrap
focus: "Bootstrap Brownfield in execute: tutti i task di execute fatti; pronto per la chiusura del Bootstrap; richiesta group-reels-by-place parcheggiata"
---

# Current System Design — ReelOrganizer

**Stato:** approved

## Guardrail

- Dati sulla VPS: schema additivo soltanto. Nuove tabelle ok; nuove colonne su tabelle
  esistenti solo con esplicita segnalazione all'owner (vedi [[additive-schema-migration]]).
- Ogni nuova route che legge/scrive per id usa `app/scoping.py::get_owned` / `user_query`
  (vedi [[get-owned]]).
- Nessuna cancellazione a cascata: di default si blocca, non si cascata.
- `.claude/` non si committa mai; `wiki/` si committa solo dopo la revisione dell'owner.
- Niente browser né HTTPS locale in questo ambiente: le verifiche di UI le fa l'owner dal vivo.

## Item aperti

- Richiesta parcheggiata: [[group-reels-by-place]] — raggruppare i reel per luogo nella
  lista. Diventa la prima unità Delivery (`change`) alla chiusura del Bootstrap.
- Richiesta di backlog: [[tiktok-import]] — non iniziata, non prioritaria.
- Le domande aperte di §7 sotto.

## Variante Brownfield (Current System Design)

Fonte: letto dalla codebase al commit `965b11b` (branch `dev`), 2026-10-16.

### 1. Panoramica del sistema

ReelOrganizer è un'unica app FastAPI self-hosted: l'utente incolla link di reel
Instagram, il sistema scarica il video (`yt-dlp`), trascrive l'audio (`faster-whisper`),
chiede a un modello (Anthropic o OpenAI) di proporre luogo e categoria e, dopo conferma,
salva il reel. I reel si consultano in una lista e su una mappa Leaflet. Più account
privati convivono sullo stesso deploy (creati solo da CLI). Un solo processo, un solo
SQLite.

### 2. Architettura

- **Entry point:** `app/main.py` (`app.main:app`) monta i router di `app/routers/*`,
  `AuthMiddleware` e `SessionMiddleware`; il DB si prepara in `lifespan`
  (`create_db_and_tables`).
- **Dati** (`app/models.py`, SQLModel/SQLite): `User`, `Location` (hub o satellite via
  `parent_id`, un solo livello; `lat/lon` nullable), `Reel` (`location_id` obbligatorio,
  `note`, `caption`, `transcript`, `created_at`), `Category` (per utente), `ReelType`
  (N:M reel↔categoria), `AiSession/AiMessage`, `AskSession/AskMessage`.
- **Isolamento utenti:** `user_id` su `Location`, `Reel`, `AiSession`, `AskSession`;
  helper `user_query` / `get_owned` in `app/scoping.py`.
- **UI:** template Jinja2 server-side + HTMX. `index.html` carica `#map-container`
  (`/ui/map`) e `#reel-list` (`/ui/reels`) in `hx-trigger="load"`. Creazione, modifica ed
  eliminazione rispondono con la lista rigenerata e la mappa come swap `hx-swap-oob`.
- **Lista reel** (area della richiesta in corso): `app/routers/reels.py::_reel_list_context`
  esegue `user_query(Reel, user_id)` (con filtro opzionale hub + satelliti), poi filtri
  Python per tipo e testo, poi `_serialize_reel` per ciascun reel (una query per i tipi e
  una per la location). Rende `app/templates/partials/reel_list.html` → `<ul class="reel-list">` di
  `app/templates/partials/_reel_card.html`; ogni card mostra il nome del luogo (linkato al reel), nota e icone dei
  tipi. Esiste anche `GET /api/reels` con la stessa logica, che restituisce JSON.
- **Paginazione:** interamente client-side, `app/static/js/reel-list.js`: il server
  restituisce tutti i reel, il JS nasconde tutti tranne i primi 5 e aggiunge «Carica altri».
- **Deduplica dei luoghi:** `app/location_matching.py` (`resolve_place`,
  `normalize_place_name`, distanza haversine con soglie 150 m auto-match / 2 km candidati,
  somiglianza nome 0.8); usata dal flusso AI di categorizzazione.
- **AI:** `app/ai/` (provider Anthropic/OpenAI dietro `get_provider`), router
  `ai_categorize`, `ai_multi_categorize`, `ai_ask`, `note_regeneration`.
- **Ingest:** `app/ingest/instagram.py` (`yt-dlp`, cookie opzionali),
  `app/ingest/transcribe.py` (Whisper CPU).
- **Altre superfici:** mappa (`app/routers/map.py`), gestione luoghi
  (`locations.py`), categorie, audit (`/strumenti/audit`), export Markdown.

### 3. Build / test / run

- build: `docker build -t reel-organizer .`
- test: `uv run pytest -q` — 492 passed il 2026-10-16 (circa 58 s)
- run (locale): `uv run uvicorn app.main:app`; richiede `AUTH_USERNAME`, `AUTH_PASSWORD`,
  `SESSION_SECRET_KEY` (da `require_env`). Il cookie di sessione è Secure: su
  `http://localhost` non si fa login, quindi le verifiche UI passano dall'owner.
- lint / typecheck: nessuno configurato in `pyproject.toml`
- deploy: Docker su VM dietro reverse proxy Apache/nginx (README radice,
  `docs/deployment-*-tls.md`); aggiornamento = rebuild + ricrea il container

### 4. Convenzioni

- Router per dominio in `app/routers/`; coppie `router` (`/api/...`, JSON) e `ui_router`
  (`/ui/...`, frammenti HTML).
- Query sempre via `user_query` / `get_owned`; id da client mai letti con `session.get`
  nudo.
- Schema: `create_all` + `_ADDITIVE_COLUMNS` in `app/db.py`; mai `ALTER` distruttivi.
- Test pytest in `tests/` (un file per area), `TestClient` e DB temporanei.
- Testi UI in italiano, identificatori in inglese.

### 5. Rischi e aree fragili

- La lista reel **non ha `ORDER BY`**: l'ordine «di inserimento» è quello implicito di
  SQLite, non garantito; ogni ordinamento nuovo deve essere esplicito.
- La paginazione client-side lavora sull'ordine del DOM: raggruppare o ordinare
  nel server cambia cosa finisce nei primi 5; i gruppi potrebbero spezzarsi sul bordo
  della pagina.
- `_serialize_reel` fa 2 query per reel e `_filter_reels_by_text` una per reel: la lista
  scala male oltre qualche centinaio di reel (non è un problema oggi, solo un limite).
- Lo schema non è alterabile alla leggera (dati reali sulla VPS, memoria dell'owner).
- `get_owned` è opt-in: una route nuova che lo dimentica reintroduce la classe di bug già
  corretta in `ed5d7fa`.
- Più reel con lo stesso luogo: la deduplica avviene a monte (`resolve_place`); eventuali
  duplicati storici creati prima di quella logica restano come `Location` distinte.

### 6. Decisioni implicite osservate

| # | Decisione | Dove si vede | Promuovere ad ADR? |
|---|---|---|---|
| 1 | Un luogo = una `Location`, per convenzione (dedup solo nel flusso AI e nell'audit, non nel form manuale); reel dello stesso luogo condividono `location_id`; il reel duplicato per link è solo un avviso | `app/models.py`, `app/location_matching.py` | sì → [[001-one-place-one-location]] (fatto) |
| 2 | Hub/satellite a un solo livello | `app/models.py::Location`, [[hub-satellite-location]] | no — resta nel concept (owner, 2026-10-16) |
| 3 | Lista completa al server, paginazione solo client | `app/routers/reels.py`, `app/static/js/reel-list.js` | sì → [[002-client-side-reel-pagination]] (fatto) |
| 4 | Aggiornamento UI via HTMX con swap OOB di lista e mappa | `app/routers/reels.py::ui_create_reel` | no |
| 5 | Isolamento per `user_id` via helper opt-in | `app/scoping.py` | già documentata in [[get-owned]], non serve ADR |
| 6 | Schema solo additivo | `app/db.py` | già documentata in [[additive-schema-migration]] |

### 7. Domande aperte

- **Owner:** vale lo stesso comportamento di raggruppamento per i filtri (hub, tipo,
  testo)? (Dipende dalla richiesta [[group-reels-by-place]], si decide nel brainstorm
  Delivery, non qui.)
- **Owner:** la deduplica automatica dei luoghi ha già creato duplicati in produzione che
  il raggruppamento renderebbe visibili? Non verificabile da qui (dati solo sulla VPS).
- ~~ADR candidate~~ risolto: 001 e 003 formalizzati in execute, 002 resta nel concept.
- Non verificato in questo ambiente: il comportamento reale in browser (nessun browser
  qui); questa pagina descrive codice e test, non la UI vista dal vivo.
