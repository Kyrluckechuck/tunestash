"""Simple validation tests that don't depend on Django models."""

from library_manager.validation import (
    extract_spotify_id,
    get_spotify_url_type,
    is_spotify_album_url,
    is_spotify_playlist_url,
    is_spotify_track_url,
    validate_spotify_url,
)
from library_manager.validators import is_local_track


class TestValidationFunctionsSimple:
    """Test validation utility functions without Django dependencies."""

    def test_validate_spotify_url_valid(self) -> None:
        """Test valid Spotify URL validation."""
        valid_urls = [
            "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
            "https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "spotify:track:4iV5W9uYEdYUVa79Axb7Rh",
            "spotify:album:4aawyAB9vmqN3uQ7FjRGTy",
            "spotify:artist:0TnOYISbd1XYRBk9myaseg",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        ]

        for url in valid_urls:
            is_valid, error = validate_spotify_url(url)
            assert is_valid is True, f"URL {url} should be valid: {error}"

    def test_validate_spotify_url_invalid(self) -> None:
        """Test invalid Spotify URL validation."""
        invalid_urls = [
            "invalid:url",
            "http://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://example.com",
            "",
            None,
            "spotify:",
            "https://open.spotify.com/",
            "not-a-url",
        ]

        for url in invalid_urls:
            is_valid, error = (
                validate_spotify_url(url) if url is not None else (False, "URL is None")
            )
            assert is_valid is False, f"URL {url} should be invalid"
            assert error is not None

    def test_extract_spotify_id_valid(self) -> None:
        """Test extracting Spotify ID from valid URLs."""
        test_cases = [
            (
                "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
                "4iV5W9uYEdYUVa79Axb7Rh",
            ),
            (
                "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
                "4aawyAB9vmqN3uQ7FjRGTy",
            ),
            (
                "https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
                "0TnOYISbd1XYRBk9myaseg",
            ),
            ("spotify:track:4iV5W9uYEdYUVa79Axb7Rh", "4iV5W9uYEdYUVa79Axb7Rh"),
            ("spotify:album:4aawyAB9vmqN3uQ7FjRGTy", "4aawyAB9vmqN3uQ7FjRGTy"),
        ]

        for url, expected_id in test_cases:
            extracted_id = extract_spotify_id(url)
            assert (
                extracted_id == expected_id
            ), f"Expected {expected_id}, got {extracted_id} for {url}"

    def test_is_spotify_playlist_url(self) -> None:
        """Test playlist URL detection."""
        playlist_urls = [
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
            "https://open.spotify.com/playlist/123",
        ]

        non_playlist_urls = [
            "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
            "https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
        ]

        for url in playlist_urls:
            assert (
                is_spotify_playlist_url(url) is True
            ), f"{url} should be detected as playlist"

        for url in non_playlist_urls:
            assert (
                is_spotify_playlist_url(url) is False
            ), f"{url} should not be detected as playlist"

    def test_is_spotify_album_url(self) -> None:
        """Test album URL detection."""
        album_urls = [
            "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
            "spotify:album:4aawyAB9vmqN3uQ7FjRGTy",
            "https://open.spotify.com/album/123",
        ]

        non_album_urls = [
            "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
        ]

        for url in album_urls:
            assert (
                is_spotify_album_url(url) is True
            ), f"{url} should be detected as album"

        for url in non_album_urls:
            assert (
                is_spotify_album_url(url) is False
            ), f"{url} should not be detected as album"

    def test_is_spotify_track_url(self) -> None:
        """Test track URL detection."""
        track_urls = [
            "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "spotify:track:4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/track/123",
        ]

        non_track_urls = [
            "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
        ]

        for url in track_urls:
            assert (
                is_spotify_track_url(url) is True
            ), f"{url} should be detected as track"

        for url in non_track_urls:
            assert (
                is_spotify_track_url(url) is False
            ), f"{url} should not be detected as track"

    def test_get_spotify_url_type(self) -> None:
        """Test URL type detection."""
        test_cases = [
            ("https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh", "track"),
            ("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy", "album"),
            ("https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg", "artist"),
            ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "playlist"),
            ("spotify:track:4iV5W9uYEdYUVa79Axb7Rh", "track"),
            ("spotify:album:4aawyAB9vmqN3uQ7FjRGTy", "album"),
        ]

        for url, expected_type in test_cases:
            url_type = get_spotify_url_type(url)
            assert (
                url_type == expected_type
            ), f"Expected {expected_type}, got {url_type} for {url}"

    def test_validate_spotify_url_edge_cases(self) -> None:
        """Test edge cases for URL validation."""
        edge_cases = [
            ("https://open.spotify.com/track/", True),
            ("spotify:track:", True),
            ("https://open.spotify.com/unknown/123", True),
            ("spotify:unknown:123", True),
        ]

        for url, expected_valid in edge_cases:
            is_valid, error = validate_spotify_url(url)
            assert (
                is_valid == expected_valid
            ), f"URL {url} should be {expected_valid}, got {is_valid}"

    def test_extract_spotify_id_edge_cases(self) -> None:
        """Test edge cases for ID extraction."""
        edge_cases = [
            ("https://open.spotify.com/track/", None),
            ("spotify:track:", None),
            ("https://open.spotify.com/unknown/123", "123"),
            ("spotify:unknown:123", "123"),
        ]

        for url, expected_id in edge_cases:
            extracted_id = extract_spotify_id(url)
            assert (
                extracted_id == expected_id
            ), f"Expected {expected_id}, got {extracted_id} for {url}"

    def test_url_type_detection_case_insensitive(self) -> None:
        """Test that URL type detection is case insensitive."""
        test_cases = [
            ("https://open.spotify.com/TRACK/4iV5W9uYEdYUVa79Axb7Rh", "track"),
            ("https://open.spotify.com/ALBUM/4aawyAB9vmqN3uQ7FjRGTy", "album"),
            ("https://open.spotify.com/PLAYLIST/37i9dQZF1DXcBWIGoYBM5M", "playlist"),
            ("spotify:TRACK:4iV5W9uYEdYUVa79Axb7Rh", "track"),
            ("spotify:ALBUM:4aawyAB9vmqN3uQ7FjRGTy", "album"),
        ]

        for url, expected_type in test_cases:
            url_type = get_spotify_url_type(url)
            assert (
                url_type == expected_type
            ), f"Expected {expected_type}, got {url_type} for {url}"


