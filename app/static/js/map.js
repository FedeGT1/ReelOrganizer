function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

const SATELLITE_HIDE_THRESHOLD_PX = 50;

let currentLocationId = null;
let currentTypes = [];

function buildTypeQuery(types) {
    return types.map((t) => "type=" + encodeURIComponent(t)).join("&");
}

function refreshMap() {
    const typeQuery = buildTypeQuery(currentTypes);
    const url = "/ui/map" + (typeQuery ? "?" + typeQuery : "");
    htmx.ajax("GET", url, { target: "#map-container", swap: "innerHTML" });
}

function refreshReelList() {
    const params = [];
    if (currentLocationId) {
        params.push("location_id=" + encodeURIComponent(currentLocationId));
    }
    const typeQuery = buildTypeQuery(currentTypes);
    if (typeQuery) {
        params.push(typeQuery);
    }
    const searchInput = document.getElementById("reel-search-input");
    const q = searchInput ? searchInput.value.trim() : "";
    if (q) {
        params.push("q=" + encodeURIComponent(q));
    }
    const url = "/ui/reels" + (params.length ? "?" + params.join("&") : "");
    htmx.ajax("GET", url, { target: "#reel-list", swap: "innerHTML" });
}

window.toggleType = (key) => {
    const index = currentTypes.indexOf(key);
    if (index === -1) {
        currentTypes.push(key);
    } else {
        currentTypes.splice(index, 1);
    }
    refreshMap();
    refreshReelList();
};

window.clearTypes = () => {
    currentTypes = [];
    refreshMap();
    refreshReelList();
};

window.clearLocationFilter = () => {
    currentLocationId = null;
    refreshReelList();
};

function initReelMap(containerId, dataId, typeValues) {
    currentTypes = typeValues || [];

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
            currentLocationId = loc.id;
            refreshReelList();
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

let searchDebounceTimer = null;

window.handleSearchInput = () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        refreshReelList();
    }, 400);
};
