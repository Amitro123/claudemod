"""Test configuration: the `slow` marker and the fast lane.

Fast lane (seconds): `python -m pytest plugins/inspector/tests -m "not slow" -q`. Pure logic and stub
evidence only: no git repository is built and the collector does not run.
Slow set: everything that builds a repository or runs the collector, one repository per module.
"""
import pytest

# modules whose tests build repositories / run the collector, minus a few pure-logic tests inside them
SLOW_MODULES = {"test_evidence", "test_collector_equality"}
PURE = {"test_subject_verdict", "test_default_excludes_are_overridden_by_path_and_component_root"}


# single tests that build a repository or spawn a long subprocess inside otherwise fast modules
SLOW_TESTS = {"test_cards_on_stdin_and_evidence_collected_again", "test_stdout_is_utf8_under_a_legacy_codepage"}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: builds a repository or runs the collector (tens of seconds)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.originalname in SLOW_TESTS or (
                item.module.__name__.split(".")[-1] in SLOW_MODULES and item.originalname not in PURE):
            item.add_marker(pytest.mark.slow)
