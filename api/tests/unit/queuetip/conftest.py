"""Shared fixtures for QueueTip unit tests."""

import pytest

from src.queuetip import outbound_guard


@pytest.fixture(autouse=True)
def _stub_outbound_dns(monkeypatch):
    """Resolve every hostname to a public address so tests never hit real DNS.

    Individual tests override `_resolve_host` to exercise the SSRF guard.
    """
    monkeypatch.setattr(outbound_guard, "_resolve_host", lambda host: ["93.184.216.34"])
