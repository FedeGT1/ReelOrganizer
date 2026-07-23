# Design — AI chat UI for reel categorization

Status: approved by user, ready for implementation planning.

## 1. Goal

Wire a UI onto the already-existing `/api/ai/categorize` backend (built per
`docs/superpowers/specs/2026-07-21-japan-reel-organizer-design.md` §5.3) so
the user can paste a reel link + caption/description, have the AI propose a
place + type(s), answer clarifying questions when the AI lacks information,
and save the reel (creating a new location if needed) — all without ever
touching the manual add-reel form. This closes the last unimplemented piece
of the original design's suggested order (§9 step 5, UI half).

## 2. What already exists (unchanged)

- `POST /api/ai/categorize` (`app/routers/ai_categorize.py`): session-based
  (`AiSession`/`AiMessage`), calls `ai_client.categorize()` with full message
  history, filters returned `types` against `VALID_TYPES`, matches an
  existing `Location` by case-insensitive substring on `place_name`.
- `app/ai/client.py`, `app/ai/prompts.py`: Anthropic call with
  `output_config.format` JSON-schema enforcement.

No changes to the session/message persistence model or the matching logic.

## 3. Schema and prompt changes

`RESPONSE_SCHEMA` (`app/ai/prompts.py`) gains two nullable numeric fields:

```json
{
  "lat": "number | null",
  "lon": "number | null"
}
```

added to `properties` and `required` (schema stays `additionalProperties: false`,
consistent with the existing fields).

