---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/unit
  - status/draft
connected files: ["group-reels-by-place", "current-system-design", "001-one-place-one-location", "002-client-side-reel-pagination", "hub-satellite-location"]
unit_kind: change
phase: execute
status: wip
owner: "fedegt1"
amendments: none
---

# C_01 — group-reels-by-place

## Spec

**Stato:** approved

Richiesta di origine: [[group-reels-by-place]]. Baseline: [[current-system-design]].

### 1. Ambito

**Dentro.** La lista reel nella UI (`/ui/reels` e i re-render della stessa lista dopo
creazione, modifica, eliminazione e flussi AI) raggruppa i reel per luogo, dove il luogo
è la `Location` a cui il reel punta (`Reel.location_id`), di norma un satellite.

- Ogni gruppo ha un'intestazione con il nome del luogo e il numero di reel, anche se il
  luogo ha un solo reel. Per un satellite l'intestazione riporta anche l'hub
  («Fushimi Inari · Kyoto»); un luogo che è esso stesso un hub riporta solo il proprio nome.
- Dentro un gruppo i reel sono dal più recente al più vecchio.
- I gruppi sono ordinati per reel più recente: in cima il luogo dove è stato aggiunto un
  reel per ultimo.
- La paginazione conta i gruppi, non i reel: «Carica altri» mostra 5 gruppi per volta e un
  gruppo non si spezza mai.

**Fuori.**

- Gli hub non cambiano e non diventano chiave di raggruppamento; il filtro per hub resta
  come oggi.
- Nessuna modifica allo schema e nessuna unione di luoghi duplicati (vedi
  [[001-one-place-one-location]]).
- La mappa, l'audit, l'export e le chat AI non cambiano.
- `GET /api/reels` (JSON) mantiene il suo ordine attuale: cambia solo la UI.

### 2. Obiettivi

Chi ha più reel dello stesso luogo, aggiunti in momenti diversi, li vede insieme invece
che sparsi in ordine di inserimento.

### 3. Vincoli

