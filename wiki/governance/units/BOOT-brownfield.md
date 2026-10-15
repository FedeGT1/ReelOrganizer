---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/unit
  - status/record
connected files: ["current-system-design", "group-reels-by-place"]
unit_kind: bootstrap-brownfield
phase: —
status: done
owner: "fedegt1"
amendments: none
---

# BOOT-brownfield — brownfield

## Spec

**Stato:** approved

La spec di questo Bootstrap è il Current System Design: [[current-system-design]].
Richiesta che ha fatto aprire la governance: [[group-reels-by-place]] (parcheggiata,
diventa la prima unità Delivery alla chiusura).

## Plan

**Stato:** approved

Fonte unica: [[current-system-design]] §6 e §7. ADR selezionati dall'owner il 2026-10-16:
001 e 003. L'ipotesi «hub/satellite a un livello» resta nel concept
[[hub-satellite-location]], non diventa ADR.

### Ordinamento dei task

Gli ADR prima, poi `CLAUDE.md` e indice ADR.

#### bootstrap-brownfield-01 — Formalizza ADR-001: un luogo, una Location

- **Slug:** adr-one-place-one-location
- **Descrizione:** Scrive il file governance/adrs/001-one-place-one-location.md dal template: i reel dello stesso luogo condividono `location_id`; chi decide cos'è «lo stesso luogo» è `resolve_place`.
- **Tier di modello:** simple
- **Depends on:** —
- **Criterio di completamento:** la pagina ADR esiste, segue `adr.md`, riporta la conferma dell'owner con data, ed è linkata da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito; ogni percorso di codice citato esiste su `dev`.

#### bootstrap-brownfield-02 — Formalizza ADR-002: lista reel completa dal server, paginazione solo client

- **Slug:** adr-client-side-pagination
- **Descrizione:** Scrive il file governance/adrs/002-client-side-reel-pagination.md: il server restituisce tutti i reel, `app/static/js/reel-list.js` ne mostra 5 alla volta. Elenca anche l'assenza di `ORDER BY` come conseguenza.
- **Tier di modello:** simple
- **Depends on:** —
- **Criterio di completamento:** la pagina ADR esiste, segue `adr.md`, riporta la conferma dell'owner con data, ed è linkata da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito; `reel-list.js` e `_reel_list_context` citati esistono su `dev`.

#### bootstrap-brownfield-03 — Aggiorna CLAUDE.md

- **Slug:** claude-md-brownfield
- **Descrizione:** Estende `CLAUDE.md` (oggi solo blocco governance) con stack, comandi build/test/run, convenzioni e guardrail dal Current System Design; rimanda a ADR-001 e ADR-002.
- **Tier di modello:** medium
- **Depends on:** bootstrap-brownfield-01, bootstrap-brownfield-02
- **Criterio di completamento:** `CLAUDE.md` contiene stack, comandi, convenzioni e guardrail coerenti con la §3-§5 del design, e il blocco governance esistente resta invariato.
- **Passo di verifica:** diff di `CLAUDE.md` rivisto dall'owner; ogni comando citato è verificato contro `pyproject.toml`/README.

#### bootstrap-brownfield-04 — Inizializza l'indice ADR

- **Slug:** adrs-index
- **Descrizione:** Crea governance/adrs/README.md dal template readme e linka ADR-001 e ADR-002.
- **Tier di modello:** simple
- **Depends on:** bootstrap-brownfield-01, bootstrap-brownfield-02
- **Criterio di completamento:** governance/adrs/README.md esiste, elenca i due ADR ed è linkato da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito, nessuna pagina orfana.

## Implementation record

### 1. Cosa è stato fatto

Formalizzati due ADR retrospettivi ([[001-one-place-one-location]], [[002-client-side-reel-pagination]]), esteso `CLAUDE.md` con stack, comandi, convenzioni e decisioni durature, creato l'indice ADR. Il Current System Design è stato approvato dall'owner prima del piano. La verifica degli ADR sul codice ha corretto il design: l'unicità di luogo e reel non è garantita (il form manuale non passa da `resolve_place`; il reel duplicato è solo un avviso).

### 2. File modificati

- `CLAUDE.md` — esteso (blocco governance invariato).
- `wiki/governance/` — design, unità, INDEX, `adrs/` (001, 002, README).
- `wiki/KANBAN.md`, `wiki/README.md`, `wiki/_meta/tags.md` — testata, link, tag.
- `wiki/change-requests/business-requests/group-reels-by-place.md` — richiesta parcheggiata.
- Nessun file in `app/`, `tests/` o `scripts/`.

### 3. Esiti di verifica

