---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/meta
  - status/authoritative
connected files: ["01-why-a-full-login-instead-of-basic-auth", "03-the-multiuser-retrofit", "get-owned"]
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

## See also

- [[KANBAN]]
- [[RELEASES]]
