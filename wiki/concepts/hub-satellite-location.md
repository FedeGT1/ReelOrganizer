---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/concept
  - domain/location
  - component/reel-organizer
  - status/authoritative
connected files: ["02-the-ai-categorization-flow", "components/reel-organizer/README"]
---

# Hub / satellite location

Every place is one `Location` row. A **hub** is a main city/region
(`is_hub=True`, `parent_id=None`); a **satellite** ("gita", day trip) hangs off exactly
one hub (`is_hub=False`, `parent_id=<hub's id>`). There is no deeper nesting — a
satellite cannot itself be a hub for another satellite.

**Defined in** `app/models.py` (`Location`)

**Fields** — `id`, `user_id`, `name`, `is_hub: bool`, `parent_id: Optional[str]`,
`lat`/`lon: Optional[float]`, `geocode_confidence: Optional[str]`.

**Who sets it** → `app/routers/locations.py` (manual create/edit/merge), or
`app/routers/ai_categorize.py::_resolve_location_and_create_reel` when the AI
categorization flow creates a new place on confirm — see
[[02-the-ai-categorization-flow]].

**Who reads it** → `app/location_matching.py::resolve_place` (match an AI-proposed name
against existing hubs/satellites), `app/routers/map.py` (render the hub→satellite
hierarchy), `app/routers/ai_ask.py` (scope "ask" questions to a hub and its satellites).

**Watch out for** — `lat`/`lon` are nullable even on a hub. A hub with no coordinates yet
is a normal, expected state (the audit tool at `/strumenti/audit` exists specifically to
find and fix these), not a data-integrity error.

## See also

- [[02-the-ai-categorization-flow]]
- [[category-taxonomy]]
- [[components/reel-organizer/README]]
