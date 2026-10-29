"""Twilio outbound phone call — rings USER_PHONE_NUMBER with Jiya briefing."""
from __future__ import annotations

import logging

from newtalk.config.settings import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    USER_PHONE_NUMBER,
    PUBLIC_BASE_URL,
)

logger = logging.getLogger(__name__)


def twilio_configured() -> bool:
    return bool(
        TWILIO_ACCOUNT_SID
        and TWILIO_AUTH_TOKEN
        and TWILIO_FROM_NUMBER
        and USER_PHONE_NUMBER
        and PUBLIC_BASE_URL
    )


def place_phone_call(briefing_id: int) -> str:
    """Initiate outbound call. Returns Twilio call SID."""
    from twilio.rest import Client

    if not twilio_configured():
        raise EnvironmentError(
            "Twilio not fully configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "TWILIO_FROM_NUMBER, USER_PHONE_NUMBER, PUBLIC_BASE_URL in .env"
        )

    twiml_url = f"{PUBLIC_BASE_URL.rstrip('/')}/voice/twiml?briefing_id={briefing_id}"
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    call = client.calls.create(
        to=USER_PHONE_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=twiml_url,
        method="GET",
    )
    logger.info("Twilio call placed: %s → %s (sid=%s)", TWILIO_FROM_NUMBER, USER_PHONE_NUMBER, call.sid)
    return call.sid
