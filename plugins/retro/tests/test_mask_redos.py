"""retro mask(): linear time on hostile input (issue #196, a regression of the argument-list rule from #193).

Broken invariant: "mask() runs in time linear in the length of the text". ARGV_USER_RE repeated a group with a
pair-of-backslashes branch and a single-backslash branch that also matched a backslash followed by a backslash. The
group was ambiguous: a pair matched as the pair branch or as two single steps, so a run of N backslashes had 2^(N/2) ways to fail and the regex backtracked through all of
them (N=36 took 4 s, N=40 did not finish). A transcript line holding such a run hung the digest.

What each table pins. Regression tests (they fail on the code before the fix): test_backslash_run_terminates (the
N=200 rows), test_long_backslash_run_is_linear (its long rows), the `email-dots` row of
test_other_rules_linear_at_200k, and test_email_leading_punctuation (the EMAIL_RE rows). Pins (they PASS on the
code before the fix, so they are not failing-first): the 9 MASK_ROWS rows and the other 9 rows of
test_other_rules_linear_at_200k; they only guard that the fix did not change what is masked or break a shape that
was already linear. Do not read them as regression tests.

Every hostile input runs in a subprocess with a hard timeout: a regression shows as a timeout, never as a hung test
run. Never call mask() on these inputs in the test process itself."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DISTILL = ROOT / "skills" / "distill" / "scripts"

CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import transcript as T
spec = json.loads(sys.stdin.read())
text = spec["prefix"] + spec["fill"] * spec["n"] + spec["suffix"]
out = T.mask(text) if spec["fn"] == "mask" else T.mask_data({"k": [text, ["x", text]]})
print(len(json.dumps(out)))
"""


def run_masked(fn: str, prefix: str, fill: str, n: int, suffix: str = "", timeout: float = 10.0):
    """mask()/mask_data() on prefix + fill*n + suffix in a child process; the child's stdout, or TimeoutExpired."""
    spec = json.dumps({"fn": fn, "prefix": prefix, "fill": fill, "n": n, "suffix": suffix})
    r = subprocess.run([sys.executable, "-I", "-c", CHILD, str(DISTILL)], input=spec, capture_output=True,
                       text=True, encoding="utf-8", timeout=timeout, check=True)
    return r.stdout.strip()


BS = "\\"
# (id, prefix, suffix, why this shape): the run of backslashes sits where ARGV_USER_RE repeats its group.
SHAPES = [
    ("reported", '"-u", "', "", "the shape from the report: a run of backslashes after the opening quote, then the end"),
    ("bracketed", '["curl","-u","', "", "the same inside an argument list written without spaces"),
    ("user-side-colon", '"-u", "a:', "", "after the colon the second repeated group takes the run"),
    ("then-quote", '"-u", "', '"x', "a closing quote after the run: the match fails late, after the whole run was tried"),
    ("then-newline", '"-u", "', "\n", "a newline after the run: the group stops there and the lookahead fails"),
    ("escaped-form", '\\"-u\\", \\"', "", "the json.dumps form, where every quote carries a backslash"),
    ("single-quotes", "'-u', '", "", "single quotes, the Python repr form"),
]


@pytest.mark.parametrize("fn", ["mask", "mask_data"])
@pytest.mark.parametrize("shape", SHAPES, ids=[s[0] for s in SHAPES])
def test_backslash_run_terminates(fn, shape):
    """N=200 backslashes: the vulnerable regex needs about 2**100 steps, so any cap fails it; 10 s leaves headroom
    for a slow Windows runner (the fixed code takes milliseconds)."""
    _id, prefix, suffix, _why = shape
    try:
        run_masked(fn, prefix, BS, 200, suffix, timeout=10.0)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{fn}() did not finish in 10 s on {_id} (exponential backtracking)")


@pytest.mark.parametrize("n", [20000, 200000])
@pytest.mark.parametrize("shape", SHAPES[:3], ids=[s[0] for s in SHAPES[:3]])
def test_long_backslash_run_is_linear(shape, n):
    """Terminating at N=200 is not linear: a very long run must also finish (and the digest of it must be sound)."""
    _id, prefix, suffix, _why = shape
    try:
        run_masked("mask", prefix, BS, n, suffix)
    except subprocess.TimeoutExpired:
        pytest.fail(f"mask() did not finish in 10 s on {_id} with {n} backslashes")


