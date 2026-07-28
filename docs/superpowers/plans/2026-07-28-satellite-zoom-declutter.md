# Satellite Zoom Decluttering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide a satellite's marker, label, and connecting line to its hub when they're within 50px of each other on screen, recomputed on every zoom change.

**Architecture:** Pure client-side change in `app/static/js/map.js`. Satellites are collected into a small array during marker construction; a `updateSatelliteVisibility()` function walks it on load and on Leaflet's `zoomend` event, hiding/showing each satellite's three layers (marker, click hit-area, connecting line) together based on pixel distance to its parent hub.

**Tech Stack:** Vanilla JS, Leaflet (already loaded).

## Global Constraints

- No backend or template changes — this is entirely within `app/static/js/map.js`.
- Threshold is a fixed **50px** pixel distance (not real-world km, not a zoom-level cutoff), per `docs/superpowers/specs/2026-07-28-satellite-zoom-declutter-design.md`.
- Only satellite-vs-own-hub distance is considered — satellite-vs-satellite decluttering is explicitly out of scope.
- Hiding a satellite is purely visual (Leaflet layer add/remove) — no change to click-to-filter behavior, hide-empty logic, or anchor-hub computation.
- No JS test infrastructure exists for this file — verification is manual, in a real browser. Given a real regression already shipped once in this project specifically because no browser was available during implementation, this must be explicitly confirmed live (not just reasoned about) before being considered done.

---

### Task 1: Hide close satellites on zoom

**Files:**
- Modify: `app/static/js/map.js`

**Interfaces:**
- None external — this is a self-contained change to `initReelMap`, the only function in this file that other code calls (from `partials/map.html`'s inline `<script>`).

- [ ] **Step 1: Replace the full contents of `app/static/js/map.js`**

```javascript
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

const SATELLITE_HIDE_THRESHOLD_PX = 50;

function initReelMap(containerId, dataId) {
    const dataEl = document.getElementById(dataId);
    const locations = JSON.parse(dataEl.textContent);

    const map = L.map(containerId).setView([36.5, 138.0], 5);

    L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        {
            attribution: "&copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ",
            maxZoom: 18,
        }
    ).addTo(map);

    const satelliteEntries = [];

    locations.forEach((loc) => {
        const classes = ["station", loc.is_hub ? "hub" : "satellite"];
        if (loc.anchor) classes.push("anchor");
        if (loc.dimmed) classes.push("dimmed");

        const marker = L.circleMarker([loc.lat, loc.lon], {
            radius: loc.is_hub ? 10 : 6,
            className: classes.join(" "),
        }).addTo(map);

        marker.bindTooltip(escapeHtml(loc.name), {
            permanent: true,
            direction: "top",
            className: "station-label",
        });

        const hitArea = L.circleMarker([loc.lat, loc.lon], {
            radius: loc.is_hub ? 22 : 16,
            opacity: 0,
            fillOpacity: 0,
        }).addTo(map);

        hitArea.on("click", () => {
            htmx.ajax("GET", "/ui/reels?location_id=" + loc.id, {
                target: "#reel-list",
                swap: "innerHTML",
            });
        });

        if (!loc.is_hub && loc.parent_lat !== null && loc.parent_lon !== null) {
            const line = L.polyline(
                [
                    [loc.parent_lat, loc.parent_lon],
                    [loc.lat, loc.lon],
                ],
                { className: "satellite-line" }
            ).addTo(map);

            satelliteEntries.push({
                layers: [marker, hitArea, line],
                ownLatLng: [loc.lat, loc.lon],
                parentLatLng: [loc.parent_lat, loc.parent_lon],
                visible: true,
            });
        }
    });

    function updateSatelliteVisibility() {
        satelliteEntries.forEach((entry) => {
            const ownPoint = map.latLngToContainerPoint(entry.ownLatLng);
            const parentPoint = map.latLngToContainerPoint(entry.parentLatLng);
            const dx = ownPoint.x - parentPoint.x;
            const dy = ownPoint.y - parentPoint.y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            const shouldBeVisible = distance >= SATELLITE_HIDE_THRESHOLD_PX;

            if (shouldBeVisible !== entry.visible) {
                entry.layers.forEach((layer) => {
                    if (shouldBeVisible) {
                        layer.addTo(map);
                    } else {
                        layer.remove();
                    }
                });
                entry.visible = shouldBeVisible;
            }
        });
    }

    updateSatelliteVisibility();
    map.on("zoomend", updateSatelliteVisibility);
}
```

- [ ] **Step 2: Run the full test suite (sanity check — no Python code changed)**

Run: `uv run pytest -q`
Expected: all PASS, unchanged from before this change (this file has no automated coverage).

- [ ] **Step 3: Manual browser verification — do not skip**

Start the dev server, log in, and on the home page:
- Zoom out to the default/national view. A hub with a satellite that's geographically very close to it (e.g. a hub and a satellite only a few km apart) should show only the hub — the satellite's marker, label, and dashed line should not be visible.
- Zoom in on that hub. Once the satellite is far enough from the hub in screen pixels, its marker, label, and line should appear.
- Zoom back out — it should hide again.
- Confirm a satellite that's geographically far from its hub (e.g. Nikko under Tokyo/Kanto) stays visible even at the default zoomed-out view, since it's never within 50px of its hub on screen.
- Confirm clicking a hub still filters the reel list to include a currently-hidden satellite's reels (the hide is visual only).

Report back whether this worked as expected — this step has no automated coverage, so it's the only verification this change gets before being considered done.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/map.js
git commit -m "feat: hide satellites too close to their hub at the current zoom level"
```
