from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.queuetip.resolution import apple
from src.queuetip.resolution.errors import AppleResolverError, PlaylistNotFoundError

URL = "https://music.apple.com/ca/playlist/volleyball/pl.u-abc123"


def _amp_resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def _track(name, artist, isrc, tid):
    return {
        "id": tid,
        "attributes": {"name": name, "artistName": artist, "isrc": isrc},
    }


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(apple, "get_token", lambda *a, **k: "FAKE_TOKEN")


def test_resolve_apple_playlist_follows_pagination():
    page1 = {"data": [_track("A", "X", "I1", "1")], "next": "/v1/.../tracks?offset=1"}
    page2 = {"data": [_track("B", "Y", "I2", "2")]}
    client = MagicMock()
    client.get.side_effect = [_amp_resp(page1), _amp_resp(page2)]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        result = apple.resolve_apple_playlist(URL)
    assert client.get.call_count == 2
    assert [c.track_name for c in result] == ["A", "B"]
    assert result[0].source == "apple"
    assert result[0].isrc == "I1"
    assert result[1].artist_name == "Y"


def test_resolve_apple_playlist_404():
    client = MagicMock()
    client.get.return_value = _amp_resp({}, status=404)
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(PlaylistNotFoundError):
            apple.resolve_apple_playlist(URL)


def test_resolve_apple_playlist_http_500():
    r = _amp_resp({}, status=500)
    r.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=r
    )
    client = MagicMock()
    client.get.return_value = r
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(AppleResolverError):
            apple.resolve_apple_playlist(URL)


def test_amp_get_retries_once_on_401_then_succeeds():
    """First attempt returns 401; second (after token refresh) succeeds."""
    track_body = {"data": [_track("Retry Song", "Retry Artist", "ISRC1", "t1")]}
    client = MagicMock()
    client.get.side_effect = [
        _amp_resp({}, status=401),
        _amp_resp(track_body, status=200),
    ]
    tokens = iter(["TOKEN_1", "TOKEN_2"])
    with (
        patch("src.queuetip.resolution.apple.httpx.Client") as ctor,
        patch("src.queuetip.resolution.apple.get_token", side_effect=tokens),
    ):
        ctor.return_value.__enter__.return_value = client
        result = apple.resolve_apple_playlist(URL)
    assert client.get.call_count == 2
    assert len(result) == 1
    assert result[0].track_name == "Retry Song"


def test_amp_get_raises_on_double_401():
    """Both attempts return 401 — raise_for_status on the second raises AppleResolverError."""
    r401_first = _amp_resp({}, status=401)
    r401_second = _amp_resp({}, status=401)
    r401_second.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=r401_second
    )
    client = MagicMock()
    client.get.side_effect = [r401_first, r401_second]
    tokens = iter(["TOKEN_1", "TOKEN_2"])
    with (
        patch("src.queuetip.resolution.apple.httpx.Client") as ctor,
        patch("src.queuetip.resolution.apple.get_token", side_effect=tokens),
    ):
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(AppleResolverError):
            apple.resolve_apple_playlist(URL)


def test_resolve_apple_track_album_url_uses_i_param():
    """resolve_apple_track with ?i= album URL resolves via the song id (456), not album id (123)."""
    album_url = "https://music.apple.com/us/album/some-album/123?i=456"
    song_body = {"data": [_track("Album Track", "Band", "ISRC99", "456")]}
    with patch(
        "src.queuetip.resolution.apple._amp_get", return_value=song_body
    ) as mock_get:
        result = apple.resolve_apple_track(album_url)
    assert result.track_name == "Album Track"
    called_path = mock_get.call_args[0][0]
    assert called_path.endswith(
        "/songs/456"
    ), f"Expected path ending in /songs/456, got: {called_path!r}"
    assert "123" not in called_path
