"""Issue #185: nothing secret may leave the machine in a decision-model request body (P20).

Broken invariant: `decide.scrub()` was documented as the guard for the body sent to openrouter.ai, but it masked only
email addresses, and ran only inside `decide._post`: a token in a commit subject, a PR title or a changed path went
into the body as written, and any other `post` (the injected one, every builder that calls it directly) saw it raw.

Fake values only: tokens are built at run time from short pieces so no secret scanner flags this file.
Run: python -m pytest plugins/inspector/tests/test_decide_scrub.py -q
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import decide  # noqa: E402
import evidence  # noqa: E402
import merge_cards  # noqa: E402
import premerge  # noqa: E402
import synth  # noqa: E402

GH = "ghp_" + "a1B2" * 9                      # 40 characters, the shape of a classic GitHub token
GH_PAT = "github_pat_" + "x9Y8" * 6
SK = "sk-" + "proj-q1W2" * 3
STRIPE = "sk_" + "live_" + "Zz9Y8x7W6v5U4t3S2r1Q"
AKIA = "AKIA" + "ABCD1234EFGH5678"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIx.c2lnbmF0dXJl"
SECRET = "wJalrFake" + "SecretValue1234"

# (reason, text in, text out). One row per shape the issue names, plus the neighbour each pattern could swallow.
MASKED = [
    ("GitHub classic token", f"fix: use {GH} in ci", "fix: use [token] in ci"),
    ("GitHub fine-grained token", f"drop {GH_PAT}", "drop [token]"),
    ("token glued to a word by an underscore (a file name)", f"keys/old_{GH}.json", "keys/old_[token].json"),
    ("sk- key with hyphens inside", f"rotate {SK} now", "rotate [token] now"),
    ("Stripe-style sk_live key", f"set {STRIPE}", "set [token]"),
    ("AWS access key id", f"leaked {AKIA}!", "leaked [token]!"),
    ("JWT", f"cookie {JWT}", "cookie [token]"),
    ("Authorization header, Bearer scheme, single-quoted in a curl line",
     "curl -H 'Authorization: Bearer abc123' x", "curl -H 'Authorization: [token]' x"),
    ("Authorization header, Basic scheme", "Authorization: Basic dXNlcjpwdw==", "Authorization: [token]"),
    ("Authorization header, a scheme nobody lists", "Authorization: Zorp abcdef", "Authorization: [token]"),
    ("Authorization header with a quoted key and value (JSON)", '{"Authorization": "Bearer abc"}',
     '{"Authorization": "[token]"}'),
    ("bare Bearer token", "send Bearer abcdefghijklmnopqrstuvwx", "send Bearer [token]"),
    ("curl -u user:pw", "curl -u alice:s3cret https://x.io", "curl -u [token] https://x.io"),
    ("curl -u with an empty user (Azure DevOps PAT)", "curl -u :pat123 url", "curl -u [token] url"),
    ("curl -u with an empty password", "curl -u bob: url", "curl -u [token] url"),
    ("curl -u attached to the flag", "curl -ualice:pw url", "curl -u[token] url"),
    ("curl -u quoted, with a space in the password", 'curl -u "alice:p w" url', "curl -u [token] url"),
    ("curl --user=", "curl --user=alice:pw url", "curl --user=[token] url"),
    ("argument-list form of curl -u", '["curl", "-u", "alice:pw"]', '["curl", "-u", "[token]"]'),
    ("password inside a URL", "git clone https://bob:hunter2@github.com/o/r.git",
     "git clone https://[token]@github.com/o/r.git"),
    ("?key= query value", "GET /v1/x?key=abc123def456&x=1", "GET /v1/x?key=[token]&x=1"),
    ("&sig= SAS signature", "https://a.blob.core.windows.net/c?sv=2020&sig=Zm9vYmFy%2Bbar%3D&se=1",
     "https://a.blob.core.windows.net/c?sv=2020&sig=[token]&se=1"),
    ("aws configure set secret", f"aws configure set aws_secret_access_key {SECRET}",
     "aws configure set aws_secret_access_key [token]"),
    ("aws configure set with a profile prefix and flag", f"aws configure set profile.dev.aws_secret_access_key {SECRET} --region x",
     "aws configure set profile.dev.aws_secret_access_key [token] --region x"),
    ("aws_secret_access_key assignment", f"aws_secret_access_key = {SECRET}", "aws_secret_access_key = [token]"),
    ("npm config set _authToken", "npm config set //registry.npmjs.org/:_authToken abcd1234efgh",
     "npm config set //registry.npmjs.org/:_authToken [token]"),
    (".npmrc _authToken line", "//registry.npmjs.org/:_authToken=abcd1234efgh", "//registry.npmjs.org/:_authToken=[token]"),
    ("environment assignment of a TOKEN variable", "export GITHUB_TOKEN=abc123def", "export GITHUB_TOKEN=[token]"),
    ("private key block", "add\n-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\nok", "add\n[private-key]\nok"),
    ("email is still masked (the 2026-11-15 content-filter case)", "Co-Authored-By: X <a@b.co>", "Co-Authored-By: X <[address]>"),
]

# Text a reader needs: it must come out byte for byte. Each row names the neighbour a pattern could swallow.
UNCHANGED = [
    ("git push -u is not curl -u", "git push -u origin main"),
    ("sudo -u user has no colon", "sudo -u bob make install"),
    ("a commit hash", "revert a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0"),
    ("prose with key and token", "rotate the API key and fix token refresh"),
    ("a subject that says key and token with a colon", "fix: key rotation, token: expired"),
    ("a pinned version is not an address", "bump react@18.3.1"),
    ("task- is not sk-", "task-force sk-short"),
    ("a path with token in its name", "src/auth/token_store.py (+3/-1)"),
    ("a URL without credentials", "see https://example.com/a?b=1&c=2"),
    ("a bare ?key= with nothing after it", "an empty ?key= is rejected"),
    ("npm config set of a plain setting", "npm config set registry https://r.example.com"),
    ("aws configure set of a plain setting", "aws configure set region us-east-1"),
    ("the word Authorization with no colon", "Authorization header is now optional"),
    ("a lowercase variable is not an env secret", "token=expired handling"),
    ("Windows path and backslashes", r"C:\work\keys\notes.txt"),
]


@pytest.mark.parametrize("reason,text,want", MASKED, ids=[r[0] for r in MASKED])
def test_secret_shapes_are_masked(reason, text, want):
    assert decide.scrub(text) == want
    assert decide.scrub(want) == want                      # idempotent: masking the output changes nothing


@pytest.mark.parametrize("reason,text", UNCHANGED, ids=[r[0] for r in UNCHANGED])
def test_ordinary_text_is_byte_identical(reason, text):
    assert decide.scrub(text) == text


def test_scrub_walks_nested_bodies_and_keys_the_json_valid():
    body = {"state": f"## Unit #1: x {GH}\nnext line", "q": {"k": [f"Bearer {'t' * 20}", 3, None, True]}}
    s = decide.scrub(body)
    assert GH not in json.dumps(s) and "\nnext line" in s["state"] and s["q"]["k"][1:] == [3, None, True]
    assert json.loads(json.dumps(s)) == s


# Hostile 20k-character inputs, one per pattern family: each must finish in well under a second. A pattern with a
# nested unbounded quantifier over overlapping classes takes seconds or minutes on these.
N = 20_000
HOSTILE = {
    "letters": "A" * N,
    "sk- repeated": "sk-" * (N // 3),
    "short gh tokens": "ghp_" + "a" * 19 + " ",
    "colons": ":" * N,
    "url userinfo": "https://" + "a:" * (N // 2),
    "scheme repeats": "x://" * (N // 4),
    "authorization repeats": "Authorization:" * (N // 14),
    "authorization quotes": "Authorization:" + "\"'" * (N // 2),
    "query repeats": "?key=" * (N // 5),
    "amp repeats": "&sig=&" * (N // 6),
    "env words": "TOKEN" * (N // 5),
    "env words with equals": "A_TOKEN=" * (N // 8),
    "jwt start": "eyJ" + "a" * N,
    "jwt dots": "eyJ" + "aaaaaaaaaa." * (N // 11),
    "curl no colon": "curl -u " + "a" * N,
    "curl many flags": "-u " * (N // 3),
    "curl quotes": "curl -u \"" + "a:\"" * (N // 3),
    "argv start": '["-u", "' + "a" * N,
    "argv colons": '["-u", "' + "a:" * (N // 2),
    "argv backslashes": '["-u", "' + "\\" * N,
    "private key begins": "-----BEGIN PRIVATE KEY-----" * (N // 27),
    "base32 run": "a" * N,
    "aws configure repeats": "aws configure set " * (N // 18),
    "aws dotted": "configure set " + "a." * (N // 2),
    "npm repeats": ":_authToken " * (N // 12),
    "spaces": " " * N,
    "email domain dots": "a@" + "a." * (N // 2),
    "email at signs": "a@" * (N // 2),
    "email local part": "a." * (N // 2) + "@",
    "mixed": ("Bearer " + "a" * 15 + " -u a:b ") * (N // 30),
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_hostile_inputs_finish_fast(name):
    text = HOSTILE[name]
    t0 = time.perf_counter()
    decide.scrub(text)
    assert time.perf_counter() - t0 < 1.0, f"{name}: scrub took {time.perf_counter() - t0:.2f}s on {len(text)} characters"


# The real request body, built without a network, from a repository whose history carries tokens in a commit
# subject, a PR title and a changed path.
class Recorder:
    def __init__(self):
        self.bodies: list = []

    def __call__(self, url, body, headers):
        self.bodies.append(body)
        return {"answers": {}}


@pytest.fixture(scope="module")
def token_repo(tmp_path_factory):
    r = synth.new_repo(tmp_path_factory.mktemp("scrub185") / "repo")
    synth.commit(r, {"README.md": "# demo\n"}, "initial")
    synth.merge_pr(r, 1, "feat", [({f"src/keys/{GH}.py": "x = 1\n"}, f"Add loader, token {GH} and {AKIA}")],
                   f"feat: add loader {SK}")
    synth.merge_pr(r, 2, "feat2", [({"src/more.py": "y = 2\n"},
                                    f"Add more\n\nAuthorization: Bearer {'q' * 24}\nCo-Authored-By: Z <z@example.org>")],
                   "feat: more")
    return r


def test_the_collectors_request_body_carries_no_token(token_repo):
    post = Recorder()
    evidence.investigate(str(token_repo), "main", min_lines=1, decision_model="m/x", decide_post=post)
    sent = json.dumps(post.bodies)
    assert post.bodies, "the decision phase sent nothing: the fixture no longer exercises the body"
    assert "Unit #1" in sent and "Add loader" in sent         # the subject stays readable
    for secret in (GH, AKIA, SK, "q" * 24, "z@example.org"):
        assert secret not in sent, f"{secret[:8]}... reached the request body"


def test_unit_text_and_request_body_are_masked_before_post_sees_them():
    text = decide.unit_text("#1", f"t {SK}", [f"s {GH}"], [{"path": f"a/{GH}.py", "ins": 1, "del": 0}], [f"v {AKIA}"])
    body, _ = decide.request_body({"#1": text}, "m")
    assert not any(s in json.dumps(body) for s in (SK, GH, AKIA))


def test_the_premerge_body_carries_no_token():
    post = Recorder()
    premerge.check(f"+++ b/x.py\n+token = '{GH}'\n+curl -u alice:pw url\n", f"fix {SK}", post=post)
    sent = json.dumps(post.bodies)
    assert post.bodies and GH not in sent and SK not in sent and "alice:pw" not in sent


def test_the_merge_cards_pair_body_carries_no_token():
    post = Recorder()
    raw = [{"where": f"src/{GH}.py:1", "what": f"uses {SK}", "impact": "x"}, {"where": "b.py:2", "what": f"Bearer {'r' * 24}", "impact": "y"}]
    merge_cards.ask_pairs(raw, [(0, 1, 0, 0)], "m", post=post)
    sent = json.dumps(post.bodies)
    assert post.bodies and not any(s in sent for s in (GH, SK, "r" * 24))
