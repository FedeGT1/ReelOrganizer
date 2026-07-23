function initReelMap(containerId, dataId) {
    const dataEl = document.getElementById(dataId);
    const locations = JSON.parse(dataEl.textContent);

    const map = L.map(containerId).setView([36.5, 138.0], 5);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 18,
    }).addTo(map);

    locations.forEach((loc) => {
        const classes = ["station", loc.is_hub ? "hub" : "satellite"];
        if (loc.anchor) classes.push("anchor");
        if (loc.dimmed) classes.push("dimmed");

        const marker = L.circleMarker([loc.lat, loc.lon], {
            radius: loc.is_hub ? 10 : 6,
            className: classes.join(" "),
        }).addTo(map);

        marker.bindTooltip(loc.name, {
            permanent: true,
            direction: "top",
            className: "station-label",
        });

        marker.on("click", () => {
            htmx.ajax("GET", "/ui/reels?location_id=" + loc.id, {
                target: "#reel-list",
                swap: "innerHTML",
            });
        });

        if (!loc.is_hub && loc.parent_lat !== null && loc.parent_lon !== null) {
            L.polyline(
                [
                    [loc.parent_lat, loc.parent_lon],
                    [loc.lat, loc.lon],
                ],
                { className: "satellite-line" }
            ).addTo(map);
        }
    });
}
