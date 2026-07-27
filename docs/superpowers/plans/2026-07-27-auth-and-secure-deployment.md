# Basic Auth + Secure Remote Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session-based login to ReelOrganizer (protecting every route by default) and document a secure nginx + TLS deployment on the user's existing VM, so the app can be safely reached from anywhere without exposing it to unauthenticated access.

**Architecture:** A Starlette `SessionMiddleware` (signed cookie, no DB table) backs a single fixed username/password login form. A second, custom `AuthMiddleware` enforces auth on every request except an explicit allowlist (`/login`, `/health`, `/static/*`), failing closed by default. An in-memory per-IP rate limiter throttles repeated failed logins. Separately, a deployment doc covers adding an isolated nginx server block (alongside two existing WordPress sites already on the VM) with Let's Encrypt TLS, and binding the app's Docker port to localhost only.

**Tech Stack:** FastAPI, Starlette `SessionMiddleware` (`itsdangerous` for cookie signing), Jinja2, pytest. nginx + certbot on Ubuntu/Debian for the deployment doc.

## Global Constraints

- No new database table for sessions — cookie-based only, consistent with the project's no-migrations design (see `docs/superpowers/specs/2026-07-27-auth-and-secure-deployment-design.md`).
- `AUTH_USERNAME`, `AUTH_PASSWORD`, `SESSION_SECRET_KEY` are required env vars — the app must refuse to start if any is missing (no insecure default).
- Credential comparison uses `secrets.compare_digest` for both username and password.
- Every route is protected by default except `/login`, `/health`, and `/static/*` — a new route added later needs no additional wiring to be protected.
- `/api/*` unauthenticated requests get a `401` JSON body; other unauthenticated page requests get a redirect to `/login`; unauthenticated HTMX requests (`HX-Request: true` header) get a `200` with an `HX-Redirect: /login` header instead of a raw redirect, so htmx does a real client-side navigation instead of swapping the login page's HTML into a fragment.
- Rate limiting: 5 failed attempts per IP within 15 minutes locks that IP out for 15 minutes. In-memory, resets on process restart.
- Session cookie: `https_only=True`, `same_site="lax"`, `max_age` = 30 days.
- The nginx/deployment work touches only a new, isolated server block for the app's own domain — it must never modify `nginx.conf` or the existing WordPress server blocks.
- Client IP for rate limiting is read from `X-Forwarded-For` (set by nginx), falling back to the raw connection IP — safe specifically because the Docker port-binding change (Task 4) makes nginx the only way to reach the app.

---

### Task 1: `app/auth.py` — rate limiter, client IP, credential verification

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth_helpers.py`

**Interfaces:**
- Produces: `require_env(name: str) -> str`, `get_client_ip(request: Request) -> str`, `verify_credentials(username: str, password: str) -> bool`, `class RateLimiter` with `is_locked_out(key: str) -> bool`, `record_failure(key: str) -> None`, `reset(key: str) -> None`, `clear_all() -> None`, and a module-level singleton `rate_limiter = RateLimiter()`. Later tasks import all of these directly from `app.auth`.

This task has no FastAPI app wiring at all — everything here is tested in isolation.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_helpers.py`:

