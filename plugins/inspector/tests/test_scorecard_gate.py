"""Tests for evals/gate/scorecard_gate.py with synthetic data only."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE_SCRIPT = Path(__file__).parent.parent / "evals" / "gate" / "scorecard_gate.py"
THRESHOLDS_FILE = Path(__file__).parent.parent / "evals" / "gate" / "thresholds.json"


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def run_gate(tmp_path, row=None, history=None, thresholds=None, extra_args=None):
    args = [sys.executable, str(GATE_SCRIPT)]
    if row is not None:
        p = tmp_path / "row.json"
        write_json(p, row)
        args += ["--row", str(p)]
    elif history is not None:
        p = tmp_path / "hist.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in history), encoding="utf-8")
        args += ["--history", str(p)]
    if thresholds is not None:
        t = tmp_path / "thr.json"
        write_json(t, thresholds)
        args += ["--thresholds", str(t)]
    if extra_args:
        args += extra_args
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def good_row():
    return {"precision": 0.95, "not_real": 2, "duplicate_clusters": 1,
            "gold": {"recall": 0.85, "covered": 4, "items": 5},
            "cost": {"cost_per_verified_lead": 1.2}}


def bad_row():
    return {"precision": 0.50, "not_real": 2, "duplicate_clusters": 1,
            "gold": {"recall": 0.60, "covered": 3, "items": 5},
            "cost": {"cost_per_verified_lead": 1.2}}


DEFAULT_THRESHOLDS = {"thresholds": {"precision_min": 0.90, "recall_min": 0.75,
                                      "not_real_max": None, "cost_per_verified_lead_max": None,
                                      "duplicate_clusters_max": None}, "status": "provisional"}


def test_good_row_passes(tmp_path):
    code, out, _ = run_gate(tmp_path, row=good_row(), thresholds=DEFAULT_THRESHOLDS)
    assert code == 0
    assert "All thresholds passed" in out


def test_bad_precision_fails(tmp_path):
    code, out, _ = run_gate(tmp_path, row=bad_row(), thresholds=DEFAULT_THRESHOLDS)
    assert code == 1
    assert "FAIL" in out and "precision_min" in out


def test_bad_recall_fails(tmp_path):
    row = good_row()
    row["gold"]["recall"] = 0.60
    code, out, _ = run_gate(tmp_path, row=row, thresholds=DEFAULT_THRESHOLDS)
    assert code == 1
    assert "recall_min" in out


def test_null_thresholds_are_skipped(tmp_path):
    thr = {"thresholds": {"precision_min": None, "recall_min": None}, "status": "provisional"}
    code, out, _ = run_gate(tmp_path, row=bad_row(), thresholds=thr)
    assert code == 0
    assert "SKIP" in out


def test_history_checks_last_row(tmp_path):
    rows = [bad_row(), good_row()]
    code, out, _ = run_gate(tmp_path, history=rows, thresholds=DEFAULT_THRESHOLDS)
    assert code == 0


def test_history_bad_last_row_fails(tmp_path):
    rows = [good_row(), bad_row()]
    code, out, _ = run_gate(tmp_path, history=rows, thresholds=DEFAULT_THRESHOLDS)
    assert code == 1


def test_missing_gold_fails_configured_recall(tmp_path):
    """A configured recall_min threshold with no gold data must FAIL, not silently skip."""
    row = good_row()
    row["gold"] = None
    code, out, _ = run_gate(tmp_path, row=row, thresholds=DEFAULT_THRESHOLDS)
    assert code == 1
    assert "FAIL" in out and "recall_min" in out and "missing" in out


def test_missing_gold_with_allow_missing_warns(tmp_path):
    """--allow-missing downgrades missing-data to WARNING and exits 0."""
    row = good_row()
    row["gold"] = None
    code, out, _ = run_gate(tmp_path, row=row, thresholds=DEFAULT_THRESHOLDS, extra_args=["--allow-missing"])
    assert code == 0
    assert "WARN" in out and "recall_min" in out
    assert "All thresholds passed" not in out
    assert "could not be checked" in out


def test_missing_precision_fails_by_default(tmp_path):
    """A row with no precision and a configured precision_min must FAIL."""
    row = good_row()
    del row["precision"]
    thr = {"thresholds": {"precision_min": 0.70, "recall_min": None}, "status": "test"}
    code, out, _ = run_gate(tmp_path, row=row, thresholds=thr)
    assert code == 1
    assert "FAIL" in out and "precision_min" in out and "missing" in out


def test_missing_precision_with_allow_missing_warns(tmp_path):
    row = good_row()
    del row["precision"]
    thr = {"thresholds": {"precision_min": 0.70, "recall_min": None}, "status": "test"}
    code, out, _ = run_gate(tmp_path, row=row, thresholds=thr, extra_args=["--allow-missing"])
    assert code == 0
    assert "WARN" in out


def test_all_data_missing_with_configured_thresholds_fails(tmp_path):
    """An empty row against configured thresholds must fail on every configured one."""
    thr = {"thresholds": {"precision_min": 0.70, "recall_min": 0.75}, "status": "test"}
    code, out, _ = run_gate(tmp_path, row={}, thresholds=thr)
    assert code == 1
    assert out.count("FAIL") >= 2


def test_allow_missing_never_says_all_passed(tmp_path):
    """Even with --allow-missing, warnings must not produce 'All thresholds passed'."""
    thr = {"thresholds": {"precision_min": 0.70, "recall_min": 0.75}, "status": "test"}
    code, out, _ = run_gate(tmp_path, row={}, thresholds=thr, extra_args=["--allow-missing"])
    assert code == 0
    assert "WARN" in out
    assert "All thresholds passed" not in out


def test_invalid_input_exits_2(tmp_path):
    code, _, err = run_gate(tmp_path, row="not a dict", thresholds=DEFAULT_THRESHOLDS)
    assert code == 2


def test_default_thresholds_file_is_valid_json():
    data = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    assert "thresholds" in data and isinstance(data["thresholds"], dict)
    assert data.get("status") == "provisional"


def test_report_shows_status_label(tmp_path):
    thr = {"thresholds": {"precision_min": 0.70}, "status": "provisional"}
    _, out, _ = run_gate(tmp_path, row=good_row(), thresholds=thr)
    assert "provisional" in out
