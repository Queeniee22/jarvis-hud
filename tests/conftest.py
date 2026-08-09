"""Shared test setup.

The important thing here is the network block. A test that quietly reaches
the real Obsidian API (or ElevenLabs, or Google) stops testing the code and
starts testing the developer's machine: it passes or fails depending on
whether a service happens to be running, it is slow, and it can mutate a real
vault. That happened once already -- `is_known_path` gained a re-list on miss,
and an existing unit test silently began making live HTTPS calls.

Blocked at the `requests` layer rather than at `socket`: on Windows asyncio
uses real sockets internally for its own self-pipe, so blocking those breaks
the event loop itself rather than catching bad tests.
"""
import pytest
import requests


class NetworkUsedInTest(RuntimeError):
    pass


_BLOCKED = ("request", "get", "post", "put", "delete", "patch", "head")


@pytest.fixture(autouse=True)
def _no_real_http(request, monkeypatch):
    """Fail any test that makes a real HTTP call.

    Mark a test with @pytest.mark.allow_network if it genuinely needs one.
    """
    if request.node.get_closest_marker("allow_network"):
        return

    def blocked(*args, **kwargs):
        target = next((a for a in args if isinstance(a, str)), "an external service")
        raise NetworkUsedInTest(
            f"this test tried to make a real HTTP call to {target}. "
            "Patch the client function instead (e.g. vault.list_files), or "
            "mark the test @pytest.mark.allow_network if that is intended."
        )

    for name in _BLOCKED:
        monkeypatch.setattr(requests, name, blocked, raising=False)
        monkeypatch.setattr(requests.Session, name, blocked, raising=False)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "allow_network: test may make real HTTP calls"
    )
