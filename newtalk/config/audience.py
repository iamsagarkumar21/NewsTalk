"""Load audience profile for India-focused personalization."""
from __future__ import annotations

from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "audience_config.yaml"


def load_audience_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_perspective_prompt() -> str:
    cfg = load_audience_config()
    return cfg.get("perspective", "").strip()


def get_greeting() -> str:
    cfg = load_audience_config()
    return cfg.get("greeting", "Good evening. Today's briefing will take about 9 minutes.")
