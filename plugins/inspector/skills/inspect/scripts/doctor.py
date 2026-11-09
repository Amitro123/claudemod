#!/usr/bin/env python3
"""Report this Inspector copy and compare a specified installed/source copy, read-only.

python doctor.py --repo . [--compare-plugin /path/to/other/inspector] [--evidence evidence.json]
This cannot determine which copy an existing Claude session has loaded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # also under `python -I`
import snapshot  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', default='.')
    ap.add_argument('--compare-plugin', type=Path)
    ap.add_argument('--evidence', type=Path)
    args = ap.parse_args(argv)
    result = {'plugin': snapshot.plugin_identity(), 'runtime_loaded_copy': 'not verified'}
    mismatch = False
    try:
        result['repository'] = snapshot.git(args.repo, 'rev-parse', '--show-toplevel')
        result['head'] = snapshot.git(args.repo, 'rev-parse', 'HEAD')
        result['warnings'] = snapshot.workspace_warnings(args.repo, result['head'])
        if args.compare_plugin:
            other = snapshot.plugin_identity(args.compare_plugin)
            result['other_plugin'] = other
            result['same_plugin_contents'] = other['fingerprint'] == result['plugin']['fingerprint']
            mismatch = not result['same_plugin_contents']
        if args.evidence:
            data = json.loads(args.evidence.read_text(encoding='utf-8'))
            _, warnings = snapshot.validate(data, repo=args.repo)
            result['warnings'].extend(warnings)
            result['evidence_ref'] = data.get('ref_sha')
    except (OSError, ValueError, KeyError) as exc:
        result['error'] = str(exc)
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 1 if mismatch else 0


if __name__ == '__main__':
    raise SystemExit(main())
