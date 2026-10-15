---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-16"
tags:
  - kind/meta
  - status/authoritative
connected files: ["WIKI-RULES.md", "doc-map.md"]
---

# Tag taxonomy

The only vocabulary this wiki uses. Nested facets, lowercase kebab-case, one `kind/`
tag per note. Do not invent a near-synonym — if a new facet is genuinely needed, add it
here deliberately rather than letting a one-off tag creep into a page.

This is a first bootstrap: there is no prior wiki vocabulary to map onto, so there is no
old-to-new table here. If one is ever imported later, that table belongs on this page.

## `kind/` — one per note, required

| Tag | Used on |
|---|---|
| `kind/explainer` | Long-form *why* pages |
| `kind/concept` | One idea, one identifier, ~15 lines |
| `kind/component` | The one deployable unit (there is only one in this project — see below) |
| `kind/change-request` | Something asked for outside agreed scope |
| `kind/bug-report` | Behaviour contradicting a stated expectation |
| `kind/meta` | This page, `doc-map.md`, `README.md` |
| `kind/design` | Governance design page (`governance/design/`) |
| `kind/unit` | Governance unit page (`governance/units/`) |
| `kind/adr` | Architecture decision record (`governance/adrs/`) |

## `component/`

ReelOrganizer is a single-process FastAPI monolith, not a set of services — there is
exactly one component tag:

| Tag | Used on |
|---|---|
| `component/reel-organizer` | The app itself — `app/` in the repo |

## `topic/` — cross-cutting subjects

| Tag | Covers |
|---|---|
| `topic/auth` | Login, sessions, rate limiting, password hashing |
| `topic/multiuser` | Per-user data ownership and the single→multi retrofit |
| `topic/ai-categorization` | The categorize/confirm chat flow for a new reel |
| `topic/ai-ask` | The separate "chat with your saved reels" flow |
| `topic/ingest` | Instagram download + transcription pipeline |
| `topic/deployment` | Docker, reverse proxy, VM constraints |
| `topic/data-model` | SQLModel schema and migrations |

## `domain/` — business vocabulary, in the project's own language

| Tag | Covers |
|---|---|
| `domain/location` | Hub/satellite place model |
| `domain/reel` | The saved Instagram/TikTok content unit |
| `domain/category` | The food/culture/nature... taxonomy |

## `vendor/` — external systems

| Tag | Covers |
|---|---|
| `vendor/anthropic` | Claude API (default AI provider) |
| `vendor/openai` | Alternate AI provider |
| `vendor/yt-dlp` | Reel/video download |
| `vendor/faster-whisper` | Local speech-to-text |
| `vendor/instagram` | Source platform, cookie auth |

## `status/` — orthogonal to everything above

| Tag | Means |
|---|---|
| `status/authoritative` | Verified against code on `dev` |
| `status/draft` | Written but not (fully) verified |
| `status/superseded` | Kept for the record, do not act on it |
| `status/record` | Closed governance unit, kept as a record |

## See also

- [[WIKI-RULES]]
- [[doc-map]]
