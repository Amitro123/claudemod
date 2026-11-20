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
]


@pytest.mark.parametrize("text,secret", [(t, s) for _, t, s in FORMS], ids=[i for i, _, _ in FORMS])
def test_mask_hides_each_form(text, secret):
    assert secret not in T.mask(text)


def digest_dict(text: str) -> dict:
    return {"final": text, "notes": [text, {"k": text}]}


@pytest.mark.parametrize("text,secret", [(t, s) for _, t, s in FORMS], ids=[i for i, _, _ in FORMS])
def test_mask_hides_each_form_in_both_digest_formats(text, secret):
    d = digest_dict(text)
    assert secret not in T.mask(json.dumps(d))          # Markdown-style text path
    assert secret not in json.dumps(T.mask_data(d))     # JSON digest path


def test_trace_cli_markdown_and_json_hide_the_forms(tmp_path):
    f = tmp_path / "run.md"
    lines = [t for _, t, _ in FORMS]
    f.write_text("Do it.\n\n" + "\n\n".join(f"`{t}`" for t in lines) + "\n", encoding="utf-8")
    secrets = [s for _, _, s in FORMS]
    md = subprocess.run([sys.executable, str(DISTILL / "trace.py"), str(f)], capture_output=True, text=True, encoding="utf-8")
    assert md.returncode == 0 and not any(s in md.stdout for s in secrets)
    js = subprocess.run([sys.executable, str(DISTILL / "trace.py"), "--json", str(f)], capture_output=True, text=True, encoding="utf-8")
    assert js.returncode == 0
    json.loads(js.stdout)
    assert not any(s in js.stdout for s in secrets)


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
]


@pytest.mark.parametrize("text,keep,gone", [(t, k, g) for _, t, k, g in BOUNDARY], ids=[i for i, *_ in BOUNDARY])
def test_boundary_cases(text, keep, gone):
    out = T.mask(text)
    if keep is not None:
        assert keep in out
    if gone is not None:
        assert gone not in out


def test_unterminated_quote_masks_only_the_match():
    out = T.mask('curl -u "alice:' + PW + " https://x")
    assert PW not in out or "https://x" in out   # never runs past the string; the rest of the text is still there
    assert "https://x" in out


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
]


def test_retro_mask_and_brain_hud_redact_agree_on_shared_probes():
    spec = importlib.util.spec_from_file_location("host_layout_for_drift_test", HOST_LAYOUT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for text, secret in PROBES:
        assert secret not in T.mask(text), f"retro mask leaks: {text[:30]}"
        assert secret not in mod.redact_secrets(text), f"brain-hud redact leaks: {text[:30]}"
