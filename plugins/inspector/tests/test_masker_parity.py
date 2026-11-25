"""retro's mask() and inspector's mask_secrets() hold hand-kept copies of the same credential rules.

Inspector is self-contained, so decide.py copies retro's transcript.py rules ("inspector is self-contained, so these
are a copy"). On 2026-11-25 they drifted apart four times in one day: #199 widened inspector's TOKEN_RE and BEARER_RE
and left retro's (#207); #207 then copied inspector's `\\b` before Bearer into retro (a regression); #203's `\\r` fix
reached retro and not inspector until #208. Each time a review found it, by importing both and comparing by hand.
This test is that comparison, so the next drift fails CI instead of waiting for a review.

A rule only one side has (retro's GUID or HOME rules, inspector's password-flag or JSON-key rules) is not compared:
porting those is a decision, not a drift. A rule both have and that differs on purpose is named in DIFFER, with why.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGINS / "inspector" / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(PLUGINS / "retro" / "skills" / "distill" / "scripts"))
import decide  # noqa: E402
import transcript  # noqa: E402

# Both sides have these, and they must differ: rule name -> why.
DIFFER = {
    "EMAIL_RE": "retro keeps the domain ([address]@example.com, a group for it); inspector masks the whole address",
}


def rules(module) -> set[str]:
    return {n for n in dir(module) if n.endswith("_RE") and hasattr(getattr(module, n), "pattern")}


SHARED = sorted(rules(transcript) & rules(decide))


def test_the_copies_share_the_credential_rules():
    # A guard on the guard: if a rename made the shared set empty, every parity test below would pass vacuously.
    assert {"TOKEN_RE", "BEARER_RE", "X_API_KEY_RE", "AUTH_HEADER_RE", "CURL_USER_RE", "ARGV_USER_RE",
            "PRIVATE_KEY_RE", "ADO_PAT_RE"} <= set(SHARED), SHARED


@pytest.mark.parametrize("name", [n for n in SHARED if n not in DIFFER])
def test_a_shared_rule_is_the_same_in_both_copies(name):
    r, i = getattr(transcript, name), getattr(decide, name)
    assert (r.pattern, r.flags) == (i.pattern, i.flags), (
        f"{name} differs between plugins/retro/skills/distill/scripts/transcript.py and "
        f"plugins/inspector/skills/inspect/scripts/decide.py: change both, or name it in DIFFER with why")


@pytest.mark.parametrize("name", sorted(DIFFER))
def test_a_rule_listed_as_different_still_is(name):
    # When the two are made the same again, the DIFFER entry goes too.
    assert name in SHARED
    r, i = getattr(transcript, name), getattr(decide, name)
    assert (r.pattern, r.flags) != (i.pattern, i.flags), f"{name} is the same in both now: remove it from DIFFER"