- Schema additivo: nessuna colonna nuova (non serve).
- Ogni route resta dietro `user_query` / `get_owned`; nessuna route nuova prevista.
- Nessun browser in ambiente di sviluppo: la verifica visiva la fa l'owner dal vivo.
- [[002-client-side-reel-pagination]] resta valida: il server consegna ancora tutta la
  lista e il browser la pagina; cambia l'unità di paginazione (gruppo) e l'ordine diventa
  esplicito lato server (chiude la conseguenza «nessun `ORDER BY`» di quell'ADR).

### 4. Aree coinvolte

- `app/routers/reels.py` — `_reel_list_context`: ordinamento esplicito e raggruppamento.
- `app/templates/partials/reel_list.html` — rendering a gruppi con intestazione.
- `app/templates/partials/_reel_card.html` — resta un `<li>` autonomo (usato anche da
  `note_regeneration.py` e `audit_results.html`).
- `app/static/js/reel-list.js` — paginazione per gruppi.
- `app/static/css/style.css` — stile dell'intestazione di gruppo.
- Consumatori del frammento lista, da non rompere: `ai_categorize.py`,
  `ai_multi_categorize.py`, `reels.py` (swap `hx-swap-oob` su `#reel-list`).
- `tests/` — `test_ui_fragments.py`, `test_reels_api.py`, `test_ai_ui.py`,
  `test_note_regeneration.py`, `test_audit.py`.
- Sezioni del Current System Design coinvolte: §2 (lista reel, paginazione), §5 (rischi
  sull'ordine), §6 riga 3.

### 5. Criteri di successo

- Tre reel che puntano allo stesso satellite, aggiunti in momenti diversi con altri reel
  in mezzo, compaiono adiacenti sotto un'unica intestazione con nome del luogo, hub e «3».
- Un luogo con un solo reel ha la propria intestazione; dentro il gruppo l'ordine è dal
  più recente.
- Aggiungere un reel a un luogo già presente porta quel gruppo in cima.
- Con più di 5 luoghi, «Carica altri» rivela 5 gruppi per volta e mostra quanti gruppi
  restano; nessun gruppo è visibile solo in parte.
- Con un filtro attivo (hub, tipo, testo) la lista filtrata è raggruppata allo stesso
  modo.
- Eliminazione, modifica, rigenerazione della nota e import AI lasciano la lista
  raggruppata e coerente.
- La suite di test esistente passa; i nuovi test coprono ordine, raggruppamento e
  paginazione per gruppi.

### 6. Rischi

- Luoghi duplicati storici (creati dal form manuale o prima di `resolve_place`) restano
  gruppi separati: la feature li rende visibili, non li risolve.
- La riscrittura di `reel-list.js` può rompere «Carica altri» dopo uno swap HTMX: da
  verificare dal vivo.
- La rigenerazione nota sostituisce una singola card (`closest li`): il conteggio
  dell'intestazione non cambia, ma la card deve restare nel suo gruppo.
- Parità di `created_at` tra reel dello stesso luogo: serve un ordine stabile di
  spareggio.

### 7. Domande aperte

Nessuna. Decise dall'owner il 2026-10-16:

- chiave = luogo del reel (non l'hub); intestazione per luogo; gruppi per reel più recente;
  5 gruppi per volta;
- reel dentro il gruppo dal più recente; intestazione anche per i luoghi con un solo
  reel; intestazione del satellite con l'hub («Satellite · Hub»); `GET /api/reels`
  invariato.

Nessun reel è senza luogo: `location_id` è obbligatorio.

### 8. Baseline freshness check

- `[ ]` Fresco — procedi.
- `[x]` Refresh locale necessario — task di refresh faranno parte del piano di questa unità.
- `[ ]` Refresh più ampio necessario — escalation all'owner prima di procedere oltre con
  questa unità.

Note: `app/` e `tests/` identici al commit su cui è basato il design
(`git diff 965b11b HEAD -- app tests scripts` vuoto). Il design §2 non elenca i
consumatori del frammento lista (`ai_categorize.py`, `ai_multi_categorize.py`) né gli usi
di `_reel_card.html` in `note_regeneration.py` e `audit_results.html`: da aggiungere alla
§2 alla chiusura dell'unità.

## Plan

**Stato:** approved

Fonte unica: la `## Spec` di questa pagina e gli ADR [[001-one-place-one-location]] e
[[002-client-side-reel-pagination]]. Piano approvato dall'owner il 2026-10-16.

### Regole del piano (promemoria)

- Niente codice nel piano; i test si scrivono prima dell'implementazione (TDD).
- Nessuna nuova decisione: ciò che manca è un amendment.
- `reel-list.js` non ha infrastruttura di test nel repo: la sua verifica è la struttura
  HTML (task 06) più il controllo dal vivo dell'owner (task 07).

### Ordinamento dei task

01 → 02 → 03 → (04, 05, 06) → 07.

### Task

#### C_01_01 — Refresh baseline: consumatori della lista reel

- **Slug:** refresh-baseline-reel-list
- **Descrizione:** Aggiorna la §2 di `governance/design/current-system-design.md` con i consumatori reali del frammento lista (`ai_categorize.py`, `ai_multi_categorize.py`, `reels.py`) e della card (`note_regeneration.py`, `audit_results.html`).
- **Tier di modello:** simple
- **Depends on:** —
- **Criterio di completamento:** la §2 del design elenca tutti i consumatori verificati sul codice, senza modificare il resto del design.
- **Passo di verifica:** ogni consumatore citato si ritrova con `grep` su `dev`; `check_wiki.py` pulito.

#### C_01_02 — Raggruppamento e ordinamento lato server

- **Slug:** server-grouping
- **Descrizione:** In `_reel_list_context` (`app/routers/reels.py`) ordina in modo esplicito e raggruppa i reel per `location_id`: reel dal più recente, gruppi per reel più recente con spareggio stabile; per ogni gruppo nome del luogo, nome dell'hub se è un satellite e conteggio.
- **Tier di modello:** medium
- **Depends on:** C_01_01
- **Criterio di completamento:** il contesto restituisce gruppi nell'ordine della Spec §1; i filtri (hub, tipo, testo) producono gruppi coerenti; `GET /api/reels` non cambia.
- **Passo di verifica:** nuovi test in `tests/` (ordine gruppi, ordine nel gruppo, spareggio con `created_at` uguale, satellite con hub, hub senza hub, filtri) falliscono prima e passano dopo; `uv run pytest -q` verde.

#### C_01_03 — Template a gruppi

- **Slug:** grouped-template
- **Descrizione:** `app/templates/partials/reel_list.html` rende un'intestazione per gruppo (nome, hub per i satelliti, conteggio) con le card del gruppo; `_reel_card.html` resta un `<li>` autonomo.
- **Tier di modello:** medium
- **Depends on:** C_01_02
- **Criterio di completamento:** il frammento HTML di `/ui/reels` mostra un'intestazione per luogo con le sue card, anche per i luoghi con un solo reel; il banner del filtro hub resta.
- **Passo di verifica:** test sul frammento (`test_ui_fragments.py`) verdi; `uv run pytest -q` verde.

#### C_01_04 — Paginazione per gruppi

- **Slug:** group-pagination
- **Descrizione:** `app/static/js/reel-list.js` mostra 5 gruppi per volta, con «Carica altri» e l'etichetta dei gruppi rimanenti; un gruppo non si spezza; la paginazione si reinizializza a ogni swap su `#reel-list`.
- **Tier di modello:** medium
- **Depends on:** C_01_03
- **Criterio di completamento:** con più di 5 luoghi si vedono 5 gruppi interi e «Carica altri (N gruppi rimanenti)»; dopo creazione, modifica, eliminazione o filtro la paginazione riparte.
- **Passo di verifica:** controllo dal vivo dell'owner nel task C_01_07; la struttura HTML da cui dipende è coperta dai test del task C_01_06.

#### C_01_05 — Stile dell'intestazione di gruppo

- **Slug:** group-header-style
- **Descrizione:** Regole in `app/static/css/style.css` per l'intestazione di gruppo, coerenti con `.reel-list`, leggibili a circa 400 px di larghezza.
- **Tier di modello:** simple
- **Depends on:** C_01_03
- **Criterio di completamento:** l'intestazione è visivamente distinta dalle card e non causa scroll orizzontale.
- **Passo di verifica:** controllo dal vivo dell'owner nel task C_01_07 (nessun browser in ambiente di sviluppo).

#### C_01_06 — Test dei consumatori della lista

- **Slug:** consumer-tests
- **Descrizione:** Adegua e completa i test dei flussi che rendono la lista o la card (`test_ui_fragments.py`, `test_ai_ui.py`, `test_note_regeneration.py`, `test_audit.py`, `test_reels_api.py`) perché verifichino lista raggruppata dopo create/edit/delete e flussi AI, card autonoma, e API JSON invariata.
- **Tier di modello:** medium
- **Depends on:** C_01_03
- **Criterio di completamento:** ogni consumatore elencato in Spec §4 ha almeno un test sulla lista raggruppata o sulla card; nessun test preesistente rimosso senza motivo.
- **Passo di verifica:** `uv run pytest -q` verde con il conteggio dei test non inferiore a 492.

#### C_01_07 — Verifica dal vivo e conferma dell'owner

- **Slug:** live-verification
- **Descrizione:** L'owner controlla in browser: raggruppamento, intestazioni con hub, ordine dei gruppi, «Carica altri» a 5 gruppi, filtri, modifica, eliminazione, rigenerazione nota, import AI.
- **Tier di modello:** simple
- **Depends on:** C_01_04, C_01_05, C_01_06
- **Criterio di completamento:** conferma esplicita dell'owner, registrata nel task record, per ciascun punto dei criteri di successo della Spec §5.
- **Passo di verifica:** esito del controllo dal vivo scritto nel task record.

### Annullati

*(nessuno)*

## Implementation record

### C_01_01 — Refresh baseline: consumatori della lista reel

- **Stato:** done
- **Branch:** governance/C_01_01-refresh-baseline-reel-list (mergiato in `dev`, commit di merge `--no-ff`)

#### 1. Cosa è stato fatto

Aggiornata la §2 di `governance/design/current-system-design.md` con i consumatori verificati del frammento lista (`reels.py`, `ai_categorize.py`, `ai_multi_categorize.py`) e della card (`note_regeneration.py`, `audit_results.html`). Trovato inoltre che l'audit rende `<ul class="reel-list">` proprie fuori da `#reel-list`: le regole CSS `.reel-list` si applicano anche lì e `reel-list.js` no.

#### 2. File modificati

- `wiki/governance/design/current-system-design.md` — §2, paragrafo sui consumatori.

#### 3. Verifica

- Ogni consumatore citato ritrovato con `grep` su `dev`: passed.
- `check_wiki.py`: nessun nuovo errore.

#### 4. Review

- Findings critici/importanti: nessuno.
- Findings minori / follow-up: blocco aggiunto in §2 lungo ma leggibile, non riscritto; il merge porta con sé anche lo stato del control plane del branch.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: review con report esplicito; approvazione e merge in `dev` richiesti dall'owner.

#### 6. Deviazioni / follow-up

- Segnalazione per C_01_05: le regole CSS `.reel-list` valgono anche nell'audit; l'intestazione di gruppo non deve alterare quelle liste.

### C_01_02 — Raggruppamento e ordinamento lato server in _reel_list_context

- **Stato:** done
- **Branch:** governance/C_01_02-server-grouping (mergiato in `dev`, commit di merge `--no-ff`)
- **Commit:** 0a40e0d

#### 1. Cosa è stato fatto

`_reel_list_context` (`app/routers/reels.py`) restituisce ora anche `groups`: i reel sono raggruppati per `location_id`, dal più recente dentro il gruppo, con i gruppi ordinati per reel più recente e spareggio stabile (nome del luogo, poi id). Ogni gruppo porta nome, nome dell'hub per i satelliti (`None` per un hub), conteggio e le card serializzate. La chiave `reels` piatta e `GET /api/reels` sono invariati; ogni reel è serializzato una volta sola. Il template non è ancora cambiato (task C_01_03).

#### 2. File modificati

- `app/routers/reels.py` — `_group_reels_by_place` e la chiave `groups`.
- `tests/test_reel_list_grouping.py` — 11 test nuovi (nove falliti prima, due di caratterizzazione).

#### 3. Verifica

- TDD: 9 test nuovi in rosso su `KeyError: 'groups'` prima dell'implementazione, tutti verdi dopo: passed.
- `uv run pytest -q`: 503 passed (492 + 11): passed.
- `GET /api/reels` ordine invariato (test di caratterizzazione): passed.

#### 4. Review

- Findings critici/importanti: nessuno.
- Findings minori / follow-up: doppia serializzazione dei reel trovata in self-review e rimossa. La chiave `reels` piatta resta finché il template non passa ai gruppi: valutare la rimozione in C_01_03/C_01_06.
  Review: `session.get(Location, …)` del raggruppamento non è filtrato per utente (come `_serialize_reel`); nessun buco concreto, i `location_id` arrivano da reel già filtrati. Costo di una `get` per gruppo accettato.

#### 5. Approvazione owner

- Esito: approved (2026-10-16)
- Note: review con report esplicito; approvazione e merge in `dev` richiesti dall'owner.

#### 6. Deviazioni / follow-up

- Nessuna.

### C_01_03 — Template a gruppi con intestazione per luogo

- **Stato:** review
- **Branch:** governance/C_01_03-grouped-template
- **Commit:** 5019b8f

#### 1. Cosa è stato fatto

`app/templates/partials/reel_list.html` rende un `<section class="reel-group" data-location-id>` per gruppo, con un `<h3 class="reel-group-header">` (nome del luogo, ` · hub` per i satelliti, conteggio) e le card del gruppo in un `<ul class="reel-list">` proprio. `_reel_card.html` è invariato e resta un `<li>` autonomo. Il banner del filtro hub è conservato. La chiave `reels` piatta del contesto, senza più consumatori, è rimossa insieme al test che la richiedeva.

#### 2. File modificati

- `app/templates/partials/reel_list.html` — rendering a gruppi.
- `app/routers/reels.py` — rimossa la chiave `reels` dal contesto.
- `tests/test_reel_list_template.py` — 8 test nuovi (sette in rosso prima).
- `tests/test_reel_list_grouping.py` — rimosso `test_flat_reels_key_is_still_provided`.

#### 3. Verifica

- TDD: 7 test su 8 in rosso prima dell'implementazione, tutti verdi dopo: passed.
- `uv run pytest -q`: 510 passed (503 + 8 − 1): passed.
- Audit (`audit_results.html`) e rigenerazione nota non toccati: usano ancora `_reel_card.html` in una `ul.reel-list` propria.

#### 4. Review

- Findings critici/importanti: nessuno nel task. Stato intermedio noto, vedi §6.
- Findings minori / follow-up: intestazione non ancora stilata (C_01_05).

#### 5. Approvazione owner

- Esito: pending
- Note: —

#### 6. Deviazioni / follow-up

- **Stato intermedio su `dev` fino a C_01_04**: `reel-list.js` cerca la prima `ul.reel-list` e nasconde i reel oltre il quinto di *quel* gruppo, mostrando «Carica altri» dopo di esso; gli altri gruppi restano interi. Nessun dato perso, ma la paginazione è sbagliata finché non arriva C_01_04: non rilasciare `dev` tra i due task.
- Rimossa la chiave `reels` piatta (follow-up di C_01_02).

## Closure record

*(non ancora)*

## Amendments

Nessuno.

| Task | Motivo | Modifica proposta | Stato (`pending`/`accepted`/`rejected`) |
|---|---|---|---|

## Review notes

Nessuna.
