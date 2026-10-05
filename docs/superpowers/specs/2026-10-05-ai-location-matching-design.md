# AI location matching & confirmation

## Context

Analyzing a markdown export of the live data with an external AI (Claude
Desktop) surfaced data-quality issues produced by the AI-driven reel import
flow (`app/routers/ai_categorize.py`, shared by the single-place and
multi-place/batch flows). The flow never asks the user to confirm a location
match — it always decides automatically — and today's heuristics get it
wrong in predictable ways:

1. **Hub resolution is exact-match-only.** `_find_hub_by_name` requires the
   AI's `near_hub` guess to match an existing hub's name exactly
   (case-insensitive). On any mismatch, `_resolve_location_and_create_reel`
   silently promotes the new place to a **brand-new top-level hub**
   (`is_hub = hub is None`). Real example: "Sanmachi Historic District,
   Takayama" became its own hub instead of a satellite of "Nagoya / Chubu".
2. **Satellite matching is unqualified bidirectional substring match.**
   `_find_matching_location` merges a new, more specific place into an
   existing broader one whenever one name contains the other as a substring
   — with no distance check and no similarity threshold. Real examples:
   "Pokémon Center Shibuya" collapsed into the existing generic "Shibuya";
   a Kamakura day-trip reel, the Kōtoku-in Daibutsu, and Hase-dera — three
   physically distinct places — all collapsed into one "Kamakura" location.
3. **The same substring check also misses true duplicates** when formatting
   differs. "Surugaya - Akihabara" and "Surugaya Akihabara (駿河屋秋葉原)" are
   the same real shop but neither string literally contains the other, so a
   second, duplicate `Location` row was created.

A fourth issue found in the same analysis (one reel ambiguously describing
what might be "Shisui Premium Outlets" or "Pokémon Store OUTLET Kisarazu")
is a content-ambiguity problem in the AI's place extraction, not a matching
heuristic — **out of scope** for this change.

## Goals

- Stop creating orphan top-level hubs as a silent fallback.
- Stop silently collapsing a specific new place into a broader existing one.
- Stop creating duplicate locations for the same real place when the name is
  formatted differently.
- When the right answer isn't clearly determinable automatically, **ask the
  user** instead of guessing — but add zero extra friction to the cases that
  are already unambiguous today.

## Non-goals

- Fixing the existing ~150-location backlog of bad data. The user is
  correcting that by hand (editing/merging via the existing "Gestisci hub"
  and reel-edit UI); this change only prevents new occurrences going
  forward.
- A general "merge two existing locations" admin tool.
- Solving AI place-name-extraction ambiguity (the Shisui/Pokémon Store case).
- Any database schema change. `Reel.location_id` already has no uniqueness
  constraint and multiple reels already share one location today (confirmed
  by the existing live data and by `tests/test_reels_api.py`); this design
  relies on that existing, unchanged behavior rather than introducing it.

## Design

### 1. Matching algorithm (`app/location_matching.py`, new module)

Pure logic, no FastAPI routes, so it's unit-testable in isolation from the
AI client and HTTP layer.

- `normalize_place_name(name: str) -> str`: lowercase, strip diacritics
  (`unicodedata`, same approach as `categories.slugify`), drop any
  parenthetical suffix (e.g. `(駿河屋秋葉原)`), collapse punctuation/whitespace
  to single spaces, trim. Run on both the incoming name and every existing
  location/hub name before any comparison below.
- `haversine_distance_m(lat1, lon1, lat2, lon2) -> float`: standard
  great-circle distance in meters.