```python
import pytest

from app.auth import RateLimiter, get_client_ip, require_env, verify_credentials


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_require_env_returns_value(monkeypatch):
    monkeypatch.setenv("SOME_TEST_VAR", "hello")
    assert require_env("SOME_TEST_VAR") == "hello"


def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_TEST_VAR", raising=False)
    with pytest.raises(RuntimeError):
        require_env("SOME_TEST_VAR")


def test_verify_credentials_correct(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "alice")
    monkeypatch.setenv("AUTH_PASSWORD", "s3cret")
    assert verify_credentials("alice", "s3cret") is True


def test_verify_credentials_wrong_password(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "alice")
    monkeypatch.setenv("AUTH_PASSWORD", "s3cret")
    assert verify_credentials("alice", "wrong") is False


def test_verify_credentials_wrong_username(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "alice")
    monkeypatch.setenv("AUTH_PASSWORD", "s3cret")
    assert verify_credentials("bob", "s3cret") is False


def test_get_client_ip_uses_x_forwarded_for():
    from starlette.requests import Request as StarletteRequest

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")],
        "client": ("127.0.0.1", 12345),
    }
    request = StarletteRequest(scope)
    assert get_client_ip(request) == "203.0.113.5"


def test_get_client_ip_falls_back_to_client_host():
    from starlette.requests import Request as StarletteRequest

    scope = {"type": "http", "headers": [], "client": ("198.51.100.7", 12345)}
    request = StarletteRequest(scope)
    assert get_client_ip(request) == "198.51.100.7"


def test_rate_limiter_locks_out_after_max_attempts():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=3, window_seconds=900, lockout_seconds=900, clock=clock)

    for _ in range(3):
        assert limiter.is_locked_out("1.2.3.4") is False
        limiter.record_failure("1.2.3.4")

    assert limiter.is_locked_out("1.2.3.4") is True


def test_rate_limiter_lockout_expires_after_lockout_window():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=2, window_seconds=900, lockout_seconds=100, clock=clock)

    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.is_locked_out("1.2.3.4") is True

    clock.advance(101)
    assert limiter.is_locked_out("1.2.3.4") is False


def test_rate_limiter_reset_clears_failures():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=2, window_seconds=900, lockout_seconds=900, clock=clock)

    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.is_locked_out("1.2.3.4") is True

    limiter.reset("1.2.3.4")
    assert limiter.is_locked_out("1.2.3.4") is False


def test_rate_limiter_old_failures_outside_window_do_not_count():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=2, window_seconds=10, lockout_seconds=900, clock=clock)

    limiter.record_failure("1.2.3.4")
    clock.advance(11)
    limiter.record_failure("1.2.3.4")
    assert limiter.is_locked_out("1.2.3.4") is False


def test_rate_limiter_clear_all_resets_every_key():
    clock = FakeClock()
    limiter = RateLimiter(max_attempts=1, window_seconds=900, lockout_seconds=900, clock=clock)

    limiter.record_failure("1.2.3.4")
    limiter.record_failure("5.6.7.8")
    assert limiter.is_locked_out("1.2.3.4") is True
    assert limiter.is_locked_out("5.6.7.8") is True

    limiter.clear_all()

    assert limiter.is_locked_out("1.2.3.4") is False
    assert limiter.is_locked_out("5.6.7.8") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'` (or import errors for the missing names).

- [ ] **Step 3: Implement `app/auth.py`**

```python
import os
import secrets
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def verify_credentials(username: str, password: str) -> bool:
    expected_username = os.environ.get("AUTH_USERNAME", "")
    expected_password = os.environ.get("AUTH_PASSWORD", "")
    username_ok = secrets.compare_digest(username, expected_username)
    password_ok = secrets.compare_digest(password, expected_password)
    return username_ok and password_ok


class RateLimiter:
    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 900,
        lockout_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def is_locked_out(self, key: str) -> bool:
        locked_until = self._locked_until.get(key)
        return locked_until is not None and self._clock() < locked_until

    def record_failure(self, key: str) -> None:
        now = self._clock()
        window_start = now - self.window_seconds
        recent = [t for t in self._failures[key] if t >= window_start]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= self.max_attempts:
            self._locked_until[key] = now + self.lockout_seconds

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)

    def clear_all(self) -> None:
        self._failures.clear()
        self._locked_until.clear()


rate_limiter = RateLimiter()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth_helpers.py
git commit -m "feat: add auth helpers (rate limiter, client IP, credential check)"
```

---

### Task 2: Login/logout routes + session middleware wiring

**Files:**
- Create: `app/routers/auth.py`
- Create: `app/templates/login.html`
- Modify: `app/main.py`
- Modify: `app/templates/base.html`
- Modify: `app/static/css/style.css`
- Modify: `pyproject.toml` (add `itsdangerous`)
- Modify: `tests/conftest.py` (env vars needed for `app.main` to import successfully)
- Test: `tests/test_auth.py` (new file — route-level login/logout behavior only; global enforcement and the full regression pass come in Task 3)

**Interfaces:**
- Consumes: `require_env`, `get_client_ip`, `verify_credentials`, `rate_limiter` from `app.auth` (Task 1).
- Produces: `app.routers.auth.router` (FastAPI `APIRouter`, no prefix, exposing `GET/POST /login` and `GET /logout`), included into `app` in `main.py`. `main.py` also gains a module-level `SessionMiddleware` registration and three `require_env(...)` calls that must run before `app = FastAPI(...)` is created.

This task does **not** add global auth enforcement yet — that's Task 3. After this task, the app behaves exactly as before except `/login` and `/logout` exist and work.

- [ ] **Step 1: Add the `itsdangerous` dependency**

`SessionMiddleware` requires it but it isn't in the project's dependencies yet.

```bash
uv add itsdangerous
```

