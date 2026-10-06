# Location audit & merge tool

## Context

Analyzing a markdown export of the live data (see
`docs/superpowers/specs/2026-10-05-ai-location-matching-design.md`) found
~150 existing `Location` rows with real data-quality problems: duplicate
locations for the same place saved under differently-formatted names
(e.g. "Surugaya - Akihabara" vs "Surugaya Akihabara (駿河屋秋葉原)"), and
specific places collapsed into a broader existing location by the old
matching heuristics. The 2026-10-05 work fixed the *forward-going* bug
(new AI-imported reels no longer get silently mismatched) but explicitly
left the existing backlog for manual cleanup (`docs/todo-next-step.md`).

This spec covers a tool to make that manual cleanup faster: scan all
existing locations for the same kind of anomaly the new matching logic
would catch on a fresh import, and let the user merge confirmed
duplicates directly from the UI.

## Goals

- Surface likely-duplicate and worth-reviewing location pairs across the
  whole existing dataset, reusing the already-tested `resolve_place`
  tiers rather than inventing new matching logic.
- Let the user merge a confirmed duplicate pair in one action (reassign
  reels, delete the redundant location) without leaving the audit page.
- Introduce a "Strumenti" section in the nav to group this and the other
  admin-ish pages that have accumulated as flat nav links.

## Non-goals

- Detecting anomalies with no coordinate signal (e.g. "Sanmachi Historic
  District, Takayama" wrongly standing alone as a hub far from its
  correct parent "Nagoya / Chubu") — this needs geographic domain
  knowledge the deterministic name+distance matching can't provide. Left
  for manual review, as today.
- Any AI-assisted detection pass. Deterministic only, consistent with the
  rest of this matching logic and the export feature's "no AI" precedent.
- Persisting "ignore this pair" decisions. A dismissed pair reappears on
  the next scan — acceptable for v1 given the dataset's size (~150
  locations); revisit if it proves annoying in practice.
- Any new nav grouping mechanism (dropdown, etc.) beyond a plain `/strumenti`
  list page.

## Design

### 1. Detection: reuse `resolve_place`, excluded against itself

`resolve_place` (`app/location_matching.py`) gains one new, optional,
backward-compatible parameter: `exclude_location_id: Optional[str] = None`.
When set, that location is filtered out of the candidate pool before any
tier check runs. Every existing call site (`ai_categorize.py`,
`ai_multi_categorize.py`) is unaffected — they never pass it, default
`None` preserves current behavior exactly.

The audit scan, for every existing `Location`, calls:
```
resolve_place(session, location.name, None, location.lat, location.lon,
              exclude_location_id=location.id)
```
and buckets the result:
- `place_tier == "auto"` → **duplicato quasi certo**: this location, run
  through the same tiers used for real-time import, would auto-match
  another existing one.
- `place_tier == "ambiguous"` with non-empty `place_candidates` →
  **da verificare**: nearby, but not name-similar enough to auto-match.

Pairs are deduplicated (A↔B found once regardless of which side the scan
visits first) using a `frozenset({a.id, b.id})` key, since the scan visits
every location and would otherwise find each real pair twice (once from
each side). Because `resolve_place`'s tier checks are directional (the
hub-containment rule only fires one way), the same pair can come back
`auto` from one side's scan and merely a `candidate` from the other's —
run the scan in two passes (first collect every `auto` pair over all
locations, then collect `candidate` pairs over all locations, skipping
any key already claimed by the first pass) so a pair never ends up listed
in both sections.

No persistence — the scan runs fully live on each page load/merge
(trivial cost at ~150 locations: one `resolve_place` call per location,
each an O(n) scan over short strings).

### 2. Merge operation

New function `_merge_locations(session, keep_id, drop_id)` in
`app/routers/locations.py` (alongside the existing `_create_location`/
`_update_location`/`_delete_location`, reusing the existing
`_has_children` helper):
- 404 if either id doesn't exist.
- 409 if `drop_id` has child locations (reuses the exact guard
  `_delete_location` already applies) — merging a location that is
  itself a parent would orphan its satellites, so it's blocked, directing
  the user to reassign/delete those first, same as today's delete flow.
- Otherwise: every `Reel` with `location_id == drop_id` gets reassigned
  to `keep_id` (commit), then `drop_id` itself is deleted (commit).
- `keep_id`'s own row (name, lat, lon, geocode_confidence) is **never**
  modified — same principle already established for the AI-import
  confirm flow: reusing a location only ever adds a reel to it.

Exposed as `POST /api/locations/{keep_id}/merge/{drop_id}` (JSON API, for
consistency with the rest of `locations.py`'s router) and wrapped by a
UI-facing endpoint in the new `app/routers/audit.py` that performs the
merge then re-renders the audit results (so a completed merge
immediately disappears from the list, live).

### 3. UI

**Nav (`app/templates/base.html`)**: replaces the flat links for
"Gestisci categorie", "Gestisci hub", "Esporta reel", "Cookie Instagram"
with a single "Strumenti" link. Nav becomes: Home, Strumenti, Chiedi
all'AI, Logout.

**`GET /strumenti`** (`strumenti.html`): a plain list of links — Gestisci
categorie, Gestisci hub, Esporta reel, Cookie Instagram, Audit pregresso
— no htmx needed, these are just links to pages that already exist.

**`GET /strumenti/audit`** (`audit.html`): a shell page with an "Esegui
scansione" button (`hx-get="/ui/audit/scan"`, not on page load — the scan
is user-triggered) targeting an empty results container.

**`GET /ui/audit/scan`**: runs the detection above, renders
`partials/audit_results.html` with two sections, "Duplicati quasi certi"
and "Da verificare" — each pair shows both locations' names, reel counts,
and (for the "da verificare" section) the distance between them, plus two
buttons, one per side, "Tieni questa" — clicking one merges the *other*
side into the clicked one.

**`POST /ui/audit/merge/{keep_id}/{drop_id}`**: calls `_merge_locations`,
guarded by `hx-confirm="..."` on the button (htmx's built-in confirm,
already used elsewhere in this app for the Instagram-cookies delete
button — no new JS). On the 409 (blocked merge), catches it and re-renders
the results with an error notice instead of letting a raw error response
break the htmx swap, following the same pattern `locations.py`'s own
`ui_update_location`/`ui_delete_location` already use for their error
cases.

### Testing

- `app/location_matching.py`: new tests for `exclude_location_id` — a
  location excluded from the pool is never returned as
  `place_location_id` or in `place_candidates`; existing callers/tests
  (which never pass it) remain green unmodified.
- `app/routers/locations.py`: `_merge_locations` — happy path (reels
  reassigned, drop location gone, keep location's own fields untouched);
  409 when `drop_id` has children; 404 for missing ids.
- `app/routers/audit.py`: scan groups and dedupes pairs correctly (a
  certain-duplicate pair appears once, not twice); a pair found via one
  location's scan matches what the other location's scan would also
  find; empty state when no anomalies exist.
- `/ui/audit/scan` and `/ui/audit/merge/...`: integration tests via the
  existing `client`/`session` fixtures — scan renders expected pairs;
  merge removes the pair from a subsequent scan and reassigns reels;
  merge against a location with children renders the error notice instead
  of a raw 409.

## Impact surface

Modify: `app/location_matching.py` (additive parameter),
`app/routers/locations.py` (new `_merge_locations` + endpoint),
`app/templates/base.html` (nav).
Create: `app/routers/audit.py`, `app/templates/strumenti.html`,
`app/templates/audit.html`, `app/templates/partials/audit_results.html`,
and their test files.
