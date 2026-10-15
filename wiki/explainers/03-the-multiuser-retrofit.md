---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/explainer
  - topic/multiuser
  - topic/data-model
  - component/reel-organizer
  - status/authoritative
connected files: ["components/reel-organizer/README", "01-why-a-full-login-instead-of-basic-auth", "get-owned", "additive-schema-migration"]
---

# The multiuser retrofit

> ReelOrganizer shipped single-user (one fixed `AUTH_USERNAME`/`AUTH_PASSWORD`, no
> `user_id` anywhere) and was retrofitted to multiple private accounts on 2026-10-09
> without a schema reset, a maintenance window, or re-entering any existing data.

## The problem

The original brief (`docs/japan-reel-organizer-specifiche.md`) explicitly put
multi-user/auth "out of scope" — single-user, no auth at all, was the starting design.
Auth arrived first as one shared username/password. Multiuser came later, on top of a
database that already held one real deployment's data. The constraint wasn't "add a
`user_id` column" — SQLModel's `create_all()` only creates missing tables, it never
alters an existing one — it was "add it to a database that's already running on
someone's VM, without asking them to wipe it."

## How it works

The retrofit is two independent layers that happen to land together.

**Schema**: `app/db.py::_ADDITIVE_COLUMNS` lists every column added to an
already-shipped table — `user_id` on `location`, `reel`, `aisession`, `asksession`, plus
a couple of unrelated additive columns picked up along the way (`geocode_confidence`,
`caption`, `transcript`). `_ensure_columns` runs `ALTER TABLE ... ADD COLUMN` for
whichever of those don't exist yet, every startup, driven by `PRAGMA table_info`. See
[[additive-schema-migration]] for the general policy this follows.

**Data ownership**: a brand-new `User` table (`app/models.py`) backs login instead of
the env-var pair. `_migrate_to_multiuser` (`app/db.py`) runs once per database: it
detects pre-multiuser data via `_needs_user_migration` (no `User` rows yet, or any
`user_id IS NULL` row in the scoped tables), creates exactly one bootstrap `User` from
the existing `AUTH_USERNAME`/`AUTH_PASSWORD` env vars if none exists yet
(`_get_or_create_bootstrap_user`), and backfills every orphaned row in `location`,
`reel`, `aisession`, `asksession` onto that user's id. `Category` is handled separately
(`_migrate_category_table_if_needed`) because its primary key itself changed shape — from
`key` alone to a `(user_id, key)` composite — which `ALTER TABLE ADD COLUMN` can't do, so
that one table is rebuilt via a `category_new` swap instead of an in-place column add.

Every query that used to read "all locations" now reads "this user's locations" —
`app/scoping.py::user_query`/`get_owned` are the two chokepoints every router is expected
to use (see [[get-owned]]). New accounts are created by the operator via
`scripts/create_user.py` (`docker exec -it reel-organizer uv run python -m
scripts.create_user <username>`), which also seeds that account's own default hubs and
categories (`d6056f4`) — seeding moved from "once, globally, at first boot" to
"per-user, at account creation," so a second account doesn't inherit or share the first
account's starter data.

## The parts that surprise people

The migration path (`e4f5f77` → `ead51f5`, five commits) had to be patched once after
the fact: `ead51f5` ("detect a fresh install as needing the bootstrap-user migration
too") fixed a case where a *brand-new* database — not an upgraded one — wasn't being
recognized as needing the bootstrap step, because the original check only looked for
orphaned rows, and a fresh DB has no rows at all yet.

A second, more serious gap surfaced after the whole per-resource scoping sweep
(`8937939` through `7858191`, scoping every router one at a time): three write paths
still accepted a client-supplied `location_id` and used it directly without an ownership
check — `_resolve_location_and_create_reel` in the AI-confirm flow,
`_reassign_reel_location` in the audit tool's reel-split-and-reassign flow, and the
new-session branch of the ask flow. Fixed in `ed5d7fa` by adding the same `get_owned`
check every other mutation already had. The failure mode this closed: a crafted
`location_id` belonging to another account would have attached a reel (or an ask
conversation) to that account's location instead of 404ing — not visible in the UI since
the dropdown only ever offers the current user's own locations, but reachable by anyone
who could craft the HTTP request directly.

## Trade-offs and what was rejected

Separate per-user SQLite files were an available alternative — no shared schema, no
`user_id` column anywhere, true isolation at the filesystem level. Rejected because it
would have meant rewriting the connection/session layer (`app/db.py` assumes one
`engine`) and migrating every account's data into its own file as part of the same
change, instead of adding one nullable column to four tables and backfilling it. The
column approach also kept the single-process, single-SQLite-file deployment story the
rest of the app (and the Docker volume setup) already depended on.

## See also

- [[components/reel-organizer/README]]
- [[get-owned]]
- [[additive-schema-migration]]
- [[01-why-a-full-login-instead-of-basic-auth]]
