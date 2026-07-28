# Reel Editing — Design

## Goal

Reels can currently only be created or deleted — there is no way to fix a wrong category, correct a note, or move a reel to a different location once it's saved. This adds full edit support (link, note, location, categories) for existing reels, reusing the existing add-reel popup instead of introducing new UI chrome.

## Architecture

The app already has one popup dialog (`#add-reel-dialog` in `app/templates/index.html`) with two tabs — "Assistente AI" and "Manuale" — opened via the "+ Aggiungi reel" button. The "Manuale" tab's content (`#reel-add-form-panel`) is a single persistent DOM node that HTMX loads once on page load with the blank add form (`GET /ui/reels/add-form`).

Editing reuses this exact dialog and panel: clicking "Modifica" on a reel replaces `#reel-add-form-panel`'s content with a new, pre-filled edit form (instead of the blank add form), forces the dialog open on the "Manuale" tab, and lets the user save or cancel. No changes are needed to `app/static/js/reel-dialog.js` — the existing open/close/tab-switch/`reel-saved`-closes-dialog logic all keeps working unchanged, since editing is just "different content loaded into the same panel."

## Components

**`app/templates/partials/reel_edit_form.html`** (new) — mirrors `reel_add_form.html`'s fields (link, location dropdown, note, category checkboxes) but pre-filled with the reel's current values, posts via `hx-put` to `/ui/reels/{reel_id}` instead of `hx-post` to `/ui/reels`, and adds an "Annulla" button.

**`GET /ui/reels/{reel_id}/edit-form`** (new, in `app/routers/reels.py`) — 404 if the reel doesn't exist; otherwise renders `reel_edit_form.html` with the reel's current link/note/location_id, the full location list and taxonomy (same context as the add form), and the reel's currently-assigned category keys (so the matching checkboxes render checked).

**`PUT /ui/reels/{reel_id}`** (new) — validates the link the same way `POST /ui/reels` does (`_is_safe_link`, 400 on failure), updates the reel's `link`/`location_id`/`note`, replaces its `ReelType` rows with the submitted set, then responds with:
- the blank add-form markup as the direct response body (so `#reel-add-form-panel`, which is the form's own `hx-target`, resets back to normal — the exact mechanism `ui_ai_confirm` already uses today to reset the same panel after an AI-driven save),
- an out-of-band fragment refreshing `#reel-list`,
- an out-of-band fragment refreshing `#map-container` (in case the location changed),
- an `HX-Trigger: reel-saved` response header, which the existing dialog JS already listens for to auto-close the popup.

This is the same response-construction pattern `ui_ai_confirm` already uses in `app/routers/ai_categorize.py` — no new client-side mechanism.

**`PUT /api/reels/{reel_id}`** (new) — same update logic exposed as a plain JSON endpoint (`ReelCreate`-shaped payload), for parity with the existing full CRUD API on locations (`PUT /api/locations/{id}`) and so the update logic has a plain, dependency-free test surface independent of HTMX rendering.

**`app/templates/partials/reel_list.html`** — each `<li>` gets a new "Modifica" button, positioned before the existing delete button:
```html
<button hx-get="/ui/reels/{{ reel.id }}/edit-form" hx-target="#reel-add-form-panel" hx-swap="innerHTML"
        onclick="document.getElementById('add-reel-dialog').showModal(); document.querySelector('.tab-btn[data-tab=manual]').click();"
        aria-label="Modifica">✏️</button>
```
The `hx-get` fetches the pre-filled edit form into the shared panel; the plain `onclick` opens the dialog and force-switches to the "Manuale" tab (reusing the existing tab-button's own click handler rather than duplicating its logic) — both fire on the same click, matching the project's existing convention of combining an `hx-*` attribute with a plain inline handler for cross-cutting UI actions (see the category filter chips in `map.html`).

**Edit form's "Annulla" button** — resets the shared panel back to the blank add form and closes the dialog, so the popup never shows stale edit data the next time it's opened for a different purpose:
```html
<button type="button" hx-get="/ui/reels/add-form" hx-target="#reel-add-form-panel" hx-swap="innerHTML"
        onclick="document.getElementById('add-reel-dialog').close()">Annulla</button>
```

## Data Flow

1. User clicks "Modifica" on a reel in the list.
2. The dialog opens on the "Manuale" tab; `#reel-add-form-panel` is replaced with the edit form, pre-filled with that reel's current data.
3. User edits link/note/città/categorie and clicks "Salva" (the form's own submit button, unchanged styling/wording from the add form).
4. `PUT /ui/reels/{reel_id}` updates the DB, returns the blank add-form (resetting the panel) plus OOB-refreshed reel list and map, plus the `reel-saved` trigger.
5. The dialog auto-closes (existing JS), the reel list and map reflect the change immediately.
6. If the user clicks "Annulla" instead, the panel resets to the blank add form and the dialog closes — nothing is persisted.

## Error Handling

- Invalid/unsafe link on save → 400, same `_is_safe_link` check `POST /ui/reels` already applies.
- Editing a reel that no longer exists (e.g. deleted in another tab) → 404 on both `GET .../edit-form` and `PUT /ui/reels/{reel_id}`, matching the existing 404 behavior on `DELETE /ui/reels/{reel_id}` for a missing reel.
- Submitting category keys that aren't valid taxonomy entries is silently filtered out, exactly like `POST /ui/reels` already does today (`if type_value in valid_type_keys`).

## Testing

- `tests/test_reels_api.py`: `PUT /api/reels/{id}` updates link/location_id/note/types and returns them; updating a missing reel returns 404; submitting an unsafe link returns 400.
- `tests/test_ui_fragments.py` (or wherever `test_ui_list_reels`/`ui_create_reel` tests currently live): `GET /ui/reels/{id}/edit-form` renders the form pre-filled with the reel's current link/note and with its current category checkboxes checked; a missing reel returns 404.
- UI save test: `PUT /ui/reels/{id}` with new field values returns 200, the response contains the OOB `#reel-list` fragment reflecting the change, the OOB `#map-container` fragment, and the `HX-Trigger: reel-saved` header (mirroring the existing `test_ui_ai_confirm_resets_panel_and_updates_reel_list`-style assertions).
- UI cancel path needs no server-side test — "Annulla" only triggers the existing, already-tested `GET /ui/reels/add-form` route; no new server behavior to cover there.
