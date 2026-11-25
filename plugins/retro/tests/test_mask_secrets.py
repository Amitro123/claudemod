"""retro mask(): the credential shapes a transcript contains (issue #183, promise P21).

Broken invariant: "TOKEN_RE and the Bearer rule cover the credential shapes a transcript contains". The list was
written for ghp_/gho_ and a Bearer scheme only; ghu_/ghs_/ghr_, Authorization headers of any scheme and
`curl -u user:pass` passed through. Fake values are built at runtime so no literal secret sits in the repository."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DISTILL = ROOT / "skills" / "distill" / "scripts"
sys.path.insert(0, str(DISTILL))

import trace as TR  # noqa: E402
import transcript as T  # noqa: E402

BODY = "Q7" * 15            # 30 alphanumerics
B64 = "Zm9vYmFy" * 4        # a Basic credential shape
PW = "Pw" + "Zx9" * 6       # a password
STRIPE = "sk_" + "live_" + BODY  # an API key used as the user name

# (id, text, secret that must be gone)
FORMS = [
    ("ghp", "token ghp_" + BODY + " end", BODY),
    ("gho", "token gho_" + BODY + " end", BODY),
    ("ghu", "token ghu_" + BODY + " end", BODY),
    ("ghs", "token ghs_" + BODY + " end", BODY),
    ("ghr", "token ghr_" + BODY + " end", BODY),
    ("auth-bearer", "curl -H 'Authorization: Bearer " + BODY + "' https://x", BODY),
    ("auth-basic", "Authorization: Basic " + B64, B64),
    ("auth-token", "Authorization: token " + BODY, BODY),
    ("curl-u", "curl -u alice:" + PW + " https://x", PW),
    ("auth-basic-quoted-key", 'headers={"Authorization": "Basic ' + B64 + '"}', B64),
    ("auth-token-quoted-key", "headers={'Authorization': 'token " + "ab12" * 10 + "'}", "ab12" * 10),
    # review round 2: an empty side of the colon, schemes beyond bearer/basic/token, the argument-list form
    ("curl-u-empty-user", "curl -u :" + PW + " https://x", PW),                              # Azure DevOps: PAT as password
    ("curl-u-empty-password", "curl https://api.stripe.com/v1/charges -u " + STRIPE + ": ", STRIPE),  # Stripe: key as user
    ("auth-negotiate", "Authorization: Negotiate " + B64, B64),
    ("auth-ntlm", "Authorization: NTLM " + B64, B64),
    ("argv-list", 'run(["curl", "-u", "alice:' + PW + '", "https://x"])', PW),
    ("argv-list-user-eq", "['curl', '--user=alice:" + PW + "', 'https://x']", PW),
    # 2026-11-25 inspector run (lead on transcript.py:457-459): shapes the inspector's copy of this masker (decide.py)
    # gained in #199 and retro did not. Each fails on the code before this change.
    ("bearer-lowercase", "curl -H 'bearer " + BODY + "' https://x", BODY),        # no Authorization name, scheme in lower case
    ("bearer-uppercase", "BEARER " + BODY, BODY),
    ("x-api-key-header", "curl -H 'x-api-key: " + BODY + "' https://x", BODY),    # Anthropic, many REST APIs
    ("x-api-key-json", '{"X-Api-Key": "' + BODY + '"}', BODY),                    # the header name quoted, in a dict
    ("x-api-key-equals", "X-API-KEY=" + BODY, BODY),
    ("npm-token", "//registry.npmjs.org/ token npm_" + "Q7" * 18, "Q7" * 18),
    ("stripe-live-key", "key " + STRIPE, BODY),
    ("stripe-restricted-test", "rk_" + "test_" + BODY, BODY),
    ("google-api-key", "key=AIza" + "Q7" * 17 + "Z", "Q7" * 17 + "Z"),             # 35 characters after AIza
    ("aws-session-key-id", "ASIA" + "Q7ZX" * 4, "Q7ZX" * 4),                       # temporary credentials (STS)
]


@pytest.mark.parametrize("text,secret", [(t, s) for _, t, s in FORMS], ids=[i for i, _, _ in FORMS])
def test_mask_hides_each_form(text, secret):
    assert secret not in T.mask(text)


def digest_dict(text: str) -> dict:
    return {"final": text, "notes": [text, {"k": text}]}


@pytest.mark.parametrize("text,secret", [(t, s) for _, t, s in FORMS], ids=[i for i, _, _ in FORMS])
def test_mask_hides_each_form_in_both_digest_formats(text, secret):
    d = digest_dict(text)
    assert secret not in T.mask(json.dumps(d))          # text path over serialized data
    assert secret not in json.dumps(T.mask_data(d))     # JSON digest path


@pytest.mark.parametrize("text,secret", [(t, s) for _, t, s in FORMS], ids=[i for i, _, _ in FORMS])
def test_trace_cli_markdown_and_json_hide_each_form(tmp_path, text, secret):
    # one file per form: the text is the last paragraph, so it is the digest's `final` and reaches the output
    f = tmp_path / "run.md"
    f.write_text("Do it.\n\n" + text + "\n", encoding="utf-8")
    md = subprocess.run([sys.executable, str(DISTILL / "trace.py"), str(f)], capture_output=True, text=True, encoding="utf-8")
    assert md.returncode == 0 and secret not in md.stdout
    js = subprocess.run([sys.executable, str(DISTILL / "trace.py"), "--json", str(f)], capture_output=True, text=True, encoding="utf-8")
    assert js.returncode == 0
    json.loads(js.stdout)
    assert secret not in js.stdout


@pytest.mark.parametrize("text", [
    "sudo -u bob ls",
    "git push -u origin main",
    "Authorization is required",
    "ghx_abc",
    "the gh command and ghost words",
], ids=["sudo-u", "git-push-u", "authorization-prose", "ghx-prefix", "gh-in-prose"])
def test_plain_text_is_unchanged(text):
    assert T.mask(text) == text


# Each case names why it was chosen. This covers the named shapes only, not every variant.
BOUNDARY = [
    ("short-token-stays", "ghs_" + "ab" * 5, "ghs_" + "ab" * 5, None),                  # under 20 chars: not a token shape
    ("user-equals-form", "curl --user=alice:" + PW + " https://x", None, PW),            # --user=value, no space
    ("quoted-password-with-space", 'curl -u "alice:pa ss' + PW + '" https://x', None, "ss" + PW),  # space inside quotes
    ("lowercase-header", "authorization: bearer " + BODY, None, BODY),                   # case-insensitive
    ("header-no-scheme", "Authorization: " + BODY, None, BODY),                          # raw value after the colon
    ("token-in-url", "git clone https://x:ghs_" + BODY + "@github.com/o/r", None, BODY),  # embedded in a URL
    ("powershell-header", 'Invoke-WebRequest -H "Authorization: Bearer ' + BODY + '" https://x', None, BODY),
    ("curl-u-cut-inside-quote", 'curl -H x -u "alice:' + PW[:6], None, PW[:6]),             # Call.brief() cuts at 160 chars
    ("curl-u-single-quote-cut", "curl -u 'alice:" + PW[:6], None, PW[:6]),                  # same cut, single quote
    ("curl-u-quote-in-password", 'curl -u alice:pa"' + PW + " https://x", None, PW),        # quote char inside password
    ("curl-u-attached", "curl -ualice:" + PW + " https://x", None, PW),                     # short form without a space
    ("header-split-lines", "Authorization:\nnext line", "next line", None),                 # match stays on one line
    # review round 2
    ("curl-u-empty-both", "curl -u : https://x", None, None),                               # a bare colon: nothing to hide, must not crash
    ("curl-u-docker-uid-gid", "docker run -u 1000:1000 img", "img", "1000:1000"),            # MASKED on purpose: uid:gid is the shape of user:pass; over-masking is the safe side
    ("curl-u-no-colon-stays", "curl -u alice https://x", "curl -u alice https://x", None),   # no colon: curl prompts for the password, nothing to hide
    ("json-in-markdown-closing-quote", '{"cmd": "curl -u alice:' + PW + '", "y": 1}', '[token]", "y": 1}', PW),  # the quote that closes the string stays
    ("json-in-markdown-single-quote", "{'cmd': 'curl -u alice:" + PW + "', 'y': 1}", "[token]', 'y': 1}", PW),
    ("curl-u-in-parens", "(curl -u alice:" + PW + ")", None, PW),                            # a credential before a close paren is still hidden
    ("auth-any-scheme-unquoted", "Authorization: Digest " + B64 + " https://x", None, B64),  # an unknown scheme word is consumed with its value
    ("auth-scheme-word-only-line", "Authorization: Bearer\nnext", "next", None),            # scheme with no value: stays on its line
    # 2026-11-25 parity with the inspector copy: prose and short names stay readable
    ("bearer-in-prose", "the bearer of bad news", "the bearer of bad news", None),            # under 16 characters after the word
    ("npm-word-stays", "run npm_install and npm_config_cache", "run npm_install and npm_config_cache", None),  # under 30
    ("stripe-short-stays", "sk_" + "live_ab", "sk_" + "live_ab", None),                       # under 10 after the prefix
    ("x-api-key-in-prose", "send the x-api-key header", "send the x-api-key header", None),   # no `:` or `=`: no value
]


@pytest.mark.parametrize("text,keep,gone", [(t, k, g) for _, t, k, g in BOUNDARY], ids=[i for i, *_ in BOUNDARY])
def test_boundary_cases(text, keep, gone):
    out = T.mask(text)
    if keep is not None:
        assert keep in out
    if gone is not None:
        assert gone not in out


def test_unterminated_quote_masks_to_end_of_line_only():
    out = T.mask('curl -u "alice:' + PW + " https://x\nnext line")
    assert PW not in out
    assert "next line" in out   # the match never runs past its line


def test_header_inside_json_string_stays_valid_json():
    d = {"cmd": 'curl -H "Authorization: Bearer ' + BODY + '" -u "alice:' + PW + '" https://x'}
    raw = json.dumps(T.mask_data(d))
    back = json.loads(raw)
    assert BODY not in raw and PW not in raw and "https://x" in back["cmd"]
    # the masked JSON text itself (not per string) also keeps its quotes
    assert json.loads(T.mask(json.dumps({"c": "Authorization: Bearer " + BODY})))


HOST_LAYOUT = ROOT.parent / "brain-hud" / "skills" / "mistake-brain" / "scripts" / "host_layout.py"
PROBES = [
    ("ghp_" + BODY, BODY), ("gho_" + BODY, BODY), ("ghu_" + BODY, BODY), ("ghs_" + BODY, BODY), ("ghr_" + BODY, BODY),
    ("Authorization: Bearer " + BODY, BODY), ("Authorization: Basic " + B64, B64), ("Authorization: token " + BODY, BODY),
    ("curl -u alice:" + PW + " https://x", PW), ("curl --user=alice:" + PW + " https://x", PW),
    ('headers={"Authorization": "Basic ' + B64 + '"}', B64),
    # not a shared probe: brain-hud's redact_secrets keeps a quoted `'Authorization': 'token <hex>'`; retro masks it
    # (test_mask_hides_each_form), and brain-hud is out of this change's scope.
]


def test_retro_mask_and_brain_hud_redact_agree_on_shared_probes():
    spec = importlib.util.spec_from_file_location("host_layout_for_drift_test", HOST_LAYOUT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for text, secret in PROBES:
        assert secret not in T.mask(text), f"retro mask leaks: {text[:30]}"
        assert secret not in mod.redact_secrets(text), f"brain-hud redact leaks: {text[:30]}"


def test_argument_list_in_json_digest_keeps_json_valid_and_hides_credential():
    # mask_data sees "-u" and the credential as two strings of one list: it pairs them (the text rules can't)
    d = {"args": ["curl", "-u", "alice:" + PW, "https://x"], "more": ["--user", ":" + PW]}
    raw = json.dumps(T.mask_data(d))
    back = json.loads(raw)
    assert PW not in raw and back["args"][0] == "curl" and back["args"][3] == "https://x" and len(back["args"]) == 4


def test_call_brief_cut_at_160_chars_still_hides_a_cut_credential():
    cmd = "curl -sS -X POST https://example.invalid/api/very/long/path " + "x" * 80 + " -u alice:" + PW
    brief = T.Call(id="1", tool="Bash", input={"command": cmd}).brief()
    assert len(brief) <= 160
    for cut in (brief, brief[:-3]):
        assert "PwZ" not in T.mask(cut)


# ---- review fixes (PR #193): escaped quotes, backslash in argv text, separators, quadratic time ----
# Broken invariant: "a curl credential is hidden whatever quotes surround it". The quoted branch of CURL_USER_RE
# expected a bare quote, but Call.brief() falls back to json.dumps(input), where the same quote is `\"`.
ESCAPED = [
    ("dq-u", 'curl -u "alice:' + PW + '" https://x'),
    ("dq-user-long", 'curl --user "svc:' + PW + '" https://x'),
    ("dq-empty-user", 'curl -u ":' + PW + '" https://x'),
    ("dq-user-equals", 'curl --user="svc:' + PW + '" https://x'),
    ("sq-u", "curl -u 'alice:" + PW + "' https://x"),
]


@pytest.mark.parametrize("cmd", [c for _, c in ESCAPED], ids=[i for i, _ in ESCAPED])
def test_escaped_quote_credential_is_hidden_everywhere(cmd):
    d = {"cmd": cmd}
    brief = T.Call(id="1", tool="Bash", input=d).brief()   # no "command" key: brief() is json.dumps(input)
    assert "\\\"" in brief or "'" in cmd                   # the form under test really has escaped quotes
    assert PW not in T.mask(brief)
    assert PW not in T.mask(json.dumps(d))
    assert PW not in json.dumps(T.mask_data(d))
    assert "https://x" in T.mask(brief)                    # the rest of the command stays
    assert json.loads(T.mask(json.dumps(d)))["cmd"].endswith("https://x")   # masked JSON text still parses


ARGV_TEXT = [
    ("backslash-password", json.dumps(["curl", "-u", "alice:p\\w" + PW]), "w" + PW),          # JSON text `p\w...`
    ("backslash-ends-password", json.dumps(["curl", "-u", "alice:" + PW + "\\"]), PW),         # `...\\"` closes the string
    ("backslash-in-user", json.dumps(["curl", "--user", "DOM\\alice:" + PW]), PW),
    ("nested-escaped-quotes", json.dumps(json.dumps(["curl", "-u", "alice:" + PW])), PW),     # `[\"curl\", \"-u\", ...]`
]


@pytest.mark.parametrize("text,gone", [(t, g) for _, t, g in ARGV_TEXT], ids=[i for i, *_ in ARGV_TEXT])
def test_argument_list_text_hides_credential_with_backslash(text, gone):
    assert gone not in T.mask(text)


def test_argv_text_scales_linearly_in_colons():
    import time
    times = {}
    for n in (2000, 4000, 8000):
        text = '"-u", "' + ":" * n + "\n"
        t0 = time.perf_counter()
        T.mask(text)
        times[n] = time.perf_counter() - t0
    assert times[8000] < 0.25, times       # was 0.77 s: quadratic in the number of colons


SEPARATORS = [
    # (id, text, must stay, must be gone)
    ("semicolon", "curl -u alice:" + PW + ";echo ok", ";echo ok", PW),                # a shell separator ends the value
    ("pipe", "curl -u alice:" + PW + "|grep x", "|grep x", PW),
    ("ampersand", "curl -u alice:" + PW + "&&echo ok", "&&echo ok", PW),
    ("close-paren", "(curl -u alice:" + PW + ")", ")", PW),
    # DELIBERATE: a comma is a legal password character and the usual separator of prose and JSON; the value runs
    # through it. `,more` is lost, which is the safe side (the credential is whole-hidden, never half-hidden).
    ("comma-consumed", "curl -u alice:" + PW + ",more", None, PW),
    ("comma-no-leak", "curl -u alice:ab,c" + PW, None, PW),
]


@pytest.mark.parametrize("text,keep,gone", [(t, k, g) for _, t, k, g in SEPARATORS], ids=[i for i, *_ in SEPARATORS])
def test_unquoted_credential_stops_at_shell_separators(text, keep, gone):
    out = T.mask(text)
    assert gone not in out
    if keep is not None:
        assert keep in out


def test_argv_list_pairing_over_masks_a_colon_string_on_purpose():
    # DELIBERATE (safe side): mask_data cannot tell a credential from any other colon string after a -u element.
    # Over-masking keeps the JSON valid; a tighter rule would leak `["curl", "-u", ":" + PW]`-style forms.
    out = T.mask_data(["note", "-u", "Time: 10:30", "after"])
    assert out == ["note", "-u", "[token]", "after"]
    assert T.mask_data(["curl", "-u", "alice:" + PW]) == ["curl", "-u", "[token]"]
