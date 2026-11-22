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
JWT = ".".join(["ey" + "JhbGciOiJIUzI1NiJ9", "ey" + "JzdWIiOiIx", "c2lnbmF0" + "dXJl"])
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
    # Review round 2 (issue #185).
    ("env assignment, single-quoted value with a space (the tail used to leak)", "DB_PASSWORD='a b' next", "DB_PASSWORD=[token] next"),
    ("env assignment, double-quoted value with a space", 'DB_PASSWORD="a b c" next', "DB_PASSWORD=[token] next"),
    ("env assignment, quote cut off by a limit: masked to the end of the line", "DB_PASSWORD='a b c\nnext line", "DB_PASSWORD=[token]\nnext line"),
    ("env assignment, unterminated at the end of the text", 'API_KEY="a b', "API_KEY=[token]"),
    ("env assignment inside JSON text, escaped quotes", r'{"cmd": "DB_PASSWORD=\"a b\" run"}', '{"cmd": "DB_PASSWORD=[token] run"}'),
    ("lowercase bearer", "curl -H bearer abcdefghijklmnopqrstuvwx url", "curl -H bearer [token] url"),
    ("upper-case BEARER", "BEARER abcdefghijklmnopqrstuvwx", "BEARER [token]"),
    ("x-api-key header, lowercase, in a curl line", "curl -H 'x-api-key: abc123def456' u", "curl -H 'x-api-key: [token]' u"),
    ("X-Api-Key header", "X-Api-Key: abc123def456", "X-Api-Key: [token]"),
    ("X-API-KEY header as a JSON key", '{"X-API-KEY": "abc123"}', '{"X-API-KEY": "[token]"}'),
    ("--password=VALUE", "mysql --password=hunter2 db", "mysql --password=[token] db"),
    ("--password VALUE", "mysql --password hunter2 --x", "mysql --password [token] --x"),
    ("--pass=VALUE", "tool --pass=hunter2", "tool --pass=[token]"),
    ("--password quoted with a space", 'tool --password "a b" run', "tool --password [token] run"),
    ("JSON password", '{"password": "hunter2"}', '{"password": "[token]"}'),
    ("JSON api_key without a space after the colon", '{"api_key":"k1x2"}', '{"api_key":"[token]"}'),
    ("JSON apikey", '{"apikey": "k1x2"}', '{"apikey": "[token]"}'),
    ("JSON client_secret with spaces in the value", '{"client_secret": "a b c"}', '{"client_secret": "[token]"}'),
    ("JSON access_token, single quotes (a Python dict)", "{'access_token': 'x y'}", "{'access_token': '[token]'}"),
    ("JSON password with a quote of the other kind inside", '{"password": "pa\'ss word"}', '{"password": "[token]"}'),
    ("JSON inside a JSON string: backslash-escaped quotes", r'{"msg": "{\"password\": \"hun ter2\", \"ok\": 1}"}',
     r'{"msg": "{\"password\": \"[token]\", \"ok\": 1}"}'),
    ("Azure AccountKey", "DefaultEndpointsProtocol=https;AccountName=a;AccountKey=Zm9vYmFyYmF6cXV4==;EndpointSuffix=core.windows.net",
     "DefaultEndpointsProtocol=https;AccountName=a;AccountKey=[token];EndpointSuffix=core.windows.net"),
    ("Azure SharedAccessKey", "Endpoint=sb://x.servicebus.windows.net/;SharedAccessKeyName=root;SharedAccessKey=Zm9vYmFy+/b=",
     "Endpoint=sb://x.servicebus.windows.net/;SharedAccessKeyName=root;SharedAccessKey=[token]"),
    # Round 3 (issue #185). F1: in plain JSON, Python-dict or shell text a backslash before a quote is an ordinary escape,
    # so the value goes on to the bare closing quote; only the JSON-text shape (\"password\": \"x\") ends at \".
    ("JSON password with an escaped quote inside: the tail used to leak", r'{"password": "a\"SECRETSECRET"}', '{"password": "[token]"}'),
    ("JSON password ending in an escaped backslash", r'{"password": "C:\\"}', '{"password": "[token]"}'),
    ("Python dict password with an escaped apostrophe", r"{'password': 'it\'s SECRETSECRET'}", "{'password': '[token]'}"),
    ("--password double-quoted with an escaped quote", r'tool --password "a\"SECRETSECRET" run', "tool --password [token] run"),
    ("--password shell-quoted apostrophe", r"""tool --password 'it'\''s SECRETSECRET' run""", "tool --password [token] run"),
    ("--password adjacent shell segments form one word", 'tool --password "a b"cd ef run', "tool --password [token] ef run"),
    ("--password inside JSON text, escaped quotes", r'{"cmd": "tool --password \"a b\" run"}', r'{"cmd": "tool --password [token] run"}'),
    # F2: a newline after the colon, more flag names, `=` after an api-key header name, more JSON key names.
    ("JSON password with a newline after the colon", '{"password":\n  "hunter2"}', '{"password":\n  "[token]"}'),
    ("--db-password: the keyword inside the flag name", "mysql --db-password hunter2 db", "mysql --db-password [token] db"),
    ("--client-secret=", "tool --client-secret=abc123", "tool --client-secret=[token]"),
    ("--token VALUE", "tool --token abc123 run", "tool --token [token] run"),
    ("--api-key VALUE", "tool --api-key abc123 run", "tool --api-key [token] run"),
    ("--secret=VALUE", "tool --secret=abc123", "tool --secret=[token]"),
    ("--passphrase VALUE", "tool --passphrase 'a b' run", "tool --passphrase [token] run"),
    ("X-Api-Key=VALUE", "X-Api-Key=abc123def456", "X-Api-Key=[token]"),
    ("x-api-key = VALUE with spaces around the sign", "x-api-key = abc123def456", "x-api-key = [token]"),
    ("JSON secretKey", '{"secretKey": "k1 x2"}', '{"secretKey": "[token]"}'),
    ("JSON privateKey", '{"privateKey": "k1x2"}', '{"privateKey": "[token]"}'),
    ("JSON passphrase", '{"passphrase": "a b"}', '{"passphrase": "[token]"}'),
    ("JSON pwd", '{"pwd": "k1x2"}', '{"pwd": "[token]"}'),
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
    # Review round 2 (issue #185).
    ("prose: a bearer of bad news is under the 16-character minimum", "the bearer of bad news"),
    ("prose: bearer token rotation", "bearer token rotation is due"),
    ("docker login --password-stdin is not --password", "docker login --password-stdin"),
    ("--password followed by another flag has no value to hide", "tool --password --verbose"),
    ("--passphrase-file is not --pass", "ssh-keygen --passphrase-file x"),
    ("JSON null is not a secret value", '{"password": null}'),
    ("JSON key that only starts with password", '{"password_policy": "strict"}'),
    ("JSON key tokens (plural) is not token", '{"tokens": "many"}'),
    ("Azure SharedAccessKeyName is a name, not the key", "SharedAccessKeyName=RootManageSharedAccessKey;Endpoint=sb://x/"),
    ("x-api-key mentioned without a colon", "the x-api-key header is required"),
    ("env name that only contains PASSWORD", "DB_PASSWORD_FILE=/run/secrets/db"),
    # Round 3 (issue #185): a flag whose name holds a keyword but whose next word is not a value.
    ("--password-stdin takes no value: the next word is a redirect", "docker login --password-stdin < pw.txt"),
    ("--password-file: the next word is a path, not the password", "tool --password-file ./p.txt run"),
    ("--password-file=PATH is a path", "tool --password-file=/run/secrets/p run"),
    ("--secret-file: a path", "tool --secret-file ./s.txt run"),
    ("--token-count: a number", "tool --token-count 5 run"),
    ("--max-tokens: a number of LLM tokens", "llm --max-tokens 100 run"),
    ("--tokenizer: a name, not a token", "llm --tokenizer fast run"),
    ("--token-type: a kind of token, not the token", "tool --token-type bearer run"),
    ("--no-password is a boolean flag", "mysql --no-password db"),
    ("--passphrase-file: a path", "ssh-keygen --passphrase-file x"),
    ("JSON key that only starts with pwd", '{"pwd_policy": "strict"}'),
]

