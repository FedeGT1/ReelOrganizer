# Basic Auth + Secure Remote Deployment — Design

## Purpose

ReelOrganizer is currently a personal, single-user app with no authentication, meant to be run locally. The goal is to deploy it on the user's own VM and access it remotely (including from Japan, with no shared local network/VPN available), while preventing anyone else from reaching or modifying it. This requires two things working together: a login layer in the app itself, and a secure network path (TLS) to reach it from anywhere.

## Scope

**In scope:**
- Session-based login for the whole app (all pages and all API routes), backed by a single fixed username/password.
- Basic anti-bruteforce protection on the login endpoint.
- nginx reverse proxy configuration (TLS termination) for the app's domain, on a VM that already runs nginx for two unrelated WordPress sites on other domains.
- Firewall and cookie/security hardening appropriate for exposing the app to the public internet.

**Out of scope:**
- General VM/SSH hardening (e.g., fail2ban on SSH, VM-wide firewall policy beyond what this app needs) — a VM-wide concern, not specific to this app.
- Multi-user accounts, password reset flows, OAuth/SSO — single fixed user is all that's needed.
- Any change to the existing WordPress nginx server blocks or global `nginx.conf` — this deployment adds one new, isolated server block for the app's own domain only.

## Part 1: Application-level login

### Session mechanism

Starlette's `SessionMiddleware` (signed cookie, no server-side session store, no new DB table — consistent with the project's "no migrations" philosophy). Configured with:
- `secret_key` from the required env var `SESSION_SECRET_KEY`.
- `https_only=True` — the cookie is only ever sent over HTTPS. This is safe because nginx is the only way to reach the app (see Part 2) and always terminates TLS before forwarding.
- `same_site="lax"`.
- `max_age` = 30 days (session survives across restarts of the browser, per the chosen session length).

### Credentials

- `AUTH_USERNAME` and `AUTH_PASSWORD`, plain values in env vars — same pattern the project already uses for `ANTHROPIC_API_KEY`.
- The app **refuses to start** if `AUTH_USERNAME`, `AUTH_PASSWORD`, or `SESSION_SECRET_KEY` is missing (fail closed, no insecure default).
- Comparison uses `secrets.compare_digest` for both username and password to avoid timing attacks.

### Enforcement (fail-closed middleware)

A single ASGI middleware inspects every incoming request:
- **Public allowlist** (no auth required): `/login` (GET/POST), `/static/*`, `/health`.
- Everything else requires `request.session.get("authenticated") is True`.
- If not authenticated:
  - Path starts with `/api/` → `401 JSON` (`{"detail": "Not authenticated"}`).
  - Otherwise → `307` redirect to `/login`.

New routes added in the future are protected by default — nothing to remember to wire up per-router.

### Login/logout flow

- `GET /login` — renders a minimal login form (username, password, submit). Reuses the project's existing CSS for visual consistency but does not extend `base.html`'s nav (nothing to link to before authenticating).
- `POST /login` — form fields `username`, `password`.
  - If the client's IP is currently locked out (see below), respond immediately with a "too many attempts" message — do not check credentials.
  - If credentials are valid: set `request.session["authenticated"] = True`, clear any failure count for this IP, redirect to `/`.
  - If invalid: record a failed attempt for this IP, re-render the login form with a generic error ("Credenziali non valide") — never reveal whether the username or the password was wrong.
- `GET /logout` — clears the session, redirects to `/login`.
- `base.html` gets a "Logout" link in the nav.

### Anti-bruteforce rate limiting

- In-memory, per-process, keyed by client IP: a dict of `{ip: [timestamps of recent failures]}`.
- 5 failed attempts within a 15-minute window → further attempts from that IP are rejected for 15 minutes without even checking the password.
- A successful login clears that IP's failure history.
- Resets on app restart (acceptable: not a persistence guarantee, just a speed bump).
- **Client IP source**: read from the `X-Forwarded-For` header set by nginx (see Part 2) rather than the raw ASGI connection IP, which would otherwise always be nginx's own address (127.0.0.1). Trusting this header is safe specifically because Part 2 ensures nginx is the *only* way to reach the app process.

## Part 2: Secure deployment (nginx + TLS + firewall)

The VM already runs nginx serving two WordPress sites on two other domains. This deployment adds a **new, separate nginx server block** for the app's own domain — it does not touch the existing WordPress server blocks or `nginx.conf`.

### Docker port binding

The app container currently publishes `-p 8000:8000` (reachable on every interface). Change to `-p 127.0.0.1:8000:8000` — the app is reachable only from the VM itself, never directly from the internet. nginx is the sole entry point.

### nginx server block (new file, e.g. `/etc/nginx/sites-available/reelorganizer`)

- Port 80: only serves the ACME HTTP-01 challenge path for the app's domain; redirects everything else to HTTPS. Matched by `server_name` to the app's domain only, so it doesn't interact with the WordPress sites' own port-80 blocks.
- Port 443: TLS via a Let's Encrypt certificate (obtained with `certbot --nginx -d <app-domain>`, which edits only this new server block, not the WordPress ones). `proxy_pass` to `http://127.0.0.1:8000`, forwarding `Host`, `X-Forwarded-Proto`, and `X-Forwarded-For`.
- Security headers added inside this server block only (so they don't affect the WordPress sites): `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.

### Certificate renewal

Handled by certbot's own systemd timer (installed automatically with the `certbot` package on Ubuntu/Debian) — no custom cron job. The nginx plugin's renewal hook reloads nginx automatically after a successful renewal.

### Firewall (ufw)

Allow only 22 (SSH), 80, 443 inbound. This is the one piece that's VM-wide rather than app-specific, but it's the minimum needed to make "only nginx is reachable" actually true at the network level, not just by convention.

## Testing strategy

This is the part that needs the most care, since a global fail-closed middleware would otherwise break every existing test that calls `client.get(...)` expecting a 200.

- `tests/conftest.py`'s `client` fixture: set `AUTH_USERNAME`/`AUTH_PASSWORD`/`SESSION_SECRET_KEY` test env vars and perform a login (`client.post("/login", data={...})`) before yielding the client, so all existing and future tests keep working unchanged, already authenticated.
- New `tests/test_auth.py` covers the unauthenticated/adversarial paths explicitly, using a plain un-authenticated `TestClient(app)` (not the auto-login fixture):
  - Unauthenticated request to `/` redirects to `/login`.
  - Unauthenticated request to an `/api/*` route returns 401 JSON.
  - `/health` and `/static/*` remain reachable without auth.
  - Correct credentials log in and set the session; the app is then reachable.
  - Wrong credentials show a generic error and do not authenticate.
  - 5 failed attempts from the same IP lock out a 6th attempt (even with correct credentials) until the window passes.
  - `/logout` clears the session (subsequent request is unauthenticated again).
  - Missing `AUTH_USERNAME`/`AUTH_PASSWORD`/`SESSION_SECRET_KEY` at startup raises/prevents app startup.

## Documentation

README gains a new "Authentication & remote access" section covering: the three required env vars, the Docker port-binding change, and a pointer to a new `docs/deployment-nginx-tls.md` (or similar) with the exact nginx/certbot/ufw commands for Ubuntu/Debian, explicitly scoped to "add a new site alongside existing ones" rather than a from-scratch nginx setup.
