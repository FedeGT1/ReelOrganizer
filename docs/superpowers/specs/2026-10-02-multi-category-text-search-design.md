# Multi-category filter + text search — Design

## Problem

Today the reel list and map support filtering by **one** category at a time
(`type` query param) and by one location. There's no way to search by free
text (note content or location name), and no way to combine more than one
category in a single filter.

## Goals

- Select multiple categories at once; a reel matches only if it has **all**
  selected categories (AND semantics).
- The multi-category filter affects both the map (pin dimming) and the reel
  list, consistent with today's single-category behavior.
- Add a live text search box that filters the reel list by note content or
  location name (case-insensitive substring match).
- All active filters (location, categories, text) combine with AND and are
  preserved independently — changing one never resets the others.

## Non-goals

- Text search does not affect the map.
- No OR semantics for categories (AND only, per product decision).
- No full-text/fuzzy search — simple case-insensitive substring match.

## Behavior

### Categories (multi-select, AND)

- Category chips (today rendered in `map.html`) become toggleable: clicking
  a chip adds/removes it from the active set rather than replacing it.
- "Tutti" clears all selected categories.
- A reel matches the category filter if it is tagged with *every* selected
  category (AND). Example: selecting "Cibo" + "Shopping" shows only reels
  tagged with both.
- This filter narrows both:
  - the map: a location is shown (not dimmed) only if it has at least one
    reel matching all selected categories — same mechanism as today's
    single-category dimming, generalized to a set.
  - the reel list: same AND matching.

### Location (unchanged)

- Clicking a map pin scopes the reel list to that location (+ its
  satellites). Location never filters the map itself.

### Text search (reel list only)

- A search input filters the reel list live, debounced ~400ms after the
  last keystroke.
- Matches case-insensitive substring against the reel's **note** or its
  location's **name**.
- Does not affect the map.

### Combination

- Location, categories, and text search combine with AND.
- Changing one filter preserves the current state of the others (matches
  existing behavior already implemented for location/category).

## Backend changes

### Shared helper

New helper, e.g. in `app/routers/categories.py` or a shared module:

```python
def reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None:
    """None means 'no filter'. Otherwise the AND-intersection of reel ids
    tagged with every type in `types`."""
    if not types:
        return None
    result: set[str] | None = None
    for t in types:
        ids = set(session.exec(select(ReelType.reel_id).where(ReelType.type == t)).all())
        result = ids if result is None else result & ids
    return result
```

Used by both `reels.py` and `map.py` to replace the current single-type
lookups (`locations_with_type` → `locations_with_types`).

### `app/routers/reels.py`

- `list_reels` (API) and `ui_list_reels` / `_reel_list_context`: `type`
  query param becomes `type: list[str] = Query([])` (repeatable
  `?type=a&type=b`); add `q: Optional[str] = None`.
- Category filtering uses `reel_ids_matching_types`.
- Text search: after the existing Python-side filtering (consistent with
  how type filtering already works — fetch then filter in Python, no need
  for SQL joins given personal-scale data), filter reels where
  `q.lower()` is a substring of `(reel.note or "").lower()` or the joined
  location's `name.lower()`.
- `_reel_list_context` signature becomes
  `(session, location_id=None, type_values: list[str] = [], q: Optional[str] = None)`.

### `app/routers/map.py`

- `locations_with_type` → `locations_with_types(session, type_values: list[str])`,
  built on `reel_ids_matching_types`.
- `visible_location_ids` and `render_map_html` take `type_values: list[str]`
  instead of a single `type_value`.
- `/ui/map` route: `type: list[str] = Query([])`.

### Routes affected

`GET /api/reels`, `GET /ui/reels`, `GET /ui/map` all move from a single
optional `type` to a repeatable `type` list; `/api/reels` and `/ui/reels`
additionally gain `q`.

## Frontend changes

### `app/static/js/map.js`

- Replace singular `currentType` with `currentTypes: string[]`.
- Add:
  - `window.toggleType(key)` — add/remove `key` from `currentTypes`, then
    call `refreshMap()` and `refreshReelList()`.
  - `window.clearTypes()` — empty `currentTypes`, then refresh both.
  - `window.refreshMap()` — builds `/ui/map?type=...&type=...` from
    `currentTypes` and swaps `#map-container` via `htmx.ajax`.
  - `window.refreshReelList()` — builds `/ui/reels?location_id=...&type=...&q=...`
    from `currentLocationId`, `currentTypes`, and the search input's current
    value, swaps `#reel-list`.
  - `window.clearLocationFilter()` — sets `currentLocationId = null`, calls
    `refreshReelList()`.
- The pin click handler and `map.html`'s inline `hx-on:click` URL-building
  are replaced by calls to these centralized functions (removing the
  duplicated ad-hoc URL construction).
- `initReelMap(...)` still receives the server-echoed active types (as a
  JSON array) on each map re-render, to keep `currentTypes` in sync with
  what the server just rendered (same pattern as today's single `active_type`).

### `app/templates/partials/map.html`

- Chips become `active`-toggling elements calling `window.toggleType('{{ key }}')`;
  active state driven by `{{ 'active' if key in active_types else '' }}`.
- "Tutti" chip calls `window.clearTypes()`.
- `initReelMap(..., {{ active_types | tojson }})`.

### `app/templates/index.html`

- Add a search `<input type="search" id="reel-search-input">` **above**
  `#reel-list`, outside the swap target, so typing never gets interrupted
  by a DOM replacement.
- A debounced (`~400ms`) `input` listener calls `window.refreshReelList()`.

### `app/templates/partials/reel_list.html`

- The location "Mostra tutti" banner link becomes a button calling
  `window.clearLocationFilter()` instead of a server-templated
  `hx-get` href that only knew about a single `active_type`.

## Testing

- `tests/test_reels_api.py` / new cases: multi-type AND filtering (2
  categories, reel with both matches, reel with only one doesn't); text
  search matching note, matching location name, no match; combined with
  location filter.
- `tests/test_map_api.py`: multi-type dimming logic (AND across categories).
- `tests/test_ui_fragments.py` / `tests/test_index_page.py`: new chip
  markup (toggle attributes), search input presence and wiring.

## Open questions / risks

None outstanding — all key behavior decisions were confirmed during
brainstorming (AND semantics, map+list scope for categories, list-only
scope for text search, live debounced search, note+location search fields).
