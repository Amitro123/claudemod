"""OPENROUTER_API_KEY never reaches a report, a message or an exception (issue #186, promise P20).

The invariant: every caller that sends the key (`decide.ask`, `premerge.check`, `merge_cards.ask_pairs`, and the eval
client's `openrouter_decisions` / `openrouter_decide`) either sends a clean key or sends nothing and says why without
the value. Before #186 `premerge` and the eval client used the raw value: a trailing newline made urllib raise
`ValueError: Invalid header value b'Bearer <key>\\n'`, and `premerge` printed that text, key and all.

`post` is a stub that applies the header check urllib applies (`http.client`'s own) and raises the same text, so no
network is used. One test drives the real `decide._post` to a closed local port to pin that text to the library's.
The table covers the shapes named in it, not every malformed value.
"""
from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(PLUGIN / "evals" / "decision-fix"))
import client  # noqa: E402
import decide  # noqa: E402
import merge_cards  # noqa: E402
import premerge  # noqa: E402

KEY = "sk-or-v1-FAKEFAKEFAKE0123456789abcdef"

# (id, value of OPENROUTER_API_KEY, why this shape)
BAD = [
    ("inner-lf", KEY[:12] + "\n" + KEY[12:], "a key pasted across two lines: strip() alone does not help"),
    ("tab", KEY + "\tx", "a pasted `KEY<tab>comment` from a table"),
    ("paste-markers", "\x1b[200~" + KEY + "\x1b[201~", "a terminal's bracketed-paste markers: control bytes urllib does not refuse"),
]
CLEAN = [
    ("plain", KEY, "control: a good key"),
    ("lf", KEY + "\n", "the #186 report: `echo` or a .env line adds a newline; stripped, then sent"),
    ("crlf", KEY + "\r\n", "the same value saved on Windows"),
    ("spaces-around", "  " + KEY + "  ", "spaces around a good key are stripped, the key is sent"),
]


def stub_post(sent: list):
    def post(url, body, headers, *a, **k):
        v = headers["Authorization"]
        if http.client._is_illegal_header_value(v.encode("latin-1")):   # what urllib's putheader checks
            raise ValueError(f"Invalid header value {v.encode('latin-1')!r}")
        sent.append(v)
        return {"error": {"message": "stub: no model here"}}
    return post


def callers(post):
    """Each caller, run once; what it reports (its meta, or the exception it raised) as text."""
    def run(f):
        try:
            return json.dumps(f(), default=str)
        except Exception as e:   # the eval client raises; the text of what it raises is its report
            return f"{type(e).__name__}: {e}"
    return {
        "decide.ask": lambda: run(lambda: decide.ask({"#1": "fix: x"}, post=post)[1]),
        "premerge.check": lambda: run(lambda: premerge.check("diff --git a/x b/x\n+1\n", "t", post=post)["meta"]),
        "premerge.report": lambda: premerge.report(premerge.check("diff --git a/x b/x\n+1\n", "t", post=post)),
        "merge_cards.ask_pairs": lambda: run(lambda: merge_cards.ask_pairs(
            [{"where": "a.py:1", "what": "w"}, {"where": "b.py:1", "what": "w"}], [(0, 1, 0.9, "")], "m", post=post)[1]),
        "client.openrouter_decisions": lambda: run(lambda: client.openrouter_decisions("U", [{"id": "q1", "text": "?"}], post=post)),
        "client.openrouter_decide": lambda: run(lambda: client.openrouter_decide("U", [{"id": "q1", "text": "?"}], "m/x", post=post)),
    }


NAMES = list(callers(None))


@pytest.mark.parametrize("value", [r[1] for r in BAD], ids=[r[0] for r in BAD])
@pytest.mark.parametrize("name", NAMES)
def test_a_malformed_key_is_never_sent_and_never_reported(monkeypatch, name, value) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", value)
    sent: list = []
    out = callers(stub_post(sent))[name]()
    assert KEY[8:20] not in out, f"{name} reported the key: {out[:300]}"
    assert sent == [], "nothing is sent with a key that is not a key"
    assert "OPENROUTER_API_KEY" in out, f"{name} says which variable to fix: {out[:300]}"


@pytest.mark.parametrize("value", [r[1] for r in CLEAN], ids=[r[0] for r in CLEAN])
@pytest.mark.parametrize("name", NAMES)
def test_a_clean_key_is_sent_stripped(monkeypatch, name, value) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", value)
    sent: list = []
    out = callers(stub_post(sent))[name]()
    assert sent and all(v == f"Bearer {KEY}" for v in sent), sent
    assert KEY[8:20] not in out, f"{name} reported the key: {out[:300]}"


@pytest.mark.parametrize("name", NAMES)
def test_no_key_keeps_the_proxy_placeholder(monkeypatch, name) -> None:
    # Out of scope for #186 and unchanged: with no variable the session proxy injects the key.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    sent: list = []
    callers(stub_post(sent))[name]()
    assert sent and all(v == "Bearer set-by-the-session-proxy" for v in sent), sent


def test_the_stub_raises_what_urllib_raises(monkeypatch) -> None:
    # The real _post to a closed local port: urllib refuses the header before it connects, with this text.
    monkeypatch.setattr(decide, "DECISIONS_URL", "http://127.0.0.1:9/")
    with pytest.raises(ValueError) as real:
        decide._post("http://127.0.0.1:9/", {}, {"Authorization": f"Bearer {KEY}\n"}, timeout=2)
    with pytest.raises(ValueError) as stub:
        stub_post([])("u", {}, {"Authorization": f"Bearer {KEY}\n"})
    assert str(real.value) == str(stub.value)
