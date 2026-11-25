"""The shared redaction cases (tests/redaction-cases.ts, a JSON object after `export default`): the Python side redacts every one and keeps the rest.
brain.test.tsx runs the same file against journal.ts, so the two lists can't drift apart (2026-11-14 inspection)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "mistake-brain" / "scripts"))
from host_layout import redact_secrets  # noqa: E402

CASES = json.loads((ROOT / "tests" / "redaction-cases.ts").read_text(encoding="utf-8").split("\nexport default ", 1)[1])


def test_every_shared_secret_is_redacted():
    left = [(said, out) for said, secret in CASES["redact"] if secret in (out := redact_secrets(said))]
    assert left == []


def test_every_shared_plain_line_is_kept():
    assert [k for k in CASES["keep"] if redact_secrets(k) != k] == []


# Issue #184's forms (a space-separated config subcommand, ?key=/&sig=, a quoted Authorization key, the curl -u
# forms) were a Python-only table here while journal.ts lacked them; since #195 they are in the shared file, under
# `redact`, `keep` and `after` ([text, must be gone, must stay]), and both redactors run them.


def test_every_shared_after_row_drops_the_secret_and_keeps_the_rest():
    bad = []
    for said, gone, stays in CASES["after"]:
        out = redact_secrets(said)
        if any(g in out for g in gone) or any(k not in out for k in stays):
            bad.append((said, out))
    assert bad == []
