---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-16"
tags:
  - kind/meta
  - status/authoritative
connected files: ["C_01-group-reels-by-place", "01-why-a-full-login-instead-of-basic-auth", "03-the-multiuser-retrofit", "get-owned"]
---

# Changelog

Delivered requirement → code evidence, dated by the commit on `dev`. Seeded 2026-10-09
from `git log` across the project's full history (2026-07-21 → 2026-10-09, 288 commits).
Not exhaustive of every commit — rows are the requirement-level milestones, not a 1:1
mirror of `git log`; `git log` itself remains authoritative for anything finer-grained.

| Date | Delivered | Evidence |
|---|---|---|
| 2026-07-21 | Initial FastAPI/SQLModel/SQLite scaffold per the original brief | `cc93fe0` |
| 2026-07-27 | Single-user login (session-based, fail-closed middleware, rate-limited) — see [[01-why-a-full-login-instead-of-basic-auth]] | `39bfdc5`, `c7b6755`, `e10c6ae` |
| 2026-08–2026-09 | Core product: manual + AI-assisted reel categorization, Leaflet map, hub/satellite locations, Instagram auto-import (yt-dlp + faster-whisper), multi-place reel splitting, location audit tool, Instagram-cookie upload tool, note regeneration, CSV export | `app/routers/*`, `app/ingest/*`, `app/ai/*` (see [[02-the-ai-categorization-flow]]) |
| 2026-10-09 | Multiuser retrofit: `User` table, scrypt-hashed per-account login, `app/scoping.py` ownership helpers, every router scoped to the current user, additive-column + bootstrap-user migration for existing deployments, `scripts/create_user.py` admin CLI | `dc70771` … `b0169d3` (full span, see [[03-the-multiuser-retrofit]]) |
| 2026-10-09 | Fixed: three write paths (AI-confirm, audit reassign, ask-session creation) accepted a client-supplied `location_id` without an ownership check | `ed5d7fa` (see [[get-owned]]) |
| 2026-10-16 | C_01_01 — Current System Design §2 refreshed with the real consumers of the reel list fragment and card (prerequisite for [[C_01-group-reels-by-place]]) | merge of `governance/C_01_01-refresh-baseline-reel-list` into `dev` |
| 2026-10-16 | C_01_02 — Reel list context now returns reels grouped by place (newest reel first inside a group, groups by most recent reel, hub name on satellite groups); UI not yet switched | `app/routers/reels.py::_group_reels_by_place`, `tests/test_reel_list_grouping.py` |
| 2026-10-16 | C_01_03 — Reel list rendered as one section per place with a header (place name, hub on satellites, reel count); pagination script not yet adapted (C_01_04) | `app/templates/partials/reel_list.html`, `tests/test_reel_list_template.py` |
| 2026-10-16 | C_01_04 — Reel list pagination now works on place groups (5 groups at a time, "Carica altri (N gruppi rimanenti)", re-init on swap and OOB swap) | `app/static/js/reel-list.js`, `app/static/css/style.css` |
| 2026-10-16 | C_01_05 — Place group header styled (name left, count right, gold rule; long names wrap, no horizontal scroll); audit lists untouched | `app/static/css/style.css` |
| 2026-10-16 | C_01_06 — Tests for every reel-list consumer: grouped list after create/edit/delete and AI flows, standalone card on note regeneration, audit lists ungrouped, `/api/reels` still flat JSON | `tests/test_ui_fragments.py`, `tests/test_ai_ui.py`, `tests/test_ai_multi_categorize.py`, `tests/test_note_regeneration.py`, `tests/test_audit.py`, `tests/test_reels_api.py` |

## See also

- [[KANBAN]]
- [[RELEASES]]