`build_system_prompt` gains an instruction: if the proposed place doesn't
match an existing hub/satellite, estimate `lat`/`lon` (decimal degrees) for
its real-world position in Japan; if it can't be estimated with reasonable
confidence, leave both `null` and use `question` to ask for the nearest
city/area instead. If the place matches an existing location, `lat`/`lon`
can be left `null` (they're ignored in that case — see §5).

## 4. Server-side safety net for missing coordinates

Per the user's decision, there is no manual lat/lon entry UI — corrections
happen only by replying in the chat. So the flow must never reach a
"confirm" state for a *new* location without usable coordinates.

In the shared turn-processing logic (see §6), after getting the model's
result and computing `matched_location_id`:

```
if matched_location_id is None and result["question"] is None and (
    result.get("lat") is None or result.get("lon") is None
):
    result["question"] = (
        "Non riesco a stimare le coordinate di questo posto: "
        "qual e' la citta' o zona piu' vicina?"
    )
```

This overridden `result` is what gets persisted as the assistant `AiMessage`
and shown to the user — so an under-specified new location always turns
into another chat turn, never a broken "confirm" button.

## 5. Save/confirm logic (new)

Given the latest proposal for a session, on confirm:

- If `matched_location_id` is set → reuse that location as-is (ignore any
  `lat`/`lon` in the proposal).
- Else, resolve `near_hub` (a name string) against existing hubs
  (case-insensitive exact match on `Location.name` where `is_hub == True`):
  - Match found → create a **satellite**: `Location(name=place_name,
    is_hub=False, parent_id=<hub.id>, lat=lat, lon=lon)`.
  - No match (including `near_hub` empty/null, or a hallucinated name that
    doesn't correspond to any existing hub — treated the same way, a known
    limitation, not blocking) → create a new **hub**: `Location(name=place_name,
    is_hub=True, parent_id=None, lat=lat, lon=lon)`.
- Either way, then create the `Reel` (`link`, `location_id`, `note`) and its
  `ReelType` rows (filtered against `VALID_TYPES`, same as the manual form).
- `link` is re-validated with the existing `_is_safe_link` check (same rule
  as the manual form) — the chat flow doesn't get a lighter security bar.

## 6. New routes (`app/routers/ai_categorize.py`)

The existing turn logic (get-or-create `AiSession`, append user `AiMessage`,
call `ai_client.categorize`, filter types, apply the §4 safety net, append
assistant `AiMessage`, compute `matched_location_id`) is extracted into a
private helper shared by the JSON endpoint and the new UI endpoints — no
behavior change to `POST /api/ai/categorize` itself.

New `ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/ui/ai/panel` | Empty/initial chat panel (loaded via `hx-get` on page load, same pattern as `/ui/map` and `/ui/reels`). |
| POST | `/ui/ai/message` | Advance the conversation one turn and re-render the full panel. |
| POST | `/ui/ai/confirm` | Execute §5 and reset the panel; also refreshes the reel list. |

**`POST /ui/ai/message`** form fields: `session_id` (optional, hidden,
empty string on the first turn), `link` (only required/shown as a visible
input on the first turn; carried as a hidden field on every turn after),
`message` (the visible text field — description on turn 1, free-form reply
on later turns). First turn combines `link` + `message` into one user
`AiMessage` (e.g. `"Link: {link}\nDescrizione: {message}"`); the link itself
is validated with `_is_safe_link` up front (`400` if not `http(s)`) since an
invalid link should never enter the conversation.

**`POST /ui/ai/confirm`** form fields: `session_id`, `link`, `place_name`,
`near_hub`, `types` (repeated), `note`, `lat`, `lon`, `matched_location_id`
(empty string when unmatched) — all carried as hidden fields on the confirm
button's form, populated from the latest proposal (see §7). Runs §5, then
returns a response that:
1. Resets `#ai-chat-panel` to the empty state (same content as
   `GET /ui/ai/panel`).
2. Refreshes the reel list via an HTMX out-of-band swap:
   `<div hx-swap-oob="innerHTML:#reel-list">…rendered partials/reel_list.html…</div>`
   — mirrors the existing `#reel-list` `<section>` in `index.html`, so the
   list updates without a page reload even though the confirm form's own
   `hx-target` is `#ai-chat-panel`.

## 7. Template (`app/templates/partials/ai_chat.html`, new)

Renders, in order:
1. **History**: every `AiMessage` for the session so far, oldest first.
   User turns render as plain text bubbles. Assistant turns are parsed from
   their stored JSON and rendered as either a question bubble (if
   `question` is set) or a proposal card (place name, `near_hub` if any,
   type icons via `TAXONOMY`, note, confidence badge).
2. **Confirm form** — shown only when the *latest* turn is an assistant
   proposal with `question` set to `null` (i.e. nothing pending). Hidden
   inputs carry that proposal's fields plus the freshly-recomputed
   `matched_location_id`, per §6.
3. **Input form** — always present. First turn (no `session_id` yet): a URL
   input (`link`) + a description textarea. Later turns: the `link` hidden
   field plus a single free-text reply textarea. This single control is
   also how the user issues corrections ("in realtà è vicino a Kyoto") —
   there is no separate structured edit UI.

`index.html` gains a new section above the existing manual add-reel form:

```html
<section id="ai-chat-panel" hx-get="/ui/ai/panel" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento assistente AI...</p>
</section>
```

The manual form/section is unchanged and stays available side-by-side.

## 8. Error handling

- Invalid `link` (not `http(s)`) → `400`, same as the manual form; caught
  before any AI call or DB write.
- Anthropic API errors (network, auth, rate limit) surface as a generic
  error bubble appended to the chat ("Errore nel contattare l'assistente,
  riprova") rather than a raw 500 page — caught in the shared turn helper.
- Unknown `session_id` (e.g. stale hidden field after a DB reset) → same
  `404` behavior as the existing JSON endpoint; the UI layer maps this to
  resetting the panel to the empty state with a small notice, rather than
  a broken page.

## 9. Out of scope

- Structured/manual editing of AI proposals (fields, dropdowns) — corrections
  happen only via chat replies (§7, user decision).
- Manual lat/lon entry for AI-proposed new locations — handled entirely by
  the §4 safety net instead.
- Any change to `POST /api/ai/categorize`'s existing JSON contract or to
  session/message persistence.
- Streaming/typing-indicator UX — a plain request/response HTMX round-trip
  per turn is sufficient for a personal hobby app.

## 10. Testing

- `tests/test_ai_prompts.py`: extend schema test to assert `lat`/`lon` are
  present in `properties` and `required`.
- New `tests/test_ai_ui.py` (mirrors `tests/test_ui_fragments.py`'s style
  for the `/ui/*` router tests):
  - `GET /ui/ai/panel` renders the empty-state input form.
  - `POST /ui/ai/message` (no `session_id`) creates a session and renders
    the returned proposal or question.
  - `POST /ui/ai/message` (existing `session_id`) continues the
    conversation and renders updated history.
  - A result with `matched_location_id` unset and `lat`/`lon` both `null`
    and no model-provided `question` still ends up showing a question
    bubble, not a confirm button (§4 safety net).
  - `POST /ui/ai/confirm` with `matched_location_id` set creates a `Reel`
    on the existing location, no new `Location` row.
  - `POST /ui/ai/confirm` with `near_hub` matching an existing hub creates
    a satellite `Location` (`is_hub=False`, correct `parent_id`) plus the
    `Reel`.
  - `POST /ui/ai/confirm` with no `near_hub` match creates a new hub
    `Location` (`is_hub=True`, `parent_id=None`).
  - `POST /ui/ai/confirm` rejects a non-`http(s)` `link` with `400` and
    creates nothing.
  - `POST /ui/ai/confirm` response includes the OOB `#reel-list` swap
    with the newly created reel.
