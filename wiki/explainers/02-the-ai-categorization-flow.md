---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/explainer
  - topic/ai-categorization
  - domain/location
  - component/reel-organizer
  - status/authoritative
connected files: ["components/reel-organizer/README", "hub-satellite-location", "ai-session-vs-ask-session", "category-taxonomy"]
---

# The AI categorization flow

> A pasted reel link never gets a place or category assigned automatically — the AI
> proposes one, the app reconciles it against existing data, and a human always clicks
> confirm before anything is written.

## The problem

The app's one hard constraint, stated in its own system prompt
(`app/ai/prompts.py::build_system_prompt`): the AI **cannot open the Instagram link**.
It only ever sees the caption or a free-text description the user pastes in, plus the
auto-downloaded transcript when available. So the AI is reasoning from fragments — "that
noodle place near Dotonbori" — not from the actual video, and it will sometimes not know
where something is, or guess wrong, or find a place name that matches two different real
locations. The flow exists to make all three of those cases safe instead of silently
wrong.

## How it works

Each conversation is an `AiSession` (`app/models.py`) with ordered `AiMessage` rows,
scoped to the current user. `app/routers/ai_categorize.py::_run_turn` is the core loop:
append the user's message, replay the full history to the model
(`app/ai/client.py::categorize`, which turns on the provider's web-search tool), get back
a JSON object matching `build_response_schema` — `place_name`, `near_hub`, `types`,
`note`, `confidence`, `question`, `lat`/`lon`, `candidates` — then run
`_apply_result_post_processing`.

That post-processing step is where the AI's answer meets the real database:
`app/location_matching.py::resolve_place` normalizes the proposed name (accent/case/
punctuation-insensitive) and checks it against the user's existing `Location` rows by
exact or substring match, then by proximity + name-similarity if coordinates are given
(within 150m and ≥0.8 `SequenceMatcher` ratio). A clean match sets `place_tier="auto"` —
no extra step for the user. Anything else comes back `"ambiguous"` with a candidate list
within 2km, and the UI shows that list instead of silently picking one.

If the AI itself is unsure, it fills `question` and the chat waits for a reply instead of
guessing a location (that's what the system prompt tells it to do when even a web search
doesn't clarify things). If it found several plausible *web* matches for an ambiguous
name, it fills `candidates` with short labels and picks its best guess for the rest of
the fields — the UI still shows the list, but doesn't block on an extra round-trip.
`MISSING_COORDINATES_QUESTION` is a server-side safety net on top of that: if the result
is ambiguous, has no question/candidates already, and has no lat/lon either, the backend
forces a clarifying question rather than letting an un-placeable pin reach confirmation.

Nothing is written to `Location`/`Reel`/`ReelType` until `POST /ui/ai/confirm`
(`app/routers/ai_categorize.py::ui_ai_confirm`). That handler re-checks for a duplicate
link (`app/reel_links.py::find_duplicate_reel`) and shows a warning requiring a second
click if the link was already saved, then re-validates that any client-supplied
`resolution_location_id` actually belongs to the current user before creating the reel
— see [[get-owned]] and the ownership-check history there. Only after a successful save
does it delete the now-finished `AiSession`/`AiMessage` rows for that conversation.

## The parts that surprise people

A reel that lists several distinct places (the README's own example: "10 places to see
in Kyoto") doesn't go through `_run_turn` once — `app/ai/client.py::detect_places` runs
first on the raw message, and if it flags `is_multi_place` with ≥2 names,
`app/routers/ai_multi_categorize.py::start_multi_place_batch` takes over: it fires one
`categorize()` call per place **in parallel**, capped at `MAX_CONCURRENT_CATEGORIZE_CALLS
= 5` even though up to `MAX_PLACES = 15` places are allowed, specifically to avoid
bursting the provider with 15 simultaneous requests. Each place becomes its own checklist
row the user resolves independently, not one combined proposal.

The system prompt also asks the model to always estimate `lat`/`lon` for a *new*,
specific place even when it already resolved a `near_hub` — `near_hub` only controls
grouping on the map, it doesn't excuse the model from estimating coordinates. And the
note text is explicitly told not to describe the place in terms of "the reel" or "what
they visited" — it's meant to read like a guidebook entry about the place itself, not a
caption to the video.

## Trade-offs and what was rejected

Auto-saving a high-confidence match was an available shortcut — `place_tier="auto"`
already tells the backend the match is clean — and it was rejected. The confirm step
always renders, even for an exact hub match, because a wrong auto-save (two Tokyo ramen
shops with near-identical names, say) is harder to notice and undo later than one extra
click now.

## See also

- [[components/reel-organizer/README]]
- [[hub-satellite-location]]
- [[category-taxonomy]]
- [[ai-session-vs-ask-session]]
