# Location Management — Design

## Purpose

Locations (hub cities and their satellite day-trips) are currently seeded once and otherwise fixed — the manual add-reel form's dropdown only ever shows that original list. The user wants to add, edit, and delete locations from the UI, the same way categories already work.

## Scope

**In scope:**
- A new dedicated page, `/locations` ("Gestisci città"), following the exact structural pattern already established by `/categories`: a list with inline edit/delete, plus an add form below it.
- The missing update capability on the backend (`app/routers/locations.py` already has create/list/delete; no update endpoint exists yet).
- Explicit hub-vs-satellite choice in the add/edit form, with a parent-hub dropdown shown for satellites.
- Manual numeric lat/lon input (consistent with the existing "the map is schematic, approximate is fine" decision from the original map design).
- Reusing the existing hierarchy-integrity constraint (a location with children can't be deleted) for edits too: a location with satellites or reels attached can't be turned into a satellite itself, with a clear inline error instead of a silently-failed request.

**Out of scope:**
- Any change to how the manual add-reel form or the AI chat flow choose/display locations — they keep reading whatever locations exist at the time they're loaded, same as they already do for categories.
- A map-based coordinate picker — manual number inputs only, per the earlier map design decision.
- Bulk reassignment tooling for a hub's satellites before deleting/converting it — the user reassigns or deletes them individually first, same as today.

## Architecture

### Backend

`app/routers/locations.py` gains an update path, following the same helper-function pattern `app/routers/categories.py` already uses (a private `_update_location` function consumed by both the JSON API and the new UI routes):

- `PUT /api/locations/{location_id}` — accepts the same fields as creation (`name`, `is_hub`, `parent_id`, `lat`, `lon`). If the location currently has child locations (or is being turned into a satellite while children exist), reject with a 409, mirroring the existing delete constraint exactly. When `is_hub` is `true`, `parent_id` is ignored and forced to `None` server-side — hubs don't have parents in this schema.
- A new `ui_router` (prefix `/ui/locations`) with the same five-route shape `categories.py` already has: `GET` (list), `POST` (create), `GET /{id}/edit` (inline edit form), `POST /{id}` (update), `DELETE /{id}` (delete).

One deliberate difference from the categories UI routes: `DELETE /ui/locations/{id}` catches the "still has children" conflict itself and re-renders the list with a visible inline error message, rather than letting the request fail silently (HTMX doesn't swap content on non-2xx responses, so an unhandled conflict would otherwise just do nothing with no explanation — categories never needed this because they have no hierarchy to conflict over).

### Frontend

New templates mirroring the categories ones file-for-file:
- `app/templates/locations.html` — page shell (same shape as `categories.html`).
- `app/templates/partials/location_list.html` — each row shows the name, a hub/satellite badge (and parent hub name if it's a satellite), lat/lon, and Modifica/Elimina buttons (styled like the already-fixed category list rows: compact buttons, chip-style name badge, aligned in a row).
- `app/templates/partials/location_edit_row.html` — inline edit form replacing a row, same interaction pattern as `category_edit_row.html`.

The add/edit form: a text input for the name, two radio options ("È un hub" / "È un satellite di:" with a `<select>` of existing hubs next to the second option), and two numeric (`type="number" step="any"`) inputs for lat/lon. No JavaScript is added to show/hide the parent dropdown based on the radio choice — both are always visible, and the backend simply ignores `parent_id` when `is_hub` is true. This keeps the form free of new client-side logic for a low-frequency admin action.

`app/templates/base.html` gains a fourth nav button, "Gestisci città", next to the existing three. `app/main.py` registers the new routers and a `GET /locations` page route, matching the `/categories` pattern exactly.

## Testing

Same shape as the existing categories test suite: `tests/test_locations_api.py` gains update-endpoint tests (success, 409-on-children, ignoring `parent_id` for hubs); a new `tests/test_locations_ui.py` covers the five UI routes, including the child-conflict-shows-inline-error case specifically (the one behavior with no categories precedent to copy).
