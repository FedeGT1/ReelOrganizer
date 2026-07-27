document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.getElementById("add-reel-dialog");
    if (!dialog) {
        return;
    }

    const openBtn = document.getElementById("open-add-reel");
    const closeBtn = document.getElementById("close-add-reel");
    const tabButtons = dialog.querySelectorAll(".tab-btn");
    const panels = dialog.querySelectorAll(".tab-panel");

    openBtn.addEventListener("click", () => dialog.showModal());
    closeBtn.addEventListener("click", () => dialog.close());

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            dialog.close();
        }
    });

    tabButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;
            tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
            panels.forEach((p) => {
                p.hidden = p.dataset.panel !== target;
            });
        });
    });

    document.body.addEventListener("reel-saved", () => {
        dialog.close();
    });
});
