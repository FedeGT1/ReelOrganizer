---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-09"
tags:
  - kind/explainer
  - topic/auth
  - component/reel-organizer
  - status/authoritative
connected files: ["components/reel-organizer/README", "03-the-multiuser-retrofit", "get-owned"]
---

# Why a full login form instead of HTTP Basic Auth

> ReelOrganizer gates every page and API route behind a session-cookie login with rate
> limiting, rather than the simpler HTTP Basic Auth a single-user personal tool would
> normally reach for.

## The problem

This is a personal app meant to be exposed on the open internet (no VPN, no IP
allowlist — the operator wants to add a reel from a phone anywhere). The constraint
isn't "needs auth" — it's "needs auth that survives being internet-facing with a
starting user base of one, on infrastructure the operator doesn't fully control" (an
EOL Ubuntu 20.10 VPS shared with two other Apache sites). Basic Auth would have been
the few-lines option: the browser handles the prompt, no templates, no session
middleware.

## How it works

`app/auth_middleware.py::AuthMiddleware` runs on every request before anything else,
checking `request.session.get("user_id")`. Two paths are exempt: `/login` and `/health`
(`PUBLIC_PATHS`), plus anything under `/static/`. Everything else either passes through,
gets a JSON 401 (`/api/*`), an `HX-Redirect` header (HTMX requests), or a 307 redirect to
`/login`.

The credential check itself (`app/routers/auth.py::login_submit`) looks up a `User` row
by username, verifies the password with `app/auth.py::verify_password` (scrypt,
`N=2**14, r=8, p=1`, 64-byte digest, random 16-byte salt per hash, stored as
`salt_hex$digest_hex`), and on success puts `user_id` in the signed session cookie set
up in `app/main.py` via Starlette's `SessionMiddleware` (`https_only` by default,
`same_site=lax`, 30-day `max_age`).

Failed attempts go through `app/auth.py::RateLimiter`: 5 failures in a 15-minute window
locks that client IP out for 15 minutes (`max_attempts=5`, `window_seconds=900`,
`lockout_seconds=900`). The key is the client IP from `X-Forwarded-For` (or the raw
socket address if that header is absent) — see `get_client_ip`.

## The parts that surprise people

The session cookie's `Secure` flag (`https_only`, controlled by
`SESSION_COOKIE_SECURE`, default `true`) means the login form **cannot work over plain
`http://localhost`** — the browser silently refuses to send the cookie back and the user
bounces to `/login` forever. This is intentional for the real deployment, but it means
there is no way to exercise the login UI locally without HTTPS (a self-signed cert via
uvicorn's `--ssl-keyfile`/`--ssl-certfile`, or testing against the real TLS-terminated
deployment).

The rate limiter is in-process memory, not persisted — a restart clears all lockouts.
For a single small VM running one container, that's an accepted trade-off, not an
oversight: see `RateLimiter.clear_all`, used only in tests.

## Trade-offs and what was rejected

Basic Auth was explicitly considered and rejected in favor of this heavier design. The
reasons that tipped it: Basic Auth has no first-class logout (clearing it requires
closing the browser or a credential-cache trick), no rate limiting without extra
middleware anyway, and — once [[03-the-multiuser-retrofit|multiuser]] arrived — no
natural place to carry a `user_id` the rest of the app could scope queries against. A
session cookie backed by a real `User` table solved both the brute-force exposure and
the multiuser identity problem with one mechanism, at the cost of needing a login
template, a session secret, and the HTTPS-only requirement above.

## See also

- [[components/reel-organizer/README]]
- [[03-the-multiuser-retrofit]]
- [[get-owned]]