# Hostile inputs for the other rules (the audit of issue #196): each must finish in 10 s at 200k characters.
# (id, prefix, fill, suffix, why)
OTHER_RULES = [
    ("email-dots", "", "a.", "", "EMAIL_RE: every word boundary is a start that scans the rest of the run"),
    ("email-no-at", "", "a", "", "EMAIL_RE: one long run of local-part characters with no @"),
    ("auth-spaces", "authorization:", " ", "x", "AUTH_HEADER_RE: a long run of blanks after the colon"),
    ("curl-u-spaces", "-u", " ", "x", "CURL_USER_RE: a long run of blanks after the flag"),
    ("curl-u-open-quote", '-u "', "a", "", "CURL_USER_RE: a quoted credential never closed"),
    ("privkey-open", "-----BEGIN PRIVATE KEY-----", "a", "", "PRIVATE_KEY_RE: a block never closed"),
    ("home-long", "C:\\Users\\", "a", "", "HOME_RE: a long user-name segment"),
    ("many-flags", "", "-u ", "", "CURL_USER_RE: a flag at every third character"),
    ("many-argv-openers", "", '"-u", "a', "", "ARGV_USER_RE: an opener at every start"),
    ("many-argv-colon-bs", "", '"-u", "a:\\', "", "ARGV_USER_RE: opener, colon and a backslash, repeated"),
    # Review of #207: the patterns ported from inspector, with inspector's own hostile shapes (test_decide_scrub.py)
    ("bearer-repeats", "", "bearer ", "", "BEARER_RE: a start at every word, each short of 16"),
    ("bearer-long-blanks", "Bearer", " ", "x", "BEARER_RE: a long run of blanks after the word"),
    ("x-api-key-repeats", "", "x-api-key:", "", "X_API_KEY_RE: a name and sign at every start"),
    ("x-api-key-quotes", "", '"x-api-key"\\"', "", "X_API_KEY_RE: quoted names with escaped quotes"),
    ("x-api-key-blanks", "x-api-key", " ", "=", "X_API_KEY_RE: a long run of blanks before the sign"),
    ("token-prefixes", "", "npm_sk_live_AIza", "", "TOKEN_RE: a prefix at every start, none long enough"),
]


@pytest.mark.parametrize("rule", OTHER_RULES, ids=[r[0] for r in OTHER_RULES])
def test_other_rules_linear_at_200k(rule):
    _id, prefix, fill, suffix, _why = rule
    n = 200000 // max(1, len(fill))
    try:
        run_masked("mask", prefix, fill, n, suffix)
    except subprocess.TimeoutExpired:
        pytest.fail(f"mask() did not finish in 10 s on {_id} at 200k characters")


# Boundary rows: the credential is still masked after the change, and what follows it is kept.
# (id, text, secret that must be gone, text that must remain, why)
PW = "Pw" + "Zx9" * 6
MASK_ROWS = [
    ("plain", '["curl", "-u", "alice:' + PW + '"]', PW, '"]', "baseline: nothing to escape"),
    ("backslash-before-quote", '"-u", "alice:' + PW + '\\"', PW, "", "a backslash before the closing quote escapes it: the quote closes the match"),
    ("backslash-in-user", '"-u", "dom\\alice:' + PW + '", "x"', PW, '"x"', "a single backslash inside the value is part of it"),
    ("two-backslashes-in-user", '"-u", "dom\\\\alice:' + PW + '", "x"', PW, '"x"', "an even run (a pair) inside the value is one escaped backslash"),
    ("three-backslashes-in-user", '"-u", "d\\\\\\a:' + PW + '", "x"', PW, '"x"', "an odd run: a pair and a single one"),
    ("four-then-quote", '"-u", "alice:' + PW + '\\\\\\\\", "x"', PW, '"x"', "an even run before the quote leaves the quote unescaped: the string ends there"),
    ("backslash-before-newline", '"-u", "alice:' + PW + '", "x\\\nnext line', PW, "next line", "a backslash before a newline later in the text does not reach back into the match"),
    ("email-with-underscore", "x_alice@example.com", "alice", "example.com", "keep-pin, passes on old code too: `_` is in the local-part class, so it is masked with the rest of the local part before and after the fix"),
    ("escaped-form", '\\"-u\\", \\"alice:' + PW + '\\"', PW, "", "the json.dumps form"),
]


# Intended behaviour differences of EMAIL_RE (its lookbehind replaces `\b`): (id, text, expected output, why).
# Each row fails on the code before the fix (verified against origin/main's transcript.py).
EMAIL_ROWS = [
    ("leading-hyphen", "-alice@example.com", "[address]@example.com", "the lookbehind takes the leading `-` into the local part; old output kept `-[address]`"),
    ("leading-dot", ".alice@example.com", "[address]@example.com", "the leading `.` is consumed too; old output kept `.[address]`"),
    ("leading-plus", "+alice@example.com", "[address]@example.com", "the leading `+` is consumed too; old output kept `+[address]`"),
    ("leading-percent", "%alice@example.com", "[address]@example.com", "the leading `%` is consumed too; old output kept `%[address]`"),
    ("nonascii-then-underscore", "ü_alice@example.com", "ü[address]@example.com",
     "`\b` never fell between a non-ASCII letter and `_` (both are word characters), so old code missed the address"),
]


@pytest.mark.parametrize("row", EMAIL_ROWS, ids=[r[0] for r in EMAIL_ROWS])
def test_email_leading_punctuation(row):
    sys.path.insert(0, str(DISTILL))
    import transcript as T
    _id, text, expected, _why = row
    assert T.mask(text) == expected


@pytest.mark.parametrize("row", MASK_ROWS, ids=[r[0] for r in MASK_ROWS])
def test_argv_credentials_still_masked(row):
    sys.path.insert(0, str(DISTILL))
    import transcript as T
    _id, text, secret, keep, _why = row
    out = T.mask(text)
    assert secret not in out, out
    assert "[token]" in out or "[address]" in out, out
    if keep:
        assert keep in out, out
