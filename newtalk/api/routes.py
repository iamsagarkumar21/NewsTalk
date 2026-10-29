"""Dashboard API: invite-code sign-in and the signed-in user's profile."""

from __future__ import annotations

import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from newtalk.api.security import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    get_repo,
    login_limiter,
    require_admin,
    require_user,
    sign_session,
)
from newtalk.config.interests import (
    DEFAULT_LANGUAGE,
    DEFAULT_TIMEZONE,
    INTEREST_TOPICS,
    LANGUAGE_CODES,
    LANGUAGES,
    TOPIC_SLUGS,
)
from newtalk.db.repository import NewTalkRepository
from newtalk.notify.telegram import link_url

router = APIRouter(prefix="/api")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class SessionIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class ProfileIn(BaseModel):
    call_name: str
    interests: list[str] = []
    free_text: str | None = None
    call_time: str | None = None
    language: str = DEFAULT_LANGUAGE
    timezone: str = DEFAULT_TIMEZONE

    @field_validator("call_name")
    @classmethod
    def _call_name(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 40:
            raise ValueError("call_name must be 1-40 characters")
        return v

    @field_validator("interests")
    @classmethod
    def _interests(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in TOPIC_SLUGS]
        if unknown:
            raise ValueError(f"unknown interests: {', '.join(unknown)}")
        return list(dict.fromkeys(v))

    @field_validator("free_text")
    @classmethod
    def _free_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 300:
            raise ValueError("free_text must be at most 300 characters")
        return v or None

    @field_validator("call_time")
    @classmethod
    def _call_time(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        match = _TIME_RE.match(v)
        if not match:
            raise ValueError("call_time must be HH:MM (24-hour)")
        if int(match.group(2)) % 5 != 0:
            raise ValueError("call_time must be in 5-minute steps")
        return v

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        if v not in LANGUAGE_CODES:
            raise ValueError(
                f"language must be one of: {', '.join(sorted(LANGUAGE_CODES))}"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("unknown timezone") from exc
        return v

    def check_has_interest(self) -> None:
        if not self.interests and not self.free_text:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "interests"],
                        "msg": "choose at least one topic or describe your interests",
                    }
                ],
            )


class ConsentIn(BaseModel):
    granted: bool


class PauseIn(BaseModel):
    paused: bool


class DeleteIn(BaseModel):
    confirm: bool = False


class InvitesIn(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    note: str | None = Field(default=None, max_length=100)


def _profile_view(profile) -> dict | None:
    if profile is None:
        return None
    return {
        "call_name": profile.call_name,
        "interests": json.loads(profile.interests_json or "[]"),
        "free_text": profile.free_text,
        "understood": json.loads(profile.normalized_json)
        if profile.normalized_json
        else None,
        "call_time": profile.call_time,
        "language": profile.language,
        "timezone": profile.timezone,
    }


def _me_view(user, repo: NewTalkRepository) -> dict:
    profile = repo.get_profile(user.id)
    channel = repo.get_channel(user.id)
    return {
        "user_id": user.id,
        "profile": _profile_view(profile),
        "defaults": {"language": DEFAULT_LANGUAGE, "timezone": DEFAULT_TIMEZONE},
        "consented": bool(profile and profile.consented_at),
        "paused": bool(profile and profile.paused),
        "telegram_linked": bool(channel and channel.telegram_chat_id),
        "delivery_mode": channel.delivery_mode if channel else "browser",
    }


def _is_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )


@router.get("/topics")
def topics():
    return {"topics": INTEREST_TOPICS, "languages": LANGUAGES}


