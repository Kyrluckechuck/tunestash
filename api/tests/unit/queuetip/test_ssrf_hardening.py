"""SSRF hardening for the Subsonic client, connection mutations and Apple fetch."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from queuetip.models import Account, SubsonicConnection
from src.queuetip import outbound_guard
from src.queuetip.errors import ValidationError
from src.queuetip.resolution import apple
from src.queuetip.resolution.errors import AppleResolverError
from src.queuetip.schema.mutation import (
    _create_subsonic_connection,
    _update_subsonic_connection,
)
from src.queuetip.subsonic import client as subsonic_client
from src.queuetip.subsonic.client import SubsonicClient, SubsonicError

PAGE_HTML = '<script type="module" src="/assets/index~deadbeef12.js"></script>'
BUNDLE_JS = 'var x="eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJBTVAifQ.SIGNATUREPART";'


@pytest.fixture(autouse=True)
def _docker_net(monkeypatch):
    monkeypatch.setenv(outbound_guard.BLOCKED_NETWORKS_ENV, "172.18.0.0/16")


def _ok() -> MagicMock:
    body = {"subsonic-response": {"status": "ok"}}
    return MagicMock(status_code=200, json=lambda: body, text="")


def _client(url: str = "https://navi.example.com") -> SubsonicClient:
    return SubsonicClient(server_url=url, username="alice", password="pw")


# ── client ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url", ["http://web:5000", "http://127.0.0.1:5000", "http://169.254.169.254"]
)
def test_blocked_server_url_makes_no_request(url):
    c = _client(url)
    with (
        patch.object(subsonic_client.httpx, "get") as g,
        patch.object(subsonic_client.httpx, "post") as p,
    ):
        with pytest.raises(SubsonicError):
            c.ping()
        with pytest.raises(SubsonicError):
            c.create_playlist("x", ["1"])
    g.assert_not_called()
    p.assert_not_called()


def test_dns_rebinding_rechecked_on_every_request(monkeypatch):
    c = _client()
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    monkeypatch.setattr(outbound_guard, "_resolve_host", lambda host: next(answers))
    with patch.object(subsonic_client.httpx, "get", return_value=_ok()) as g:
        c.ping()
        with pytest.raises(SubsonicError):
            c.ping()
    assert g.call_count == 1


def test_redirects_are_not_followed():
    c = _client()
    with patch.object(subsonic_client.httpx, "get", return_value=_ok()) as g:
        c.ping()
    body = {"subsonic-response": {"status": "ok", "playlist": {"id": "1"}}}
    created = MagicMock(status_code=200, json=lambda: body, text="")
    with patch.object(subsonic_client.httpx, "post", return_value=created) as p:
        c.create_playlist("x", [])
    assert g.call_args.kwargs["follow_redirects"] is False
    assert p.call_args.kwargs["follow_redirects"] is False


def test_upstream_bodies_never_surface_in_errors():
    c = _client()
    resp = MagicMock(status_code=500, text="INTERNAL-SECRET-BODY")
    with patch.object(subsonic_client.httpx, "get", return_value=resp):
        with pytest.raises(SubsonicError) as exc:
            c.ping()
    assert "INTERNAL-SECRET-BODY" not in str(exc.value)
    assert "500" in str(exc.value)

    bad = MagicMock(status_code=200, text="INTERNAL-SECRET-BODY")
    bad.json.side_effect = ValueError("nope")
    with patch.object(subsonic_client.httpx, "get", return_value=bad):
        with pytest.raises(SubsonicError) as exc:
            c.ping()
    assert "INTERNAL-SECRET-BODY" not in str(exc.value)


def test_connection_errors_do_not_leak_details():
    c = _client()
    err = httpx.ConnectError("[Errno 111] Connection refused to 10.1.2.3")
    with patch.object(subsonic_client.httpx, "get", side_effect=err):
        with pytest.raises(SubsonicError) as exc:
            c.ping()
    assert "10.1.2.3" not in str(exc.value)
    assert "refused" not in str(exc.value)


# ── mutations (save-time validation) ────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://web:5000",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "ftp://x.example",
    ],
)
def test_create_rejects_ssrf_server_url(url):
    account = Account.objects.create(display_name="t")
    with pytest.raises(ValidationError):
        _create_subsonic_connection(account, "Nav", url, "user", "pw")
    assert not SubsonicConnection.objects.filter(account=account).exists()


@pytest.mark.django_db
def test_update_rejects_ssrf_server_url():
    account = Account.objects.create(display_name="t")
    conn = _create_subsonic_connection(
        account, "Nav", "https://nav.example", "user", "pw"
    )
    with pytest.raises(ValidationError):
        _update_subsonic_connection(
            account, conn.id, None, "http://postgres:5432", None, None, None
        )
    conn.refresh_from_db()
    assert conn.server_url == "https://nav.example"


@pytest.mark.django_db
def test_create_allows_lan_server_url():
    account = Account.objects.create(display_name="t")
    conn = _create_subsonic_connection(
        account, "Nav", "http://192.168.1.20:4533", "user", "pw"
    )
    assert conn.server_url == "http://192.168.1.20:4533"


# ── Apple Music resolver ────────────────────────────────────────────────────


def _resp(text):
    r = MagicMock()
    r.text = text
    r.status_code = 200
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.parametrize(
    "url",
    [
        "http://web:5000/graphql?x=music.apple.com/us/song/a/1",
        "https://evil.example/music.apple.com/us/song/a/1",
        "http://music.apple.com/us/song/a/1",
        "https://music.apple.com.evil.example/us/song/a/1",
        "https://127.0.0.1/music.apple.com/us/song/a/1",
    ],
)
def test_fetch_token_rejects_non_apple_page_urls(url):
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        with pytest.raises(AppleResolverError):
            apple._fetch_token(url)
    ctor.assert_not_called()


def test_fetch_token_blocks_redirect_to_other_host():
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        client = MagicMock()
        client.get.side_effect = [_resp(PAGE_HTML), _resp(BUNDLE_JS)]
        ctor.return_value.__enter__.return_value = client
        apple._fetch_token("https://music.apple.com/ca/playlist/x/pl.u-1")
    hooks = ctor.call_args.kwargs["event_hooks"]["request"]
    hooks[0](httpx.Request("GET", "https://music.apple.com/other"))
    with pytest.raises(AppleResolverError):
        hooks[0](httpx.Request("GET", "http://web:5000/"))
