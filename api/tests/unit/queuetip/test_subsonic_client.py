"""Unit tests for the Subsonic REST client.

Mocks httpx.get to exercise envelope parsing, error-code mapping, and the
two auth modes. No DB, no network, no Django fixtures — these are pure
behaviour tests on the client module.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.subsonic import client as subsonic_client
from src.queuetip.subsonic.client import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    SubsonicAuthError,
    SubsonicClient,
    SubsonicError,
    SubsonicNotFoundError,
)


def _ok_response(payload: dict | None = None) -> MagicMock:
    body = {"subsonic-response": {"status": "ok", **(payload or {})}}
    return MagicMock(status_code=200, json=lambda: body, text="")


def _err_response(code: int, message: str = "boom") -> MagicMock:
    body = {
        "subsonic-response": {
            "status": "failed",
            "error": {"code": code, "message": message},
        }
    }
    return MagicMock(status_code=200, json=lambda: body, text="")


def _client(auth_mode: str = AUTH_PASSWORD) -> SubsonicClient:
    return SubsonicClient(
        server_url="https://navi.example.com/",  # trailing slash should be trimmed
        username="alice",
        password="hunter2",
        auth_mode=auth_mode,
    )


def test_server_url_trailing_slash_trimmed():
    c = _client()
    assert c.server_url == "https://navi.example.com"


def test_ping_sends_request_to_rest_ping_view():
    c = _client()
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response()) as g:
        c.ping()
    assert g.call_count == 1
    url, _ = g.call_args.args[0], g.call_args.kwargs
    assert url == "https://navi.example.com/rest/ping.view"


def test_password_auth_emits_user_token_salt():
    c = _client(auth_mode=AUTH_PASSWORD)
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response()) as g:
        c.ping()
    params = dict(g.call_args.kwargs["params"])
    assert params.get("u") == "alice"
    assert "t" in params and len(params["t"]) == 32  # md5 hex
    assert "s" in params and len(params["s"]) >= 8  # salt
    assert "apiKey" not in params


def test_api_key_auth_emits_apikey_and_omits_user():
    c = _client(auth_mode=AUTH_API_KEY)
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response()) as g:
        c.ping()
    params = dict(g.call_args.kwargs["params"])
    assert params.get("apiKey") == "hunter2"  # the "password" arg holds the key
    assert "u" not in params and "t" not in params and "s" not in params


def test_error_code_40_raises_auth_error():
    c = _client()
    with patch.object(
        subsonic_client.httpx,
        "get",
        return_value=_err_response(40, "Wrong username or password"),
    ):
        with pytest.raises(SubsonicAuthError, match="Wrong username"):
            c.ping()


def test_error_code_70_raises_not_found():
    c = _client()
    with patch.object(
        subsonic_client.httpx,
        "get",
        return_value=_err_response(70, "Playlist not found"),
    ):
        with pytest.raises(SubsonicNotFoundError, match="Playlist not found"):
            c.get_playlist("missing-id")


def test_error_other_code_raises_generic_error():
    c = _client()
    with patch.object(
        subsonic_client.httpx,
        "get",
        return_value=_err_response(30, "Required parameter missing"),
    ):
        with pytest.raises(SubsonicError, match="code 30"):
            c.ping()


def test_search_tracks_normalizes_single_song_dict_to_list():
    """Some Subsonic servers return a bare dict instead of a list when there's
    exactly one match. Client must coerce both shapes the same way."""
    c = _client()
    payload = {
        "searchResult3": {
            "song": {  # single dict, not a list
                "id": "T1",
                "title": "Solo Track",
                "artist": "X",
                "isrc": "USXXX0000001",
            }
        }
    }
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response(payload)):
        tracks = c.search_tracks("solo")
    assert len(tracks) == 1
    assert tracks[0].id == "T1"
    assert tracks[0].isrc == "USXXX0000001"


def test_search_tracks_drops_entries_without_id():
    """Defensive — a malformed entry without an id can't be linked to anyway."""
    c = _client()
    payload = {
        "searchResult3": {
            "song": [
                {"id": "OK", "title": "A", "artist": "X"},
                {"title": "B", "artist": "X"},  # no id
            ]
        }
    }
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response(payload)):
        tracks = c.search_tracks("q")
    assert [t.id for t in tracks] == ["OK"]


def test_get_open_subsonic_extensions_returns_empty_on_error():
    """The endpoint is best-effort — a classic Subsonic server returns code 30
    or 404. The probe must return [] in those cases, never raise."""
    c = _client()
    with patch.object(
        subsonic_client.httpx,
        "get",
        return_value=_err_response(30, "Unknown method"),
    ):
        assert c.get_open_subsonic_extensions() == []


def test_get_open_subsonic_extensions_parses_advertised_list():
    c = _client()
    payload = {
        "openSubsonicExtensions": [
            {"name": "transcodeOffset", "versions": [1]},
            {"name": "songLyrics", "versions": [1, 2]},
        ]
    }
    with patch.object(subsonic_client.httpx, "get", return_value=_ok_response(payload)):
        ext = c.get_open_subsonic_extensions()
    assert ext == ["transcodeOffset", "songLyrics"]


def test_overwrite_playlist_reads_current_then_sends_remove_plus_add():
    """overwrite_playlist must (1) read current length via getPlaylist, then
    (2) call updatePlaylist with songIndexToRemove for each existing index
    AND songIdToAdd for each new track. Order matters — Subsonic processes
    in the listed order."""
    c = _client()
    responses = [
        # getPlaylist — current contents (3 entries)
        _ok_response(
            {
                "playlist": {
                    "id": "PL1",
                    "entry": [
                        {"id": "old-a"},
                        {"id": "old-b"},
                        {"id": "old-c"},
                    ],
                }
            }
        ),
        # updatePlaylist
        _ok_response(),
    ]
    with patch.object(subsonic_client.httpx, "get", side_effect=responses) as mock_get:
        c.overwrite_playlist("PL1", ["new-1", "new-2"])

    # Second call (updatePlaylist) — inspect its params.
    update_call = mock_get.call_args_list[1]
    params = update_call.kwargs["params"]
    keys_seen = [k for k, _ in params]
    # 3 removes + 2 adds + auth/api keys
    assert keys_seen.count("songIndexToRemove") == 3
    assert keys_seen.count("songIdToAdd") == 2


def test_delete_playlist_is_idempotent_on_404():
    """If the playlist is already gone (code 70), delete returns cleanly —
    we don't want to fail user-initiated removals on stale state."""
    c = _client()
    with patch.object(
        subsonic_client.httpx,
        "get",
        return_value=_err_response(70, "Already deleted"),
    ):
        # Must not raise.
        c.delete_playlist("missing")
