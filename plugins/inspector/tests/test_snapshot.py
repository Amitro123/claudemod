"""Saved evidence and local plugin copies must not silently drift.

Fast lane first (fake evidence, no git repository, no collector). The slow set shares ONE repository and
ONE collector run for the module and clones it when a test needs to change the checkout.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'skills/inspect/scripts'))
import crosscheck
import doctor
import evidence
import snapshot
from test_evidence import commit, new_repo, run

SHA = 'a' * 40


def fake_evidence(**options) -> dict:
    meta = snapshot.metadata('.', {'path': None, 'since': None, 'unit': None, **options}, repo_path='/nowhere')
    return {'timeline': [], 'ref_sha': SHA, 'snapshot': meta}


def same_path(a, b) -> bool:
    return Path(a).resolve() == Path(b).resolve()        # git reports forward slashes on Windows


# ---- fast lane -------------------------------------------------------------------------------------

def test_changed_plugin_and_future_schema_are_rejected():
    ev = fake_evidence()
    ev['snapshot']['plugin']['fingerprint'] = 'old'
    with pytest.raises(ValueError, match='Inspector files changed'):
        snapshot.validate(ev)
    ev['snapshot']['schema'] = 999
    with pytest.raises(ValueError, match='Unsupported evidence schema'):
        snapshot.validate(ev)


def test_legacy_is_visibly_unverified():
    assert 'unverified' in snapshot.validate({'timeline': []})[1][0]


def test_saved_scope_cannot_be_silently_overridden():
    with pytest.raises(ValueError, match='Requested path differs'):
        snapshot.validate(fake_evidence(), expected_scope={'path': 'other'})


def test_fingerprint_follows_content_not_location(tmp_path):
    def plugin(root: Path, text: str) -> Path:
        (root / '.claude-plugin').mkdir(parents=True)
        (root / '.claude-plugin/plugin.json').write_text('{"version": "1"}')
        (root / 'skills/x').mkdir(parents=True)
        (root / 'skills/x/SKILL.md').write_text(text)
        (root / 'skills/x/notes.txt').write_text(text)       # other suffixes are not part of the identity
        return root
    a, b = plugin(tmp_path / 'a', 'same'), plugin(tmp_path / 'b', 'same')
    assert snapshot.plugin_identity(a)['fingerprint'] == snapshot.plugin_identity(b)['fingerprint']
    (b / 'skills/x/notes.txt').write_text('ignored')
    assert snapshot.plugin_identity(a)['fingerprint'] == snapshot.plugin_identity(b)['fingerprint']
    (b / 'skills/x/SKILL.md').write_text('changed')
    assert snapshot.plugin_identity(a)['fingerprint'] != snapshot.plugin_identity(b)['fingerprint']


def test_atomic_write_preserves_previous_snapshot_on_failure(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.json'
    path.write_text('old')

    def fail(*args):
        raise OSError('simulated replacement failure')
    monkeypatch.setattr(evidence.os, 'replace', fail)
    with pytest.raises(OSError):
        evidence.write(str(path), 'new')
    assert path.read_text() == 'old'
    assert list(tmp_path.iterdir()) == [path]


def test_show_invalid_json_fails_cleanly(tmp_path, capsys):
    path = tmp_path / 'broken.json'
    path.write_text('{')
    assert evidence.main(['--show', '#1', '--json', str(path)]) == 1
    assert 'evidence.py:' in capsys.readouterr().err


def test_cli_crosscheck_rejects_changed_plugin(tmp_path, capsys):
    ev = fake_evidence()
    ev['snapshot']['plugin']['fingerprint'] = 'obsolete'
    saved = tmp_path / 'evidence.json'
    saved.write_text(json.dumps(ev))
    cards = tmp_path / 'cards'
    cards.mkdir()
    assert crosscheck.main(['--evidence', str(saved), '--cards', str(cards)]) == 1
    assert 'Inspector files changed' in capsys.readouterr().err


def test_cli_crosscheck_rejects_a_different_scope(tmp_path, capsys):
    saved = tmp_path / 'evidence.json'
    saved.write_text(json.dumps(fake_evidence()))
    cards = tmp_path / 'cards'
    cards.mkdir()
    assert crosscheck.main(['--evidence', str(saved), '--cards', str(cards), '--path', 'other']) == 1
    assert 'Requested path differs' in capsys.readouterr().err


# ---- slow set: one repository, one collector run ---------------------------------------------------

@pytest.fixture(scope='module')
def base(tmp_path_factory):
    repo = new_repo(tmp_path_factory.mktemp('snap') / 'repo')
    commit(repo, {'a.py': 'value = 123456789\n'}, 'Initial helper')
    commit(repo, {'a.py': 'value = 987654321\n'}, 'fix: wrong value')
    return repo, evidence.investigate(str(repo))


@pytest.fixture
def work(base, tmp_path):
    """A throwaway clone plus the saved evidence pointing at it, so a test may edit the checkout."""
    repo, ev = base
    clone = tmp_path / 'clone'
    run(repo, 'clone', '-q', str(repo), str(clone))
    run(clone, 'config', 'user.email', 'test@example.com')
    run(clone, 'config', 'user.name', 'Test')
    ev = copy.deepcopy(ev)
    ev['snapshot']['repo_path'] = str(clone)
    return clone, ev


@pytest.mark.slow
def test_clean_snapshot_and_options(base):
    repo, ev = base
    target, warnings = snapshot.validate(ev)
    assert same_path(target, repo) and warnings == []
    assert ev['snapshot']['options']['max_blame'] == 400


@pytest.mark.slow
def test_advanced_head_is_historical_not_silently_current(work):
    repo, ev = work
    commit(repo, {'a.py': 'value = 111111111\n'}, 'Another change')
    assert any('Historical snapshot' in w for w in snapshot.validate(ev)[1])
    with pytest.raises(ValueError, match='Requested ref'):
        snapshot.validate(ev, expected_ref='HEAD')


@pytest.mark.slow
@pytest.mark.parametrize('how', ['unstaged', 'staged', 'untracked'])
def test_dirty_checkout_is_explicit(work, how):
    repo, ev = work
    if how == 'untracked':
        (repo / 'new.py').write_text('untracked\n')
    else:
        (repo / 'a.py').write_text('local edit\n')
        if how == 'staged':
            run(repo, 'add', 'a.py')
    assert any('Working tree' in w for w in snapshot.validate(ev)[1])
    if how == 'unstaged':
        assert any('committed files only' in w for w in evidence.investigate(str(repo))['warnings'])


@pytest.mark.slow
def test_relocated_clone_can_be_selected_explicitly(work, tmp_path):
    clone, ev = work
    ev['snapshot']['repo_path'] = str(tmp_path / 'moved-away')
    target, warnings = snapshot.validate(ev, repo=str(clone))
    assert same_path(target, clone) and warnings == []
    with pytest.raises(ValueError, match='Cannot validate'):
        snapshot.validate(ev)


@pytest.mark.slow
def test_wrong_repository_rejected(base, tmp_path):
    _, ev = base
    other = new_repo(tmp_path / 'other')
    commit(other, {'different.py': 'other\n'}, 'Different history')
    with pytest.raises(ValueError, match='Cannot validate'):
        snapshot.validate(ev, repo=str(other))


@pytest.mark.slow
def test_same_version_different_installed_files(base, tmp_path, capsys):
    repo, _ = base
    mine = snapshot.plugin_identity()
    other = tmp_path / 'installed'
    (other / '.claude-plugin').mkdir(parents=True)
    (other / '.claude-plugin/plugin.json').write_text(json.dumps({'version': mine['version']}))
    (other / 'skills').mkdir()
    (other / 'skills/SKILL.md').write_text('Changed instruction\n')
    assert doctor.main(['--repo', str(repo), '--compare-plugin', str(other)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['plugin']['version'] == report['other_plugin']['version']
    assert report['same_plugin_contents'] is False
    assert report['runtime_loaded_copy'] == 'not verified'


@pytest.mark.slow
def test_show_moved_clone_and_historical_warning(work, tmp_path, capsys):
    clone, ev = work
    saved = tmp_path / 'evidence.json'
    ev['snapshot']['repo_path'] = str(tmp_path / 'moved-away')
    saved.write_text(json.dumps(ev))
    commit(clone, {'a.py': 'next change\n'}, 'Next')
    assert evidence.main(['--show', ev['timeline'][-1]['unit'], '--json', str(saved), '--repo', str(clone)]) == 0
    result = capsys.readouterr()
    assert 'Historical snapshot' in result.err
    assert '+value = 987654321' in result.out
