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
