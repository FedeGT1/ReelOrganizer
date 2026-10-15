---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/meta
  - status/authoritative
connected files: ["_meta/tags.md"]
---

# Glossary

Flat list: term, definition, where it appears. A term with its own `concepts/` note is
linked here, not re-explained.

| Term | Definition | Where it appears |
|---|---|---|
| Hub | A main location/city/region (`Location.is_hub == True`). See [[hub-satellite-location]]. | `app/models.py`, `app/location_matching.py` |
| Satellite / gita | A day-trip location nested under a hub (`Location.parent_id` set). Italian "gita" (day trip) is the term used in the UI and in `docs/`. See [[hub-satellite-location]]. | `app/models.py`, `app/templates/locations.html` |
| Reel | One saved piece of content (link + note + caption + transcript + categories), named after Instagram Reels even though the backlog ([[tiktok-import]]) proposes importing non-Reel content under the same name. | `app/models.py` |
| Category | One tag in the food/culture/nature/... taxonomy, per-user and user-editable. See [[category-taxonomy]]. | `app/models.py`, `app/routers/categories.py` |
| Categorize flow | The AI chat that proposes a place + categories for a *new* reel being added. See [[02-the-ai-categorization-flow]] and [[ai-session-vs-ask-session]]. | `app/routers/ai_categorize.py` |
| Ask flow | The separate AI chat for asking free-form questions about *already-saved* reels, scoped by hub/category. See [[ai-session-vs-ask-session]]. | `app/routers/ai_ask.py` |
| Audit tool | The `/strumenti/audit` page for AI-assisted bulk review of locations missing coordinates or mis-assigned reels. | `app/routers/audit.py` |
| `get_owned` | The ownership-check helper every route must call before acting on a client-supplied id. See [[get-owned]]. | `app/scoping.py` |
| sslip.io | Free wildcard-DNS service (`<ip-with-dashes>.sslip.io`) used to get a real HTTPS hostname on the VM without owning a domain. | `README.md`, deployment docs |
| Hanko | Japanese name stamp; the original visual-design brief (`docs/japan-reel-organizer-specifiche.md`) used hanko-stamp red as the sole accent color. Largely superseded by the current Leaflet-map UI — see [[_meta/doc-map]]. | `docs/japan-reel-organizer-specifiche.md` |
| AF / analisi funzionale | Not used on this project — there is no separate functional-analysis document; the repo's own README and this wiki serve that role. | — |

## See also

- [[tags]]
- [[doc-map]]
