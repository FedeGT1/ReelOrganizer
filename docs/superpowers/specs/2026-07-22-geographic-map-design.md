# Design — Geographic map background + "nascondi vuoti" toggle

Status: approved by user, ready for implementation planning.

## 1. Goal

Two changes to the map view (`app/templates/partials/map.html`, `app/routers/map.py`):

1. Replace the current schematic railway-map SVG (dots floating on a blank
   background, connected by dashed lines) with a real geographic rendering:
   an accurate coastline of Japan, land/sea coloring, and hubs/satellites
   placed at their true latitude/longitude.
2. Add a toggle that hides locations with no reels (combinable with the
   existing type filter), so the map only shows places the user has actually
   saved something for.

## 2. Data model changes

### `Location` (`app/models.py`)

| field       | type            | notes |
|-------------|-----------------|-------|
| lat, lon    | float, nullable | **replaces** `x`, `y`. Real-world coordinates, required for both hubs and satellites (satellites no longer computed via radial layout). |
| map_inset   | bool, default False | True only for locations rendered in a fixed-position inset box instead of being projected onto the main map (Okinawa is the only current case — geographically too far south to share the main map's scale). |

`x`/`y` are removed — this app recreates its SQLite DB fresh on startup with
no migrations (README §Persistence), so this is a clean field swap, not an
additive change.

`app/layout.py` (`radial_positions`) is deleted; satellites get real
coordinates directly, so radial placement around the hub is no longer
needed.

### Seed data (`app/seed.py`)

Real coordinates for the existing 9 hubs and 10 satellites, e.g.:

| Location | lat | lon |
|---|---|---|
| Sapporo / Hokkaido | 43.0621 | 141.3544 |
| Sendai / Tohoku | 38.2682 | 140.8694 |
| Tokyo / Kanto | 35.6762 | 139.6503 |
| Nagoya / Chubu | 35.1815 | 136.9066 |
| Kyoto - Osaka / Kansai | 34.85 | 135.60 |
| Hiroshima / Chugoku | 34.3853 | 132.4553 |
| Matsuyama / Shikoku | 33.8392 | 132.7657 |
| Fukuoka / Kyushu | 33.5904 | 130.4017 |
| Okinawa | 26.2124 | 127.6809 | *(`map_inset=True`)* |

Satellites (examples — exact values finalized in implementation):
Nikko, Kamakura, Hakone, Kawagoe (Tokyo); Nara, Uji, Himeji (Kansai);
Miyajima (Hiroshima); Otaru (Sapporo); Dazaifu (Fukuoka) — each gets its
real lat/lon.

## 3. Projection

A new module `app/geo.py` owns the single lat/lon → SVG-coordinate mapping,
used both by the map endpoint and by the one-off coastline-generation
script, so points and coastline are always aligned:

```python
def project(lat: float, lon: float) -> tuple[float, float]: ...
```

Linear (equirectangular-style) scaling against a fixed bounding box covering
the main islands (Hokkaido through Kyushu/Shikoku). The bounding box and
padding are derived from the coastline dataset's real extent when it's
generated (§4), not guessed by hand, so the coastline always fills the
viewBox consistently and pins never fall outside it.

Okinawa (and anything else with `map_inset=True`) is *not* run through
`project()` for placement — it's drawn in a fixed-position dashed-border box
in a corner of the map (standard convention on real Japan maps), independent
of the main scale. Its lat/lon are still stored for data integrity, just not
used for on-map placement.

## 4. Coastline

Source: a public-domain geographic dataset (e.g. Natural Earth admin-0
country boundaries) — no attribution or license concerns, no runtime
dependency. A one-off script (`scripts/generate_coastline.py`) run during
implementation:

1. Extracts Japan's main-island polygons (Hokkaido, Honshu, Shikoku,
   Kyushu — Okinawa and remote small islands excluded, since Okinawa is
   inset and others are irrelevant to this app).
