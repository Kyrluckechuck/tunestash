"""Tests for the MetadataEmbedder."""

from unittest.mock import MagicMock, patch

import pytest
from downloader.providers.base import TrackMatch, TrackMetadata
from downloader.providers.metadata import (
    MetadataEmbedder,
    create_metadata_from_match,
)


@pytest.fixture
def embedder():
    """Create a MetadataEmbedder instance."""
    return MetadataEmbedder()


@pytest.fixture
def spotify_metadata():
    """Create sample Spotify metadata."""
    return TrackMetadata(
        spotify_id="4iV5W9uYEdYUVa79Axb7Rh",
        title="Blinding Lights",
        artist="The Weeknd",
        album="After Hours",
        album_artist="The Weeknd",
        duration_ms=200000,
        isrc="USUG11904206",
        track_number=9,
        total_tracks=14,
        disc_number=1,
        total_discs=1,
        release_date="2020-03-20",
        cover_url="https://i.scdn.co/image/ab67616d0000b273ef017e899c0547766997d874",
        copyright="2020 Republic Records",
        genres=("synth-pop", "r&b"),
    )


@pytest.fixture
def track_match():
    """Create a sample TrackMatch."""
    return TrackMatch(
        provider="tidal",
        provider_track_id="123456",
        title="Blinding Lights",
        artist="The Weeknd",
        album="After Hours",
        duration_ms=200000,
        isrc="USUG11904206",
        confidence=0.95,
        cover_url="https://resources.tidal.com/images/abc/640x640.jpg",
        track_number=9,
        total_tracks=14,
        release_date="2020-03-20",
    )