@router.post("/session")
def sign_in(
    body: SessionIn,
    request: Request,
    response: Response,
    repo: NewTalkRepository = Depends(get_repo),
):
    client = request.client.host if request.client else "unknown"
    if not login_limiter.hit(client):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Try again later."
        )
    kind, user_id = repo.claim_invite(body.code.strip())
    if kind == "invalid":
        raise HTTPException(status_code=401, detail="Invalid invite code")
    response.set_cookie(
        COOKIE_NAME,
        sign_session(user_id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    return {"user_id": user_id, "is_new": kind == "new"}


@router.delete("/session")
def sign_out(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def get_me(user=Depends(require_user), repo: NewTalkRepository = Depends(get_repo)):
    return _me_view(user, repo)


@router.put("/me")
def put_me(
    body: ProfileIn,
    user=Depends(require_user),
    repo: NewTalkRepository = Depends(get_repo),
):
    body.check_has_interest()
    existing = repo.get_profile(user.id)
    changed_interests = (
        existing is None
        or json.loads(existing.interests_json or "[]") != body.interests
        or existing.free_text != body.free_text
    )
    fields = dict(
        call_name=body.call_name,
        interests=body.interests,
        free_text=body.free_text,
        call_time=body.call_time,
        language=body.language,
        timezone=body.timezone,
    )
    if changed_interests:
        fields["normalized_json"] = None
    repo.upsert_profile(user.id, **fields)
    if changed_interests:
        _run_normalizer(user.id, body.interests, body.free_text, repo)
    return _me_view(user, repo)


def _run_normalizer(
    user_id: int, interests: list[str], free_text: str | None, repo: NewTalkRepository
) -> None:
    """Best-effort interest normalization — never blocks the response."""
    import threading

    def _do():
        try:
            from newtalk.composer.interest_normalizer import normalize_interests

            normalize_interests(interests, free_text, repo=repo, user_id=user_id)
        except Exception:
            pass

    if free_text:
        threading.Thread(target=_do, daemon=True).start()
    else:
        _do()


def _require_profile(user, repo: NewTalkRepository) -> None:
    if repo.get_profile(user.id) is None:
        raise HTTPException(status_code=409, detail="Save your profile first")


@router.post("/me/consent")
def set_consent(
    body: ConsentIn,
    user=Depends(require_user),
    repo: NewTalkRepository = Depends(get_repo),
):
    _require_profile(user, repo)
    repo.set_consent(user.id, body.granted)
    return _me_view(user, repo)


@router.post("/me/pause")
def set_pause(
    body: PauseIn,
    user=Depends(require_user),
    repo: NewTalkRepository = Depends(get_repo),
):
    _require_profile(user, repo)
    repo.set_paused(user.id, body.paused)
    return _me_view(user, repo)


@router.delete("/me")
def delete_me(
    body: DeleteIn,
    response: Response,
    user=Depends(require_user),
    repo: NewTalkRepository = Depends(get_repo),
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail='Send {"confirm": true} to delete')
    repo.delete_user(user.id)
    response.delete_cookie(COOKIE_NAME)
    return {"deleted": True}


@router.post("/admin/invites", dependencies=[Depends(require_admin)])
def create_invites(body: InvitesIn, repo: NewTalkRepository = Depends(get_repo)):
    codes = [repo.create_invite_code(note=body.note).code for _ in range(body.count)]
    return {"codes": codes}


def _telegram_client():
    from newtalk.config import settings
    from newtalk.notify.telegram import TelegramClient

    return TelegramClient() if settings.TELEGRAM_BOT_TOKEN else None


@router.post("/me/call")
def call_me_now(user=Depends(require_user), repo: NewTalkRepository = Depends(get_repo)):
    """Test call: prepares a briefing now, returns a single-use token for the call page."""
    from newtalk.scheduler.ring import start_test_call

    result = start_test_call(user.id, repo, client=None)
    if result.get("error"):
        status = 429 if "3 test calls" in result["error"] else 409
        raise HTTPException(status_code=status, detail=result["error"])
    return {
        "token": result["token"],
        "briefing_id": result["briefing_id"],
        "story_count": result["story_count"],
        "call_path": f"/app/call.html#{result['token']}",
    }


@router.get("/me/telegram")
def telegram_status(user=Depends(require_user), repo: NewTalkRepository = Depends(get_repo)):
    channel = repo.get_channel(user.id)
    return {
        "linked": bool(channel and channel.telegram_chat_id),
        "link_url": link_url(user.id),
    }


@router.delete("/me/telegram")
def telegram_unlink(user=Depends(require_user), repo: NewTalkRepository = Depends(get_repo)):
    repo.update_channel(user.id, telegram_chat_id=None)
    return {"linked": False}


@router.get("/me/calls")
def my_calls(user=Depends(require_user), repo: NewTalkRepository = Depends(get_repo)):
    """Recent attempts plus text transcripts (briefing script and Q&A) for the dashboard."""
    attempts = [
        {
            "date": a.local_date.isoformat(),
            "slot": a.slot,
            "status": a.status,
            "briefing_id": a.briefing_id,
        }
        for a in repo.list_call_attempts(user.id, limit=10)
    ]
    transcripts = [
        {
            "briefing_id": b.id,
            "date": b.date.isoformat() if b.date else None,
            "story_count": b.story_count,
            "script": b.script_text,
            "qa": [{"q": q.question, "a": q.answer} for q in b.qa_logs],
        }
        for b in repo.list_briefings(user.id, limit=5)
    ]
    return {"attempts": attempts, "transcripts": transcripts}
