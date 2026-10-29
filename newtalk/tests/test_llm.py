import sys
import os
from pathlib import Path

# ── Make sure project root is importable ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # NewsTalk/
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env BEFORE any other import touches os.environ ─────────────────────
from dotenv import load_dotenv
for _p in [PROJECT_ROOT / "newtalk" / ".env", PROJECT_ROOT / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        print(f"Loaded .env from: {_p}")
        break

# ── Now it is safe to import the LiteLLM client ──────────────────────────────
from newtalk.llm.litellm_client import call_llm, load_llm_config


def run_test():
    print("\nLoading LiteLLM Config...")
    config = load_llm_config()

    # Verify keys are visible
    groq_key   = os.environ.get("GROQ_API_KEY", "")
    or_key     = os.environ.get("OPENROUTER_API_KEY", "")
    print(f"GROQ_API_KEY     loaded: {bool(groq_key)}  "
          f"(preview: {groq_key[:8]}...{groq_key[-4:]} )" if groq_key else
          f"GROQ_API_KEY     loaded: False — set it in .env")
    print(f"OPENROUTER_API_KEY loaded: {bool(or_key)}  "
          f"(preview: {or_key[:8]}...{or_key[-4:]} )" if or_key else
          f"OPENROUTER_API_KEY loaded: False — set it in .env")

    messages = [{"role": "user", "content": "Reply with exactly one word: Success"}]

    # ── Test 1: Groq / scorer ─────────────────────────────────────────────────
    print(f"\n--- Testing Groq  (scorer)         → {config['scorer']['model']} ---")
    try:
        resp = call_llm(role="scorer", messages=messages)
        print(f"✅  Response: {resp.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"❌  Error: {e}")

    # ── Test 2: OpenRouter free / context_writer ──────────────────────────────
    print(f"\n--- Testing OpenRouter (context_writer) → {config['context_writer']['model']} ---")
    try:
        resp = call_llm(role="context_writer", messages=messages)
        print(f"✅  Response: {resp.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"❌  Error: {e}")

    # ── Test 3: Groq / qa (fast, low-latency) ────────────────────────────────
    print(f"\n--- Testing Groq  (qa — fast)      → {config['qa']['model']} ---")
    try:
        resp = call_llm(role="qa", messages=messages)
        print(f"✅  Response: {resp.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"❌  Error: {e}")

    print("\nLiteLLM wrapper test completed.")


if __name__ == "__main__":
    run_test()
