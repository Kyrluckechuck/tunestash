"""
Tests for Qobuz download provider.
"""

from unittest.mock import AsyncMock, patch

import pytest
import requests
from downloader.providers.base import (
    QualityPreference,
    TrackMatch,
)
from downloader.providers.qobuz import (
    MIN_MATCH_CONFIDENCE,
    QOBUZ_CAPABILITIES,
    QOBUZ_QUALITY_MAP,
    QobuzProvider,
)


@pytest.fixture
def provider():
    """Create a QobuzProvider instance."""
    return QobuzProvider()


class TestQobuzProviderInit:
    """Tests for QobuzProvider initialization."""

    def test_default_init(self):
        """Test default initialization."""
        provider = QobuzProvider()
        assert provider._min_confidence == MIN_MATCH_CONFIDENCE
        assert provider.name == "qobuz"
        assert provider.display_name == "Qobuz"

    def test_custom_confidence(self):
        """Test custom confidence threshold."""
        provider = QobuzProvider(min_confidence=0.9)
        assert provider._min_confidence == 0.9

    def test_use_mp3_default_false(self):
        """Test use_mp3 defaults to False."""
        provider = QobuzProvider()
        assert provider._use_mp3 is False

    def test_use_mp3_option(self):
        """Test use_mp3 can be set to True."""
        provider = QobuzProvider(use_mp3=True)
        assert provider._use_mp3 is True


class TestQobuzProviderCapabilities:
    """Tests for provider capabilities."""

    def test_capabilities(self, provider):
        """Test capabilities are correct."""
        caps = provider.capabilities
        assert caps == QOBUZ_CAPABILITIES
        assert caps.supports_search is True
        assert caps.supports_isrc_lookup is False
        assert caps.embeds_metadata is False
        assert "mp3" in caps.formats
        assert "flac" in caps.formats


class TestQobuzQualityMapping:
    """Tests for quality level mapping."""

    def test_quality_map_high(self):
        """Test HIGH quality maps to FLAC (quality 6) for conversion to M4A."""
        assert QOBUZ_QUALITY_MAP[QualityPreference.HIGH] == 6

    def test_quality_map_lossless(self):
        """Test LOSSLESS quality maps to FLAC (quality 6)."""
        assert QOBUZ_QUALITY_MAP[QualityPreference.LOSSLESS] == 6

    def test_quality_map_hires(self):
        """Test HI_RES quality maps to FLAC 24-bit (quality 27)."""
        assert QOBUZ_QUALITY_MAP[QualityPreference.HI_RES] == 27


class TestQobuzProviderIsAvailable:
    """Tests for availability checking."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_is_available_success(self, provider):
        """Test availability check when API responds."""
        mock_response = {"success": True, "data": {"albums": {"items": []}}}

        with patch.object(
            provider, "_search_music", AsyncMock(return_value=mock_response)
        ):
            result = await provider.is_available()
            assert result is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_is_available_failure(self, provider):
        """Test availability check when API fails."""
        with patch.object(
            provider, "_search_music", AsyncMock(side_effect=Exception("API error"))
        ):
            result = await provider.is_available()
            assert result is False


class TestQobuzProviderSearchTrack:
    """Tests for track searching."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_track_no_results(self, provider):
        """Test search when no albums found."""
        mock_response = {"success": True, "data": {"albums": {"items": []}}}

        with patch.object(
            provider, "_search_music", AsyncMock(return_value=mock_response)
        ):
            result = await provider.search_track(
                title="Unknown Song", artist="Unknown Artist"
            )
            assert result is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_track_with_match(self, provider):
        """Test search when a matching track is found."""
        mock_search = {
            "data": {
                "albums": {
                    "items": [
                        {
                            "id": "album123",
                            "title": "Test Album",
                            "artist": {"name": "Test Artist"},
                            "tracks_count": 10,
                        }
                    ]
                }
            }
        }
        mock_album = {
            "data": {
                "title": "Test Album",
                "artist": {"name": "Test Artist"},
                "image": {"large": "https://example.com/cover.jpg"},
                "tracks_count": 10,
                "tracks": {
                    "items": [
                        {
                            "id": 12345,
                            "title": "Test Song",
                            "duration": 180,
                            "performer": {"name": "Test Artist"},
                            "isrc": "USRC12345678",
                        }
                    ]
                },
            }
        }

        with (
            patch.object(
                provider, "_search_music", AsyncMock(return_value=mock_search)
            ),
            patch.object(provider, "_get_album", AsyncMock(return_value=mock_album)),
        ):
            result = await provider.search_track(
                title="Test Song",
                artist="Test Artist",
                duration_ms=180000,
            )

            assert result is not None
            assert result.provider == "qobuz"
            assert result.title == "Test Song"
            assert result.artist == "Test Artist"
            assert result.confidence >= MIN_MATCH_CONFIDENCE

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_track_exception(self, provider):
        """Test search when an exception occurs."""
        with patch.object(
            provider,
            "_search_music",
            AsyncMock(side_effect=requests.RequestException("Network error")),
        ):
            result = await provider.search_track(
                title="Test Song", artist="Test Artist"
            )
            assert result is None


