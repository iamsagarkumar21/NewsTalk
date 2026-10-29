"""Quick diagnostic — run this to see exactly what dotenv parses from your .env file."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import dotenv_values

env_path = Path(__file__).resolve().parent.parent / ".env"
print(f"Reading: {env_path}")
print(f"Exists:  {env_path.exists()}\n")

# Show raw first 200 bytes so we can spot CRLF / BOM
with open(env_path, "rb") as f:
    raw = f.read(300)
print("=== RAW BYTES (first 300) ===")
print(repr(raw))
print()

# Show what dotenv actually parsed
print("=== DOTENV PARSED VALUES ===")
values = dotenv_values(env_path)
for k, v in values.items():
    print(f"  key={repr(k)}  value_len={len(v) if v else 0}")