Verify `pyproject.toml`'s `dependencies` list now includes `"itsdangerous>=2.2.0"` (or whatever version `uv add` resolves) and that `uv.lock` was updated.

- [ ] **Step 2: Add required env vars to `tests/conftest.py`**

`app.main` will soon raise at import time if `AUTH_USERNAME`, `AUTH_PASSWORD`, or `SESSION_SECRET_KEY` is missing. `tests/conftest.py`'s `client` fixture lazily imports `app.main`, so these must be set before that import happens — i.e., at module level, at the very top of the file, before any other import.

Edit `tests/conftest.py` — add these three lines as the very first lines of the file, before the existing `import pytest`:

```python
import os

os.environ["AUTH_USERNAME"] = "testuser"
os.environ["AUTH_PASSWORD"] = "testpass"
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-for-production"

```

Leave the rest of the file (the `session` and `client` fixtures) unchanged for now — Task 3 will modify the `client` fixture further.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_auth.py`:

```python
def test_get_login_returns_form(anon_client):
    response = anon_client.get("/login")
    assert response.status_code == 200
    assert "form" in response.text.lower()


def test_post_login_wrong_credentials_shows_error(anon_client):
    response = anon_client.post("/login", data={"username": "testuser", "password": "wrong"})
    assert response.status_code == 401
    assert "non valide" in response.text.lower()


def test_post_login_correct_credentials_redirects_and_sets_cookie(anon_client):
    response = anon_client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session=" in response.headers.get("set-cookie", "")


def test_logout_redirects_to_login():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
```

This task doesn't have an `anon_client` fixture yet (that's introduced in Task 3) — add a minimal one just for this task's tests, at the top of `tests/test_auth.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(name="anon_client")
def anon_client_fixture():
    from app.main import app

    return TestClient(app, base_url="https://testserver")
```

Put this fixture above the four test functions in the same file.

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `app.routers.auth` doesn't exist yet, and `app.main` doesn't yet require the three env vars or register `SessionMiddleware`, so imports/route lookups fail (404s or import errors).

- [ ] **Step 5: Create `app/templates/login.html`**

```html
{% extends "base.html" %}
{% block content %}
<section class="login-form">
    <h2>Accedi</h2>
    {% if error %}
    <p class="error">{{ error }}</p>
    {% endif %}
    <form method="post" action="/login">
        <label>Username
            <input type="text" name="username" required autofocus>
        </label>
        <label>Password
            <input type="password" name="password" required>
        </label>
        <button type="submit">Accedi</button>
    </form>
</section>
{% endblock %}
```

- [ ] **Step 6: Add login form styling to `app/static/css/style.css`**

Append to the end of the file:

```css
.login-form {
    max-width: 320px;
    margin: 3rem auto;
}

.login-form label {
    display: block;
    margin-bottom: 0.75rem;
}

.login-form input {
    display: block;
    width: 100%;
    margin-top: 0.25rem;
    padding: 0.4rem;
    box-sizing: border-box;
}

.login-form .error {
    color: var(--color-hanko);
}
```

- [ ] **Step 7: Create `app/routers/auth.py`**

```python
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import get_client_ip, rate_limiter, verify_credentials
from app.web import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = get_client_ip(request)

    if rate_limiter.is_locked_out(client_ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Troppi tentativi falliti. Riprova tra qualche minuto."},
            status_code=429,
        )

    if verify_credentials(username, password):
        rate_limiter.reset(client_ip)
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)

    rate_limiter.record_failure(client_ip)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Credenziali non valide."},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
```

- [ ] **Step 8: Wire `SessionMiddleware` and required env vars into `app/main.py`**

Modify `app/main.py`. The top of the file (imports and the `_ai_log_path`/`_ai_logger` block) stays as-is; add the auth-related pieces around it:

```python
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import require_env
from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, auth, categories, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates

_ai_log_path = os.environ.get("AI_DEBUG_LOG_PATH", "data/ai_debug.log")
os.makedirs(os.path.dirname(_ai_log_path) or ".", exist_ok=True)
_ai_logger = logging.getLogger("app.ai")
_ai_logger.setLevel(logging.DEBUG)
if not _ai_logger.handlers:
    _ai_handler = logging.FileHandler(_ai_log_path)
    _ai_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _ai_logger.addHandler(_ai_handler)

require_env("AUTH_USERNAME")
require_env("AUTH_PASSWORD")
_session_secret_key = require_env("SESSION_SECRET_KEY")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret_key,
    https_only=True,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)
