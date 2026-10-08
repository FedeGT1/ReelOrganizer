import hashlib
import os
import secrets
import time
from collections import defaultdict
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt_hex, _, digest_hex = password_hash.partition("$")
    if not digest_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return secrets.compare_digest(candidate, expected)


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


def verify_credentials(session: Session, username: str, password: str) -> Optional[User]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


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
