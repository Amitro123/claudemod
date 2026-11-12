"""Reader probe for src/size.py:3 at 0632e9a: a bold SIZE line is not read."""
import re
import sys


def parse_size(text):  # copied from src/size.py:1-5 at 0632e9a
    m = re.search(r"^\s*SIZE:\s*(small|large)\b", text, re.I | re.M)
    return m.group(1).lower() if m else None


got = parse_size("**SIZE:** large")
print(f"parse_size('**SIZE:** large') -> {got!r}, want 'large'")
sys.exit(1 if got != "large" else 0)
