---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/concept
  - topic/data-model
  - topic/deployment
  - component/reel-organizer
  - status/authoritative
connected files: ["03-the-multiuser-retrofit", "components/reel-organizer/README"]
---

# Additive schema migration

The policy this project runs schema changes under: an existing deployment's database is
upgraded in place, automatically, on startup — never reset, never requiring the operator
to delete `data/*.db`. New *tables* are created for free by `create_all()`; new *columns*
on an existing table need an explicit entry, because `create_all()` never alters a table
that already exists.

**Defined in** `app/db.py::_ADDITIVE_COLUMNS`, applied by `_ensure_columns`, called every
`create_db_and_tables()` (i.e. every app startup).

**Values** — as of 2026-10-09: `location` gets `geocode_confidence`, `user_id`; `reel`
gets `caption`, `transcript`, `user_id`; `aisession` and `asksession` each get `user_id`.

**Who sets it** → whoever adds a field to a `SQLModel` table class in `app/models.py` —
if the table already shipped, the new column must also be added to
`_ADDITIVE_COLUMNS` or it silently never exists on an upgraded database (the comment in
`app/db.py` calls this out directly).

**Who reads it** → `create_db_and_tables()` at every startup, before any request is
served.

**Watch out for** — this mechanism only *adds* columns. A primary-key shape change (what
happened to `Category` going from `key` alone to `(user_id, key)`) can't be expressed as
an `ALTER TABLE ADD COLUMN` and needs its own one-off table-rebuild, like
`app/db.py::_migrate_category_table_if_needed` — don't assume every future schema change
fits the simple column-list pattern.

## See also

- [[03-the-multiuser-retrofit]]
- [[components/reel-organizer/README]]
