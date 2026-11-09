"""Run the inspector's slow test files in parallel, one pytest subprocess per file.

The three lanes (all from the repository root):
  fast lane   python -m pytest plugins/inspector/tests -m "not slow" -q     (seconds, no repository is built)
  slow lane   python plugins/inspector/tests/run_slow.py                    (every slow file at once, one table)
  one file    python -m pytest plugins/inspector/tests/test_evidence.py -m slow -q
Options: --jobs N (default min(4, cpu count)), --keep (keep the output folder), FILE... (run only these files).

Safe to run in parallel: every test builds its repositories under pytest's tmp_path, each file gets its own
--basetemp, and the collector's default cache lives inside each repository's .git. Nothing is shared.
Per-file output goes to a temp folder (printed on failure). Exit code is non-zero if any file failed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# longest first (observed on a loaded machine) so the parallel run is not ended by one late long file
WEIGHT = ["test_github_enrich", "test_evidence", "test_collector_equality", "test_golden_history", "test_snapshot",
          "test_precision", "test_dossier_big", "test_crosscheck", "test_github_utf8", "test_integration_fixes"]


def slow_files() -> list[str]:
    p = subprocess.run([sys.executable, "-m", "pytest", str(HERE), "-m", "slow", "--collect-only", "-q", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    names = sorted({Path(l.split("::")[0]).name for l in p.stdout.splitlines() if "::" in l})
    return sorted(names, key=lambda n: (WEIGHT.index(n[:-3]) if n[:-3] in WEIGHT else len(WEIGHT), n))


def run_one(name: str, work: Path) -> tuple[str, str, float, int]:
    t = time.time()
    log = work / f"{name}.log"
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "pytest", str(HERE / name), "-m", "slow", "-q", "-p", "no:cacheprovider",
                             "--basetemp", str(work / f"tmp-{name}")], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode
    lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return name, (lines[-1] if lines else "no output"), time.time() - t, rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    files = [f if f.endswith(".py") else f + ".py" for f in a.files] or slow_files()
    work = Path(tempfile.mkdtemp(prefix="inspector-slow-"))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        res = list(ex.map(lambda f: run_one(f, work), files))
    w = max(len(r[0]) for r in res)
    print(f"{'file'.ljust(w)}  result  seconds  summary")
    for name, summary, secs, rc in res:
        print(f"{name.ljust(w)}  {'PASS' if rc == 0 else 'FAIL'}    {secs:7.1f}  {summary}")
    bad = [r for r in res if r[3] != 0]
    print(f"{len(res) - len(bad)}/{len(res)} files passed; wall {time.time() - t0:.1f}s; serial sum {sum(r[2] for r in res):.1f}s")
    if bad:
        print(f"logs: {work}")
    elif not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
