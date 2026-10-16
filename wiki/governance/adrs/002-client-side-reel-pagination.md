---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/adr
  - status/authoritative
connected files: ["current-system-design", "group-reels-by-place", "001-one-place-one-location", "BOOT-brownfield"]
---

# ADR-002 — Lista reel completa dal server, paginazione solo client

**Status:** accepted
**Decisori:** Owner
**Unità di contesto:** BOOT

## Contesto

La lista reel può crescere e su mobile non va mostrata tutta insieme. La scelta di dove
paginare è visibile nel codice ma non era scritta.

## Decisione

Il server restituisce **tutti** i reel dell'utente che passano i filtri, senza `limit` né
`offset`: lo fanno `_reel_list_context` (`app/routers/reels.py`, frammento HTMX) e
`GET /api/reels` (JSON). La paginazione è solo nel browser: `app/static/js/reel-list.js`
mostra 5 **gruppi di luogo** per volta (`REEL_LIST_GROUP_SIZE`) con «Carica altri (N gruppi
rimanenti)», ed è rieseguita a ogni `htmx:afterSwap` e `htmx:oobAfterSwap` su `#reel-list`.

*Aggiornato da [[C_01-group-reels-by-place]] (2026-10-16, confermato dall'owner): in origine
la pagina era di 5 reel e la lista non aveva ordinamento esplicito (ordine implicito di
SQLite). Ora `_reel_list_context` ordina e raggruppa per luogo in Python
(`_group_reels_by_place`) e il browser pagina i gruppi; un gruppo non si spezza mai.*

La query non ha `ORDER BY`; l'ordine è esplicito in Python. I filtri (hub con satelliti, tipo, testo) sono applicati in Python dopo la
query; il rendering fa due query per reel (tipi e location).

## Alternative considerate

- **Paginazione lato server (`limit`/cursore)** — scala meglio, ma richiede un
  ordinamento esplicito, stato lato server e un nuovo endpoint HTMX. Non scelta: con le
  dimensioni attuali il costo non è un problema.
- **Nessuna paginazione** — più semplice, ma lista lunghissima su mobile.

## Conseguenze

- Ogni swap (creazione, modifica, eliminazione, filtro) ricarica e ricostruisce la lista
  intera; il costo cresce linearmente con i reel.
- Qualunque raggruppamento o ordinamento lato server deve essere esplicito (oggi lo è, in
  Python) e la paginazione lavora sulla struttura a gruppi del DOM, senza test JS nel repo.
- La scelta è quella che [[group-reels-by-place]] aveva messo in discussione: confermata,
  con l'unità di paginazione portata da reel a gruppo.

## Conferma dell'owner

Questo ADR è stato confermato con l'owner durante l'execute di
bootstrap-brownfield-02 il 2026-10-16.
