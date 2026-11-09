"""Identity and freshness checks for saved evidence; no automatic cache or network access."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

SCHEMA_VERSION = 1
ALLOW_PLUGIN_CHANGE = 'INSPECTOR_ALLOW_PLUGIN_CHANGE'   # =1: a changed plugin is a warning, not an error
PLUGIN_ROOT = Path(__file__).resolve().parents[3]


def plugin_identity(root: Path = PLUGIN_ROOT) -> dict:
    manifest = json.loads((root / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))
    paths = [root / '.claude-plugin/plugin.json']
    for folder in ('skills', 'agents'):
        paths.extend(p for p in (root / folder).rglob('*')
                     if p.is_file() and p.suffix in {'.py', '.md', '.json'})
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return {'version': manifest['version'], 'fingerprint': digest.hexdigest(),
            'path': str(root.resolve())}


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError(f'Cannot validate saved evidence repository: {proc.stderr.strip()}')
    return proc.stdout.strip()


def metadata(repo: str, options: dict, repo_path: str | None = None) -> dict:
    return {'schema': SCHEMA_VERSION, 'plugin': plugin_identity(), 'options': options,
            'repo_path': repo_path or git(repo, 'rev-parse', '--show-toplevel')}


def workspace_warnings(repo: str, sha: str, head: str | None = None) -> list[str]:
    """`head`: HEAD when the caller already resolved it (saves one git call)."""
    warnings = []
    if (head or git(repo, 'rev-parse', 'HEAD')) != sha:
        warnings.append(f'Historical snapshot at {sha}: checkout HEAD differs. '
                        'Read code at the snapshot SHA or collect again for current code.')
    if git(repo, 'status', '--porcelain', '--untracked-files=normal'):
        warnings.append('Working tree has staged, unstaged or untracked files. '
                        'Evidence describes committed files only; do not mix it with local edits.')
    return warnings


def validate(data: dict, repo: str | None = None, expected_ref: str | None = None,
             expected_scope: dict | None = None) -> tuple[str, list[str]]:
    if not isinstance(data, dict) or not isinstance(data.get('timeline'), list):
        raise ValueError('Invalid evidence: expected an object with a timeline array; collect again.')
    warnings: list[str] = []
    meta = data.get('snapshot')
    if meta is None:
        # Old evidence remains readable, but cannot be treated as a verified reusable cache.
        return repo or data.get('repo_path', '.'), [
            'Legacy evidence has no provenance: freshness and plugin version are unverified. Collect again before relying on it.']
    if not isinstance(meta, dict) or meta.get('schema') != SCHEMA_VERSION:
        raise ValueError('Unsupported evidence schema; collect again with this Inspector version.')
    if not isinstance(meta.get('plugin'), dict):
        raise ValueError('Invalid saved plugin identity; collect again.')
    if meta['plugin'].get('fingerprint') != plugin_identity()['fingerprint']:
        message = ('Inspector files changed since collection (possibly a different installed copy); '
                   'collect again.')
        if os.environ.get(ALLOW_PLUGIN_CHANGE) != '1':
            raise ValueError(message + f' While developing the plugin itself, set {ALLOW_PLUGIN_CHANGE}=1 '
                             'to read it with a warning instead.')
        warnings.append(message.replace('collect again.', 'reading it anyway: results may not match this code.'))
    options = meta.get('options')
    if not isinstance(options, dict):
        raise ValueError('Invalid saved collection options; collect again.')
    for key, value in (expected_scope or {}).items():
        if value is not None and options.get(key) != value:
            raise ValueError(f'Requested {key} differs from saved evidence; collect again for that scope.')
    target = repo or meta.get('repo_path')
    sha = data.get('ref_sha')
    if not isinstance(target, str) or not isinstance(sha, str) or len(sha) != 40:
        raise ValueError('Invalid evidence repository or ref SHA; collect again.')
    if git(target, 'rev-parse', '--verify', f'{sha}^{{commit}}') != sha:
        raise ValueError('Snapshot commit is unavailable in this repository; collect again.')
    if expected_ref and git(target, 'rev-parse', '--verify', f'{expected_ref}^{{commit}}') != sha:
        raise ValueError('Requested ref differs from saved evidence; collect again for that ref.')
    return target, warnings + workspace_warnings(target, sha)
