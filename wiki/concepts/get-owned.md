---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/concept
  - topic/multiuser
  - component/reel-organizer
  - status/authoritative
connected files: ["03-the-multiuser-retrofit", "01-why-a-full-login-instead-of-basic-auth"]
---

# `get_owned`

The one function every route is expected to call before reading or mutating a row by a
client-supplied id, instead of `session.get(Model, id)` directly. It returns the row only
if it exists **and** belongs to the current user; otherwise `None`, which callers turn
into a 404.

**Defined in** `app/scoping.py`

```
get_owned(session, Model, id_, user_id) -> Optional[ModelT]
```

(`Category` has its own `get_owned_category` instead, since its primary key is already
`(user_id, key)` — there's no separate ownership check to do.)

**Who sets it** → n/a, it's a read-only guard, not a value.

**Who reads/calls it** → every router touching `Location`, `Reel`, `AiSession`, or
`AskSession` by id from client input: `app/routers/ai_categorize.py`,
`app/routers/ai_ask.py`, `app/routers/audit.py`, `app/routers/locations.py`,
`app/routers/reels.py`, and others.

**Watch out for** — it is opt-in, not enforced by a type system or a decorator. Three
write paths shipped without it and silently trusted a client-supplied `location_id`
until `ed5d7fa` added the missing checks — see [[03-the-multiuser-retrofit]] for what
those were. Adding a new route that touches one of these models by id without routing
through `get_owned`/`user_query` reintroduces the same class of bug.

## See also

- [[03-the-multiuser-retrofit]]
- [[01-why-a-full-login-instead-of-basic-auth]]
