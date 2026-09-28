# Multi-Place Reel Import — Design

## Goal

Some reels list several distinct places in one caption/transcript (e.g. "10 luoghi imperdibili da vedere a Kyoto"). Today the AI-assisted flow forces exactly one place per reel, so a listicle reel either gets mis-categorized as a single place or the user has to manually re-paste the same link nine more times. This adds detection of multi-place reels and lets the user pick which of the detected places to save as separate pins — all sharing the same Instagram link — while leaving the existing single-place flow completely untouched for every reel that names just one place (the overwhelming majority).

## Architecture

**No database schema change.** A `Reel` already has no uniqueness constraint on `link` — multiple `Reel` rows can point at the same link with different `location_id`s. A "10 places" reel becomes up to N separate `Reel` rows sharing one link, using the exact same `Location`/`Reel`/`ReelType` tables and hub/satellite resolution logic that exists today.

**Reuse over new protocol.** Rather than teaching the existing single-call categorization schema (`app/ai/prompts.py: build_response_schema`) to describe an arbitrary-length list of places in one response — which would require inventing a new, untested way to ask a clarifying question about one item inside a list — this multiplies the existing, working single-place flow (`_run_turn`, `ai_client.categorize`, the hub-coordinate fallback, the web-search-assisted lookup, the single-place clarifying-question mechanism) once per detected place name. Each detected place gets its own independent `AiSession`, running through code that is not modified by this feature at all.

**New pieces:**

1. **`app/ai/client.py`: `detect_places(message: str) -> dict`** — a small, separate Anthropic call (same model/pattern as `categorize()`) that classifies whether the combined link+caption+transcript text explicitly lists multiple distinct places, and if so extracts their names as they appear in the text (capped at 15 names — instructed in the prompt, to bound cost and list length for outlier captions). Its own JSON schema in `app/ai/prompts.py` (e.g. `build_places_response_schema()`): `{"is_multi_place": bool, "place_names": list[str] | null}`. This is entirely separate from `build_response_schema`/`build_system_prompt` — zero changes to the existing single-place schema or prompt.

2. **Multi-place router logic** (new functions in `app/routers/ai_categorize.py` or a new sibling module, e.g. `app/routers/ai_multi_categorize.py`): on the first turn of `/ui/ai/message` (no `session_id` yet), before doing anything else, call `detect_places()` on the combined message.
   - `is_multi_place` false, `place_names` empty/single, or the call raises → fall through to today's existing single-place path, completely unchanged (this is the overwhelmingly common case and the safe default on any classifier failure).
   - `is_multi_place` true with 2+ names → for each name, create a new `AiSession` and call the existing `_run_turn(session, None, seeded_message)`, where `seeded_message` is the original combined text plus an instruction to focus on that one named place. Collect the N `(ai_session.id, result, matched_location_id)` tuples.

3. **New partial + endpoints for the multi-place batch:**
   - **`POST /ui/ai/multi/message`** — renders (and, given a `clarify_session_id`/`clarify_text` pair, advances) the aggregated batch view. Takes the full list of `session_ids` in the current batch (hidden fields, so every render is self-contained and stateless beyond the DB) plus an optional single `clarify_session_id`/`clarify_text` pair. If clarification fields are present, calls `_run_turn(session, clarify_session_id, clarify_text)` to advance only that one session (one new Claude call); every other session's current state is read back from its stored `AiMessage` history (no new Claude call — mirrors how `_build_ai_chat_context` already reads back stored state for the single-place flow). Renders one row per session: a pre-checked checkbox with the resolved place's data (as an HTML-escaped JSON value, mirroring how candidate chips already round-trip data through form fields today) if `question` is null, or the clarifying question plus a small text input and "Chiarisci" button (posting back to this same endpoint) if not.
   - **`POST /ui/ai/multi/confirm`** — takes `link`, the full `session_ids` list (for cleanup), and one `place_json` form value per *checked* row (unchecked rows simply don't submit anything — plain HTML checkbox semantics, no JS needed). For each submitted `place_json`, runs the same location-resolution + `Reel`/`ReelType` creation logic `POST /ui/ai/confirm` already uses today (extracted into a small shared helper so neither endpoint duplicates it), all against the one shared `link`. Deletes all `AiSession`/`AiMessage` rows for every `session_id` in the batch (checked or not — the whole batch is done once confirmed). Emits one combined OOB refresh of `#reel-list`/`#map-container`/`#reel-add-form-panel`, exactly like today's single confirm.

## Data Flow

1. User pastes link (optionally via "Importa da Instagram", unchanged), writes/edits the description, presses "Invia" — same entry point as today.
2. `ui_ai_message`'s first-turn branch calls `detect_places()` first.
3. **Single place or classifier failure** → identical to today's behavior, no visible change.
4. **Multiple places detected** → one independent `AiSession` per name, each run through the unmodified `_run_turn`. The response renders a checklist: resolved places pre-checked with their proposal, unresolved ones showing their own clarifying question and a small answer field.
5. User optionally answers a clarification for one row (only that row's session advances; a single new Claude call), unchecks any places they don't want, and presses "Aggiungi selezionati".
6. `POST /ui/ai/multi/confirm` creates one `Reel` per checked row (same link, that row's resolved location/types/note), cleans up every session in the batch, and refreshes the list/map once.

## Error Handling

- Classifier error/timeout → treated as "single place", falls through to the existing flow — never a visible error for this step.
- A place that never resolves (user ignores or never satisfactorily answers its clarifying question) → stays un-checkable indefinitely but never blocks confirming the other, resolved places.
- No rows checked at confirm time → nothing is created; same "never save without an explicit selection" principle already governing the rest of the app.
- The 15-name cap is enforced by prompt instruction to `detect_places()`, not application code — if a caption names more, only the first 15 are offered.

## Testing

- `detect_places()`: same mocking pattern as `ai_client.categorize()` — a single-place/no-place caption returns `is_multi_place: false`; an explicit list returns the expected `place_names`.
- Multi-place router logic: mock `_run_turn`/`ai_client.categorize` to return a sequence of distinct results (some resolved, one with a `question`) and verify: N sessions created, N rows rendered, resolved rows pre-checked, the unresolved row shows its clarifying question instead of a checkbox, and answering that row's clarification re-renders only with that one session advanced (others' rendered content unchanged).
- `POST /ui/ai/multi/confirm`: only checked `place_json` rows produce new `Reel`s (all sharing the submitted `link`, distinct `location_id`s); unchecked rows produce nothing; every session in the batch (checked or not) is deleted afterward.
- No real Anthropic calls in automated tests, consistent with the rest of the project.