class TestIsLocalTrack:
    """Test local track detection for Spotify playlist items."""

    def test_is_local_track_with_is_local_true(self) -> None:
        """Test detection when is_local flag is explicitly True."""
        local_track = {
            "is_local": True,
            "id": None,
            "name": "My Local Song",
            "artists": [{"name": "Unknown Artist", "id": None}],
        }
        assert is_local_track(local_track) is True

    def test_is_local_track_with_null_id(self) -> None:
        """Test detection when track has null ID (fallback check)."""
        track_with_null_id = {
            "id": None,
            "name": "Weird Track",
            "artists": [{"name": "Artist", "id": None}],
        }
        assert is_local_track(track_with_null_id) is True

    def test_is_local_track_regular_track(self) -> None:
        """Test that regular Spotify tracks are not detected as local."""
        regular_track = {
            "is_local": False,
            "id": "6rqhFgbbKwnb9MLmUQDhG6",
            "name": "Real Spotify Song",
            "artists": [{"name": "Real Artist", "id": "0TnOYISbd1XYRBk9myaseg"}],
            "external_urls": {
                "spotify": "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6"
            },
        }
        assert is_local_track(regular_track) is False

    def test_is_local_track_without_is_local_field(self) -> None:
        """Test track without is_local field but with valid ID."""
        track_missing_field = {
            "id": "6rqhFgbbKwnb9MLmUQDhG6",
            "name": "Song Without is_local Field",
            "artists": [{"name": "Artist", "id": "0TnOYISbd1XYRBk9myaseg"}],
        }
        assert is_local_track(track_missing_field) is False

    def test_is_local_track_empty_dict(self) -> None:
        """Test with empty dictionary."""
        assert is_local_track({}) is False

    def test_is_local_track_none(self) -> None:
        """Test with None input."""
        assert is_local_track(None) is False

    def test_is_local_track_non_dict(self) -> None:
        """Test with non-dict input."""
        assert is_local_track("not a dict") is False
        assert is_local_track(123) is False
        assert is_local_track([]) is False
