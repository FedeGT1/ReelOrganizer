# Reel List Client-Side Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show reels in groups of 5 with a "Carica altri" button, purely client-side, without changing how the server loads or filters reels.

**Architecture:** A single new vanilla-JS file hides all `<li>` beyond the first 5 inside `ul.reel-list` and inserts a "load more" button after it. It re-runs on every htmx swap/out-of-band-swap of `#reel-list`, so every fresh server render (filter change, add, edit, delete) resets to showing the first 5. No backend route, query param, or Jinja template changes.

**Tech Stack:** Vanilla JS (no build step, no JS test runner — matches `map.js` / `reel-dialog.js`), htmx 1.9.12 events, plain CSS.

## Global Constraints

- No changes to `app/routers/reels.py`, `/api/reels`, `/ui/reels`, or any Jinja template under `app/templates/` (per spec "Non-goals"). Source: `docs/superpowers/specs/2026-10-01-reel-list-pagination-design.md`.
- Group size is 5 reels per reveal (fixed constant, not configurable). Source: spec Goal.
- No server-side pagination params (`limit`/`offset`). Source: spec Non-goals.
- UI copy is in Italian, matching the rest of the app (e.g. "Carica altri", "rimanenti"). Source: existing templates (`reel_list.html` uses "Mostra tutti", "Elimina", "Modifica").
- No new automated test suite is being introduced — this project has no JS test runner, and `map.js` / `reel-dialog.js` already ship untested. Verification is manual in-browser. Source: spec Testing/verification section.

---

### Task 1: Add `.btn-load-more` styling

**Files:**
- Modify: `app/static/css/style.css:238` (insert new rule immediately after the `.reel-list .btn-maps:hover` block, before the blank line that precedes `#ai-chat-messages` at line 240)

**Interfaces:**
- Produces: CSS class `.btn-load-more` that later tasks' JS will assign to the generated button element.

- [ ] **Step 1: Insert the CSS rule**

Open `app/static/css/style.css` and find this existing block:

```css
.reel-list .btn-maps:hover {
    background: var(--color-ink-medium);
    color: var(--color-paper);
}

#ai-chat-messages {
```

Insert a new rule between them so the file reads:

```css
.reel-list .btn-maps:hover {
    background: var(--color-ink-medium);
    color: var(--color-paper);
}

.btn-load-more {
    display: block;
    width: 100%;
    margin-top: 0.75rem;
    background: transparent;
    color: var(--color-ink);
    border: 1px solid var(--color-ink-medium);
}

.btn-load-more:hover {
    background: var(--color-ink-medium);
    color: var(--color-paper);
}

#ai-chat-messages {
```

- [ ] **Step 2: Visually sanity-check the rule**

Run: `grep -n "btn-load-more" app/static/css/style.css`
Expected: two matches (`.btn-load-more` and `.btn-load-more:hover`), both between `.reel-list .btn-maps:hover` and `#ai-chat-messages` in the file.

- [ ] **Step 3: Commit**

```bash
git add app/static/css/style.css
git commit -m "style: add .btn-load-more for reel list pagination"
```

---

### Task 2: Create `reel-list.js` with pagination logic

**Files:**
- Create: `app/static/js/reel-list.js`

**Interfaces:**
- Consumes: DOM structure produced by `app/templates/partials/reel_list.html` — a `#reel-list` container (already in `app/templates/index.html:25`) whose innerHTML, once rendered, contains `ul.reel-list > li` items. Also consumes htmx's `htmx:afterSwap` and `htmx:oobAfterSwap` events (fired by htmx 1.9.12, already loaded via `app/templates/base.html:14`).
- Produces: global function `initReelPagination()` (no arguments, no return value) that task 3's wiring does not need to call directly — it self-registers via the two `document.addEventListener` calls at the bottom of this file.

- [ ] **Step 1: Write the file**

Create `app/static/js/reel-list.js` with this exact content:

```js
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
```

- [ ] **Step 2: Check the file for syntax errors**

Run: `node --check app/static/js/reel-list.js`
Expected: no output, exit code 0. (If `node` is not installed, skip this step — it is a convenience check, not a build dependency.)

- [ ] **Step 3: Commit**

```bash
git add app/static/js/reel-list.js
git commit -m "feat: add client-side reel list pagination in groups of 5"
```

---

### Task 3: Wire `reel-list.js` into the page

**Files:**
- Modify: `app/templates/base.html:15-16`

**Interfaces:**
- Consumes: `app/static/js/reel-list.js` from Task 2 (served at `/static/js/reel-list.js`, same static mount other scripts use).

- [ ] **Step 1: Add the script tag**

In `app/templates/base.html`, find:

```html
    <script src="/static/js/map.js"></script>
    <script src="/static/js/reel-dialog.js"></script>
```

Replace with:

```html
    <script src="/static/js/map.js"></script>
    <script src="/static/js/reel-dialog.js"></script>
    <script src="/static/js/reel-list.js"></script>
```

- [ ] **Step 2: Verify the include**

Run: `grep -n "reel-list.js" app/templates/base.html`
Expected: `17:    <script src="/static/js/reel-list.js"></script>` (present after the `map.js` and `reel-dialog.js` script tags).

- [ ] **Step 3: Commit**

```bash
git add app/templates/base.html
git commit -m "feat: load reel-list.js on every page"
```

---

### Task 4: Manual verification in the browser

**Files:**
- None (no code changes — this task is a verification pass over Tasks 1-3).

**Interfaces:**
- Consumes: the running app with Tasks 1-3 applied.

- [ ] **Step 1: Start the app**

Run the project's normal local dev command (e.g. `uvicorn app.main:app --reload` from the repo root — check `README.md` if unsure of the exact invocation) and open the home page in a browser.

- [ ] **Step 2: Verify grouping on a filter with more than 5 reels**

Pick (or temporarily add, via the existing "+ Aggiungi reel" dialog) a location or category with more than 5 reels. Click that filter (map pin or category icon). Confirm:
- Only the first 5 reels are visible.
- A "Carica altri (N rimanenti)" button appears below the list, with N equal to the true remaining count.

- [ ] **Step 3: Verify incremental reveal**

Click "Carica altri" repeatedly. Confirm each click reveals exactly 5 more reels (or fewer on the last click if remainder < 5), the button's count updates correctly, and the button disappears once everything is visible.

- [ ] **Step 4: Verify reset on filter change**

With some groups revealed, click a different filter (another location/category) or "Mostra tutti". Confirm the view resets to showing only the first 5 of the new set, with a fresh "Carica altri" button if applicable.

- [ ] **Step 5: Verify reset on add/edit/delete**

Add a new reel, edit an existing one, and delete one, each time while more than 5 reels are in view. Confirm after each action the list still correctly shows first 5 + working "Carica altri" (these actions use `hx-swap-oob` or `hx-target="#reel-list"`, exercising both event listeners from Task 2).

- [ ] **Step 6: Verify no regression on small lists**

Filter down to a location/category with 5 or fewer reels. Confirm all are shown immediately and no "Carica altri" button appears.

- [ ] **Step 7: Report results**

No commit for this task. If any check in Steps 2-6 fails, note exactly which one and the observed vs. expected behavior before any further work proceeds.
