---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-15"
tags:
  - kind/meta
  - status/authoritative
connected files: ["WIKI-RULES.md", "_meta/tags.md", "README.md"]
---

# Doc map — what's in the wiki vs. still in the repo, and why

Survey done 2026-10-09 against `dev` (HEAD `b0169d3`). This is the only place that
records what was found, where it ended up, and what was deliberately left alone.

## Authoritative — stays in the repo, linked from here, never copied

| Document | Status | Where it's linked from |
|---|---|---|
| `README.md` (root) | Current, matches code (env vars, Docker flow, multiuser CLI all verified against `app/main.py`, `app/auth.py`, `scripts/create_user.py`) | [[components/reel-organizer/README]] |
| `docs/deployment-apache-tls.md` | Current operational runbook, not re-verified line-by-line this pass (reverse-proxy config is infra, not app code) | [[components/reel-organizer/README]] |
| `docs/deployment-nginx-tls.md` | Same as above | [[components/reel-organizer/README]] |

## Historical — pre-dates the current system, kept for the record

| Document | What it is | Status |
|---|---|---|
| `docs/japan-reel-organizer-specifiche.md` | The original brief given to build the app. **Already self-flagged** at the top of the file as superseded on several points (SVG railway map → Leaflet map; auth listed as out-of-scope → now central). Left as-is; this wiki does not re-explain what it already says about itself. | Historical, not dissolved further |

## Dissolved into a wiki page — original since removed

| Document | Dissolved into | Note |
|---|---|---|
| `docs/todo-next-step.md` | [[tiktok-import]] (`change-requests/business-requests/`) | The TikTok-import idea is now tracked as a proper change-request card with status `backlog`. The source markdown file was deleted by the operator in `5f16827`; the wiki card is now the only record and is authoritative. |

## Explicitly not indexed — local-only, not part of repo history

| Path | Why excluded |
|---|---|
| `.superpowers/sdd/*` | Gitignored (confirmed: no commit history for any file under it) and machine-local. Task briefs/reports under it mix at least two different planning sessions (e.g. task 1 = Instagram-cookie work, task 20 = original AI-prompts scaffolding) reusing the same numbered-task convention, so the numbering does **not** map to one coherent timeline. Since it's never shared via git, it is not "repo history" in the sense this wiki indexes — treat `git log` on `dev` as the actual historical record instead. |

## Not yet surveyed

- `app/templates/*.html` and `app/static/` — not walked file-by-file; the behaviour they
  implement is covered through the routers that render them, not through the templates
  directly.
- `tests/` — used as evidence while writing explainers (e.g. the ownership-check tests
  added in `ed5d7fa`), not indexed as its own document.

## See also

- [[README]]
- [[WIKI-RULES]]
- [[tags]]
