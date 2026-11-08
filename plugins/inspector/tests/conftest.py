"""Test configuration: the `slow` marker (one collector run over this repository's own history)."""


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: runs the collector over a real history (tens of seconds)")