app.include_router(auth.router)
app.include_router(locations.router)
app.include_router(reels.router)
app.include_router(map_router.router)
app.include_router(map_router.ui_router)
app.include_router(reels.ui_router)
app.include_router(ai_categorize.router)
app.include_router(ai_categorize.ui_router)
app.include_router(categories.router)
app.include_router(categories.ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/categories")
async def categories_page(request: Request):
    return templates.TemplateResponse(request, "categories.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 9: Add a "Logout" link to `app/templates/base.html`**

Change:
```html
        <nav>
            <a href="/">Home</a>
            <a href="/categories">Gestisci categorie</a>
        </nav>
```
to:
```html
        <nav>
            <a href="/">Home</a>
            <a href="/categories">Gestisci categorie</a>
            <a href="/logout">Logout</a>
        </nav>
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: all PASS.

- [ ] **Step 11: Run the full existing suite**

Run: `uv run pytest -q`
Expected: all pre-existing tests still PASS (nothing is globally enforced yet — `AuthMiddleware` doesn't exist until Task 3 — so no other test's behavior should change).

- [ ] **Step 12: Manually verify the fail-closed startup guard**

This one behavior (refusing to start without the required env vars) is proven by Task 1's unit tests of `require_env` plus this manual check — not worth a fragile process-level test. Run:

```bash
env -u AUTH_USERNAME -u AUTH_PASSWORD -u SESSION_SECRET_KEY uv run python -c "import app.main"
```

Expected: `RuntimeError: AUTH_USERNAME environment variable is required` (or similar) — the import fails.

- [ ] **Step 13: Commit**

```bash
git add app/auth.py app/routers/auth.py app/templates/login.html app/templates/base.html \
  app/static/css/style.css app/main.py pyproject.toml uv.lock tests/conftest.py tests/test_auth.py
git commit -m "feat: add login/logout routes with session-based auth"
```

---

### Task 3: Global fail-closed enforcement + full regression pass

**Files:**
- Create: `app/auth_middleware.py`
- Modify: `app/main.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `RateLimiter`/`rate_limiter` internals from `app.auth` (Task 1), `SessionMiddleware`-populated `request.session` (Task 2).
- Produces: `app.auth_middleware.AuthMiddleware`, registered in `main.py` after `SessionMiddleware` so `request.session` is already populated when it runs.

This is the task that makes auth mandatory for the whole app — every other router's existing tests must keep passing via an auto-login test client fixture.

- [ ] **Step 1: Write the failing tests**

First, replace `tests/conftest.py` entirely with:

```python
import os

os.environ["AUTH_USERNAME"] = "testuser"
os.environ["AUTH_PASSWORD"] = "testpass"
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-for-production"

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.auth import rate_limiter

    rate_limiter.clear_all()
    yield
    rate_limiter.clear_all()


def _build_client(session: Session) -> TestClient:
    from app.db import get_session
    from app.main import app

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(name="client")
def client_fixture(session: Session):
    client = _build_client(session)
    client.post("/login", data={"username": "testuser", "password": "testpass"})
    yield client
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture(name="anon_client")
def anon_client_fixture(session: Session):
    client = _build_client(session)
    yield client
    from app.main import app

    app.dependency_overrides.clear()
```

Key changes from Task 2's version: the `client` fixture now logs in before yielding (so every other test file's `client` fixture usage keeps working once enforcement is added), there's a shared `anon_client` fixture backed by the real DB session override (replacing the ad-hoc one Task 2 added locally in `tests/test_auth.py`), `base_url="https://testserver"` is required so the `https_only=True` session cookie is actually sent back on subsequent requests within a test (verified: with the default `http://testserver` base URL, a `Secure`-flagged cookie is silently dropped by the test client and sessions don't persist across requests), and the autouse `_reset_rate_limiter` fixture prevents one test's failed-login attempts from locking out unrelated tests (the test client's synthetic connection IP is the same string across all `TestClient` instances, so without this reset, rate-limit state would leak between test files).

Now update `tests/test_auth.py`: remove the local `anon_client_fixture` this task added in Task 2 (it's superseded by conftest's shared one) and the `TestClient` import/construction inside `test_logout_redirects_to_login` (replace with the shared `client` fixture), then append the new enforcement tests. The full file becomes:

