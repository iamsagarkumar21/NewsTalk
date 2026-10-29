"""Session cookies, admin-key guard, repository dependency and a small login rate limiter."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request

from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository

COOKIE_NAME = "nt_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600

_repo: NewTalkRepository | None = None


def get_repo() -> NewTalkRepository:
    global _repo
    if _repo is None:
        _repo = NewTalkRepository(settings.DATABASE_URL)
        _repo.create_tables()
    return _repo


def _sign(payload: str) -> str:
    secret = settings.SESSION_SECRET
    if not secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign_session(user_id: int, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + SESSION_TTL_SECONDS)
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload)}"


def verify_session(token: str | None, now: float | None = None) -> int | None:
    """Return the user id for a valid, unexpired token, else None."""
    if not token:
        return None
    try:
        user_part, expires_part, signature = token.split(".")
        payload = f"{user_part}.{expires_part}"
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expires_part) < (now if now is not None else time.time()):
            return None
        return int(user_part)
    except (ValueError, RuntimeError):
        return None


def require_user(request: Request, repo: NewTalkRepository = Depends(get_repo)):
    user_id = verify_session(request.cookies.get(COOKIE_NAME))
    user = repo.get_user(user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = settings.ADMIN_API_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid admin key")


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string (client IP here)."""

    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, now: float | None = None) -> bool:
        """Record an attempt. False if the key is over its limit."""
        now = now if now is not None else time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - self.window:
            events.popleft()
        if len(events) >= self.max_events:
            return False
        events.append(now)
        return True


login_limiter = RateLimiter(max_events=10, window_seconds=600)


# ── call tokens (single-use, 10 min) and Telegram link tokens (stateless, 30 min) ──────────────

CALL_TOKEN_TTL_SECONDS = 600
LINK_TOKEN_TTL_SECONDS = 1800


def issue_call_token(
    repo: NewTalkRepository, user_id: int, briefing_id: int | None, now: float | None = None
) -> str:
    """Create a single-use token binding this user (and briefing) to one browser call."""
    now = now if now is not None else time.time()
    jti = secrets.token_urlsafe(24)
    expires = datetime.datetime.utcfromtimestamp(now + CALL_TOKEN_TTL_SECONDS)
    repo.create_call_token(jti, user_id, briefing_id, expires)
    return f"{jti}.{_sign('call:' + jti)[:32]}"


def redeem_call_token(repo: NewTalkRepository, token: str | None, now: float | None = None):
    """Validate signature, then atomically consume. Returns the CallToken row or None."""
    if not token or token.count(".") != 1:
        return None
    jti, sig = token.split(".")
    try:
        if not hmac.compare_digest(sig, _sign("call:" + jti)[:32]):
            return None
    except RuntimeError:
        return None
    when = datetime.datetime.utcfromtimestamp(now) if now is not None else None
    return repo.consume_call_token(jti, now=when)


def sign_link_token(user_id: int, now: float | None = None) -> str:
    """Telegram `/start` payload (<=64 chars, [A-Za-z0-9_-]) that binds a chat to a user."""
    expires = int((now if now is not None else time.time()) + LINK_TOKEN_TTL_SECONDS)
    payload = f"{user_id}_{expires}"
    return f"{payload}_{_sign('link:' + payload)[:24]}"


def verify_link_token(token: str | None, now: float | None = None) -> int | None:
    try:
        user_part, expires_part, sig = (token or "").split("_")
        payload = f"{user_part}_{expires_part}"
        if not hmac.compare_digest(sig, _sign("link:" + payload)[:24]):
            return None
        if int(expires_part) < (now if now is not None else time.time()):
            return None
        return int(user_part)
    except (ValueError, RuntimeError):
        return None
