"""Date context helper — single source of truth for today's date/time in LLM prompts."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from newtalk.config.audience import load_audience_config


def get_date_context() -> str:
    """
    Return a timezone-aware date string for LLM prompts.

    Example: "Today is Thursday, 14 August 2026 at 09:42 IST (Asia/Kolkata)."
    """
    config = load_audience_config()
    tz_name = config.get("timezone", "Asia/Kolkata")
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    return f"Today is {now.strftime('%A, %d %B %Y at %H:%M %Z (%z)')} ({tz_name})."


def get_date_only_context() -> str:
    """Return date only (no time) for prompts that don't need time precision."""
    config = load_audience_config()
    tz_name = config.get("timezone", "Asia/Kolkata")
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    return f"Today is {now.strftime('%A, %d %B %Y')} ({tz_name})."