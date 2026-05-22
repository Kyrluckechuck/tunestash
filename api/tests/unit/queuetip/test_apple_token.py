import time
from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution import apple
from src.queuetip.resolution.errors import AppleResolverError

PAGE_HTML = '<script type="module" src="/assets/index~deadbeef12.js"></script>'
BUNDLE_JS = 'var x="eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJBTVAifQ.SIGNATUREPART";'


def _resp(text, status=200):
    r = MagicMock()
    r.text = text
    r.status_code = status
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture(autouse=True)
def _clear_token_cache():
    apple._TOKEN_CACHE["token"] = None
    apple._TOKEN_CACHE["fetched_at"] = 0.0
    yield


def test_fetch_token_extracts_jwt_from_bundle():
    client = MagicMock()
    client.get.side_effect = [_resp(PAGE_HTML), _resp(BUNDLE_JS)]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        token = apple._fetch_token("https://music.apple.com/ca/playlist/x/pl.u-1")
    assert token.startswith("eyJ")
    assert client.get.call_args_list[1].args[0].endswith("/assets/index~deadbeef12.js")


def test_fetch_token_raises_when_bundle_url_missing():
    client = MagicMock()
    client.get.side_effect = [_resp("<html>no bundle here</html>")]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(AppleResolverError):
            apple._fetch_token("https://music.apple.com/ca/playlist/x/pl.u-1")


def test_get_token_returns_cached_token():
    apple._TOKEN_CACHE["token"] = "eyJcached"
    apple._TOKEN_CACHE["fetched_at"] = time.time()
    with patch("src.queuetip.resolution.apple._fetch_token") as mock_fetch:
        result = apple.get_token("https://music.apple.com/anything")
    mock_fetch.assert_not_called()
    assert result == "eyJcached"


def test_get_token_force_refresh():
    apple._TOKEN_CACHE["token"] = "eyJcached"
    apple._TOKEN_CACHE["fetched_at"] = time.time()
    with patch(
        "src.queuetip.resolution.apple._fetch_token", return_value="eyJfresh"
    ) as mock_fetch:
        result = apple.get_token("https://music.apple.com/anything", force_refresh=True)
    mock_fetch.assert_called_once()
    assert result == "eyJfresh"
