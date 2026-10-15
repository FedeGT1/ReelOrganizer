---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/adr
  - status/authoritative
connected files: ["current-system-design", "hub-satellite-location", "group-reels-by-place", "BOOT-brownfield"]
---

# ADR-001 — Un luogo, una `Location`

**Status:** accepted
**Decisori:** Owner
**Unità di contesto:** BOOT

## Contesto

I reel si consultano per luogo (lista, mappa, filtro per hub): serve un'identità stabile
del luogo a cui agganciare i reel. La decisione è visibile nel codice ma non era scritta.

## Decisione

Ogni luogo è una riga `Location` e un reel appartiene a un solo luogo tramite
`Reel.location_id` (obbligatorio). Reel dello stesso luogo condividono lo stesso
`location_id`. L'unicità del luogo è **per convenzione**, mantenuta dal flusso AI e
dall'audit tramite `resolve_place` (`app/location_matching.py`): match per nome
normalizzato; per sottostringa solo se il candidato è un hub; per prossimità (≤150 m con
somiglianza del nome ≥0,8); candidati entro 2 km sottoposti a conferma dell'utente.

Non è garantita da un vincolo del DB, né dal form manuale (`ui_create_reel` →
`_create_location` non passa da `resolve_place`). Anche i reel non sono unici per link:
`find_duplicate_reel` (`app/reel_links.py`) avvisa e chiede conferma, ma non vieta il
doppione; un link con più luoghi produce più righe `Reel`, una per luogo.

## Alternative considerate

- **Vincolo UNIQUE sul nome normalizzato per utente** — garantirebbe l'unicità, ma
  bloccherebbe omonimi legittimi, non coprirebbe il match per prossimità e richiederebbe
  una migrazione su dati reali (guardrail: schema solo additivo).
- **Relazione N:M reel↔luoghi** — un reel con più luoghi avrebbe una sola riga; scartata
  perché oggi il caso multi-luogo è già risolto con più righe `Reel` sullo stesso link e
  tutto il resto (mappa, filtri, export, ask) assume un solo luogo per reel.

## Conseguenze

- Raggruppare i reel per luogo è semplice: la chiave naturale è `location_id`
  (o l'hub, via [[hub-satellite-location]]).
- I duplicati di luogo creati dal form manuale o prima di `resolve_place` restano gruppi
  separati; si uniscono con merge in `/locations` (`_merge_locations`) o con l'audit in
  `/strumenti/audit`.
- Qualunque funzione che assuma unicità del luogo deve tollerare duplicati.
- Abilita [[group-reels-by-place]] senza modifiche allo schema.

## Conferma dell'owner

Questo ADR è stato confermato con l'owner durante l'execute di
bootstrap-brownfield-01 il 2026-10-16.