- `resolve_place(session, place_name, near_hub, lat, lon) -> PlaceResolution`
  applies, for the **place** (hub or satellite) independently from the
  **hub** it would belong under if new:

  **Place resolution**, three tiers, in order:
  1. Normalized name exact match against any existing location (hub or
     satellite) → auto-match, that location's id, done.
  2. No exact match, but there exists an existing location where
     `SequenceMatcher(None, norm_a, norm_b).ratio() >= 0.8` **and**
     `haversine_distance_m(...) <= 150` → auto-match. Both conditions are
     required together specifically so two differently-named places that
     happen to share coordinates (e.g. two shops in the same building)
     never auto-merge — unrelated names fail the ratio gate regardless of
     distance.
  3. Otherwise: no auto-match. Build a ranked candidate list (existing
     locations within 2km, ordered by distance) for the confirmation UI.
     Default intent is always "this is a new place" — a nearby-but
     differently-named candidate is never pre-selected as a match.

  **Hub resolution** (only relevant when the place itself is new, tier 3
  above, or new via tier 1/2 under a different hub than before — needs to
  land under *some* hub, or become a brand-new hub):
  1. Normalized `near_hub` exact match against an existing hub name → use
     it automatically.
  2. No exact match → ambiguous. **No automatic promotion to a new hub.**
     The confirmation UI must show an explicit hub picker (existing hubs +
     "crea nuovo hub"), defaulting to nothing pre-selected.

- `PlaceResolution` carries: tier (`auto` / `ambiguous`) for the place,
  resolved location id when auto, ranked candidates when ambiguous; and
  separately, tier (`auto` / `ambiguous`) for the hub, resolved hub id when
  auto, and the full hub list for the picker when ambiguous.

### 2. Confirmation UI

- **Confident case** (place and hub both auto-resolved): no new control.
  Just an informational line under the AI's proposal, e.g. "Verrà salvato
  sotto: Shibuya" or "Nuovo posto satellite di Tokyo / Kanto". Same number
  of clicks as today.
- **Ambiguous case**: an added block with a `<select>` of ranked candidates
  (label = name + distance, e.g. "Kamakura (2.3km)") plus an "È un posto
  nuovo" option **preselected by default**, and — only if also creating a
  new place — a second `<select>` for the hub (existing hubs + "crea nuovo
  hub"), left blank/required if the hub tier is also ambiguous.
- One shared partial template renders this block; included identically by
  `partials/ai_chat.html` (single-place, posts to `/ui/ai/confirm`) and by
  each row of `partials/ai_chat_multi.html` (multi-place, posts to
  `/ui/ai/multi/confirm`).

### 3. Endpoint / function contract changes

- `_resolve_location_and_create_reel` loses its implicit "no match found →
  become a new hub" branch entirely. It now takes an explicit resolution
  from the caller: either an existing `location_id` to reuse as-is (no
  field on that `Location` row is ever modified — the new reel is simply a
  second `Reel` row pointing at it, with its own `note`/`types`/`link`,
  same as any place that already has multiple reels today), or
  "create a new satellite under hub X", or "create a new hub" — the last
  one reachable only by the user's explicit UI choice.
- `/ui/ai/confirm` and `/ui/ai/multi/confirm` form payloads replace the
  current implicit `matched_location_id` hidden field with the user's
  explicit resolution choice (existing-location id, or new+hub-id, or
  new+new-hub).
- `_find_matching_location` and `_find_hub_by_name` are removed, replaced by
  `resolve_place`.

### Testing

- Unit tests for `normalize_place_name`, `haversine_distance_m`, and
  `resolve_place`'s three place tiers + two hub tiers, covering: exact
  match, near-miss name + close distance (auto), close distance + unrelated
  name (must NOT auto-match), far distance regardless of name (ambiguous),
  hub exact match, hub no-match (must surface as ambiguous, never silently
  promoted to a new hub).
- Update `tests/test_ai_categorize.py`, `tests/test_ai_multi_categorize.py`,
  `tests/test_ai_ui.py` for the new confirm-form contract (explicit
  resolution fields instead of implicit `matched_location_id`), and add
  cases for the ambiguous-path UI (candidate `<select>` rendered, hub picker
  rendered, "crea nuovo hub" path).

## Impact surface

Files that reference the functions being replaced today:
`app/routers/ai_categorize.py`, `app/routers/ai_multi_categorize.py`,
`app/templates/partials/ai_chat.html`, `app/templates/partials/ai_chat_multi.html`,
`tests/test_ai_ui.py`, `tests/test_ai_categorize.py`,
`tests/test_ai_multi_categorize.py`. New file: `app/location_matching.py`
(+ its test file).
