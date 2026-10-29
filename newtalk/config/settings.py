import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project (newtalk/)
BASE_DIR = Path(__file__).resolve().parent.parent

def _load_env():
    """Find and load the nearest .env file, searching upward from BASE_DIR."""
    # Search order: newtalk/.env → NewsTalk/.env (project root)
    candidates = [
        BASE_DIR / ".env",
        BASE_DIR.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(dotenv_path=p, override=True)
            return  # Stop at first found

_load_env()

# API Keys
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "NewTalk/0.1")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2")  # second Groq account key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Twilio phone calls (Jiya rings your phone)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")   # e.g. +1xxxxxxxxxx
USER_PHONE_NUMBER = os.getenv("USER_PHONE_NUMBER")     # your Indian mobile, e.g. +91xxxxxxxxxx
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")         # ngrok HTTPS URL for Twilio webhooks

# Telegram "ring" bot, dashboard session signing and admin endpoints
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
SESSION_SECRET = os.getenv("SESSION_SECRET")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# DB Configuration
_DEFAULT_DB = f"sqlite:///{BASE_DIR}/db/newtalk.db"
_raw_db = os.getenv("DATABASE_URL", _DEFAULT_DB)
# Resolve relative sqlite paths to absolute (prevents CWD-dependent drift)
if _raw_db.startswith("sqlite:///") and not _raw_db.startswith("sqlite:////"):
    rel = _raw_db[len("sqlite:///"):]
    abs_path = str(BASE_DIR.parent / rel) if not rel.startswith("/") else rel
    DATABASE_URL = f"sqlite:///{abs_path}"
else:
    DATABASE_URL = _raw_db

# Host/Port Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Freshness (override in freshness_config.yaml or env)
FRESHNESS_WINDOW_HOURS = int(os.getenv("FRESHNESS_WINDOW_HOURS", "24"))
