"""Minute-tick call scheduler: assemble at T-10 min, ring at T, handle missed calls.

Every decision is driven by DB state (`call_attempts`), so restarts and duplicate ticks are safe:
the unique (user, local date, slot) key guarantees at most one scheduled call per day.
"""

from __future__ import annotations

import datetime
import logging
from typing import Callable
from zoneinfo import ZoneInfo

from newtalk.api.security import issue_call_token
from newtalk.composer.user_briefing import assemble_user_briefing
from newtalk.db.repository import NewTalkRepository
from newtalk.notify.telegram import TelegramClient, call_page_url

logger = logging.getLogger(__name__)

PRE_ASSEMBLE = datetime.timedelta(minutes=10)
LATE_GRACE = datetime.timedelta(minutes=15)
MISSED_AFTER = datetime.timedelta(minutes=10)
MAX_ASSEMBLE_PER_TICK = 10

RING_TEXT = {
    "en": ("{name}, Jiya is calling with your briefing.", "Answer"),
    "hinglish": ("{name}, Jiya का call आ रहा है — आपकी briefing ready है।", "Answer"),
    "hi": ("{name}, Jiya आपकी briefing के साथ call कर रही है।", "उठाइए"),
}
REMINDER_TEXT = {
    "en": "{name}, you missed Jiya's call. Your briefing is still ready — tap to listen.",
    "hinglish": "{name}, आपने Jiya का call miss कर दिया। Briefing अभी भी ready है — सुनने के लिए tap करो।",
    "hi": "{name}, आपसे Jiya का call छूट गया। Briefing अभी भी तैयार है — सुनने के लिए tap कीजिए।",
}
FAILED_TEXT = {
    "en": "{name}, I couldn't prepare today's briefing. I'll try again tomorrow.",
    "hinglish": "{name}, आज की briefing तैयार नहीं हो पाई। कल फिर try करूँगी।",
    "hi": "{name}, आज की briefing तैयार नहीं हो सकी। मैं कल फिर कोशिश करूँगी।",
}


def _naive_utc(moment: datetime.datetime) -> datetime.datetime:
    return moment.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _tell_failure(client, chat_id, name: str, language: str) -> None:
    if not (client and chat_id):
        return
    try:
        client.send_message(chat_id, FAILED_TEXT.get(language, FAILED_TEXT["en"]).format(name=name))
    except Exception:  # best effort; the failure is already recorded on the attempt
        logger.warning("Could not deliver failure notice")


def _ring(
    repo: NewTalkRepository,
    client,
    chat_id: str,
    user_id: int,
    briefing_id: int,
    name: str,
    language: str,
    reminder: bool = False,
) -> None:
    token = issue_call_token(repo, user_id, briefing_id)
    url = call_page_url(token)
    if reminder:
        text, label = REMINDER_TEXT.get(language, REMINDER_TEXT["en"]), RING_TEXT.get(
            language, RING_TEXT["en"]
        )[1]
        text = text.format(name=name)
    else:
        text, label = RING_TEXT.get(language, RING_TEXT["en"])
        text = text.format(name=name)
    if url:
        client.send_message(chat_id, text, button=(label, url))
    else:
        client.send_message(chat_id, f"{text}\n(Set PUBLIC_BASE_URL to an https URL to enable the Answer button.)")


def start_test_call(
    user_id: int,
    repo: NewTalkRepository,
    client=None,
    assemble: Callable | None = None,
    now: datetime.datetime | None = None,
) -> dict:
    """On-demand call (dashboard button or /call): max 3 per local day."""
    assemble = assemble or assemble_user_briefing
    profile = repo.get_profile(user_id)
    if profile is None or not profile.consented_at:
        return {"error": "Save your profile and accept the consent first."}
    tz = ZoneInfo(profile.timezone)
    local_date = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(tz).date()
    attempt = repo.claim_test_slot(user_id, local_date)
    if attempt is None:
        return {"error": "You've used today's 3 test calls. Try again tomorrow."}
    try:
        result = assemble(user_id, repo)
    except Exception as exc:
        logger.exception("Test briefing failed for user %d", user_id)
        repo.update_call_attempt(attempt.id, status="failed", detail=str(exc)[:200])
        return {"error": "I couldn't prepare your briefing just now. Please try again shortly."}
    repo.update_call_attempt(attempt.id, status="ready", briefing_id=result["briefing_id"])
    token = issue_call_token(repo, user_id, result["briefing_id"])

    channel = repo.get_channel(user_id)
    if client is not None and channel and channel.telegram_chat_id:
        url = call_page_url(token)
        if url:
            text, label = RING_TEXT.get(profile.language, RING_TEXT["en"])
            client.send_message(
                channel.telegram_chat_id, text.format(name=profile.call_name), button=(label, url)
            )
    return {
        "attempt_id": attempt.id,
        "briefing_id": result["briefing_id"],
        "token": token,
        "story_count": result["story_count"],
    }


