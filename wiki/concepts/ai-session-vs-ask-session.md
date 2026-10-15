---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/concept
  - topic/ai-categorization
  - topic/ai-ask
  - component/reel-organizer
  - status/authoritative
connected files: ["02-the-ai-categorization-flow", "components/reel-organizer/README"]
---

# `AiSession` vs. `AskSession`

Two separate chat-history tables backing two separate, unrelated AI features. They look
structurally identical (session + ordered messages, per-user) but are never read by each
other's code path.

**Defined in** `app/models.py` — `AiSession`/`AiMessage` and `AskSession`/`AskMessage`.

**`AiSession`** — one conversation that proposes a **place + categories for a new
reel being added**. Ends by being deleted once the reel is confirmed and saved
(`app/routers/ai_categorize.py::ui_ai_confirm`) — it's throwaway scratch state, not a
record kept for history. Driven by `app/ai/client.py::categorize`. See
[[02-the-ai-categorization-flow]].

**`AskSession`** — a free-form Q&A conversation **about reels already saved**, optionally
scoped to one hub (`location_id`) and/or one category (`category_key`). Kept
indefinitely and listed back to the user (`app/routers/ai_ask.py::_list_ask_sessions`) —
it's a saved conversation, not scratch state, deletable only explicitly via `DELETE
/ui/ask/history/{session_id}`. Driven by `app/ai/client.py::ask`.

**Who reads it** → `AiSession` only from `app/routers/ai_categorize.py` and
`app/routers/ai_multi_categorize.py`; `AskSession` only from `app/routers/ai_ask.py`.

**Watch out for** — both got the same `ed5d7fa` ownership-check fix independently
(see [[03-the-multiuser-retrofit]]), because they're parallel, not shared, code paths —
fixing one did not fix the other.

## See also

- [[02-the-ai-categorization-flow]]
- [[components/reel-organizer/README]]
