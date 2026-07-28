# Satellite Zoom Decluttering — Design

## Purpose

When zoomed out, a satellite location that sits very close to its hub (in screen pixels, even if a real geographic distance separates them) adds visual clutter without adding useful information — its marker and label crowd the hub's. Hide it until the user zooms in enough for it to read clearly on its own.

## Scope

**In scope:** hiding a satellite marker, its label, and its dashed connecting line to its hub when the satellite is within a pixel-distance threshold of that hub on screen, recomputed whenever the map's zoom level changes.

**Out of scope:**
- Satellite-vs-satellite decluttering (two satellites close to each other, not to their hub) — explicitly deferred, not part of this change.
- Any change to hide-empty/anchor-hub server-side filtering logic (`app/routers/map.py`) — a hidden satellite is a purely client-side visual state; the server's notion of which locations exist and which hubs are "anchors" is unaffected.
- Any change to click-to-filter behavior — clicking a hub still filters reels from all of its satellites regardless of whether they're currently visually hidden.

## Architecture

Purely client-side, in `app/static/js/map.js` — no backend or template changes.

While building markers in `initReelMap`'s existing loop, each satellite's marker, its larger invisible click-hit-area, and its connecting polyline (already computed together today) get collected into a small array alongside the satellite's own lat/lon and its parent hub's lat/lon.

After the loop (and again on every Leaflet `zoomend` event), a `updateSatelliteVisibility()` function walks that array and, for each satellite, converts both its own and its parent's lat/lon to on-screen pixel coordinates via Leaflet's `map.latLngToContainerPoint()`, then computes the straight-line pixel distance between them. If that distance is under a fixed **50px** threshold, the satellite's marker, hit-area, and connecting line are all removed from the map (`layer.remove()`); otherwise they're added back (`layer.addTo(map)`). Removing the marker automatically hides its bound tooltip label too, since the label is attached to the marker layer, not separately rendered.

Pixel distance (not real-world km, not a fixed zoom-level cutoff) is the right measure because it reacts to both zoom and actual geographic separation: a satellite genuinely close to its hub hides sooner (at a lower zoom-out level) than one that's farther away, which is what "too close" visually means — a fixed per-zoom-level cutoff would hide/show every satellite in lockstep regardless of how close each one actually is.

## Testing

No JS test infrastructure exists in this project for `map.js` (same as the rest of the Leaflet integration) — this is verified manually in a browser, not by an automated test. Given a real regression already slipped through in the previous mobile-responsive work specifically because no browser was available during that implementation, this change should be explicitly confirmed live (zoom in/out around a hub with a close satellite) before being considered done, not just reasoned about from the code.
