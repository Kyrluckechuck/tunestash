"""Tests for track metadata enrichment from Deezer.

This covers the _build_track_metadata function that was the root cause of
the 'Unknown Album' directory bug — songs without album links were getting
empty album names, which the downloader turned into 'Unknown Album' paths.
"""

from unittest.mock import MagicMock, patch

import pytest

from library_manager.tasks.maintenance import _build_track_metadata


@pytest.mark.django_db
class TestBuildTrackMetadata:
    """Test metadata enrichment for download tasks."""

    def _make_song(self, **overrides):
        """Create a minimal Song-like mock."""
        from library_manager.models import Artist, Song

        defaults = {
            "name": "Test Song",
            "isrc": "USRC12345678",
            "deezer_id": 12345,
        }
        defaults.update(overrides)

        artist = Artist.objects.create(
            name=defaults.pop("artist_name", "Test Artist"),
            gid=f"gid-{id(defaults)}",
        )
        song = Song.objects.create(primary_artist=artist, **defaults)
        # Re-fetch with select_related so .primary_artist and .album work
        return Song.objects.select_related("primary_artist", "album").get(id=song.id)

    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_uses_deezer_album_when_song_has_no_album(self, mock_provider_cls):
        """Regression: songs without album FK should get album name from Deezer."""
        mock_track = MagicMock()
        mock_track.album_name = "Real Album Name"
        mock_track.duration_ms = 240000
        mock_track.isrc = "USRC12345678"
        mock_track.artist_name = "Deezer Artist"
        mock_provider_cls.return_value.get_track.return_value = mock_track

        song = self._make_song(album=None)
        metadata = _build_track_metadata(song)

        assert metadata.album == "Real Album Name"
        assert metadata.duration_ms == 240000
        assert metadata.artist == "Deezer Artist"

    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_keeps_existing_album_name(self, mock_provider_cls):
        """When song has an album FK, use that instead of Deezer."""
        from library_manager.models import Album

        song_no_album = self._make_song(album=None)
        artist = song_no_album.primary_artist
        album = Album.objects.create(name="DB Album", artist=artist, deezer_id=99999)
        song_no_album.album = album
        song_no_album.save(update_fields=["album_id"])
        song = (
            type(song_no_album)
            .objects.select_related("primary_artist", "album")
            .get(id=song_no_album.id)
        )

        metadata = _build_track_metadata(song)

        assert metadata.album == "DB Album"

    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_handles_deezer_api_failure(self, mock_provider_cls):
        """If Deezer API fails, should still produce valid metadata."""
        mock_provider_cls.return_value.get_track.side_effect = Exception("API error")

        song = self._make_song(album=None)
        metadata = _build_track_metadata(song)

        # Should fall back to empty album and 0 duration
        assert metadata.album == ""
        assert metadata.duration_ms == 0
        assert metadata.artist == "Test Artist"

    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_enriches_isrc_from_deezer(self, mock_provider_cls):
        """Missing ISRC on song should be filled from Deezer."""
        mock_track = MagicMock()
        mock_track.album_name = "Album"
        mock_track.duration_ms = 180000
        mock_track.isrc = "NEW_ISRC_123"
        mock_track.artist_name = "Artist"
        mock_provider_cls.return_value.get_track.return_value = mock_track

        song = self._make_song(isrc=None, album=None)
        metadata = _build_track_metadata(song)

        assert metadata.isrc == "NEW_ISRC_123"

    def test_no_deezer_id_skips_enrichment(self):
        """Songs without deezer_id shouldn't attempt API calls."""
        song = self._make_song(deezer_id=None, youtube_id="yt_test_123", album=None)
        metadata = _build_track_metadata(song)

        assert metadata.album == ""
        assert metadata.duration_ms == 0