```python
def test_get_login_returns_form(anon_client):
    response = anon_client.get("/login")
    assert response.status_code == 200
    assert "form" in response.text.lower()


def test_post_login_wrong_credentials_shows_error(anon_client):
    response = anon_client.post("/login", data={"username": "testuser", "password": "wrong"})
    assert response.status_code == 401
    assert "non valide" in response.text.lower()


def test_post_login_correct_credentials_redirects_and_sets_cookie(anon_client):
    response = anon_client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session=" in response.headers.get("set-cookie", "")


def test_logout_redirects_to_login(client):
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_unauthenticated_request_to_page_redirects_to_login(anon_client):
    response = anon_client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_unauthenticated_request_to_api_returns_401(anon_client):
    response = anon_client.get("/api/reels")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_health_and_static_remain_public(anon_client):
    response = anon_client.get("/health")
    assert response.status_code == 200

    response = anon_client.get("/static/js/map.js")
    assert response.status_code == 200


def test_htmx_request_gets_hx_redirect_header_instead_of_full_redirect(anon_client):
    response = anon_client.get("/ui/reels", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/login"


def test_login_unlocks_access_to_protected_routes(anon_client):
    response = anon_client.get("/api/reels")
    assert response.status_code == 401

    anon_client.post("/login", data={"username": "testuser", "password": "testpass"})

    response = anon_client.get("/api/reels")
    assert response.status_code == 200


def test_authenticated_client_can_reach_protected_routes(client):
    response = client.get("/api/reels")
    assert response.status_code == 200


def test_lockout_after_five_failed_attempts(anon_client):
    for _ in range(5):
        response = anon_client.post("/login", data={"username": "testuser", "password": "wrong"})
        assert response.status_code == 401

    response = anon_client.post("/login", data={"username": "testuser", "password": "testpass"})
    assert response.status_code == 429
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: the new enforcement tests FAIL (no `AuthMiddleware` exists yet, so unauthenticated requests currently succeed with 200 instead of redirecting/401ing).

- [ ] **Step 3: Implement `app/auth_middleware.py`**

```python
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_PATHS = {"/login", "/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await call_next(request)

        if request.session.get("authenticated"):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": "/login"})

        return RedirectResponse(url="/login", status_code=307)
```

- [ ] **Step 4: Register `AuthMiddleware` in `app/main.py`**

Add the import and registration, keeping `SessionMiddleware` registered first so `request.session` is populated before `AuthMiddleware` reads it (Starlette runs middleware in the order added, first-added outermost — `SessionMiddleware` must wrap `AuthMiddleware`, so it must be added first):

```python
from app.auth_middleware import AuthMiddleware
```

Add this import alongside the other `app.auth`/`app.db` imports near the top of `main.py`. Then, immediately after the existing `app.add_middleware(SessionMiddleware, ...)` call, add:

```python
app.add_middleware(AuthMiddleware)
```

- [ ] **Step 5: Run the auth tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: all PASS. If `request.session` access raises `AssertionError: SessionMiddleware must be installed to access request.session`, the two `add_middleware` calls are in the wrong order — swap them.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest -q`
Expected: **all** tests pass, including every pre-existing test file (`test_reels_api.py`, `test_ui_fragments.py`, `test_map_api.py`, `test_categories_api.py`, `test_categories_ui.py`, `test_locations_api.py`, `test_ai_categorize.py`, `test_ai_ui.py`, `test_models.py`, `test_seed.py`, etc.) — they all use the `client` fixture, which now logs in automatically before yielding.

If any pre-existing test fails, it's almost certainly because it builds its own `TestClient` directly instead of using the shared `client`/`anon_client` fixtures (bypassing the auto-login) — check for that pattern and fix the test to use the fixture instead of constructing its own client.

- [ ] **Step 7: Commit**

```bash
git add app/auth_middleware.py app/main.py tests/conftest.py tests/test_auth.py
git commit -m "feat: enforce login on every route by default (fail closed)"
```

---

### Task 4: Docker port binding + README updates

**Files:**
- Modify: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Update the intro paragraph**

In `README.md`, the first paragraph (line 3) currently ends with "...asking clarifying questions when it doesn't have enough information, and never saving anything without confirmation." Add a sentence: `Login-protected (single fixed user) so it can be safely exposed on the internet for remote access.`

- [ ] **Step 2: Add required env vars to "Running locally"**

Replace the `export ANTHROPIC_API_KEY=sk-ant-...` line and the block around it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv sync
uv run uvicorn app.main:app --reload
```

with:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AUTH_USERNAME=your-username
export AUTH_PASSWORD=your-strong-password
export SESSION_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
uv sync
uv run uvicorn app.main:app --reload
```

Immediately after this code block, add:

> `AUTH_USERNAME`/`AUTH_PASSWORD` gate every page and API route behind a login form. `SESSION_SECRET_KEY` signs the session cookie — generate it once and keep it stable across restarts (regenerating it invalidates every logged-in session). The app refuses to start if any of the three is missing.

- [ ] **Step 3: Update the Docker run command**

Replace:

```bash
docker run --rm -d -p 8000:8000 -v "$(pwd)/data:/data" -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --name reel-organizer japan-reel-organizer
```

with:

```bash
docker run --rm -d \
  -p 127.0.0.1:8000:8000 \
  -v "$(pwd)/data:/data" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e AUTH_USERNAME="$AUTH_USERNAME" \
  -e AUTH_PASSWORD="$AUTH_PASSWORD" \
  -e SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
  --name reel-organizer japan-reel-organizer
```

Immediately after, add:

> Binding to `127.0.0.1:8000` instead of `8000` means the container is only reachable from the VM itself, never directly from the internet — see [`docs/deployment-nginx-tls.md`](docs/deployment-nginx-tls.md) for putting nginx with TLS in front of it so it can be reached remotely.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document required auth env vars and localhost-only Docker port binding"
```

---

### Task 5: nginx + TLS + firewall deployment guide

**Files:**
- Create: `docs/deployment-nginx-tls.md`

**Interfaces:**
- None (documentation only). Depends on Task 4's port-binding change being in place on the VM before the nginx config is added.

- [ ] **Step 1: Write `docs/deployment-nginx-tls.md`**

```markdown
# Deploying ReelOrganizer behind nginx with TLS

This assumes: Ubuntu/Debian VM, nginx already installed and serving other
sites (e.g. WordPress) on their own domains, and a domain/subdomain you
control already pointing (DNS A record) at this VM's IP. Replace
`reels.yourdomain.com` below with your actual domain everywhere it appears.

This adds one new, isolated nginx server block for this app only — it does
not touch your existing sites' server blocks or `nginx.conf`.

## 1. Run the app container bound to localhost only

Follow the README's Docker section, making sure the port is published as
`-p 127.0.0.1:8000:8000` (not `-p 8000:8000`) — this is what makes nginx the
only way to reach the app from outside the VM.

## 2. Create a minimal HTTP server block for the new domain

```bash
sudo tee /etc/nginx/sites-available/reelorganizer > /dev/null <<'EOF'
server {
    listen 80;
    server_name reels.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/reelorganizer /etc/nginx/sites-enabled/reelorganizer
sudo nginx -t
sudo systemctl reload nginx
```

At this point `http://reels.yourdomain.com` should already proxy to the app
(over plain HTTP) — confirm with `curl -I http://reels.yourdomain.com/health`
before moving on to TLS.

## 3. Get a TLS certificate with certbot

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d reels.yourdomain.com
```

Certbot will ask for an email address, ask you to agree to Let's Encrypt's
terms, and ask whether to redirect HTTP to HTTPS — choose **redirect**.
It edits only `/etc/nginx/sites-available/reelorganizer` (the file created
in step 2): it adds a `listen 443 ssl` block with the certificate paths, and
turns the port-80 block into a redirect to HTTPS. Your existing WordPress
server blocks are untouched.

## 4. Add security headers

Certbot doesn't add these. Edit `/etc/nginx/sites-available/reelorganizer`
and inside the `server { listen 443 ssl; ... }` block (the one certbot just
created), add:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options DENY always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
```

Then:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. Confirm auto-renewal works

```bash
sudo certbot renew --dry-run
```

Certbot installs its own systemd timer on Ubuntu/Debian — no cron job needed.
The nginx plugin's renewal hook reloads nginx automatically after a real
renewal.

## 6. Firewall

Only allow SSH, HTTP, and HTTPS in — **run the SSH rule first** so you don't
lock yourself out if you're connected over SSH:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 7. Verify end-to-end

- `https://reels.yourdomain.com/login` loads the login form.
- `http://reels.yourdomain.com/login` redirects to the `https://` version.
- `curl -I http://<vm-ip>:8000` (hitting the app's port directly, bypassing
  nginx) times out or is refused — confirming the app isn't reachable
  except through nginx.

## Out of scope here

General VM/SSH hardening (e.g. `fail2ban` on SSH) is a VM-wide concern, not
specific to this app, and isn't covered by this guide.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment-nginx-tls.md
git commit -m "docs: add nginx + TLS + firewall deployment guide"
```
