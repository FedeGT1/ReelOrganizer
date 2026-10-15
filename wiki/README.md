---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/meta
  - status/authoritative
connected files: ["WIKI-RULES.md", "_meta/tags.md", "_meta/doc-map.md", "glossary.md"]
---

# ReelOrganizer wiki

A single FastAPI app for organizing Instagram (and someday TikTok) reels saved while
planning a trip, categorized by place and content type, shown on an interactive map.
Self-hosted on the operator's own VM. See [[components/reel-organizer/README|the
component page]] for what it is; this page is just the map of the wiki.

## Start here

1. [[WIKI-RULES]] — conventions, before writing or trusting anything else here.
2. [[tags]] — the tag vocabulary every note's frontmatter draws from.
3. [[components/reel-organizer/README|components/reel-organizer]] — the one component
   this project has: its job, interface, dependencies.

## Reading order (explainers)

1. [[01-why-a-full-login-instead-of-basic-auth]]
2. [[02-the-ai-categorization-flow]]
3. [[03-the-multiuser-retrofit]]

## Concepts referenced from those

- [[hub-satellite-location]]
- [[category-taxonomy]]
- [[get-owned]]
- [[ai-session-vs-ask-session]]
- [[additive-schema-migration]]

## Registers

- [[CHANGELOG]] — delivered requirement → code evidence, dated.
- [[KANBAN]] — TODO / WIP / TEST / DONE / ARCHIVED.
- [[RELEASES]] — what is deployed where, with dates.
- [[glossary]] — business terms, acronyms, external systems.

## Open asks

- `change-requests/business-requests/` — currently just
  [[tiktok-import]] (backlog, not started).

## Not yet written

`bug-reports/` exists but is empty — no reported defect has been filed into the wiki
yet. See [[_meta/doc-map|_meta/doc-map]] for what else is intentionally thin on this
first pass.
