# AI Web Search for Location Lookup — Design

## Goal

Today, when a saved reel's caption doesn't name a recognizable Japanese place, the AI categorization assistant asks the user a fallback clarifying question ("Non riesco a stimare le coordinate di questo posto: qual e' la citta' o zona piu' vicina?"). This forces the user to already know where the place is, which defeats the purpose for reels like "The world's first dedicated Dragon Ball store" — the user doesn't know the location either; that's exactly what they need help finding.

This feature gives the assistant a web search tool so it can look up real-world places named or described in a reel caption, using it only when its own knowledge isn't enough. If search turns up more than one plausible place, the assistant presents a short clickable list so the user can disambiguate with one click instead of typing a location themselves.

## Architecture

The existing categorization flow is a single Anthropic API call per chat turn (`ai_client.categorize()`), constrained to a JSON schema via `output_config.format`. Anthropic's server-side `web_search` tool composes with `output_config.format` in the same call — no client-side tool-execution loop is required, since Anthropic executes the search server-side and returns results as content blocks within the same response before Claude produces its final (schema-conforming) answer.

Changes are additive to this existing single-call architecture:

1. **`app/ai/client.py`**: add the `web_search` tool to the `messages.create()` call. Use the basic `web_search_20250305` tool type — the newer dynamic-filtering `web_search_20260209` variant's documented model support (Opus 4.6+, Sonnet 4.6+) doesn't list Haiku 4.5, which this app currently uses for categorization; the basic variant is broadly supported and sufficient here. Update response parsing: with a tool available, `response.content` may contain `server_tool_use` / `web_search_tool_result` blocks before the final `text` block — the code must pick out the schema-conforming `text` block specifically rather than assuming `content[0]`.

2. **`app/ai/prompts.py`**:
   - `build_response_schema`: add one new nullable field, `candidates`: an array of short strings (e.g. `["Tokyo - Ikebukuro", "Osaka - Namba"]`), required-but-nullable like the existing `near_hub`/`question`/`lat`/`lon` fields, following the same strict-schema pattern (`additionalProperties: false`).
   - `build_system_prompt`: change the instruction from "if you can't place this, ask the user" to a two-step instruction — try to place the location from general knowledge first (unchanged); if that fails, use the web search tool with the reel's link/caption content to try to identify the specific place; if search yields one confident match, use its coordinates as today; if search yields multiple plausible matches, populate `candidates` with short human-readable labels for each and leave `question` null; only fall back to a clarifying `question` if search also comes up empty or inconclusive.

3. **`app/routers/ai_categorize.py`** (`_run_turn` and related helpers):
   - The existing safety net (`if matched_location_id is None and question is None and (lat or lon missing): set question = MISSING_COORDINATES_QUESTION`) gains one more guard: don't apply it when `result.get("candidates")` is populated — that's a different, resolvable state, not a dead end.
   - `_assistant_turn_text(result)` gains a branch: when `candidates` is present, render a line listing the options (used both for the reconstructed conversation history sent back to the API on the next turn, and as a fallback text description) — e.g. `"Ho trovato più posti possibili: Tokyo - Ikebukuro, Osaka - Namba. Quale?"`.
   - `CategorizeResponse` gains a `candidates: Optional[list[str]] = None` field.

4. **`app/templates/partials/ai_chat.html`**: when the latest assistant result has `candidates`, render them as clickable chips (styled like the existing category filter chips) inside the assistant's chat bubble instead of (or alongside) the confidence line. Each chip is a small form/button that POSTs to the existing `/ui/ai/message` endpoint with that candidate's text as the `message` field and the current `session_id` — i.e., clicking a chip is indistinguishable from the user typing that text and hitting send. No new endpoint or state machine is introduced.

## Data Flow

1. User submits a reel (link + caption) via the existing AI tab — unchanged entry point.
2. `_run_turn` calls `ai_client.categorize(hub_names, category_labels, api_messages)`, now with the web search tool available.
3. Claude tries to place the location from its own knowledge first (existing behavior, unchanged wording/logic). If it can, response looks exactly as it does today (no `candidates`).
4. If Claude's own knowledge isn't enough, it invokes `web_search` (server-side; happens within the same request). Two outcomes:
   - **One clear match** → Claude returns `place_name`, `lat`/`lon`, `types`, etc. as today, with `candidates: null`. Flows straight to the existing confirm screen.
   - **Multiple plausible matches** → Claude returns `candidates` populated (2+ short labels), `question: null`, and its best-guess `place_name`/`lat`/`lon` from the top candidate (so the safety net has nothing to complain about, but the UI still shows the candidate list instead of jumping to confirm — see rendering below).
   - **No useful results** → Claude returns `lat`/`lon: null`, `candidates: null`, which is exactly today's condition; the existing safety net fires `MISSING_COORDINATES_QUESTION` unchanged.
5. Template renders: if `candidates` present, show them as clickable chips in the assistant bubble (not the confirm screen, even though `place_name`/`lat`/`lon` may be populated with a best guess — presence of `candidates` takes priority in the template's branching, matching how `question` already takes priority over showing "confirm" today).
6. User clicks a candidate chip → posts that candidate's text as a new chat message via the existing `/ui/ai/message` endpoint (same `session_id`) → `_run_turn` runs again, now with the disambiguating text in the conversation history, and Claude finalizes a single place. From here on, everything is identical to the existing single-match flow (confirm screen, `/ui/ai/confirm`, etc.) — no new code path.

## Error Handling

- **Search tool errors** (e.g., `web_search_tool_result` block reporting `max_uses_exceeded` or similar): these arrive as a normal 200 response with an error content block, not a raised exception — Claude is expected to notice the failed search and fall back to asking the user, same as today's "no useful results" case. No special handling needed in `client.py` beyond correctly extracting the final text block.
- **API-level errors** (network, rate limit, etc.): unchanged — the existing `except anthropic.AnthropicError` catch in `_run_turn` already produces the generic "Errore nel contattare l'assistente, riprova." fallback question.
- **`pause_turn` stop reason** (server-side tool loop hits its internal iteration cap — rare, default cap is 10 search-related iterations): `client.py`'s `categorize()` should detect this and resend the same messages once (per Anthropic's documented resume pattern: re-send the original messages plus the paused assistant response, no extra "continue" prompt needed) before giving up and raising, so a single pathological search doesn't silently truncate the answer.

## Testing

Existing tests already mock `ai_client.categorize()` at the router boundary (`app/routers/ai_categorize.py` tests patch or stub this function directly), so the new `candidates`-handling logic in `_run_turn` can be tested the same way — no real Anthropic/web-search calls needed:

- `_run_turn` does **not** apply the `MISSING_COORDINATES_QUESTION` safety net when `categorize()` returns a result with `candidates` populated.
- `_assistant_turn_text` renders a readable line listing the candidates.
- `CategorizeResponse` round-trips the `candidates` field through the `/api/ai/categorize` JSON endpoint.
- `ui_ai_message` / the `ai_chat.html` template render clickable chips for each candidate when present, and do **not** render the confirm screen in that state.
- Clicking a candidate (i.e., POSTing its text as a follow-up message) continues the same `AiSession`/`session_id` and produces a normal single-match result on the next turn (using a mocked second `categorize()` call).

`app/ai/client.py`'s actual Anthropic call (tool wiring, `output_config.format` + `web_search` composing correctly, `pause_turn` resume) is not covered by the existing mocked test suite and is not practical to test without hitting the real API — this is consistent with how the existing `categorize()` call is already untested at that layer today.
