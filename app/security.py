from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import base64
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.config import Settings


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return str(token)


def verify_csrf(request: Request, token: str) -> None:
    expected = str(request.session.get("csrf_token") or "")
    if not expected or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def verify_login(settings: Settings, username: str, password: str) -> bool:
    expected_user = settings.evaluator_username.encode()
    supplied_user = username.encode()
    supplied_password = password.encode()
    if settings.evaluator_password_hash:
        try:
            algorithm, rounds, salt, digest = settings.evaluator_password_hash.get_secret_value().split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            calculated = hashlib.pbkdf2_hmac(
                "sha256", supplied_password, base64.urlsafe_b64decode(salt), int(rounds)
            )
            password_ok = hmac.compare_digest(calculated, base64.urlsafe_b64decode(digest))
        except (ValueError, TypeError):
            password_ok = False
    else:
        expected_password = settings.evaluator_password.get_secret_value().encode()
        password_ok = hmac.compare_digest(
            hashlib.sha256(expected_password).digest(), hashlib.sha256(supplied_password).digest()
        )
    return hmac.compare_digest(expected_user, supplied_user) and password_ok


def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return str(user)


@dataclass
class LoginRateLimiter:
    max_attempts: int = 8
    window_seconds: int = 300

    def __post_init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and attempts[0] < now - self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.max_attempts:
            raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
        attempts.append(now)

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
