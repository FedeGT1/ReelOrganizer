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
mostra 5 reel per volta (`REEL_LIST_GROUP_SIZE`) con «Carica altri (N rimanenti)», ed è
rieseguita a ogni `htmx:afterSwap` su `#reel-list`.

Non c'è `ORDER BY` sulla lista: l'ordine è quello implicito di SQLite (rowid), non
garantito. I filtri (hub con satelliti, tipo, testo) sono applicati in Python dopo la
query; il rendering fa due query per reel (tipi e location).

## Alternative considerate

- **Paginazione lato server (`limit`/cursore)** — scala meglio, ma richiede un
  ordinamento esplicito, stato lato server e un nuovo endpoint HTMX. Non scelta: con le
  dimensioni attuali il costo non è un problema.
- **Nessuna paginazione** — più semplice, ma lista lunghissima su mobile.

## Conseguenze

- Ogni swap (creazione, modifica, eliminazione, filtro) ricarica e ricostruisce la lista
  intera; il costo cresce linearmente con i reel.
- Qualunque raggruppamento o ordinamento lato server deve essere esplicito e fare i
  conti con i 5 visibili: un gruppo può spezzarsi al bordo della pagina.
- La scelta è quella che [[group-reels-by-place]] mette in discussione.
- L'assenza di `ORDER BY` è un effetto da tenere presente, non una decisione presa.

## Conferma dell'owner

Questo ADR è stato confermato con l'owner durante l'execute di
bootstrap-brownfield-02 il 2026-10-16.
