"""The digest's "Blocked or denied" lists calls the host refused, not output that mentions the word (retro distill).

2026-11-25, a digest of a real Claude Code session listed two calls whose output was GitHub's `mergeable_state` field
(`mergeable=true blocked`): both succeeded, and neither was refused. The one real refusal of a later run (the auto
mode classifier denying a command) failed with `is_error`. The rule now: a failed call is listed on the old words; a
call that succeeded only when its first line opens with a refusal; a text transcript (no exit status) keeps the old rule.

The result texts in REAL are copied from that session's transcript (tool_result content and its is_error), cut to
their first lines. The table covers the shapes named in it, not every refusal a host can print.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DISTILL = Path(__file__).resolve().parents[1] / "skills" / "distill" / "scripts"
sys.path.insert(0, str(DISTILL))
import trace as TR  # noqa: E402
import transcript as T  # noqa: E402

DENIAL = ("Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Unauthorized "
          "Access]. If you have other tasks that don't depend on this action, continue working on those.")

# (id, command, result text, is_error, listed?, why)
ROWS = [
    ("field-blocked", "gh api repos/o/r/pulls/201 --jq '\"mergeable=\\(.mergeable) \\(.mergeable_state)\"'",
     "mergeable=true blocked head=80893a1", False, False, "real: GitHub's mergeable_state value, the call succeeded"),
    ("field-blocked-lines", "gh api repos/o/r/pulls/197 --jq ...; gh api .../check-runs --jq ...",
     "mergeable=true blocked\npytest in_progress null", False, False, "real: the same field on the first of several lines"),
    ("classifier-denial", "grep -n ... transcript.py; touch /x", DENIAL, True, True,
     "real: Claude Code's auto mode classifier refused the command"),
    ("failed-permission-denied", "cat /root/secret", "cat: /root/secret: Permission denied", True, True,
     "the shell's own refusal, the call failed"),
    ("ok-ssh-denied-in-a-chain", "git push origin x; echo done", "git@github.com: Permission denied (publickey).", False, True,
     "a refusal on the first line of a chain whose last command succeeded, so the call reports done"),
    ("ok-proxy-request-blocked", "curl -s https://example.invalid/x", "request blocked: no rule allows host", False, True,
     "the session proxy's refusal arrives as a body; curl itself exits 0"),
    ("ok-word-denied-in-log", "grep -c denied app.log", "12 lines denied by the WAF rule were counted", False, False,
     "a successful search whose output mentions the word"),
    ("ok-grep-quotes-the-phrases", "grep -n PROBLEM_RE transcript.py",
     'transcript.py:355:PROBLEM_RE = re.compile(r"\\b(failed|was blocked|were blocked|requires approval|permission denied"',
     False, False, "real (step 144 of the same session): a search whose output quotes the refusal phrases"),
    # Review of #205: shapes a call reported done can open with (`cmd 2>&1 | head`, `cmd; echo done` exit 0)
    ("ok-shell-two-prefixes", "cat /root/secret 2>&1 | head", "cat: /root/secret: Permission denied", False, True,
     "the shell's own refusal: `prog: path: ` is two prefixes"),
    ("ok-ls-directory", "ls /root; echo done", "ls: cannot open directory '/root': Permission denied", False, True,
     "the refusal at the end of the line, after a phrase"),
    ("ok-git-remote", "git push origin x || true", "remote: Permission to o/r.git denied to bot.", False, True,
     "git's refusal of a push"),
    ("ok-gh-403", "gh api repos/o/r/hooks || true", "HTTP 403: Resource not accessible by integration (https://api.github.com/repos/o/r/hooks)", False, True,
     "gh's 403: `HTTP 403`, no slash"),
    ("ok-git-403", "git fetch || true", "fatal: unable to access 'https://x/r.git/': The requested URL returned error: 403", False, True,
     "git over HTTPS: the 403 at the end of the line"),
    ("ok-error-403-forbidden", "curl -s https://x/a", "Error: 403 Forbidden", False, True, "a body that says so"),
    ("ok-grep-forbidden-file", "grep -rn x .", "forbidden_words.py:3:x = 1", False, False,
     "a file name that starts with the word"),
    ("ok-number-403", "wc -l log", "403 lines", False, False, "a count that happens to be 403"),
    ("ok-word-permission", "git log -1", "fix: check permission before writing the cache", False, False,
     "a commit subject that says `permission`"),
]


def session_file(tmp: Path, rows: list) -> Path:
    lines = []
    for n, (_id, cmd, text, err, _listed, _why) in enumerate(rows):
        tid = f"toolu_{n:03d}"
        lines.append({"type": "assistant", "timestamp": f"2026-11-25T10:{n:02d}:00Z", "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}})
        lines.append({"type": "user", "timestamp": f"2026-11-25T10:{n:02d}:30Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}]}})
    f = tmp / "run.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return f


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
def test_blocked_lists_refusals_only(tmp_path, row) -> None:
    d = TR.digest(T.load(session_file(tmp_path, [row])))
    assert d["stats"]["calls"] == 1
    assert bool(d["blocked"]) == row[4], d["blocked"]


def test_the_real_session_shape_lists_only_the_denial(tmp_path) -> None:
    real = [r for r in ROWS if r[5].startswith("real")]
    d = TR.digest(T.load(session_file(tmp_path, real)))
    assert [b["step"] for b in d["blocked"]] == [3], d["blocked"]


def test_a_text_transcript_keeps_the_word_rule(tmp_path) -> None:
    # A pasted chat has no exit status (Call.ok is None): the words are all there is to go on.
    c = T.Call("1", "Bash", {"command": "git push"}, result="push was denied: protected branch")
    assert TR.refused(c)
    assert not TR.refused(T.Call("2", "Bash", {"command": "ls"}, result="a.txt b.txt"))
