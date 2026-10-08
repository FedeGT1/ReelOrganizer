import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.auth import RateLimiter, get_client_ip, hash_password, require_env, verify_credentials, verify_password
from app.models import User


def _session_with_user(username: str, password: str) -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(User(username=username, password_hash=hash_password(password)))
    session.commit()
    return session


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


def test_verify_credentials_correct():
    session = _session_with_user("alice", "s3cret")
    user = verify_credentials(session, "alice", "s3cret")
    assert user is not None
    assert user.username == "alice"


def test_verify_credentials_wrong_password():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "alice", "wrong") is None


def test_verify_credentials_wrong_username():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "bob", "s3cret") is None


def test_verify_credentials_non_ascii_username_returns_none():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "café", "s3cret") is None


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


def test_hash_password_verifies_correct_password():
    password_hash = hash_password("s3cret")
    assert verify_password("s3cret", password_hash) is True


def test_hash_password_rejects_wrong_password():
    password_hash = hash_password("s3cret")
    assert verify_password("wrong", password_hash) is False


def test_hash_password_produces_different_hashes_for_same_password():
    # Different random salt each call -- defends against rainbow tables.
    assert hash_password("s3cret") != hash_password("s3cret")


def test_verify_password_rejects_malformed_hash():
    assert verify_password("s3cret", "not-a-valid-hash") is False
