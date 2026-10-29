"""An invalid primary Groq key must not take the whole pipeline down."""

import pytest

from newtalk.llm import litellm_client as lc


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "bad-key")
    monkeypatch.setenv("GROQ_API_KEY_2", "good-key")
    lc._DEAD_KEYS.clear()
    yield
    lc._DEAD_KEYS.clear()


def test_invalid_primary_key_falls_back_to_second_and_is_remembered(monkeypatch):
    import os

    used = []

    def fake_completion(**kwargs):
        used.append(os.environ["GROQ_API_KEY"])
        if os.environ["GROQ_API_KEY"] == "bad-key":
            raise Exception('GroqException - {"error":{"code":"invalid_api_key"}}')
        return "ok"

    monkeypatch.setattr(lc.litellm, "completion", fake_completion)

    assert lc.call_llm("composer", [{"role": "user", "content": "hi"}]) == "ok"
    assert used == ["bad-key", "good-key"]
    assert lc._DEAD_KEYS == {"GROQ_API_KEY"}

    used.clear()
    assert lc.call_llm("scorer", [{"role": "user", "content": "hi"}]) == "ok"
    assert used == ["good-key"], "a known-bad key must not be retried"


def test_auth_error_with_no_fallback_surfaces(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY_2")

    def always_bad(**kwargs):
        raise Exception('{"error":{"code":"invalid_api_key"}}')

    monkeypatch.setattr(lc.litellm, "completion", always_bad)
    with pytest.raises(Exception, match="invalid_api_key"):
        lc.call_llm("composer", [{"role": "user", "content": "hi"}])
