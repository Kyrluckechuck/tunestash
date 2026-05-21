"""Unit tests for get_client_ip XFF trust logic."""

from unittest.mock import MagicMock, patch

from src.queuetip.client_ip import get_client_ip


def _make_request(
    client_host: str,
    xff: str | None = None,
) -> MagicMock:
    """Build a minimal Starlette Request mock."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_host
    req.headers = {}
    if xff is not None:
        req.headers = {"x-forwarded-for": xff}
    return req


def _settings_mock(trusted: list[str]) -> MagicMock:
    """Return a mock that stands in for dj_settings with QUEUETIP_TRUSTED_PROXIES set."""
    m = MagicMock()
    m.QUEUETIP_TRUSTED_PROXIES = trusted
    return m


TRUSTED = ["10.0.0.0/8"]


def test_no_xff_returns_client_host():
    """Without XFF the direct connection address is always returned."""
    req = _make_request("1.2.3.4")
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock(TRUSTED)):
        assert get_client_ip(req) == "1.2.3.4"


def test_xff_ignored_when_client_not_trusted():
    """XFF must be ignored if the direct connection is not a trusted proxy."""
    req = _make_request("5.5.5.5", xff="1.1.1.1, 5.5.5.5")
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock(TRUSTED)):
        # 5.5.5.5 is not in 10.0.0.0/8 — treat client.host as canonical
        assert get_client_ip(req) == "5.5.5.5"


def test_xff_single_hop_trusted_proxy():
    """Single real client behind one trusted proxy."""
    req = _make_request("10.0.0.5", xff="1.1.1.1")
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock(TRUSTED)):
        assert get_client_ip(req) == "1.1.1.1"


def test_xff_chain_peels_only_trusted_hops():
    """With multiple XFF hops, only trusted ones are peeled from the right."""
    # Chain: real_client → untrusted_intermediary → trusted_proxy → us
    # XFF header value appended by trusted proxy: "1.1.1.1, 2.2.2.2"
    # direct connection (client.host): 10.0.0.5 (trusted)
    req = _make_request("10.0.0.5", xff="1.1.1.1, 2.2.2.2")
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock(TRUSTED)):
        # 2.2.2.2 is not trusted — stop there; it is the effective client
        assert get_client_ip(req) == "2.2.2.2"


def test_no_trusted_proxies_configured():
    """When QUEUETIP_TRUSTED_PROXIES is empty, always use client.host."""
    req = _make_request("10.0.0.5", xff="1.1.1.1")
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock([])):
        assert get_client_ip(req) == "10.0.0.5"


def test_client_is_none_returns_unknown():
    """If request.client is None (unusual), return 'unknown'."""
    req = MagicMock()
    req.client = None
    req.headers = {}
    with patch("src.queuetip.client_ip.dj_settings", _settings_mock(TRUSTED)):
        assert get_client_ip(req) == "unknown"
