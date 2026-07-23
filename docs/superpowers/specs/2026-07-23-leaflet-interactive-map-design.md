# Design — Interactive street/political map (Leaflet) + click-to-filter reels

Status: approved by user, ready for implementation planning.

## 1. Goal

Replace the current static geographic SVG map (real coastline drawn by hand,
fixed viewBox, no pan/zoom — see
`docs/superpowers/specs/2026-07-22-geographic-map-design.md`) with a real
interactive street/political map:

1. Real map tiles (OpenStreetMap via Leaflet), with native zoom and pan.
2. Locations rendered as Leaflet markers at their true lat/lon — no more
   custom SVG projection or hand-drawn coastline.
3. Clicking a marker filters the reel panel to that location's reels.
4. `lat`/`lon` become required when creating a location, closing the bug
   where a location created without coordinates silently rendered off the
   visible canvas.

This explicitly supersedes the "out of scope" note in the previous design
doc that rejected interactive pan/zoom — the user has now asked for it.

## 2. Library choice

**Leaflet + OpenStreetMap raster tiles**, loaded via CDN `<script>`/`<link>`
in `base.html`. No API key, no account, minimal setup — appropriate for a
personal local app. (Considered MapLibre GL for smoother vector rendering,
rejected: requires a tile-provider API key and more setup for no benefit
here.)

"Satellitare" in the original ask meant "a real interactive map", not
literal satellite imagery — confirmed with user: street/political tiles are
correct.

## 3. Removed: custom projection and coastline

Deleted entirely, since Leaflet handles real-world projection and rendering:

- `app/geo.py` (`project()`, `COASTLINE_PATHS` re-export, `VIEW_WIDTH`,
  `VIEW_HEIGHT`, `INSET_BOX`, `INSET_MARKER`, `INSET_LABEL_POS`)
- `app/coastline_data.py` (`JAPAN_COASTLINE_RINGS`)
- `scripts/generate_coastline.py`, if present, and any coastline-generation
  tooling
- `Location.map_inset` field (`app/models.py`) — Okinawa is no longer a
  special-cased inset box; it renders at its real lat/lon like everything
  else, reachable by panning/zooming south. Since this app recreates its
  SQLite DB fresh on startup with no migrations, this is a clean field
  removal, not an additive schema change.

`compute_map()` (`app/routers/map.py`) drops `x`, `y`, `map_inset` from its
per-location dict; keeps `id`, `name`, `is_hub`, `parent_id`, `lat`, `lon`,
`reel_count`.

## 4. Rendering

`ui_map` builds a list of location dicts already annotated for rendering
(visibility, anchor, dimmed — computed server-side, same source data as
today) and serializes it into the `partials/map.html` template as an
embedded JSON blob (`<script type="application/json" id="map-data">`), not
via Jinja loops building SVG/HTML directly. A `<script>` block reads that
JSON and builds the Leaflet layer:

- **Hub** → `L.circleMarker`, larger radius
- **Satellite** → `L.circleMarker`, smaller radius, plus `L.polyline`
  (dashed) to its parent hub's coordinates
- `anchor` and `dimmed` states applied via the `className` marker option,
  reusing existing CSS classes from `app/static/css/style.css`
- Only locations already filtered server-side (per the unchanged
  `visible_location_ids` logic) are included in the JSON blob — the same
  "removed from markup, not just dimmed" behavior as today for `hide_empty`

Each HTMX reload of `#map-container` (filter chip / hide_empty toggle click)
replaces the whole container, including the map `<div>`, so the init script
runs against a fresh DOM node each time — no explicit teardown of the
previous Leaflet instance needed. The view always resets to a fixed default
center/zoom on Japan after any filter change (no pan/zoom persistence across
reloads — simplest option, confirmed with user).

## 5. Click-to-filter reels

Closes a gap versus the original spec (`docs/japan-reel-organizer-specifiche.md`
§7: "click su una stazione che mostra il pannello con i reel di quella
tappa"), never wired up in any prior implementation.

- Each marker's click handler calls
  `htmx.ajax('GET', '/ui/reels?location_id=' + id, {target: '#reel-list', swap: 'innerHTML'})`
- `GET /ui/reels` (`app/routers/reels.py`, `ui_list_reels`) gains an optional
  `location_id` query param, filtering the same way `GET /api/reels` already
  does
- `partials/reel_list.html` shows a header ("Reel — {location name}") with a
  "✕ Mostra tutti" link back to unfiltered `/ui/reels` when a filter is
  active; no header when unfiltered (default/initial state)
- The "aggiungi reel" form's location `<select>` pre-selects the
  currently-filtered location as a convenience

## 6. Required lat/lon

`LocationCreate` (`app/routers/locations.py`): `lat: float` and `lon: float`
become required (drop `Optional`/`= None`). `POST /api/locations` now
returns `422` if either is missing — closes the bug class where a location
created without coordinates defaulted to `(0.0, 0.0)` and rendered off the
visible map.

Any already-existing rows with `lat`/`lon` still `NULL` (created before this
fix) are skipped defensively when building the marker JSON blob — they
won't render, but won't 500 either. No migration/backfill: user deletes and
recreates them (`DELETE /api/locations/{id}` already exists) with valid
coordinates.

## 7. Out of scope

- Literal satellite imagery tiles (confirmed: street/political tiles are
  what "satellitare" meant here)
- Geographic range validation on `lat`/`lon` (trust input — personal local
  app)
- Offline tile handling / fallback (default Leaflet behavior — grey tiles —
  is acceptable)
- Persisting pan/zoom state across filter-driven reloads

## 8. Testing

- `tests/test_geo.py` (5 tests, all against `project()`/`COASTLINE_PATHS`/
  inset box) is deleted along with `app/geo.py`.
- `tests/test_map_api.py`: the four `visible_location_ids` tests are
  unchanged (filtering logic itself doesn't change). Rewrite
  `test_map_returns_projected_coordinates_for_hub_and_satellite` — no more
  `x`/`y` in the response.
- New tests:
  - `POST /api/locations` without `lat`/`lon` → `422`
  - `GET /ui/reels?location_id=` filters to that location's reels only
  - `compute_map()` output has no `x`/`y`/`map_inset` keys
- Leaflet/JS behavior (zoom, pan, marker click, view reset) isn't
  pytest-testable — manual verification in-browser by the user.