2. Projects every coordinate through `app.geo.project()`.
3. Simplifies the polygon(s) to a clean, stylized point count (this is a
   travel-planning aid, not a survey map).
4. Emits SVG path `d` strings, saved as a Python constant module
   `app/coastline.py` (`COASTLINE_PATHS: list[str]`) — no file parsing at
   runtime, just an importable constant.

`map.html` renders each path filled with the paper color (`--color-paper`)
and stroked with ink, over a sea-colored background rect (new palette
value, indigo-adjacent, added to `style.css`).

## 5. "Nascondi vuoti" toggle

### Behavior (confirmed with user)

- New toggle button alongside the existing type-filter chips.
- State carried via a `hide_empty` query param on `/ui/map`, following the
  same htmx pattern as the type chips (each control is a link/button whose
  `hx-get` encodes the *full* desired state — active type **and**
  hide_empty — so switching one doesn't reset the other).
- Combinable with the type filter: when a type is active, "empty" means
  "no reel of that type" (reusing `locations_with_type()`); otherwise it
  means "no reels at all" (`reel_count == 0`).
- A hub with no qualifying reels of its own but with at least one
  qualifying satellite stays visible, styled as an "anchor" (outline instead
  of solid fill) rather than fully hidden — it's structurally necessary to
  anchor the satellite's dashed line.
- Matching satellites/hubs that don't qualify are **removed from the
  markup** (not just dimmed) — unlike the type filter's existing `dimmed`
  CSS class, which fades non-matching points but keeps them present.

### Implementation sketch (`app/routers/map.py`)

```python
def visible_location_ids(session, locations, type_value, hide_empty) -> set[str] | None:
    """None means 'no filtering — show everything'."""
    if not hide_empty:
        return None
    if type_value:
        qualifying = locations_with_type(session, type_value)  # existing helper
    else:
        qualifying = {loc["id"] for loc in locations if loc["reel_count"] > 0}
    anchor_hubs = {
        loc["id"] for loc in locations
        if loc["is_hub"] and any(
            sat["parent_id"] == loc["id"] and sat["id"] in qualifying
            for sat in locations
        )
    }
    return qualifying | anchor_hubs
```

`ui_map` passes `visible_ids` (or `None`) plus `anchor_hubs` into the
template; `map.html` skips rendering any location (and its connecting line)
not in `visible_ids` when it's not `None`, and applies an `anchor` class to
hub circles in `anchor_hubs`.

## 6. API changes

| Endpoint | Change |
|---|---|
| `POST /api/locations` | `LocationCreate` payload: `x`/`y` → `lat`/`lon`, add optional `map_inset` (default `False`) |
| `GET /api/locations`, `GET /api/map` | responses expose `lat`/`lon` instead of `x`/`y` |
| `GET /ui/map` | add `hide_empty: bool = False` query param, combinable with existing `type` param |

## 7. Testing

- `app/geo.py::project()` — unit tests on known reference points: relative
  ordering preserved (a hub further north yields a smaller y; further east
  yields a larger x), output stays within the viewBox bounds.
- `visible_location_ids()` — unit tests for: no filter (`None`), hide_empty
  with no type (pure `reel_count`), hide_empty + type (per-type emptiness),
  and the anchor-hub case (empty hub, filled satellite → hub visible,
  anchor-styled).
- Existing tests referencing `x`/`y`, `radial_positions`, or the map
  fixtures (`tests/test_map_api.py`, `tests/test_ui_fragments.py`,
  `tests/test_layout.py`) need updating for the schema change;
  `test_layout.py` is deleted along with `app/layout.py`.

## 8. Out of scope

- Interactive pan/zoom or live map tiles (explicitly rejected in favor of a
  static, geographically accurate SVG — see brainstorming discussion).
- Real-scale placement of Okinawa (uses a fixed inset box instead).
- Satellites under an inset hub (no current seed data needs this; not
  designed for).