class TestQobuzProviderDownloadTrack:
    """Tests for track downloading."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_success(self, provider, tmp_path):
        """Test successful HIGH quality download returns FLAC (for M4A conversion)."""
        track_match = TrackMatch(
            provider="qobuz",
            provider_track_id="12345",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180000,
            confidence=0.95,
        )

        mock_download_info = {"data": {"url": "https://cdn.example.com/track.flac"}}

        output_path = tmp_path / "test.flac"

        with (
            patch.object(
                provider,
                "_get_download_url",
                AsyncMock(return_value=mock_download_info),
            ),
            patch.object(provider, "_download_file", AsyncMock()),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.HIGH,
            )

            assert result.success is True
            assert result.provider == "qobuz"
            assert result.format == "flac"
            assert result.bitrate_kbps == 1411

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_use_mp3(self, tmp_path):
        """Test HIGH quality with use_mp3=True returns MP3 directly."""
        provider = QobuzProvider(use_mp3=True)
        track_match = TrackMatch(
            provider="qobuz",
            provider_track_id="12345",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180000,
            confidence=0.95,
        )

        mock_download_info = {"data": {"url": "https://cdn.example.com/track.mp3"}}

        output_path = tmp_path / "test.mp3"

        with (
            patch.object(
                provider,
                "_get_download_url",
                AsyncMock(return_value=mock_download_info),
            ),
            patch.object(provider, "_download_file", AsyncMock()),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.HIGH,
            )

            assert result.success is True
            assert result.provider == "qobuz"
            assert result.format == "mp3"
            assert result.bitrate_kbps == 320

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_lossless(self, provider, tmp_path):
        """Test lossless download returns FLAC format."""
        track_match = TrackMatch(
            provider="qobuz",
            provider_track_id="12345",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180000,
            confidence=0.95,
        )

        mock_download_info = {"data": {"url": "https://cdn.example.com/track.flac"}}

        output_path = tmp_path / "test.flac"

        with (
            patch.object(
                provider,
                "_get_download_url",
                AsyncMock(return_value=mock_download_info),
            ),
            patch.object(provider, "_download_file", AsyncMock()),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.LOSSLESS,
            )

            assert result.success is True
            assert result.format == "flac"
            assert result.bitrate_kbps == 1411

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_no_url(self, provider, tmp_path):
        """Test download when no URL returned."""
        track_match = TrackMatch(
            provider="qobuz",
            provider_track_id="12345",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180000,
            confidence=0.95,
        )

        mock_download_info = {"data": {}}  # No URL

        output_path = tmp_path / "test.mp3"

        with patch.object(
            provider,
            "_get_download_url",
            AsyncMock(return_value=mock_download_info),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.HIGH,
            )

            assert result.success is False
            assert "No download URL" in result.error

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_request_exception(self, provider, tmp_path):
        """Test download when request fails."""
        track_match = TrackMatch(
            provider="qobuz",
            provider_track_id="12345",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180000,
            confidence=0.95,
        )

        output_path = tmp_path / "test.mp3"

        with patch.object(
            provider,
            "_get_download_url",
            AsyncMock(side_effect=requests.RequestException("Network error")),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.HIGH,
            )

            assert result.success is False
            assert result.error_retryable is True


class TestQobuzProviderParseTrackResult:
    """Tests for track result parsing."""

    def test_parse_track_result_basic(self, provider):
        """Test basic track parsing."""
        track = {
            "id": 12345,
            "title": "Test Song",
            "duration": 180,
            "performer": {"name": "Track Artist"},
        }
        album_data = {
            "title": "Test Album",
            "artist": {"name": "Album Artist"},
            "image": {"large": "https://example.com/cover.jpg"},
            "tracks_count": 10,
            "release_date_original": "2024-01-15",
        }

        result = provider._parse_track_result(track, album_data, confidence=0.9)

        assert result is not None
        assert result.provider == "qobuz"
        assert result.provider_track_id == "12345"
        assert result.title == "Test Song"
        assert result.artist == "Track Artist"
        assert result.album == "Test Album"
        assert result.duration_ms == 180000
        assert result.confidence == 0.9
        assert result.cover_url == "https://example.com/cover.jpg"

    def test_parse_track_result_fallback_to_album_artist(self, provider):
        """Test parsing falls back to album artist when track has no performer."""
        track = {
            "id": 12345,
            "title": "Test Song",
            "duration": 180,
            "performer": {},  # Empty performer
        }
        album_data = {
            "title": "Test Album",
            "artist": {"name": "Album Artist"},
            "image": {},
            "tracks_count": 10,
        }

        result = provider._parse_track_result(track, album_data, confidence=0.9)

        assert result is not None
        assert result.artist == "Album Artist"
