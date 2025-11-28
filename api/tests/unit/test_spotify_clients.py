"""Tests for dual Spotify client architecture and fail-fast error handling."""

from unittest.mock import MagicMock, patch

from downloader.downloader import Downloader
from downloader.spotdl_wrapper import (
    PlaylistSyncError,
    _is_fail_fast_error,
)
from downloader.spotipy_tasks import (
    OAuthSpotifyClient,
    PublicSpotifyClient,
    SpotifyClient,
)


class TestPublicSpotifyClient:
    """Tests for the PublicSpotifyClient class."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        PublicSpotifyClient.reset()

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        PublicSpotifyClient.reset()

    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_uses_client_credentials(
        self, mock_spotify: MagicMock, mock_creds: MagicMock
    ) -> None:
        """PublicSpotifyClient should use Client Credentials flow."""
        client = PublicSpotifyClient()

        # Should have created client credentials manager
        mock_creds.assert_called_once()
        # Should have created Spotify client with credentials manager
        mock_spotify.assert_called_once()
        assert client.sp is not None

    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_singleton_pattern(
        self, mock_spotify: MagicMock, mock_creds: MagicMock
    ) -> None:
        """PublicSpotifyClient should reuse the same instance."""
        client1 = PublicSpotifyClient()
        client2 = PublicSpotifyClient()

        assert client1 is client2
        # Should only initialize once
        assert mock_creds.call_count == 1

    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_reset_clears_singleton(
        self, mock_spotify: MagicMock, mock_creds: MagicMock
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

    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_uses_oauth_when_available(
        self, mock_spotify: MagicMock, mock_get_oauth: MagicMock
    ) -> None:
        """OAuthSpotifyClient should use OAuth token when available."""
        mock_get_oauth.return_value = {"access_token": "test_token"}

        client = OAuthSpotifyClient()

        # Should have used the OAuth token
        mock_spotify.assert_called_once_with(auth="test_token")
        assert client.is_oauth is True

    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.SpotifyClientCredentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_falls_back_to_client_credentials(
        self,
        mock_spotify: MagicMock,
        mock_creds: MagicMock,
        mock_get_oauth: MagicMock,
    ) -> None:
        """OAuthSpotifyClient should fall back to Client Credentials when no OAuth."""
        mock_get_oauth.return_value = None

        client = OAuthSpotifyClient()

        # Should have created client credentials
        mock_creds.assert_called_once()
        assert client.is_oauth is False

    @patch("downloader.spotipy_tasks.get_spotify_oauth_credentials")
    @patch("downloader.spotipy_tasks.spotipy.Spotify")
    def test_refresh_token(
        self, mock_spotify: MagicMock, mock_get_oauth: MagicMock
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

    def test_get_tracks_batch_uses_public_client(self) -> None:
        """get_tracks_batch() should use the public client."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_public.tracks.return_value = {"tracks": [{"id": "1"}, {"id": "2"}]}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_tracks_batch(["id1", "id2"])

        mock_public.tracks.assert_called_once()
        mock_oauth.tracks.assert_not_called()

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

    def test_get_playlist_uses_oauth_client(self) -> None:
        """get_playlist() should use the OAuth client (for private access)."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_oauth.playlist.return_value = {"id": "test", "tracks": {"items": []}}
        mock_oauth.next.return_value = None

        downloader = Downloader(mock_oauth, public_client=mock_public)
        downloader.get_playlist("test_id")

        mock_oauth.playlist.assert_called_once_with("test_id")
        mock_public.playlist.assert_not_called()

    def test_get_playlist_snapshot_id_tries_public_first(self) -> None:
        """get_playlist_snapshot_id() should try public client first."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_public.playlist.return_value = {"snapshot_id": "abc123"}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "abc123"
        mock_public.playlist.assert_called_once()
        mock_oauth.playlist.assert_not_called()

    def test_get_playlist_snapshot_id_falls_back_to_oauth(self) -> None:
        """get_playlist_snapshot_id() should fall back to OAuth on public failure."""
        mock_oauth = MagicMock()
        mock_public = MagicMock()
        mock_public.playlist.side_effect = Exception("Not found")
        mock_oauth.playlist.return_value = {"snapshot_id": "private123"}

        downloader = Downloader(mock_oauth, public_client=mock_public)
        result = downloader.get_playlist_snapshot_id("test_id")

        assert result == "private123"
        mock_public.playlist.assert_called_once()
        mock_oauth.playlist.assert_called_once()


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
