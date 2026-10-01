# Reel list client-side pagination (groups of 5)

**Date:** 2026-10-01
**Status:** Approved

## Problem

The reel list (`#reel-list`) renders every matching reel in one `<ul>`, producing a long
page scroll once a user has more than a handful of reels. Filters (by location, from the
map, or by type, from the category bar) already work by calling the server
(`/ui/reels?location_id=...` / `/ui/reels?type=...`), which returns the *full* matching
set as rendered HTML — this "always fetch everything" behavior must not change.

## Goal

Keep loading the full result set from the server on every filter/add/edit/delete, exactly
as today, but reveal it to the user in groups of 5 via a "Carica altri" (load more) button,
purely on the client.

## Non-goals

- No change to `/api/reels` or `/ui/reels` query/response behavior.
- No change to how filters are triggered (map clicks, category clicks, "Mostra tutti").
- No server-side pagination, no `limit`/`offset` params.
- No persistence of "how many groups were revealed" across a full list re-render — every
  fresh render (new filter, add, edit, delete) starts back at the first group of 5, matching
  today's behavior where a filter change always restarts the view from the top.

## Design

### New file: `app/static/js/reel-list.js`

Exposes one entry point, `initReelPagination()`, which:

1. Finds `ul.reel-list` inside `#reel-list`. If absent (e.g. empty state), does nothing.
2. Removes any previously-inserted load-more button (defensive, in case of double-init).
3. Reads all direct `<li>` children. If there are 5 or fewer, does nothing further (no
   button shown).
4. Hides every `<li>` beyond the first 5 using the `hidden` attribute.
5. Inserts a `<button type="button" class="btn-load-more">` right after the `<ul>`, labeled
   with the remaining count, e.g. `Carica altri (7 rimanenti)`.
6. On click, reveals the next 5 hidden `<li>` elements (removes `hidden`), updates the
   button's remaining-count label, and removes the button once nothing is left hidden.

### Wiring into the app

`reel-list.js` is included in `base.html` alongside `map.js` / `reel-dialog.js`:

```html
<script src="/static/js/reel-list.js"></script>
```

It registers two document-level listeners once, at script load:

- `htmx:afterSwap` — if `event.detail.target` is `#reel-list` (or contains it), call
  `initReelPagination()`. This covers: initial page load (`hx-trigger="load"` on
  `#reel-list`), map/category filter clicks, "Mostra tutti", and delete (all of which swap
  `#reel-list`'s `innerHTML` directly).
- `htmx:oobAfterSwap` — if the swapped OOB element is `#reel-list`, call
  `initReelPagination()`. This covers add and edit reel, which return the updated list via
  `hx-swap-oob="innerHTML:#reel-list"`.

Both handlers call the same `initReelPagination()`, so every full re-render of the list
resets to showing the first 5 `<li>` elements, consistent with current filter behavior.

### Styling

Added to `app/static/css/style.css`, near the existing `.reel-list` rules:

- `.btn-load-more`: full-width button, visually consistent with the existing reel-list
  button styles (not styled as a destructive/edit action — a neutral, full-width "show
  more" affordance).
- No CSS needed for hiding `<li>` elements beyond the first 5 — the native `hidden`
  attribute handles that.

## Data flow

```
Server renders full matching list (unchanged)
        │
        ▼
#reel-list innerHTML replaced (or OOB-replaced)
        │
        ▼  htmx:afterSwap / htmx:oobAfterSwap fires
initReelPagination()
        │
        ├─ ≤5 <li> → nothing hidden, no button
        └─ >5 <li> → first 5 visible, rest `hidden`, "Carica altri" button shown
                 │
                 ▼ click
         reveal next 5, update/remove button
```

## Testing / verification

This is pure client-side DOM behavior with no backend change, consistent with the existing
unscripted-test status of `map.js` and `reel-dialog.js` (the project has no JS test runner).
No new Python tests are needed — existing `tests/test_ui_fragments.py` assertions on the
rendered HTML fragments are unaffected since the server-rendered markup for `reel_list.html`
itself does not change.

Verification is manual, in a browser, by the user:

- Seed/view a location or category with more than 5 reels; confirm only 5 show initially
  and a "Carica altri" button appears with the correct remaining count.
- Click "Carica altri" repeatedly; confirm groups of 5 reveal until the button disappears
  with none left hidden.
- Switch filters (map pin, category icon, "Mostra tutti"); confirm the view resets to the
  first 5 of the new filtered set.
- Add a reel, edit a reel, delete a reel; confirm the list still resets to the first 5 and
  pagination still works afterward.
- Lists with 5 or fewer reels show no button and no hidden items (no behavior change from
  today).
