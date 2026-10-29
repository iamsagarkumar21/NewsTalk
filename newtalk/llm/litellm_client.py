import time
import json
import logging

import os
import re as _re
import yaml
import litellm
from pathlib import Path
from dotenv import load_dotenv

# Load .env as the very first thing — search newtalk/.env then NewsTalk/.env
_HERE = Path(__file__).resolve().parent.parent  # newtalk/
for _p in [_HERE / ".env", _HERE.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

CONFIG_PATH = Path(__file__).resolve().parent / "llm_config.yaml"
logger = logging.getLogger(__name__)

# Per-role API key routing — lets us distribute load across Groq accounts
_ROLE_KEY_MAP = {
    "scorer":        "GROQ_API_KEY",
    "context_writer":"GROQ_API_KEY",
    "trend_scout":   "GROQ_API_KEY",
    "composer":      "GROQ_API_KEY",
    "qa":            "GROQ_API_KEY_2",
}


# Keys that Groq rejected as invalid this process lifetime -> fall back to the other account.
_DEAD_KEYS: set[str] = set()
_KEY_FALLBACK = {"GROQ_API_KEY": "GROQ_API_KEY_2", "GROQ_API_KEY_2": "GROQ_API_KEY"}


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "invalid_api_key" in text or "invalid api key" in text or "authenticationerror" in text


def _role_env_key(role: str) -> str | None:
    env_key = _ROLE_KEY_MAP.get(role)
    if env_key in _DEAD_KEYS:
        alt = _KEY_FALLBACK.get(env_key)
        if alt and alt not in _DEAD_KEYS and os.environ.get(alt):
            return alt
    return env_key


def _mark_key_dead(role: str) -> bool:
    """Record that the role's key is invalid. True if another key can be tried."""
    env_key = _role_env_key(role)
    if not env_key or env_key in _DEAD_KEYS:
        return False
    _DEAD_KEYS.add(env_key)
    alt = _KEY_FALLBACK.get(env_key)
    usable = bool(alt and alt not in _DEAD_KEYS and os.environ.get(alt))
    logger.error(
        "%s was rejected as invalid by the provider — %s",
        env_key,
        f"falling back to {alt}" if usable else "no fallback key available",
    )
    return usable


def _apply_key_for_role(role: str):
    """Swap the provider env var for the given role's configured key."""
    env_key = _role_env_key(role)
    if not env_key:
        return
    key_value = os.environ.get(env_key, "")
    if not key_value:
        return
    # All roles now use Groq
    os.environ["GROQ_API_KEY"] = key_value


_ROLE_KEY_PROVIDER = {
    "scorer":        "groq",
    "context_writer":"groq",
    "trend_scout":   "groq",
    "composer":      "groq",
    "qa":            "groq",
}


def load_llm_config() -> dict:
    """Load the logical role configurations from llm_config.yaml."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def call_llm(role: str, messages: list, **kwargs) -> litellm.ModelResponse:
    """
    Call LiteLLM completion using the configuration defined for the given role.
    """
    _apply_key_for_role(role)

    config = load_llm_config()
    if role not in config:
        raise ValueError(f"Role '{role}' is not configured in llm_config.yaml")

    role_config = config[role]
    model = role_config.get("model")
    if not model:
        raise ValueError(f"No model configured for role '{role}' in llm_config.yaml")

    completion_args = {
        "model": model,
        "messages": messages,
        "temperature": role_config.get("temperature", 0.0),
        "max_tokens": role_config.get("max_tokens", 1024),
        **kwargs,
    }

    last_exc = None
    for attempt in range(3):
        try:
            return litellm.completion(**completion_args)
        except Exception as exc:
            last_exc = exc
            if attempt < 2 and _is_auth_error(exc) and _mark_key_dead(role):
                _apply_key_for_role(role)
                continue
            if attempt < 2:
                err_str = str(exc).lower()
                if "rate" in err_str or "429" in err_str or "quota" in err_str:
                    # Parse Groq's "try again in Xs" hint, default to 10s
                    delay = 10
                    import re as _re
                    m = _re.search(r"try again in ([\d.]+)s", str(exc))
                    if m:
                        delay = float(m.group(1)) + 1
                    logger.info("Rate limited on %s — waiting %.0fs (attempt %d/3)", model, delay, attempt + 1)
                    time.sleep(delay)
                    continue
            raise
    raise last_exc


def call_llm_with_tools(
    role: str,
    messages: list,
    tools: list,
    tool_executor,
    max_tool_rounds: int = 3,
    **kwargs,
) -> tuple[litellm.ModelResponse, list[dict]]:
    """LiteLLM completion with function-calling loop."""
    _apply_key_for_role(role)

    config = load_llm_config()
    if role not in config:
        raise ValueError(f"Role '{role}' is not configured in llm_config.yaml")

    role_config = config[role]
    model = role_config.get("model")
    audit_log: list[dict] = []
    conversation = list(messages)

    for round_num in range(max_tool_rounds + 1):
        completion_args = {
            "model": model,
            "messages": conversation,
            "temperature": role_config.get("temperature", 0.0),
            "max_tokens": role_config.get("max_tokens", 1024),
            "tools": tools,
            "tool_choice": "auto",
            **kwargs,
        }

        last_exc = None
        resp = None
        for attempt in range(3):
            try:
                resp = litellm.completion(**completion_args)
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and _is_auth_error(exc) and _mark_key_dead(role):
                    _apply_key_for_role(role)
                    continue
                if attempt < 2:
                    err_str = str(exc).lower()
                    if "rate" in err_str or "429" in err_str or "quota" in err_str:
                        delay = 10
                        import re as _re
                        m = _re.search(r"try again in ([\d.]+)s", str(exc))
                        if m:
                            delay = float(m.group(1)) + 1
                        logger.info("Rate limited on %s — waiting %.0fs (attempt %d/3)", model, delay, attempt + 1)
                        time.sleep(delay)
                        continue
                raise
        if resp is None:
            raise last_exc

        choice = resp.choices[0]
        message = choice.message

        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls or round_num >= max_tool_rounds:
            return resp, audit_log

        # Append assistant message with tool calls
        assistant_msg = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
        conversation.append(assistant_msg)

        for tc in tool_calls:
            fn_name = tc.function.name
            fn_args = tc.function.arguments
            result = tool_executor(fn_name, fn_args)
            audit_log.append({
                "round": round_num + 1,
                "tool": fn_name,
                "arguments": fn_args,
                "result_preview": result[:300],
                "result_full": result,
            })
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return resp, audit_log
