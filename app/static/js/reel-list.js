const REEL_LIST_GROUP_SIZE = 5;

function updateLoadMoreLabel(button, remaining) {
    button.textContent = `Carica altri (${remaining} rimanenti)`;
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

    const list = container.querySelector("ul.reel-list");
    if (!list) {
        return;
    }

    const items = Array.from(list.children);
    items.forEach((item, index) => {
        item.hidden = index >= REEL_LIST_GROUP_SIZE;
    });

    const hiddenCount = items.length - REEL_LIST_GROUP_SIZE;
    if (hiddenCount <= 0) {
        return;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-load-more";
    updateLoadMoreLabel(button, hiddenCount);

    button.addEventListener("click", () => {
        const hiddenItems = items.filter((item) => item.hidden);
        hiddenItems.slice(0, REEL_LIST_GROUP_SIZE).forEach((item) => {
            item.hidden = false;
        });

        const remaining = items.filter((item) => item.hidden).length;
        if (remaining <= 0) {
            button.remove();
        } else {
            updateLoadMoreLabel(button, remaining);
        }
    });

    list.insertAdjacentElement("afterend", button);
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
