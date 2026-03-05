"""Tests for dual Spotify client architecture and fail-fast error handling."""

from unittest.mock import MagicMock, patch

import pytest
from downloader.downloader import Downloader
from downloader.spotdl_wrapper import (
    PlaylistSyncError,
    _is_fail_fast_error,
)
from downloader.spotipy_tasks import (
    MAX_RATE_LIMIT_WAIT_SECONDS,
    LimitedRetry,
    OAuthSpotifyClient,
    PublicSpotifyClient,
    SpotifyClient,
    SpotifyRateLimitError,
)


class TestPublicSpotifyClient:
    """Tests for the PublicSpotifyClient class."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        PublicSpotifyClient.reset()

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        PublicSpotifyClient.reset()

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_uses_client_credentials(
        self,
        mock_spotify: MagicMock,
        mock_creds: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """PublicSpotifyClient should use Client Credentials flow."""
        client = PublicSpotifyClient()

        # Should have created client credentials manager
        mock_creds.assert_called_once()
        # Should have created Spotify client with credentials manager and custom session
        mock_spotify.assert_called_once()
        assert client.sp is not None

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_singleton_pattern(
        self,
        mock_spotify: MagicMock,
        mock_creds: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """PublicSpotifyClient should reuse the same instance."""
        client1 = PublicSpotifyClient()
        client2 = PublicSpotifyClient()

        assert client1 is client2
        # Should only initialize once
        assert mock_creds.call_count == 1

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_reset_clears_singleton(
        self,
        mock_spotify: MagicMock,
        mock_creds: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """PublicSpotifyClient.reset() should clear the singleton."""
        client1 = PublicSpotifyClient()
        PublicSpotifyClient.reset()
        client2 = PublicSpotifyClient()

        assert client1 is not client2
        # Should initialize twice
        assert mock_creds.call_count == 2


class TestOAuthSpotifyClient:
    """Tests for the OAuthSpotifyClient class."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        OAuthSpotifyClient.reset()

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        OAuthSpotifyClient.reset()

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_uses_oauth_when_available(
        self,
        mock_spotify: MagicMock,
        mock_get_oauth: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """OAuthSpotifyClient should use OAuth token when available."""
        mock_get_oauth.return_value = {"access_token": "test_token"}
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        client = OAuthSpotifyClient()

        # Should have used the OAuth token with custom session
        mock_spotify.assert_called_once_with(
            auth="test_token", requests_session=mock_session
        )
        assert client.is_oauth is True

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_falls_back_to_client_credentials(
        self,
        mock_spotify: MagicMock,
        mock_creds: MagicMock,
        mock_get_oauth: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """OAuthSpotifyClient should fall back to Client Credentials when no OAuth."""
        mock_get_oauth.return_value = None

        client = OAuthSpotifyClient()

        # Should have created client credentials
        mock_creds.assert_called_once()
        assert client.is_oauth is False

    @patch("downloader.spotipy_tasks.create_limited_session")
    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_refresh_token(
        self,
        mock_spotify: MagicMock,
        mock_get_oauth: MagicMock,
        mock_create_session: MagicMock,
    ) -> None:
        """refresh_token() should update the client with new token."""
        mock_get_oauth.side_effect = [
            {"access_token": "old_token"},
            {"access_token": "new_token"},
        ]

        client = OAuthSpotifyClient()
        result = client.refresh_token()

        assert result is True
        # Should have been called twice (init + refresh)
        assert mock_get_oauth.call_count == 2


class TestSpotifyClientAlias:
    """Tests for the SpotifyClient backwards compatibility alias."""

    def setup_method(self) -> None:
        OAuthSpotifyClient.reset()

    def teardown_method(self) -> None:
        OAuthSpotifyClient.reset()

    def test_alias_is_oauth_client(self) -> None:
        """SpotifyClient should be an alias for OAuthSpotifyClient."""
        assert issubclass(SpotifyClient, OAuthSpotifyClient)


class TestDownloaderDualClients:
    """Tests for Downloader class with dual client architecture."""

    def test_accepts_both_clients(self) -> None:
        """Downloader should accept both OAuth and public clients."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()

        downloader = Downloader(mock_oauth, public_client=mock_public)

        assert downloader.spotipy_client is mock_oauth
        assert downloader.public_client is mock_public

    def test_uses_oauth_as_fallback(self) -> None:
        """Downloader should use OAuth client as fallback when no public client."""
        mock_oauth = MagicMock()

        downloader = Downloader(mock_oauth)

        assert downloader.spotipy_client is mock_oauth
        assert downloader.public_client is mock_oauth

    def test_get_track_uses_public_client(self) -> None:
        """get_track() should use the public client."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_public.track.return_value = {"id": "test", "name": "Test Track"}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_track("test_id")

        mock_public.track.assert_called_once_with("test_id")
        mock_oauth.track.assert_not_called()

    def test_get_album_uses_public_client(self) -> None:
        """get_album() should use the public client."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_public.album.return_value = {"id": "test", "tracks": {"items": []}}
        mock_public.next.return_value = None

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_album("test_id")

        mock_public.album.assert_called_once_with("test_id")
        mock_oauth.album.assert_not_called()

    def test_get_playlist_tries_oauth_first(self) -> None:
        """get_playlist() should try OAuth client first (can access private playlists)."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_oauth.playlist.return_value = {"id": "test", "tracks": {"items": []}}
        mock_oauth.next.return_value = None

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_playlist("test_id")

        mock_oauth.playlist.assert_called_once_with("test_id")
        mock_public.playlist.assert_not_called()

    def test_get_playlist_falls_back_to_public(self) -> None:
        """get_playlist() should fall back to public client when OAuth fails."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_oauth.playlist.side_effect = Exception("OAuth error")
        mock_public.playlist.return_value = {"id": "test", "tracks": {"items": []}}
        mock_public.next.return_value = None

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_playlist("test_id")

        mock_oauth.playlist.assert_called_once_with("test_id")
        mock_public.playlist.assert_called_once_with("test_id")

    def test_get_playlist_works_without_oauth(self) -> None:
        """get_playlist() should work with only public client (no OAuth configured)."""
        mock_client = MagicMock()
        mock_client.playlist.return_value = {"id": "test", "tracks": {"items": []}}
        mock_client.next.return_value = None

        # When no public_client is provided, spotipy_client is used for both
        downloader = Downloader(mock_client)

        # Should work - this is the case for users without OAuth
        result = downloader.get_playlist("test_id")

        assert result["id"] == "test"
        mock_client.playlist.assert_called_once_with("test_id")

    def test_get_playlist_snapshot_id_works_without_oauth(self) -> None:
        """get_playlist_snapshot_id() should work with only public client."""
        mock_client = MagicMock()
        mock_client.playlist.return_value = {"snapshot_id": "abc123"}

        # When no public_client is provided, spotipy_client is used for both
        downloader = Downloader(mock_client)

        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "abc123"
        mock_client.playlist.assert_called_once()

    def test_get_playlist_snapshot_id_tries_oauth_first(self) -> None:
        """get_playlist_snapshot_id() should try OAuth client first."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_oauth.playlist.return_value = {"snapshot_id": "abc123"}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "abc123"
        mock_oauth.playlist.assert_called_once()
        mock_public.playlist.assert_not_called()

    def test_get_playlist_snapshot_id_falls_back_to_public(self) -> None:
        """get_playlist_snapshot_id() should fall back to public on OAuth failure."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_oauth.playlist.side_effect = Exception("OAuth error")
        mock_public.playlist.return_value = {"snapshot_id": "public123"}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "public123"
        mock_oauth.playlist.assert_called_once()
        mock_public.playlist.assert_called_once()

    def test_get_playlist_snapshot_id_refreshes_token_on_401(self) -> None:
        """get_playlist_snapshot_id() should refresh token on 401 and retry."""
        from spotipy.exceptions import SpotifyException

        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_refresh = MagicMock(return_value=True)

        # First call fails with 401, second succeeds after refresh
        mock_oauth.playlist.side_effect = [
            SpotifyException(http_status=401, code=-1, msg="Token expired"),
            {"snapshot_id": "refreshed123"},
        ]

        downloader = Downloader(
            mock_oauth, public_client=mock_public, on_auth_error=mock_refresh
        )
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "refreshed123"
        mock_refresh.assert_called_once()
        assert mock_oauth.playlist.call_count == 2
        mock_public.playlist.assert_not_called()

    def test_get_playlist_snapshot_id_falls_back_if_refresh_fails(self) -> None:
        """get_playlist_snapshot_id() should fall back to public if refresh fails."""
        from spotipy.exceptions import SpotifyException

        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_refresh = MagicMock(return_value=False)

        mock_oauth.playlist.side_effect = SpotifyException(
            http_status=401, code=-1, msg="Token expired"
        )
        mock_public.playlist.return_value = {"snapshot_id": "public123"}

        downloader = Downloader(
            mock_oauth, public_client=mock_public, on_auth_error=mock_refresh
        )
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "public123"
        mock_refresh.assert_called_once()
        mock_oauth.playlist.assert_called_once()
        mock_public.playlist.assert_called_once()

    def test_get_playlist_snapshot_id_aborts_on_persistent_401(self) -> None:
        """get_playlist_snapshot_id() should not loop if 401 persists after refresh."""
        from spotipy.exceptions import SpotifyException

        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_refresh = MagicMock(return_value=True)

        # Both calls fail with 401 - refresh didn't help
        mock_oauth.playlist.side_effect = SpotifyException(
            http_status=401, code=-1, msg="Token expired"
        )
        mock_public.playlist.return_value = {"snapshot_id": "public123"}

        downloader = Downloader(
            mock_oauth, public_client=mock_public, on_auth_error=mock_refresh
        )
        result = downloader.get_playlist_snapshot_id("test_id")

        # Should fall back to public after exactly one refresh attempt
        assert result == "public123"
        mock_refresh.assert_called_once()
        assert mock_oauth.playlist.call_count == 2  # Initial + one retry
        mock_public.playlist.assert_called_once()


class TestFailFastErrorDetection:
    """Tests for the _is_fail_fast_error helper function."""

    def test_detects_429_rate_limit(self) -> None:
        """Should detect 429 rate limit errors."""
        exc = Exception("http status: 429")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 429

    def test_detects_rate_limit_text(self) -> None:
        """Should detect rate limit by text."""
        exc = Exception("Rate limit exceeded")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 429

    def test_detects_401_unauthorized(self) -> None:
        """Should detect 401 unauthorized errors."""
        exc = Exception("401 Unauthorized")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 401

    def test_detects_access_token_expired(self) -> None:
        """Should detect expired access token."""
        exc = Exception("Access token expired")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 401

    def test_detects_404_not_found(self) -> None:
        """Should detect 404 not found errors."""
        exc = Exception("404 Not Found")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 404

    def test_detects_max_retries(self) -> None:
        """Should detect max retries (usually from 404s)."""
        exc = Exception("Max Retries reached")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is True
        assert status_code == 404

    def test_non_fail_fast_errors(self) -> None:
        """Should return False for other errors."""
        exc = Exception("Some random network error")
        is_fail_fast, status_code = _is_fail_fast_error(exc)
        assert is_fail_fast is False
        assert status_code is None


class TestPlaylistSyncError:
    """Tests for the PlaylistSyncError exception."""

    def test_stores_status_code(self) -> None:
        """PlaylistSyncError should store the status code."""
        err = PlaylistSyncError("Rate limited", status_code=429)
        assert err.status_code == 429
        assert "Rate limited" in str(err)

    def test_default_status_code(self) -> None:
        """PlaylistSyncError status_code should default to None."""
        err = PlaylistSyncError("Some error")
        assert err.status_code is None


class TestSpotifyRateLimitError:
    """Tests for the SpotifyRateLimitError exception."""

    def test_stores_retry_after(self) -> None:
        """SpotifyRateLimitError should store the retry_after_seconds."""
        err = SpotifyRateLimitError("Rate limited", retry_after_seconds=3600)
        assert err.retry_after_seconds == 3600
        assert "Rate limited" in str(err)


class TestLimitedRetry:
    """Tests for the LimitedRetry class that caps rate limit wait times."""

    def test_allows_short_retry_after(self) -> None:
        """LimitedRetry should allow retry-after values within threshold."""
        retry = LimitedRetry(total=3)

        # Mock response with short retry-after
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "60"}  # 60 seconds

        # Should return the retry-after value without raising
        result = retry.get_retry_after(mock_response)
        assert result == 60

    def test_raises_on_excessive_retry_after(self) -> None:
        """LimitedRetry should raise SpotifyRateLimitError for long waits."""
        retry = LimitedRetry(total=3)

        # Mock response with excessive retry-after (6 hours)
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "21600"}  # 6 hours

        # Should raise SpotifyRateLimitError
        with pytest.raises(SpotifyRateLimitError) as exc_info:
            retry.get_retry_after(mock_response)

        assert exc_info.value.retry_after_seconds == 21600
        assert "exceeds maximum wait" in str(exc_info.value)

    def test_threshold_boundary(self) -> None:
        """LimitedRetry should respect the exact threshold boundary."""
        retry = LimitedRetry(total=3)

        # At threshold should be allowed
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": str(MAX_RATE_LIMIT_WAIT_SECONDS)}

        result = retry.get_retry_after(mock_response)
        assert result == MAX_RATE_LIMIT_WAIT_SECONDS

        # Just over threshold should raise
        mock_response.headers = {"Retry-After": str(MAX_RATE_LIMIT_WAIT_SECONDS + 1)}

        with pytest.raises(SpotifyRateLimitError):
            retry.get_retry_after(mock_response)

    def test_handles_no_retry_after_header(self) -> None:
        """LimitedRetry should handle responses without Retry-After header."""
        retry = LimitedRetry(total=3)

        mock_response = MagicMock()
        mock_response.headers = {}

        # Should return None (no retry-after)
        result = retry.get_retry_after(mock_response)
        assert result is None