- `uv run pytest -q`: 492 passed (2026-10-16, prima del lavoro; il codice non è stato toccato): passed.
- Task 01-04: passo di verifica di ciascuno: passed (vedi i task record).
- `check_wiki.py`: solo i 3 errori preesistenti su docs/todo-next-step.md (file cancellato apposta in `5f16827`): nessun nuovo errore.
- Comportamento in browser: non verificato (nessun browser in questo ambiente).

### 4. Deviazioni dal piano

- Nome dei file ADR `001-`/`002-` invece di `ADR-001-`/`ADR-002-` (convenzione policy §3); testo del Piano allineato. Nessun amendment.
- Selezione ADR ridotta rispetto alla bozza iniziale: l'ipotesi «hub/satellite a un livello» non è diventata ADR, per scelta dell'owner; resta nel concept [[hub-satellite-location]].

### 5. ADR toccati

- ADR-001 nuovo, accepted. ADR-002 nuovo, accepted. Nessuno aggiornato o superato.

### 6. Follow-up

- Aprire come prima unità Delivery (`change`) la richiesta [[group-reels-by-place]].
- Backlog: [[tiktok-import]], non iniziata.
- Non verificabile da qui: se la deduplica ha già lasciato luoghi duplicati in produzione (dati solo sulla VPS).

### bootstrap-brownfield-01 — Formalizza ADR-001: un luogo, una Location

- **Slug:** adr-one-place-one-location
- **Descrizione:** Scrive il file governance/adrs/001-one-place-one-location.md dal template: i reel dello stesso luogo condividono `location_id`; chi decide cos'è «lo stesso luogo» è `resolve_place`.
- **Tier di modello:** simple
- **Depends on:** —
- **Criterio di completamento:** la pagina ADR esiste, segue `adr.md`, riporta la conferma dell'owner con data, ed è linkata da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito; ogni percorso di codice citato esiste su `dev`.

#### bootstrap-brownfield-02 — Formalizza ADR-002: lista reel completa dal server, paginazione solo client

- **Slug:** adr-client-side-pagination
- **Descrizione:** Scrive il file governance/adrs/002-client-side-reel-pagination.md: il server restituisce tutti i reel, `app/static/js/reel-list.js` ne mostra 5 alla volta. Elenca anche l'assenza di `ORDER BY` come conseguenza.
- **Tier di modello:** simple
- **Depends on:** —
- **Criterio di completamento:** la pagina ADR esiste, segue `adr.md`, riporta la conferma dell'owner con data, ed è linkata da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito; `reel-list.js` e `_reel_list_context` citati esistono su `dev`.

#### bootstrap-brownfield-03 — Aggiorna CLAUDE.md

- **Slug:** claude-md-brownfield
- **Descrizione:** Estende `CLAUDE.md` (oggi solo blocco governance) con stack, comandi build/test/run, convenzioni e guardrail dal Current System Design; rimanda a ADR-001 e ADR-002.
- **Tier di modello:** medium
- **Depends on:** bootstrap-brownfield-01, bootstrap-brownfield-02
- **Criterio di completamento:** `CLAUDE.md` contiene stack, comandi, convenzioni e guardrail coerenti con la §3-§5 del design, e il blocco governance esistente resta invariato.
- **Passo di verifica:** diff di `CLAUDE.md` rivisto dall'owner; ogni comando citato è verificato contro `pyproject.toml`/README.

#### bootstrap-brownfield-04 — Inizializza l'indice ADR

- **Slug:** adrs-index
- **Descrizione:** Crea governance/adrs/README.md dal template readme e linka ADR-001 e ADR-002.
- **Tier di modello:** simple
- **Depends on:** bootstrap-brownfield-01, bootstrap-brownfield-02
- **Criterio di completamento:** governance/adrs/README.md esiste, elenca i due ADR ed è linkato da `governance/INDEX.md`.
- **Passo di verifica:** `check_wiki.py` pulito, nessuna pagina orfana.

## Implementation record

### bootstrap-brownfield-01 — Formalizza ADR-001: un luogo, una Location

#### 1. Cosa è stato fatto

Scritto [[001-one-place-one-location]] dopo verifica sul codice e conferma dell'owner. La verifica ha corretto il design: l'unicità del luogo e del reel non è garantita (il form manuale non passa da `resolve_place`; il reel duplicato per link è solo un avviso).

#### 2. File modificati

- `wiki/governance/adrs/001-one-place-one-location.md` — nuovo ADR, authoritative.
- `wiki/governance/design/current-system-design.md` — §6 riga 1 corretta, `focus` aggiornato.
- `wiki/governance/INDEX.md` — link all'ADR.

#### 3. Verifica

- Percorsi e comportamento citati letti su `dev` (`location_matching.py`, `reel_links.py`, `locations.py`, `reels.py`): passed.
- `check_wiki.py`: nessun nuovo errore.

#### 4. Review

