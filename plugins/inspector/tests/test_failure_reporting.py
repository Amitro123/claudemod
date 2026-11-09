"""Regressions where invalid or incomplete evidence looked successful."""
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'skills/inspect/scripts'))
import crosscheck
import handoff
from test_crosscheck import EV, card


def test_one_case_cannot_clear_another_cases_copy():
    ev = copy.deepcopy(EV)
    copied = {'line': 'render(x, escape=False)', 'at': ['b.py:2']}
    ev['timeline'][1]['commits'][0]['left_behind'] = [copied]
    ev['left_behind'].append({'unit': '#3', 'commit': 'c3c3c3c', **copied})
    result = crosscheck.crosscheck(ev, [card('#2', 'c2c2c2c', '#1', clear=['b.py:2']),
                                      card('#3', 'c3c3c3c', '#2')])
    assert any(x['unit'] == '#3' and 'b.py:2' in x['at'] for x in result['copies_left_unchecked'])


def test_empty_commit_blame_does_not_inherit_other_commit_blame():
    ev = copy.deepcopy(EV)
    ev['timeline'][0]['commits'].append({'sha': 'aabbccd', 'introduced_by': []})
    result = crosscheck.crosscheck(ev, [card('#2', 'aabbccd', '#1')])
    assert result['cases'][0]['culprit'].startswith('reader only')


def test_unknown_is_not_corroborated_culprit():
    result = crosscheck.crosscheck(EV, [card('#4', 'c4c4c4c', 'unknown')])
    assert result['culprits_agree'] == 0


@pytest.mark.parametrize('payload', ['null', '[17]', '{"complete":{"siblings":"invalid"}}', '{}\n{'])
def test_bad_handoff_input_does_not_replace_output(tmp_path, monkeypatch, payload):
    out = tmp_path / 'handoff.md'
    out.write_text('previous report')
    monkeypatch.setattr(sys, 'stdin', io.StringIO(payload))
    assert handoff.main(['--cards', '-', '--out', str(out)]) != 0
    assert out.read_text() == 'previous report'


def test_missing_cards_directory_is_an_error(tmp_path):
    assert crosscheck.read_cards(str(tmp_path / 'missing'))[1]


@pytest.mark.parametrize('validate_code,pytest_code,expected', [(1,0,1),(0,1,1),(0,0,0)])
def test_offline_runner_preserves_both_check_results(tmp_path, validate_code, pytest_code, expected):
    for name, code in [('claude', validate_code), ('python3', pytest_code)]:
        script = tmp_path / name
        script.write_text(f'#!/bin/sh\nexit {code}\n')
        script.chmod(0o755)
    runner = Path(__file__).parents[1] / 'evals/run-offline.sh'
    result = subprocess.run(['bash', str(runner)], env={**os.environ, 'PATH': str(tmp_path)+os.pathsep+os.environ['PATH']}, capture_output=True)
    assert result.returncode == expected


def test_commit_prefix_collision_is_not_guessed():
    ev = copy.deepcopy(EV)
    ev['timeline'][0]['commits'][0]['sha'] = 'abcdef100001'
    ev['timeline'][0]['commits'].append({'sha': 'abcdef199999', 'introduced_by': []})
    exact = crosscheck.crosscheck(ev, [card('#2', 'abcdef199999', '#1')])
    assert exact['cases'][0]['culprit'].startswith('reader only')
    ambiguous = crosscheck.crosscheck(ev, [card('#2', 'abcdef1', '#1')])
    assert ambiguous['cases'][0]['culprit'] == 'commit ambiguous or not in the evidence'


def test_unknown_commit_cannot_use_unit_evidence():
    result = crosscheck.crosscheck(EV, [card('#2', 'badbadbad', '#1', clear=['b.py:2'])])
    assert result['cases'][0]['culprit'] == 'commit ambiguous or not in the evidence'
    assert result['copies_left_unchecked'][0]['at'] == ['b.py:2', 'c.py:9']


def test_card_without_unit_still_tracks_unchecked_copies():
    c = card('', 'c2c2c2c', '#1')
    result = crosscheck.crosscheck(EV, [c])
    assert result['copies_left_unchecked'][0]['unit'] == '#2'


def test_card_array_file_is_supported(tmp_path):
    (tmp_path / 'cards.json').write_text(json.dumps([card('#2', 'c2c2c2c', '#1')]))
    cards, bad = crosscheck.read_cards(str(tmp_path))
    assert len(cards) == 1 and cards[0]['unit'] == '#2' and not bad


def test_handoff_write_failure_returns_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('[]'))
    assert handoff.main(['--cards', '-', '--out', str(tmp_path)]) == 1
