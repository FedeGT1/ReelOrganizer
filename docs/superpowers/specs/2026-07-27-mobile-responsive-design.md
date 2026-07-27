# Mobile-Responsive Redesign — Design

## Purpose

ReelOrganizer will be used mostly from a phone. The current page stacks map → AI chat → manual add form → reel list, all always visible — meaning every visit requires scrolling past the map and both "add a reel" affordances before even seeing the existing reel list, and the manual form's position on the page shifts unpredictably depending on how long the AI chat conversation above it has grown. Beyond that specific issue, several existing UI elements (buttons, checkboxes, forms) aren't sized or laid out with touch/narrow screens in mind.

## Scope

**In scope:**
- Restructuring the home page so the default view is just the map, an "add reel" entry point, and the reel list — no chat or form visible until requested.
- A full-screen (on mobile) popup for adding a reel, containing both existing add methods (AI chat, manual form) as two tabs.
- Auto-closing that popup and refreshing the map + reel list after a successful add, from either tab.
- A general responsive pass: touch-target sizing, long-URL overflow in the reel list, and the category-management add form stacking on narrow screens.

**Out of scope:**
- Making the app installable (PWA manifest/icon/home-screen launch) — explicitly deferred, not part of this pass.
- Any change to the AI categorization logic, the manual-add validation logic, or the map's filtering logic (hide-empty, type filters) — this is a presentation-layer restructure only.

## Architecture

### Home page restructure

`index.html` becomes, top to bottom: map section (unchanged) → a single **"+ Aggiungi reel"** button → the reel list section (unchanged apart from losing the manual form it currently embeds). Clicking the button opens a native HTML `<dialog>` element — chosen over a hand-rolled overlay because it gives us backdrop, Escape-to-close, and focus handling for free, needing only a few lines of vanilla JS to open/close it (consistent with the minimal-JS approach already used for the Leaflet map).

### The "Aggiungi reel" dialog

Two tabs inside the dialog, switched by a few lines of client-side JS (show/hide, no server round-trip): **"🤖 Assistente AI"** (default) and **"✏️ Manuale"**. Each tab's content is one of the two existing add flows, relocated rather than rebuilt:
- The AI tab is today's `partials/ai_chat.html`, loaded the same way it is today (`hx-trigger="load"`), just physically inside the dialog instead of inline on the page.
- The manual tab is the add-reel `<form>` that currently lives at the top of `partials/reel_list.html`, extracted into its own new partial (`partials/reel_add_form.html`) served by a new route, so it can be loaded independently inside the dialog while `reel_list.html` keeps only the filter banner and the `<ul>` of existing reels.

Splitting the form out of `reel_list.html` also cleans up that file's responsibility: it goes from "form + list" to just "list" (matching the file-structure principle of one clear responsibility per template).

### Closing and refreshing after a successful add

Neither `POST /ui/reels` (manual) nor `POST /ui/ai/confirm` (chat) change their existing response body or target — both already correctly update their own tab's content on success. The only addition: both responses set an `HX-Trigger: reel-saved` header on success (HTMX's built-in mechanism for a response to announce a custom DOM event, without changing what's swapped).

A small JS listener on `document.body` catches that `reel-saved` event and:
1. Closes the dialog.
2. Re-fetches `#reel-list` (`GET /ui/reels`) and `#map-container` (`GET /ui/map`) to reflect the new reel — both reset to their unfiltered view rather than trying to preserve whatever filter was active before opening the dialog (simpler, and a minor/acceptable tradeoff for how infrequently this matters).
3. Re-fetches both tab panels inside the dialog (`GET /ui/ai/panel` for the AI tab, `GET /ui/reels/add-form` for the manual tab) so they're back to a fresh/empty state the next time the dialog opens.

Step 3 matters because `hx-trigger="load"` only fires once, when the element is first processed by htmx at page load — reopening the `<dialog>` via `.showModal()` doesn't remove/reinsert the tab panels, so without an explicit re-fetch, reopening the popup after a save would show the AI tab's already-completed conversation (with a stale "Conferma e salva" already used) or the manual form's already-filled-in values, instead of a clean slate ready for the next reel.

This keeps the two success paths (reels.py, ai_categorize.py) almost untouched — one header addition each — rather than needing them to render each other's content via out-of-band swaps.

## Styling

- The dialog: full-screen on narrow viewports (`width/height: 100vw/100vh`, no border-radius) so the tabs and forms have comfortable room to type; on wider viewports (desktop), a centered card with a max-width instead of full-screen.
- General touch-target pass: the shared `button` rule (already used by every button in the app, including category list's Modifica/Elimina and the reel list's Elimina) gets a minimum comfortable height (~44px) — one shared rule, no per-page special-casing. The manual form's category checkboxes get the same treatment (larger clickable label area, not just the tiny checkbox square).
- Reel list links: long Instagram URLs currently can overflow horizontally on narrow screens. They get truncated with an ellipsis instead (the link matters for clicking, not for reading the full URL text).
- Category-management add form (name/emoji/color/submit): currently relies on default inline wrapping, which looks unaligned when it wraps. It stacks vertically (one field per row) always, which is simple and looks fine at any width rather than adding a narrow-only media query.

## Testing

- Backend: a test for the new `GET /ui/reels/add-form` route (renders the form with locations/taxonomy). Existing `POST /ui/reels` and `POST /ui/ai/confirm` tests get one addition each: assert the `HX-Trigger: reel-saved` header is present on a successful save.
- The dialog open/close and tab-switching behavior is pure client-side JS with no existing test infrastructure in this project (same as the Leaflet map code) — verified manually in a browser, not by an automated test.
