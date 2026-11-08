"""Build the synthetic benchmark repo (once) and run the collector on it with --timing.

    python bench_synthetic.py <repo-dir> <out-dir> [extra evidence.py args]
"""
import subprocess
import sys
from pathlib import Path

import synth

repo, out, extra = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
if not repo.exists():
    synth.build_big(repo)
script = Path(__file__).parent.parent / "skills" / "inspect" / "scripts" / "evidence.py"
sys.exit(subprocess.run([sys.executable, "-X", "utf8", str(script), "--repo", str(repo), "--out", out,
                         "--timing", *extra], stdout=subprocess.DEVNULL).returncode)
