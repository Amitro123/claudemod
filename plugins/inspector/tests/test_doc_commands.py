"""Documented-command smoke test: the commands the docs tell a reader to run, run as written.

Component tests call functions; the defects found late (a repeated `--sweep` dropping a file, a bad
escape in a card, duplicate leads) showed only when the commands ran the documented way. This test
extracts every fenced or inline command that invokes the plugin's scripts from SKILL.md, references/
and agents/, substitutes the placeholders with a temporary workspace, and runs each one as a real
subprocess (argument list, no shell, timeout). A count floor fails the test if extraction rots.

Commands with prose placeholders that cannot be made concrete, or an inline `...`, are skipped and
listed in the test's output. A bare trailing `...` after a list of paths is dropped (the list stays).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from synth import commit, new_repo  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = PLUGIN / "skills" / "inspect"
SCRIPTS = SKILL / "scripts"
DOC_FILES = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md")), *sorted((PLUGIN / "agents").glob("*.md"))]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
TIMEOUT = 60
FLOOR = 7  # documented commands that must be extracted and run; raise it when the docs gain commands
REQUIRED_SCRIPTS = {"evidence.py", "merge_cards.py", "merge_verdicts.py", "crosscheck.py", "handoff.py", "doctor.py", "plan.py"}


# ---------------------------------------------------------------- fixture workspace
def lead(where, what, **kw):
    d = {"where": where, "what": what, "level": "read", "category": "broken-flow", "reach": "default-on",
         "change": "guard the call", "test": f"a test for {where}"}
    d.update(kw)
    return d


def card(n):
    return {"case": f"#{n}", "unit": f"#{n}", "complete": {"siblings": [
        lead(f"src/c{n}.py:1{n}", f"card {n} sibling with distinct words alpha{n} beta{n} gamma{n}")], "checked_clear": []}}


def sweep(k):
    return [lead(f"src/s{k}.py:{k}0", f"sweep {k} lead with unique tokens delta{k} epsilon{k} zeta{k}")]


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def verdict(where, v="REAL"):
    return {"where": where, "verdict": v, "evidence": "probe", "corrected": {}, "false_claims": []}


ALL_LEADS = [lead("src/c1.py:11", "card 1 sibling with distinct words alpha1 beta1 gamma1"),
             lead("src/c2.py:12", "card 2 sibling with distinct words alpha2 beta2 gamma2"), *sweep(1), *sweep(2), *sweep(3)]
STDIN_CARDS = [card(1), card(2)]


def build_workspace(ws: Path, repo: bool) -> None:
    for n in (1, 2):
        write(ws / "cards" / f"{n}.json", card(n))
    for k in (1, 2, 3):
        write(ws / f"sweep-{k}.json", sweep(k))
    write(ws / "leads.json", ALL_LEADS)
    write(ws / "verdicts-1.json", [verdict(l["where"]) for l in ALL_LEADS[:3]])
    write(ws / "verdicts-2.json", [verdict(l["where"], "NOT REAL") for l in ALL_LEADS[3:]])
    write(ws / "merged.json", [{**l, "verdict": "REAL", "verified_by": "verifier", "false_claims": []} for l in ALL_LEADS])
    (ws / "docs" / "inspector").mkdir(parents=True, exist_ok=True)
    if repo:
        r = new_repo(ws / "repo")
        commit(r, {"README.md": "# demo\n", "src/total.py": "def total(xs):\n    return sum(xs[1:])\n"}, "initial")
        commit(r, {"src/total.py": "def total(xs):\n    return sum(xs)\n"}, "fix: total skipped the first item (#1)")
        commit(r, {"src/total.py": "def total(xs):\n    return sum(xs or [])\n"}, "fix: total crashed on None (#2)")
        ev = ws / "ev"
        run_script("evidence.py", ["--repo", str(r), "--out", str(ev)], cwd=ws)
        assert (ev / "evidence.json").exists()
        (ws / "evidence.json").write_bytes((ev / "evidence.json").read_bytes())
        assert (ev / "plan" / "plan.md").exists(), "the collector wrote the RUN PLAN"
        (ev / "leads.json").write_bytes((ws / "leads.json").read_bytes())  # what merge_cards.py leaves, for `plan.py --phase verify`


def run_script(script: str, args: list[str], cwd: Path, stdin: str | None = None, ok=(0,)):
    p = subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, input=stdin, capture_output=True,
                       text=True, encoding="utf-8", timeout=TIMEOUT, env=ENV)
    assert p.returncode in ok, f"{script} {args}: rc={p.returncode}\n{p.stdout[-800:]}\n{p.stderr[-800:]}"
    return p


@pytest.fixture(scope="module")
def ws(tmp_path_factory) -> Path:
    w = tmp_path_factory.mktemp("docws")
    build_workspace(w, repo=True)
    return w


@pytest.fixture()
def small(tmp_path) -> Path:
    build_workspace(tmp_path, repo=False)
    return tmp_path


# ---------------------------------------------------------------- extraction
SCRIPT_RE = re.compile(r'(?:python3?\s+)?"?(?:<skill_root>/)?scripts/(\w+\.py)"?')
FENCE_RE = re.compile(r"^[ \t]*```[a-z]*\n(.*?)^[ \t]*```", re.S | re.M)
INLINE_RE = re.compile(r"`([^`]+)`")


def _fenced_commands(block: str):
    lines, i = block.split("\n"), 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if "scripts/" not in line or not SCRIPT_RE.search(line):
            continue
        while line.endswith("\\") and i < len(lines):
            line = line[:-1].rstrip() + " " + lines[i].strip()
            i += 1
        stdin = False
        m = re.search(r"<<\s*'?(\w+)'?\s*$", line)
        if m:
            stdin = True
            line = line[:m.start()].strip()
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
            i += 1
        yield line, stdin


def extract() -> list[dict]:
    found = []
    for f in DOC_FILES:
        text = f.read_text(encoding="utf-8")
        rest = FENCE_RE.sub(lambda m: found.extend(
            {"file": f.name, "raw": c, "stdin": s} for c, s in _fenced_commands(m.group(1))) or "", text)
        for m in INLINE_RE.finditer(rest):
            span = " ".join(m.group(1).split())
            sm = SCRIPT_RE.search(span)
            if sm and "--" in span[sm.end():]:  # a bare script name is a mention, not a command
                found.append({"file": f.name, "raw": span, "stdin": False})
    return found


def concretize(c: dict, ws: Path):
    """((script, args, cwd, stdin), "") with placeholders filled, or (None, reason)."""
    m = SCRIPT_RE.search(c["raw"])
    script, tail = m.group(1), c["raw"][m.end():]
    tail = re.sub(r"\[[^\]]*\]", " ", tail)  # optional parts are left out
    for old, new in [("<the saved evidence.json>", (ws / "evidence.json").as_posix()), ("<skill_root>", SKILL.as_posix()),
                     ("<tmp>", ws.as_posix()), ("<out>", (ws / "ev").as_posix()), ("<repo>", (ws / "repo").as_posix()),
                     ("<other-plugin-root>", PLUGIN.as_posix()), ("<YYYY-MM-DD>", "2026-01-01"), ("'#N'", "'#2'")]:
        tail = tail.replace(old, new)
    tail = re.sub(r"<ids of[^>]*>", "1,2", tail)
    tail = re.sub(r"(?<=\s)\.\.\.(?=\s|$)", " ", tail)  # "a b ..." continues a list: keep the list
    if "..." in tail or re.search(r"<[^>]+>", tail):
        return None, f"cannot be made concrete: {c['raw'][:80]}"
    cwd = ws / "repo" if re.search(r"--repo\s+\.(\s|$)", tail) else ws
    return (script, shlex.split(tail), cwd, json.dumps(STDIN_CARDS) if c["stdin"] else None), ""


def test_every_documented_command_runs(ws, capsys) -> None:
    ran, skipped, scripts = [], [], set()
    for c in extract():
        got, why = concretize(c, ws)
        if got is None:
            skipped.append(f"{c['file']}: {why}")
            continue
        script, args, cwd, stdin = got
        build_workspace(ws, repo=False)  # each command starts from the pristine fixture files
        p = subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, input=stdin, capture_output=True,
                           text=True, encoding="utf-8", timeout=TIMEOUT, env=ENV)
        work_left = (script == "plan.py" and "--status" in args and p.returncode == 1  # its answer, not an error
                     and "\nLeft: " in "\n" + p.stdout and not p.stderr.strip())
        assert p.returncode == 0 or work_left, (f"documented command FAILED ({c['file']}): {c['raw']}\nrc={p.returncode}\n"
                                   f"{p.stdout[-600:]}\n{p.stderr[-600:]}")
        ran.append(f"{c['file']}: {script} {' '.join(args)[:70]}")
        scripts.add(script)
    with capsys.disabled():
        print(f"\ndocumented commands run: {len(ran)}, skipped: {len(skipped)}")
        for s in ran + ["SKIPPED " + x for x in skipped]:
            print("  ", s)
    assert len(ran) >= FLOOR, f"only {len(ran)} documented commands ran (floor {FLOOR}); did the extraction rot?"
    assert REQUIRED_SCRIPTS <= scripts, f"no documented command ran for {sorted(REQUIRED_SCRIPTS - scripts)}"


# ---------------------------------------------------------------- explicit multi-flag cases
def wheres(items):
    return {i["where"] for i in items}


def merge(small, *sweep_args, ok=(0,)):
    out = small / "o.json"
    out.unlink(missing_ok=True)
    p = run_script("merge_cards.py", ["--cards", "cards", *sweep_args, "--expect", "1,2", "--out", str(out)], small, ok=ok)
    return p, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


@pytest.mark.parametrize("sweeps", [
    ["--sweep", "sweep-1.json", "--sweep", "sweep-2.json", "--sweep", "sweep-3.json"],
    ["--sweep", "sweep-1.json", "sweep-2.json", "sweep-3.json"],
    ["--sweep", "sweep-1.json", "sweep-2.json", "--sweep", "sweep-3.json"],
    ["--sweep", "sweep-1.json", "--sweep", "sweep-2.json", "sweep-3.json"],
], ids=["repeated", "list", "mixed-a", "mixed-b"])
def test_merge_cards_keeps_every_sweep_file(small, sweeps) -> None:
    p, leads = merge(small, *sweeps)
    assert wheres(leads) == wheres(ALL_LEADS) and len(leads) == 5
    for k in (1, 2, 3):
        assert f"sweep file sweep-{k}.json: 1 leads" in p.stderr
    assert "sweep files loaded: 3" in p.stderr


def test_merge_cards_missing_sweep_exits_2(small) -> None:
    p, leads = merge(small, "--sweep", "sweep-1.json", "--sweep", "nope.json", ok=(2,))
    assert leads is None


def merge_v(small, *verdict_args, ok=(0,), extra=()):
    out = small / "mv.json"
    out.unlink(missing_ok=True)
    p = run_script("merge_verdicts.py", ["--leads", "leads.json", *verdict_args, "--out", str(out), *extra], small, ok=ok)
    return p, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


@pytest.mark.parametrize("args", [
    ["--verdicts", "verdicts-1.json", "--verdicts", "verdicts-2.json"],
    ["--verdicts", "verdicts-1.json", "verdicts-2.json"],
], ids=["repeated", "list"])
def test_merge_verdicts_applies_every_verdict_file(small, args) -> None:
    p, merged = merge_v(small, *args)
    assert {m["verdict"] for m in merged[:3]} == {"REAL"} and {m["verdict"] for m in merged[3:]} == {"NOT REAL"}
    assert "REAL: 3" in p.stderr and "NOT REAL: 2" in p.stderr


def test_merge_verdicts_drop_not_real_and_unknown_where(small) -> None:
    _, merged = merge_v(small, "--verdicts", "verdicts-1.json", "--verdicts", "verdicts-2.json", extra=["--drop-not-real"])
    assert len(merged) == 3 and all(m["verdict"] == "REAL" for m in merged)
    write(small / "bad.json", [verdict("src/nowhere.py:1")])
    merge_v(small, "--verdicts", "verdicts-1.json", "--verdicts", "bad.json", ok=(2,))


def test_lint_leads_file_folder_stdin(small) -> None:
    for src, stdin in [("merged.json", None), ("-", json.dumps(ALL_LEADS))]:
        p = run_script("lint_leads.py", [src], small, stdin=stdin)
        got = {l.split(" | ")[0] for l in p.stdout.splitlines() if " | " in l}
        assert got == wheres(ALL_LEADS), (src, got)  # a read lead without a probe draws one L4 row each: none dropped
    p = run_script("lint_leads.py", ["cards"], small)
    assert {l.split(" | ")[0] for l in p.stdout.splitlines() if " | " in l} == {"src/c1.py:11", "src/c2.py:12"}
    run_script("lint_leads.py", ["-"], small, stdin='[{"where": "a.py:1", "complete": {"siblings": "x"}}]', ok=(2,))
    run_script("lint_leads.py", ["-"], small, stdin="{not json", ok=(2,))


def test_crosscheck_file_folder_stdin(ws) -> None:
    ev = str(ws / "evidence.json")
    for src, stdin, n in [("cards", None, 2), (str(ws / "merged.json"), None, 5), ("-", json.dumps(STDIN_CARDS), 2)]:
        p = run_script("crosscheck.py", ["--evidence", ev, "--cards", src], ws, stdin=stdin)
        assert f"Cards: {n};" in p.stdout, (src, p.stdout[:300])
    run_script("crosscheck.py", ["--evidence", ev, "--cards", "-"], ws, stdin='[{"complete": []}]', ok=(2,))


def handoff(small, *args, stdin=None, ok=(0,)):
    return run_script("handoff.py", ["--cards", *args], small, stdin=stdin, ok=ok)


def rows(p):
    return [l for l in p.stdout.splitlines() if l.startswith("| ") and "`" in l]


def test_handoff_inputs_agree(small) -> None:
    assert len(rows(handoff(small, "merged.json"))) == 5
    assert len(rows(handoff(small, "-", stdin=json.dumps(ALL_LEADS)))) == 5
    assert len(rows(handoff(small, "cards"))) == 2
    assert len(rows(handoff(small, "-", stdin=json.dumps(STDIN_CARDS)))) == 2


def test_handoff_repeated_drop_lower_note(small) -> None:
    p = handoff(small, "merged.json", "--drop", "src/s1.py:10", "--drop", "src/s2.py:20",
                "--lower", "src/c1.py:11=suspect", "--lower", "src/c2.py:12=suspect",
                "--note", "src/s3.py:30=mine", "--note", "src/c1.py:11=also mine", "--out", str(small / "h.md"))
    assert len(rows(p)) == 3 and "src/s1.py:10" not in p.stdout and "src/s2.py:20" not in p.stdout
    assert p.stdout.count("| suspect ") == 2 and p.stdout.count("Note added after the readers") == 2
    assert (small / "h.md").read_text(encoding="utf-8").count("`src/") == 3


def test_handoff_invalid_input_exits_2_and_writes_nothing(small) -> None:
    out = small / "none.md"
    handoff(small, "-", "--out", str(out), stdin='[{"complete": {"siblings": 3}}]', ok=(2,))
    assert not out.exists()
