"""Pins for the defects found while merging the external 0.3.1 patch with the faster collector."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "skills/inspect/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))
import crosscheck
import evidence
import handoff
import normalize
import snapshot
from test_crosscheck import EV, card
from test_evidence import commit, new_repo


@pytest.fixture(scope="module")
def collected(tmp_path_factory):
    repo = new_repo(tmp_path_factory.mktemp("integ") / "repo")
    commit(repo, {"a.py": "value = 123456789\n"}, "Initial helper")
    commit(repo, {"a.py": "value = 987654321\n"}, "fix: wrong value")
    return repo, evidence.investigate(str(repo))


def test_all_digit_commit_prefix_is_not_a_pr_number():
    assert crosscheck.same_unit("1234567", "1234567890abcdef")      # 7 digits: a commit prefix
    assert not crosscheck.same_unit("12", "123")                    # PR ids stay exact
    assert not crosscheck.same_unit("#1234567", "1234567890abcdef")  # an explicit # is a PR


def test_crosscheck_still_prints_the_report_when_the_json_cannot_be_saved(tmp_path, capsys, monkeypatch):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps(EV))
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert crosscheck.main(["--evidence", str(ev), "--cards", "-", "--json", str(tmp_path)]) == 1
    assert "Cross-check" in capsys.readouterr().out


def test_handoff_still_prints_the_list_when_the_file_cannot_be_saved(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert handoff.main(["--cards", "-", "--out", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip()


@pytest.mark.slow
def test_snapshot_records_the_effective_excludes_and_requested_ref(collected):
    _, ev = collected
    assert "excludes" in ev["snapshot"]["options"]
    assert ev["ref_requested"] == "HEAD" and ev["ref"] == ev["ref_sha"] and len(ev["ref_sha"]) == 40


@pytest.mark.slow
def test_changed_plugin_can_be_read_with_a_warning_when_asked(collected, monkeypatch):
    import copy
    _, ev = collected
    ev = copy.deepcopy(ev)
    ev["snapshot"]["plugin"]["fingerprint"] = "old"
    with pytest.raises(ValueError, match=snapshot.ALLOW_PLUGIN_CHANGE):
        snapshot.validate(ev)
    monkeypatch.setenv(snapshot.ALLOW_PLUGIN_CHANGE, "1")
    _, warnings = snapshot.validate(ev)
    assert any("reading it anyway" in w for w in warnings)


@pytest.mark.slow
def test_a_ref_that_looks_like_an_option_is_refused(collected):
    repo, _ = collected
    with pytest.raises(ValueError, match="not a ref"):
        evidence.investigate(str(repo), ref="--output=x")


@pytest.mark.slow
def test_normalizer_blanks_only_the_volatile_plugin_fields(collected):
    _, ev = collected
    n = normalize.normalize_json(ev)
    assert n["snapshot"]["plugin"] == {"path": "<PLUGIN>", "fingerprint": "<FINGERPRINT>", "version": "<VERSION>"}
    assert n["snapshot"]["options"] == ev["snapshot"]["options"] and n["snapshot"]["schema"] == 1


@pytest.mark.parametrize("script,args", [("evidence.py", ["--help"]), ("crosscheck.py", ["--help"]),
                                         ("handoff.py", ["--help"]), ("doctor.py", ["--help"])])
def test_scripts_run_from_another_directory_in_isolated_mode(tmp_path, script, args):
    # -I drops the script folder from sys.path: the strictest import check (plain runs are a subset)
    cmd = [sys.executable, "-X", "utf8", "-I", str(SCRIPTS / script), *args]
    r = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
