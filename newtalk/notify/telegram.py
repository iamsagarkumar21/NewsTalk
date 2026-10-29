"""Telegram ring: a free notification channel with an "Answer" button.

Inbound uses long polling (`getUpdates`), so no public webhook is needed to link accounts.
Outbound messages carry an inline URL button that opens the browser call page.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from newtalk.api.security import sign_link_token, verify_link_token
from newtalk.config import settings

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str | None = None, http: httpx.Client | None = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")
        self.http = http or httpx.Client(timeout=40)

    def _call(self, method: str, **params) -> dict:
        resp = self.http.post(API.format(token=self.token, method=method), json=params)
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        return data["result"]

    def send_message(
        self, chat_id: int | str, text: str, button: tuple[str, str] | None = None
    ) -> dict:
        params: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if button:
            params["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
        return self._call("sendMessage", **params)

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", **params)


def link_url(user_id: int) -> str | None:
    """Deep link that opens the bot and binds the chat to this user on /start."""
    username = settings.TELEGRAM_BOT_USERNAME
    if not username:
        return None
    return f"https://t.me/{username.lstrip('@')}?start={sign_link_token(user_id)}"


def call_page_url(token: str) -> str | None:
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    if not base.startswith("https://"):
        return None  # browsers refuse mic access and Telegram refuses non-https buttons
    return f"{base}/app/call.html#{token}"


HELP = (
    "I'm Jiya. Link your account from the dashboard (Connect Telegram) and I'll ring you here "
    "at your call time.\n\n/call — get a call link now\n/stop — pause my daily calls\n"
    "/resume — resume them"
)


def handle_update(update: dict, repo, client, now: float | None = None) -> None:
    """Process one Telegram update: /start <token>, /call, /stop, /resume, /help."""
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    if not chat_id or not text:
        return

    command, _, arg = text.partition(" ")
    command = command.split("@")[0].lower()

    if command == "/start" and arg:
        user_id = verify_link_token(arg.strip(), now=now)
        if user_id is None or repo.get_user(user_id) is None:
            client.send_message(chat_id, "That link has expired. Open the dashboard and tap Connect Telegram again.")
            return
        repo.unlink_chat(str(chat_id))
        repo.update_channel(user_id, telegram_chat_id=str(chat_id))
        profile = repo.get_profile(user_id)
        name = profile.call_name if profile else "there"
        client.send_message(chat_id, f"Connected, {name}! I'll ring you here at your call time.")
        return

    channel_user = repo.get_user_id_by_chat(str(chat_id))
    if command in ("/start", "/help") or channel_user is None:
        client.send_message(chat_id, HELP)
        return

    if command == "/stop":
        if repo.get_profile(channel_user):
            repo.set_paused(channel_user, True)
        client.send_message(chat_id, "Paused. Send /resume whenever you want me back.")
    elif command == "/resume":
        if repo.get_profile(channel_user):
            repo.set_paused(channel_user, False)
        client.send_message(chat_id, "Welcome back! Calls are on again.")
    elif command == "/call":
        from newtalk.scheduler.ring import start_test_call

        result = start_test_call(channel_user, repo, client=client)
        if result.get("error"):
            client.send_message(chat_id, result["error"])
    else:
        client.send_message(chat_id, HELP)


def poll_forever(repo, stop: threading.Event, client: TelegramClient | None = None) -> None:
    """Long-poll loop; run in a daemon thread."""
    client = client or TelegramClient()
    offset: int | None = None
    backoff = 1.0
    while not stop.is_set():
        try:
            updates = client.get_updates(offset=offset, timeout=25)
            backoff = 1.0
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update, repo, client)
                except Exception:
                    logger.exception("Telegram update failed")
        except Exception as exc:
            logger.warning("Telegram poll error: %s (retry in %.0fs)", exc, backoff)
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)
        else:
            time.sleep(0.2)
