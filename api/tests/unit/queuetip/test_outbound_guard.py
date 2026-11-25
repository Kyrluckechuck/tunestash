"""SSRF guard: which outbound URLs are allowed."""

import pytest

from src.queuetip import outbound_guard
from src.queuetip.outbound_guard import UnsafeURLError, validate_outbound_url


@pytest.fixture(autouse=True)
def _fixed_networks(monkeypatch):
    # Pretend this container sits on the Docker bridge 172.18.0.0/16.
    monkeypatch.setenv(outbound_guard.BLOCKED_NETWORKS_ENV, "172.18.0.0/16")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5000",
        "http://127.1.2.3/",
        "http://[::1]:5000/",
        "http://0.0.0.0/",
        "http://[::]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fe80::1]/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://2130706433/",  # decimal 127.0.0.1
        "http://172.18.0.5:5000",  # container's own docker network
        "http://localhost:5000",
        "http://LOCALHOST./",
        "http://foo.localhost/",
        "http://web:5000",
        "http://worker",
        "http://beat",
        "http://postgres:5432",
        "http://valkey:6379",
        "http://frontend",
        "http://queuetip:5000",
        "http://queuetip-frontend",
        "ftp://example.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http:///nohost",
    ],
)
def test_blocked_urls(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:4533",
        "http://10.0.0.5:4533/",
        "http://172.16.0.9",
        "https://navidrome.example.com",
        "http://navi.lan:4533",
    ],
)
def test_lan_and_public_urls_allowed(url):
    validate_outbound_url(url)


def test_any_resolved_ip_blocked_rejects(monkeypatch):
    monkeypatch.setattr(
        outbound_guard, "_resolve_host", lambda host: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("https://rebind.example.com")


def test_hostname_resolving_into_container_network_rejected(monkeypatch):
    monkeypatch.setattr(outbound_guard, "_resolve_host", lambda host: ["172.18.0.9"])
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("https://sneaky.example.com")


def test_unresolvable_host_rejected(monkeypatch):
    def boom(host):
        raise OSError("nxdomain")

    monkeypatch.setattr(outbound_guard, "_resolve_host", boom)
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("https://nope.example.com")


def test_allowed_hosts_and_https_pinning():
    validate_outbound_url(
        "https://music.apple.com/us/song/x/1",
        allowed_hosts={"music.apple.com"},
        require_https=True,
    )
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(
            "https://evil.example/music.apple.com",
            allowed_hosts={"music.apple.com"},
            require_https=True,
        )
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(
            "http://music.apple.com/us/song/x/1",
            allowed_hosts={"music.apple.com"},
            require_https=True,
        )


def test_userinfo_trick_judged_on_real_host():
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://example.com@127.0.0.1/")
