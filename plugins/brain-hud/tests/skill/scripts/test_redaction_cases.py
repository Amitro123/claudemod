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


# Issue #184. Broken invariant: "a secret is introduced by keyword= / keyword: / a flag + whitespace and is one
# whitespace-free word or a fully quoted string". False when the separator is a space after a subcommand, the keyword
# is a query parameter named only key/sig, the key itself is quoted, or the value's quoting is partial, empty on one
# side, attached to the flag, escaped or cut off. Python-only (journal.ts has the same gaps; follow-up), so these
# are not in the shared redaction-cases.ts. Each row: text, the substrings that must be gone, why.
FAKE = "abcd1234efgh"
HEX40 = "0123456789abcdef0123456789abcdef01234567"
REDACT = [
    ("aws configure set aws_secret_access_key " + FAKE, [FAKE], "space separator after a subcommand"),
    ("aws configure set --profile p aws_secret_access_key " + FAKE, [FAKE], "flag before the name"),
    ("aws configure set aws_secret_access_key " + FAKE + " --profile p", [FAKE], "flag after the value"),
    ("aws configure set aws_session_token " + FAKE, [FAKE], "another keyword name, same subcommand"),
    ("npm config set //registry.npmjs.org/:_authToken " + FAKE, [FAKE], "name holds a colon and slashes"),
    ("curl https://x?key=" + FAKE, [FAKE], "key is a query parameter"),
    ("curl https://x?sig=" + FAKE, [FAKE], "sig is a query parameter"),
    ("curl https://x?signature=" + FAKE, [FAKE], "long spelling of sig"),
    ("curl 'https://x?a=1&sig=" + FAKE + "'", [FAKE], "after another parameter, quote ends the value"),
    ("curl https://x?Key=" + FAKE, [FAKE], "upper-case name"),
    ('curl -u alice:"pa ss" https://x', ["pa ss", 'ss"', "pa"], "quoted password with a space"),
    ('curl -u "alice:S3cr', ["S3cr"], "cut by a length limit, no closing quote"),
    ("curl -u 'alice:S3cr", ["S3cr"], "single-quoted cut-off"),
    ('curl -u "alice:', ["alice"], "cut right after the colon"),
    ('curl -u "alice:pa"ss', ["pa", "ss"], "cut in the middle of a password holding a quote"),
    ("curl -u :" + FAKE + " https://x", [FAKE], "empty user (a PAT as the password)"),
    ("curl -u " + FAKE + ": https://x", [FAKE], "empty password (the key is the secret)"),
    ("curl -ualice:" + FAKE + " https://x", [FAKE], "attached form, no space after -u"),
    ('curl -u \\"alice:' + FAKE + '\\" https://x', [FAKE], "backslash-escaped quotes"),
    ('curl --user="svc:' + FAKE + '"', [FAKE], "long flag with = and quotes"),
    ("curl --user alice:" + FAKE + " https://x", [FAKE], "long flag with a space"),
    ("curl -u a:" + FAKE + ";echo ok", [FAKE], "separator ends the password"),
    ("{'Authorization': 'token " + HEX40 + "'}", [HEX40], "quoted key, token scheme"),
    ("{'authorization': \"Bearer " + FAKE + "\"}", [FAKE], "quoted key, double-quoted value"),
    ('\\"Authorization\\": \\"token ' + HEX40 + '\\"', [HEX40], "escaped JSON quoting"),
    ("curl --ntlm -u DOMAIN\\user:" + FAKE + " https://x", [FAKE], "backslash in a Windows/NTLM user name"),
    ("aws  configure  set aws_secret_access_key " + FAKE, [FAKE], "more than one space between words"),
    ("npm config set -g //registry.npmjs.org/:_authToken " + FAKE, [FAKE], "flag with no value"),
    ("npm config set --global //registry.npmjs.org/:_authToken " + FAKE, [FAKE], "long flag with no value"),
    ("npm config set --location=user //registry.npmjs.org/:_authToken " + FAKE, [FAKE], "flag written with ="),
    ("aws configure set --profile=p aws_secret_access_key " + FAKE, [FAKE], "profile flag written with ="),
    ('curl -u "alice":"' + FAKE + '" https://x', [FAKE], "user and password quoted separately"),
]
# Text that is not a secret and must come back byte-identical.
KEEP = [
    ("git push -u origin main", "-u is --set-upstream, no colon"),
    ("sudo -u bob ls", "-u is a user name, no colon"),
    ("aws configure set region us-east-1", "name has no secret keyword"),
    ("npm config set registry https://registry.npmjs.org/", "name has no secret keyword"),
    ("press any key to continue", "prose, no = after key"),
    ("set key=value pairs", "key= not preceded by ? or &"),
    ("curl https://x?keyword=abc", "key must be the whole parameter name"),
    ("git show 3f2a9c1", "a hash alone is not a secret"),
    ("curl -u alice", "no colon, no secret"),
]


def test_issue_184_forms_are_redacted():
    left = [(t, why, out) for t, secrets, why in REDACT
            if any(s in (out := redact_secrets(t)) for s in secrets)]
    assert left == []


def test_issue_184_plain_lines_are_kept():
    assert [(t, why) for t, why in KEEP if redact_secrets(t) != t] == []


def test_cut_off_value_keeps_the_next_line():
    # A cut-off quoted value runs to the end of its own line only.
    out = redact_secrets('curl -u "alice:S3cr\nnext line stays')
    assert "S3cr" not in out and "next line stays" in out


def test_dash_u_does_not_cross_a_newline():
    assert "alice:pw" in redact_secrets("sudo -u\nalice:pw")


def test_separator_and_url_after_credentials_are_kept():
    assert "echo ok" in redact_secrets("curl -u a:pw;echo ok")
    assert "https://x" in redact_secrets('curl -u a:"p w" https://x')
