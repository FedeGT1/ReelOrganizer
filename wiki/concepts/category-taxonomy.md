---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/concept
  - domain/category
  - component/reel-organizer
  - status/authoritative
connected files: ["02-the-ai-categorization-flow", "03-the-multiuser-retrofit"]
---

# Category taxonomy

The set of content-type tags a reel can carry (food, culture, nature, ...). Unlike the
original brief's fixed, hardcoded taxonomy, the shipped version is a per-user, editable
table — not a constant in code.

**Defined in** `app/models.py` (`Category`, primary key `(user_id, key)`), managed via
`app/routers/categories.py`.

**Values** — not fixed in code; each account gets its own starting set, seeded by
`app/seed.py` at account creation (see [[03-the-multiuser-retrofit]]) and editable
afterwards from the "Gestisci categorie" page. There is no single verbatim list to quote
here — check a given account's `category` rows, not this page, for its current set.

**Who sets it** → the user, via `app/routers/categories.py` CRUD; seeded initially by
`app/seed.py`.

**Who reads it** → `app/routers/ai_categorize.py` (filters AI-proposed `types` against
`get_valid_type_keys` so the model can't invent a category), `app/routers/ai_ask.py`
(labels in the "ask" scope), every reel-list/map rendering.

**Watch out for** — `ReelType.type` has a `foreign_key="category.key"` but **not** on
`user_id` — a stale `ReelType` row referencing a deleted category key for the *same*
user is the failure mode to check for if a reel shows a blank category chip, not a
cross-user leak.

## See also

- [[02-the-ai-categorization-flow]]
- [[03-the-multiuser-retrofit]]
- [[hub-satellite-location]]
