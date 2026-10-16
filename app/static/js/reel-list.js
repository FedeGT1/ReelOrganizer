const REEL_LIST_GROUP_SIZE = 5;

function updateLoadMoreLabel(button, remaining) {
    const noun = remaining === 1 ? "gruppo rimanente" : "gruppi rimanenti";
    button.textContent = `Carica altri (${remaining} ${noun})`;
}

function initReelPagination() {
    const container = document.getElementById("reel-list");
    if (!container) {
        return;
    }

    const existingButton = container.querySelector(".btn-load-more");
    if (existingButton) {
        existingButton.remove();
    }

    const groupsContainer = container.querySelector(".reel-groups");
    if (!groupsContainer) {
        return;
    }

    const groups = Array.from(groupsContainer.querySelectorAll(":scope > .reel-group"));
    groups.forEach((group, index) => {
        group.hidden = index >= REEL_LIST_GROUP_SIZE;
    });

    const hiddenCount = groups.length - REEL_LIST_GROUP_SIZE;
    if (hiddenCount <= 0) {
        return;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-load-more";
    updateLoadMoreLabel(button, hiddenCount);

    button.addEventListener("click", () => {
        const hiddenGroups = groups.filter((group) => group.hidden);
        hiddenGroups.slice(0, REEL_LIST_GROUP_SIZE).forEach((group) => {
            group.hidden = false;
        });

        const remaining = groups.filter((group) => group.hidden).length;
        if (remaining <= 0) {
            button.remove();
        } else {
            updateLoadMoreLabel(button, remaining);
        }
    });

    groupsContainer.insertAdjacentElement("afterend", button);
}

document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target && event.detail.target.id === "reel-list") {
        initReelPagination();
    }
});

document.addEventListener("htmx:oobAfterSwap", (event) => {
    if (event.detail.target && event.detail.target.id === "reel-list") {
        initReelPagination();
    }
});