def tick(
    repo: NewTalkRepository,
    now: datetime.datetime | None = None,
    client=None,
    assemble: Callable = assemble_user_briefing,
    max_assemble: int = MAX_ASSEMBLE_PER_TICK,
) -> dict:
    """One scheduler pass. Returns counters (useful for tests and logs)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stats = {"assembled": 0, "rung": 0, "missed": 0, "failed": 0, "deferred": 0, "undeliverable": 0}

    for profile in repo.list_active_profiles():
        if not profile.call_time:
            continue
        uid = profile.user_id
        try:
            tz = ZoneInfo(profile.timezone)
            hour, minute = (int(x) for x in profile.call_time.split(":"))
        except (ValueError, KeyError):
            continue
        local_now = now.astimezone(tz)
        call_dt = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        local_date = call_dt.date()
        delta = local_now - call_dt
        attempt = repo.get_call_attempt(uid, local_date, "scheduled")
        channel = repo.get_channel(uid)
        chat_id = channel.telegram_chat_id if channel else None

        if attempt is None:
            if not (-PRE_ASSEMBLE <= delta <= LATE_GRACE):
                continue
            if stats["assembled"] >= max_assemble:
                stats["deferred"] += 1  # picked up on the next tick; nobody is dropped
                continue
            attempt = repo.claim_call_slot(uid, local_date, "scheduled")
            if attempt is None:
                continue
            if not chat_id:
                repo.update_call_attempt(attempt.id, status="undeliverable", detail="telegram not linked")
                stats["undeliverable"] += 1
                continue
            try:
                result = assemble(uid, repo)
            except Exception as exc:
                logger.exception("Assembly failed for user %d", uid)
                repo.update_call_attempt(attempt.id, status="failed", detail=str(exc)[:200])
                _tell_failure(client, chat_id, profile.call_name, profile.language)
                stats["failed"] += 1
                continue
            repo.update_call_attempt(attempt.id, status="ready", briefing_id=result["briefing_id"])
            stats["assembled"] += 1
            attempt = repo.get_call_attempt(uid, local_date, "scheduled")

        if attempt.status == "ready" and delta > LATE_GRACE:
            repo.update_call_attempt(attempt.id, status="failed", detail="too late to ring")
            stats["failed"] += 1
        elif attempt.status == "ready" and delta >= datetime.timedelta(0):
            try:
                _ring(repo, client, chat_id, uid, attempt.briefing_id, profile.call_name, profile.language)
                repo.update_call_attempt(
                    attempt.id, status="rung", rung_at=_naive_utc(now)
                )
                stats["rung"] += 1
            except Exception as exc:
                logger.warning("Ring failed for user %d: %s", uid, exc)
                repo.update_call_attempt(attempt.id, status="failed", detail=f"ring: {exc}"[:200])
                stats["failed"] += 1

        elif attempt.status == "rung" and attempt.rung_at:
            rung_at = attempt.rung_at.replace(tzinfo=datetime.timezone.utc)
            if now - rung_at >= MISSED_AFTER:
                repo.update_call_attempt(
                    attempt.id, status="missed", ended_at=_naive_utc(now)
                )
                stats["missed"] += 1
                reminder = repo.claim_call_slot(uid, local_date, "reminder", attempt.briefing_id)
                if reminder is not None and chat_id:
                    try:
                        _ring(
                            repo, client, chat_id, uid, attempt.briefing_id,
                            profile.call_name, profile.language, reminder=True,
                        )
                        repo.update_call_attempt(reminder.id, status="rung", rung_at=_naive_utc(now))
                    except Exception as exc:
                        repo.update_call_attempt(reminder.id, status="failed", detail=str(exc)[:200])

    if any(stats.values()):
        logger.info("Ring tick: %s", stats)
    return stats
