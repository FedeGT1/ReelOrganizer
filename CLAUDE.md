## Governance (kit)

- Ogni richiesta di lavoro di progetto (feature, evolutiva, bug, ripresa) passa PRIMA
  da `project-governance` (`.claude/skills/project-governance/SKILL.md`): invocala
  prima di leggere codice, discutere un design o scrivere qualcosa.
- Ha precedenza su `using-superpowers` e su `superpowers:brainstorming`: le skill di
  processo si usano dentro la fase instradata, non al posto del dispatcher.
- La taglia (piccola / grande) la decide il Passo 1 di `project-governance`; non
  introdurre classificazioni proprie. Il lavoro grande richiede la governance.
- Vault: wiki/

## Stack

- Linguaggio: Python 3.11+
- Framework: FastAPI, SQLModel/SQLite, Jinja2 + HTMX, Leaflet
- Package manager / build: `uv` (lock `uv.lock`), immagine Docker (`Dockerfile`)
- Test runner: pytest
- Altri: `yt-dlp`, `faster-whisper` (CPU), provider AI Anthropic/OpenAI (`app/ai/`)

## Struttura del repository

- `app/` — app FastAPI: `routers/` (per dominio, `/api/...` JSON e `/ui/...` HTMX),
  `models.py`, `db.py`, `scoping.py`, `location_matching.py`, `ai/`, `ingest/`,
  `templates/`, `static/`
- `scripts/create_user.py` — unico modo di creare account (nessun signup)
- `tests/` — pytest, un file per area
- `docs/` — runbook di deploy e piani storici
- `wiki/` — vault (concept, ADR in `wiki/governance/adrs/`, governance)

## Come build / test / run

- test: `uv run pytest -q`
- run locale: `uv run uvicorn app.main:app` (richiede `AUTH_USERNAME`, `AUTH_PASSWORD`,
  `SESSION_SECRET_KEY`; il cookie di sessione è Secure, quindi su `http://localhost` non
  si fa login)
- build/deploy: `docker build -t reel-organizer .`, poi ricrea il container (dettagli nel
  `README.md` radice)
- lint/typecheck: non configurati

## Convenzioni

- Query sempre via `user_query` / `get_owned` (`app/scoping.py`): mai `session.get` nudo
  su id forniti dal client.
- Schema solo additivo: nuove tabelle ok; nuove colonne su tabelle esistenti vanno in
  `_ADDITIVE_COLUMNS` (`app/db.py`) e si segnalano all'owner. Mai cascade delete.
- Testi UI in italiano, identificatori in inglese.
- Branch: lavoro su `dev`; `main` può restare indietro di qualche commit (branch di verità: `dev`). Commit in stile conventional (`feat:`, `fix:`, `test:`,
  `docs:`, `chore:`). Un commit per item approvato e testato.
- `.claude/` non si committa mai; `wiki/` si committa solo dopo revisione dell'owner.

## Decisioni durature

- `wiki/governance/adrs/001-one-place-one-location.md` — un luogo = una `Location`; l'unicità è per convenzione
  (`resolve_place`), non garantita dal DB né dal form manuale.
- `wiki/governance/adrs/002-client-side-reel-pagination.md` — la lista reel è completa dal server, paginata solo
  nel browser (5 gruppi di luogo per volta), con ordinamento e raggruppamento espliciti in Python.

## Guida per gli agenti

- Leggi lo stato prima di agire: `wiki/KANBAN.md` e il frontmatter delle pagine in
  `wiki/governance/`; `.claude/skills/project-governance/references/policy.md` per le
  regole.
- Non improvvisare fuori dalla skill di fase instradata; il non-assumere vale in execute.
- Nessun browser né HTTPS locale in questo ambiente: le verifiche di UI le fa l'owner.