class TestMetadataEmbedderMP4:
    """Tests for MP4/M4A metadata embedding."""

    @pytest.mark.unit
    def test_embed_mp4_metadata_mocked(self, embedder, spotify_metadata, tmp_path):
        """Test MP4 metadata embedding with mocked mutagen."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake audio data")

        # Use a real dict to capture setitem calls
        tags_dict = {}
        mock_mp4 = MagicMock()
        mock_mp4.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_mp4.__getitem__ = lambda self, k: tags_dict.__getitem__(k)
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
        ):
            # Mock cover art fetch
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"  # JPEG magic bytes
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = embedder._embed_mp4_metadata(file_path, spotify_metadata, None)

        assert result is True
        # Verify tags were set
        assert tags_dict["\xa9nam"] == [spotify_metadata.title]
        assert tags_dict["\xa9ART"] == [spotify_metadata.artist]
        assert tags_dict["\xa9alb"] == [spotify_metadata.album]
        mock_mp4.save.assert_called_once()

    @pytest.mark.unit
    def test_embed_mp4_with_track_number(self, embedder, spotify_metadata, tmp_path):
        """Test track number embedding in MP4."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake audio data")

        tags_dict = {}
        mock_mp4 = MagicMock()
        mock_mp4.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_mp4_metadata(file_path, spotify_metadata, None)

        assert tags_dict["trkn"] == [(9, 14)]
        assert tags_dict["disk"] == [(1, 1)]

    @pytest.mark.unit
    def test_embed_mp4_with_isrc(self, embedder, spotify_metadata, tmp_path):
        """Test ISRC embedding in MP4."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake audio data")

        tags_dict = {}
        mock_mp4 = MagicMock()
        mock_mp4.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_mp4_metadata(file_path, spotify_metadata, None)

        assert tags_dict["----:com.apple.iTunes:ISRC"] == [b"USUG11904206"]

    @pytest.mark.unit
    def test_embed_mp4_cover_art_from_track_match(
        self, embedder, spotify_metadata, track_match, tmp_path
    ):
        """Test cover art fallback to track match."""
        # Remove cover from spotify metadata
        spotify_metadata_no_cover = TrackMetadata(
            spotify_id="test",
            title="Test",
            artist="Artist",
            album="Album",
            album_artist="Artist",
            duration_ms=200000,
            cover_url=None,  # No cover
        )

        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake audio data")

        mock_mp4 = MagicMock()
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"  # JPEG
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = embedder._embed_mp4_metadata(
                file_path, spotify_metadata_no_cover, track_match
            )

        assert result is True
        # Cover should have been fetched from track_match URL
        mock_get.assert_called_once()
        assert track_match.cover_url in str(mock_get.call_args)


class TestMetadataEmbedderFLAC:
    """Tests for FLAC metadata embedding."""

    @pytest.mark.unit
    def test_embed_flac_metadata_mocked(self, embedder, spotify_metadata, tmp_path):
        """Test FLAC metadata embedding with mocked mutagen."""
        file_path = tmp_path / "test.flac"
        file_path.write_bytes(b"fake audio data")

        tags_dict = {}
        mock_flac = MagicMock()
        mock_flac.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_flac_class = MagicMock(return_value=mock_flac)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.flac.FLAC", mock_flac_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = embedder._embed_flac_metadata(file_path, spotify_metadata, None)

        assert result is True
        assert tags_dict["TITLE"] == [spotify_metadata.title]
        assert tags_dict["ARTIST"] == [spotify_metadata.artist]
        assert tags_dict["ALBUM"] == [spotify_metadata.album]
        assert tags_dict["ALBUMARTIST"] == [spotify_metadata.album_artist]
        mock_flac.save.assert_called_once()

    @pytest.mark.unit
    def test_embed_flac_with_track_info(self, embedder, spotify_metadata, tmp_path):
        """Test track info embedding in FLAC."""
        file_path = tmp_path / "test.flac"
        file_path.write_bytes(b"fake audio data")

        tags_dict = {}
        mock_flac = MagicMock()
        mock_flac.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_flac_class = MagicMock(return_value=mock_flac)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.flac.FLAC", mock_flac_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_flac_metadata(file_path, spotify_metadata, None)

        assert tags_dict["TRACKNUMBER"] == ["9"]
        assert tags_dict["TRACKTOTAL"] == ["14"]
        assert tags_dict["DISCNUMBER"] == ["1"]
        assert tags_dict["DISCTOTAL"] == ["1"]

    @pytest.mark.unit
    def test_embed_flac_genres(self, embedder, spotify_metadata, tmp_path):
        """Test genre embedding in FLAC."""
        file_path = tmp_path / "test.flac"
        file_path.write_bytes(b"fake audio data")

        tags_dict = {}
        mock_flac = MagicMock()
        mock_flac.__setitem__ = lambda self, k, v: tags_dict.__setitem__(k, v)
        mock_flac_class = MagicMock(return_value=mock_flac)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.flac.FLAC", mock_flac_class),
        ):
            mock_response = MagicMock()
            mock_response.content = b"\xff\xd8\xff"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_flac_metadata(file_path, spotify_metadata, None)

        assert tags_dict["GENRE"] == ["synth-pop", "r&b"]


class TestMetadataEmbedderDispatch:
    """Tests for format detection and dispatch."""

    @pytest.mark.unit
    def test_embed_metadata_m4a(self, embedder, spotify_metadata, tmp_path):
        """Test M4A dispatch."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake")

        with patch.object(embedder, "_embed_mp4_metadata", return_value=True) as mock:
            result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is True
        mock.assert_called_once()

    @pytest.mark.unit
    def test_embed_metadata_mp4(self, embedder, spotify_metadata, tmp_path):
        """Test MP4 dispatch."""
        file_path = tmp_path / "test.mp4"
        file_path.write_bytes(b"fake")

        with patch.object(embedder, "_embed_mp4_metadata", return_value=True) as mock:
            result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is True
        mock.assert_called_once()

    @pytest.mark.unit
    def test_embed_metadata_aac(self, embedder, spotify_metadata, tmp_path):
        """Test AAC dispatch."""
        file_path = tmp_path / "test.aac"
        file_path.write_bytes(b"fake")

        with patch.object(embedder, "_embed_mp4_metadata", return_value=True) as mock:
            result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is True
        mock.assert_called_once()

    @pytest.mark.unit
    def test_embed_metadata_flac(self, embedder, spotify_metadata, tmp_path):
        """Test FLAC dispatch."""
        file_path = tmp_path / "test.flac"
        file_path.write_bytes(b"fake")

        with patch.object(embedder, "_embed_flac_metadata", return_value=True) as mock:
            result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is True
        mock.assert_called_once()

    @pytest.mark.unit
    def test_embed_metadata_unsupported_format(
        self, embedder, spotify_metadata, tmp_path
    ):
        """Test unsupported format returns False."""
        file_path = tmp_path / "test.mp3"
        file_path.write_bytes(b"fake")

        result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is False

    @pytest.mark.unit
    def test_embed_metadata_case_insensitive(
        self, embedder, spotify_metadata, tmp_path
    ):
        """Test extension detection is case insensitive."""
        file_path = tmp_path / "test.M4A"
        file_path.write_bytes(b"fake")

        with patch.object(embedder, "_embed_mp4_metadata", return_value=True) as mock:
            result = embedder.embed_metadata(file_path, spotify_metadata)

        assert result is True
        mock.assert_called_once()