- Findings critici/importanti: nessuno. Un'imprecisione del design (unicità presunta) trovata e corretta.
- Findings minori / follow-up: nessuno.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: bozza confermata e nome file `001-` approvato.

#### 6. Deviazioni / follow-up

- Nome file `001-one-place-one-location.md` invece di `ADR-001-...` del Piano, per la convenzione `NNN-<slug>` di policy §3 e del template indice; allineato anche il testo del task 02.

### bootstrap-brownfield-02 — Formalizza ADR-002: lista completa dal server, paginazione solo client

#### 1. Cosa è stato fatto

Scritto [[002-client-side-reel-pagination]] dopo verifica sul codice (nessun `limit`/`offset` in `app/routers/reels.py`; `REEL_LIST_GROUP_SIZE = 5` in `reel-list.js`) e conferma dell'owner.

#### 2. File modificati

- `wiki/governance/adrs/002-client-side-reel-pagination.md` — nuovo ADR, authoritative.
- `wiki/governance/design/current-system-design.md` — §6 riga 3, `focus`.
- `wiki/governance/INDEX.md` — link all'ADR.

#### 3. Verifica

- Comportamento citato letto su `dev` (`reels.py`, `reel-list.js`, `map.js::refreshReelList`): passed.
- `check_wiki.py`: nessun nuovo errore.

#### 4. Review

- Findings critici/importanti: nessuno.
- Findings minori / follow-up: nessuno.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: bozza confermata, nome file `002-`.

#### 6. Deviazioni / follow-up

- Nessuna (il nome `002-` era già allineato al Piano dopo il task 01).

### bootstrap-brownfield-03 — Aggiorna CLAUDE.md

#### 1. Cosa è stato fatto

`CLAUDE.md` esteso con stack, struttura, comandi, convenzioni, decisioni durature (ADR-001, ADR-002) e guida per gli agenti, dal Current System Design. Il blocco governance preesistente è invariato byte per byte (prime 10 righe).

#### 2. File modificati

- `CLAUDE.md` — aggiunte le sezioni sopra; resta untracked finché l'owner non decide.

#### 3. Verifica

- Prime 10 righe identiche al file precedente: passed.
- Comandi citati verificati contro `pyproject.toml`, `Dockerfile`, `README.md` e `app/main.py` (env richieste); `uv run pytest -q` = 492 passed: passed.
- Convenzioni di branch/commit dedotte da `git log` e dalle regole dell'owner: confermate dall'owner.

#### 4. Review

- Findings critici/importanti: nessuno.
- Findings minori / follow-up: nessuno.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: testo completo rivisto e confermato.

#### 6. Deviazioni / follow-up

- Nessuna.

### bootstrap-brownfield-04 — Inizializza l'indice ADR

#### 1. Cosa è stato fatto

Creato governance/adrs/README.md dal template readme, con ADR-001 e ADR-002; linkato da `governance/INDEX.md`.

#### 2. File modificati

- `wiki/governance/adrs/README.md` — nuovo indice.
- `wiki/governance/INDEX.md` — link all'indice.

#### 3. Verifica

- `check_wiki.py`: nessun nuovo errore, nessuna pagina orfana: passed.

#### 4. Review

- Findings critici/importanti: nessuno.
- Findings minori / follow-up: nessuno.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: task di indice senza decisioni nuove; l'owner ha chiesto di procedere.

#### 6. Deviazioni / follow-up

- Nessuna.

## Closure record

**Esito:** success

### 1. Riassunto

Bootstrap Brownfield consegnato: Current System Design approvato, due ADR retrospettivi, `CLAUDE.md` e indice ADR. Nessun codice dell'app toccato. Da aprire come prima unità Delivery: [[group-reels-by-place]].

### 2. Artefatti collegati

- Spec: [[current-system-design]] (sezione `## Spec` di questa pagina rimanda lì)
- Plan: sezione `## Plan` di questa pagina
- Implementation record: sezione `## Implementation record` di questa pagina
- ADR toccati: [[001-one-place-one-location]], [[002-client-side-reel-pagination]]

### 3. Stato del control plane alla chiusura

- KANBAN aggiornato: sì — 4 card in DONE, richiesta parcheggiata in TODO.
- `status` finale (compilato allo stage 2): done.
- Current System Design aggiornato (solo Brownfield): sì — §6 righe 1 e 3, §7 ADR risolta.
- CLAUDE.md aggiornato (solo Bootstrap, o quando la Delivery ha cambiato conoscenza duratura): sì.

### 4. Sign-off

- Approvazione owner: fedegt1, 2026-10-16

## Amendments

Nessuno.

| Task | Motivo | Modifica proposta | Stato (`pending`/`accepted`/`rejected`) |
|---|---|---|---|

## Review notes

Nessuna.