# Current deliberate over-masking, written down so a change to it is a decision and not an accident.
OVERMASKED = [
    ("a hyphenated word of 20+ characters after sk- has the shape of a key", "sk-learn-model-version-two-oh", "[token]"),
    ("any 52-character lowercase base32 word has the shape of an Azure DevOps PAT", "x " + "abcdefghij" * 5 + "kl" + " y", "x [token] y"),
    ("docker run -u 1000:1000 has the shape of curl -u user:pw", "docker run -u 1000:1000 img", "docker run -u [token] img"),
    # Round 3 (issue #185): a flag-shaped word in prose is taken for the flag, and the next word for its value.
    ("`--password` in prose: the next word is taken for the value (`flag` is lost)", "--password flag now documented", "--password [token] now documented"),
    ("`--token` in prose: the next word is taken for the value", "the --token expired handling", "the --token [token] handling"),
    ("`--secret-id` is a credential (a Vault secret id), so it is masked like --secret", "vault write --secret-id abc123 run", "vault write --secret-id [token] run"),
    ("a JSON key pwd may be a working directory, but is masked as a password", '{"pwd": "/home/x"}', '{"pwd": "[token]"}'),
]


@pytest.mark.parametrize("reason,text,want", OVERMASKED, ids=[r[0] for r in OVERMASKED])
def test_documented_over_masking(reason, text, want):
    assert decide.scrub(text) == want


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
    "bearer repeats": "bearer " * (N // 7),
    "bearer long": "bearer " + "a" * N,
    "x-api-key repeats": "x-api-key:" * (N // 10),
    "x-api-key quotes": "x-api-key:" + "\"'" * (N // 2),
    "password flag repeats": "--password " * (N // 11),
    "password flag equals": "--pass=" * (N // 7),
    "password flag quote": '--password "' + "a" * N,
    "json key repeats": '"password":"' * (N // 12),
    "json key quotes": '"' * N,
    "json key long prefix": '"' + "a" * N + "password",
    "json key hyphens": '"' + "a-" * (N // 2) + 'token":"',
    "json escaped repeats": r'\"password\":\"' * (N // 15),
    "json value backslashes": '"password":"' + "\\" * N,
    "json value quote kinds": '"password":"' + "'" * N,
    "env quote repeats": "A_TOKEN='" * (N // 9),
    "env quote long": "A_TOKEN='" + "a" * N,
    "env escaped quotes": 'A_TOKEN=\\"' * (N // 10),
    "accountkey repeats": "AccountKey=" * (N // 11),
    "accountkey long": "AccountKey=" + "a" * N,
    "sharedaccesskey repeats": "SharedAccessKey=" * (N // 16),
    "sharedaccesskey name": "SharedAccessKeyName=" * (N // 20),
    # Round 3: the new and changed patterns, each in its worst shape.
    "flag name run": "--" + "password" * (N // 8),
    "flag name hyphens": "--" + "a-" * (N // 2) + "token",
    "flag stdin repeats": "--password-stdin " * (N // 17),
    "flag value quote segments": "--password " + "'a'" * (N // 3),
    "flag value dq segments": "--password " + '"a"' * (N // 3),
    "flag value backslashes": "--password " + "\\" * N,
    "flag dq backslashes": '--password "' + "\\" * N,
    "flag escaped quote long": '--password \\"' + "a" * N,
    "flag escaped quote repeats": '--password \\"' * (N // 13),
    "flag unquoted then quote": "--password " + "a'" * (N // 2),
    "json plain escapes": '"password":"' + '\\"' * (N // 2),
    "json plain escapes repeats": '"password":"a\\"' * (N // 14),
    "json newline colon": '"password":' + "\n" * N,
    "json newline colon repeats": '"password":\n' * (N // 12),
    "json key variants": '"secretKey":"' * (N // 13),
    "json privatekey long": '"' + "a" * N + "privateKey",
    "json escaped long": '\\"password\\":\\"' + "a" * N,
    "x-api-key equals": "x-api-key=" * (N // 10),
    "x-api-key spaces": "x-api-key" + " " * N,
    "x-api-key equals spaces": "x-api-key" + " =" * (N // 2),
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


# A diff of a few megabytes is now masked whole (the cut comes after the mask): still seconds, not minutes.
def test_a_large_diff_is_masked_in_linear_time():
    chunk = "+    value = compute(a, b)  # token refresh, key rotation, password policy\n+    x = {'k': 1}\n"
    big = chunk * (2_000_000 // len(chunk))
    t0 = time.perf_counter()
    decide.scrub(big)
    assert time.perf_counter() - t0 < 6.0


# Round 3 (F3): a hostile 2 MB diff, every new pattern fed its worst shape, is masked in bounded time. Cost, measured on
# 2026-11-22: about 1 s per MB of ordinary text, so 10 s is a generous bound; a quadratic pattern misses it by minutes.
def test_a_hostile_two_megabyte_diff_is_masked_in_bounded_time():
    unit = ('+ --password "a\\"b" \'x\' --db-password y --token-count 3 --password-stdin < f\n'
            '+ {"password":\n "a\\"b", "secretKey": \'it\\\'s\'} x-api-key = k X-Api-Key=v \\"password\\": \\"z\\"\n')
    big = unit * (2_000_000 // len(unit))
    t0 = time.perf_counter()
    out = decide.scrub(big)
    took = time.perf_counter() - t0
    assert took < 10.0, f"2 MB hostile diff took {took:.1f}s"
    assert "[token]" in out and "\"b\"" not in out


# Round 2: the cut at premerge.CAP used to come BEFORE the mask, so a token that straddled it was sent cut to fewer
# than 20 characters after its prefix, which no shape matches. Mask first, then cut.
@pytest.mark.parametrize("keep", [0, 4, 7, 12, 19, 25, 40])
def test_a_token_straddling_the_diff_cap_is_not_sent_in_part(keep):
    # `keep` characters of the token (prefix included) fall before the old cut at CAP
    diff = "x" * (premerge.CAP - keep - 1) + " " + GH + "\n+more\n" * 50
    body, cut = premerge.request_body(diff, "t", "m")
    assert "ghp_" not in body["state"], f"a piece of the token reached the body with {keep} characters before the cut"
    assert cut


def test_a_token_in_the_title_is_masked_too():
    body, _ = premerge.request_body("+a\n", f"fix {GH}", "m")
    assert GH not in body["state"] and "fix [token]" in body["state"]


def test_the_pair_text_cap_does_not_cut_a_token_in_part():
    # a lead's `what` is capped at 1500 characters; a token that straddles the cap must not be left cut in part
    what = "w" * (1500 - 12) + " " + GH
    text = merge_cards._pair_text({"where": "a.py:1", "what": what, "impact": "x"})
    assert "ghp_" not in text