class TestCoverArtFetch:
    """Tests for cover art fetching."""

    @pytest.mark.unit
    def test_fetch_cover_art_success(self, embedder):
        """Test successful cover art fetch."""
        with patch("downloader.providers.metadata.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.content = b"image data"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = embedder._fetch_cover_art("https://example.com/cover.jpg")

        assert result == b"image data"

    @pytest.mark.unit
    def test_fetch_cover_art_failure(self, embedder):
        """Test cover art fetch failure."""
        import requests as req

        with patch("downloader.providers.metadata.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("Network error")

            result = embedder._fetch_cover_art("https://example.com/cover.jpg")

        assert result is None

    @pytest.mark.unit
    def test_detect_jpeg_format(self, embedder, spotify_metadata, tmp_path):
        """Test JPEG detection from magic bytes."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake")

        mock_mp4 = MagicMock()
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
            patch("mutagen.mp4.MP4Cover") as mock_cover,
        ):
            mock_response = MagicMock()
            # JPEG magic bytes
            mock_response.content = b"\xff\xd8\xff\xe0"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_mp4_metadata(file_path, spotify_metadata, None)

        # Should detect JPEG format
        mock_cover.assert_called_once()
        call_args = mock_cover.call_args
        assert call_args[1]["imageformat"] == mock_cover.FORMAT_JPEG

    @pytest.mark.unit
    def test_detect_png_format(self, embedder, spotify_metadata, tmp_path):
        """Test PNG detection from magic bytes."""
        file_path = tmp_path / "test.m4a"
        file_path.write_bytes(b"fake")

        mock_mp4 = MagicMock()
        mock_mp4_class = MagicMock(return_value=mock_mp4)

        with (
            patch("downloader.providers.metadata.requests.get") as mock_get,
            patch("mutagen.mp4.MP4", mock_mp4_class),
            patch("mutagen.mp4.MP4Cover") as mock_cover,
        ):
            mock_response = MagicMock()
            # PNG magic bytes
            mock_response.content = b"\x89PNG\r\n\x1a\n"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            embedder._embed_mp4_metadata(file_path, spotify_metadata, None)

        mock_cover.assert_called_once()
        call_args = mock_cover.call_args
        assert call_args[1]["imageformat"] == mock_cover.FORMAT_PNG


class TestCreateSpotifyMetadataFromMatch:
    """Tests for create_metadata_from_match utility."""

    @pytest.mark.unit
    def test_create_from_match_full(self, track_match):
        """Test creating metadata from a full track match."""
        metadata = create_metadata_from_match(
            track_match,
            spotify_id="spotify123",
            album_artist="Album Artist",
        )

        assert metadata.spotify_id == "spotify123"
        assert metadata.title == track_match.title
        assert metadata.artist == track_match.artist
        assert metadata.album == track_match.album
        assert metadata.album_artist == "Album Artist"
        assert metadata.duration_ms == track_match.duration_ms
        assert metadata.isrc == track_match.isrc
        assert metadata.track_number == track_match.track_number
        assert metadata.total_tracks == track_match.total_tracks
        assert metadata.release_date == track_match.release_date
        assert metadata.cover_url == track_match.cover_url

    @pytest.mark.unit
    def test_create_from_match_default_album_artist(self, track_match):
        """Test album artist defaults to artist."""
        metadata = create_metadata_from_match(track_match)

        assert metadata.album_artist == track_match.artist

    @pytest.mark.unit
    def test_create_from_match_minimal(self):
        """Test creating metadata from minimal track match."""
        match = TrackMatch(
            provider="test",
            provider_track_id="123",
            title="Song",
            artist="Artist",
            album="Album",
            duration_ms=180000,
            confidence=0.9,
        )

        metadata = create_metadata_from_match(match)

        assert metadata.title == "Song"
        assert metadata.artist == "Artist"
        assert metadata.album == "Album"
        assert metadata.track_number is None
        assert metadata.isrc is None
        assert metadata.cover_url is None
