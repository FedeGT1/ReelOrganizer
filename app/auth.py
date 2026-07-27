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
