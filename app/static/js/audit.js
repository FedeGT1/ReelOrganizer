function refreshAuditResults() {
    htmx.ajax("GET", "/ui/audit/scan", { target: "#audit-results", swap: "innerHTML" });
}

document.body.addEventListener("reel-saved", () => {
    if (document.getElementById("audit-results")) {
        refreshAuditResults();
    }
});
