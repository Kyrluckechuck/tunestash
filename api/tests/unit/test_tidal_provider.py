"""Tests for the TidalProvider."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from downloader.providers.base import (
    ProviderType,
    QualityPreference,
    TrackMatch,
)
from downloader.providers.tidal import (
    TIDAL_CAPABILITIES,
    TidalProvider,
)
from downloader.providers.tidal_endpoints import TidalEndpoint, TidalEndpointManager


@pytest.fixture
def mock_endpoint():
    """Create a mock endpoint."""
    return TidalEndpoint(
        name="test",
        base_url="https://test.squid.wtf",
        weight=10,
    )


@pytest.fixture
def mock_endpoint_manager(mock_endpoint):
    """Create a mock endpoint manager with async get_endpoint."""
    manager = MagicMock(spec=TidalEndpointManager)
    manager.get_endpoint = AsyncMock(return_value=mock_endpoint)
    manager.get_all_healthy_endpoints = AsyncMock(return_value=[mock_endpoint])
    manager.mark_endpoint_success = MagicMock()
    manager.mark_endpoint_failure = MagicMock()
    return manager


@pytest.fixture
def provider(mock_endpoint_manager):
    """Create a TidalProvider with mocked endpoint manager."""
    return TidalProvider(endpoint_manager=mock_endpoint_manager)


@pytest.fixture
def sample_search_response():
    """Sample search API response (squid.wtf format)."""
    return {
        "version": "2.0",
        "data": {
            "items": [
                {
                    "id": 123456,
                    "title": "Blinding Lights",
                    "duration": 200,  # seconds
                    "isrc": "USUG11904206",
                    "trackNumber": 1,
                    "artists": [{"name": "The Weeknd"}],
                    "album": {
                        "title": "After Hours",
                        "cover": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                        "numberOfTracks": 14,
                        "releaseDate": "2020-03-20",
                    },
                },
                {
                    "id": 789012,
                    "title": "Blinding Lights (Radio Edit)",
                    "duration": 195,
                    "isrc": "USUG11904207",
                    "trackNumber": 1,
                    "artists": [{"name": "The Weeknd"}],
                    "album": {
                        "title": "After Hours (Deluxe)",
                        "cover": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                        "numberOfTracks": 16,
                        "releaseDate": "2020-03-20",
                    },
                },
            ]
        },
    }


@pytest.fixture
def sample_track_response():
    """Sample track info API response."""
    return {
        "data": {
            "id": 123456,
            "title": "Blinding Lights",
            "duration": 200,
            "isrc": "USUG11904206",
            "trackNumber": 1,
            "artists": [{"name": "The Weeknd"}],
            "album": {
                "title": "After Hours",
                "cover": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "numberOfTracks": 14,
                "releaseDate": "2020-03-20",
            },
        }
    }


@pytest.fixture
def sample_stream_response():
    """Sample stream API response."""
    manifest = {"urls": ["https://cdn.tidal.com/track/123456.m4a"]}
    manifest_b64 = base64.b64encode(json.dumps(manifest).encode()).decode()
    return {
        "data": {
            "manifest": manifest_b64,
            "mimeType": "audio/mp4",
            "audioQuality": "HIGH",
        }
    }


@pytest.fixture
def sample_lossless_stream_response():
    """Sample lossless stream API response."""
    manifest = {"urls": ["https://cdn.tidal.com/track/123456.flac"]}
    manifest_b64 = base64.b64encode(json.dumps(manifest).encode()).decode()
    return {
        "data": {
            "manifest": manifest_b64,
            "mimeType": "audio/flac",
            "audioQuality": "LOSSLESS",
        }
    }


class TestTidalProviderProperties:
    """Tests for TidalProvider basic properties."""

    @pytest.mark.unit
    def test_name(self, provider):
        """Test provider name."""
        assert provider.name == "tidal"

    @pytest.mark.unit
    def test_display_name(self, provider):
        """Test provider display name."""
        assert provider.display_name == "Tidal"

    @pytest.mark.unit
    def test_capabilities(self, provider):
        """Test provider capabilities."""
        caps = provider.capabilities
        assert caps == TIDAL_CAPABILITIES
        assert caps.provider_type == ProviderType.REST_API
        assert caps.supports_search is True
        assert caps.supports_isrc_lookup is False
        assert caps.embeds_metadata is False
        assert len(caps.available_qualities) == 3

    @pytest.mark.unit
    def test_capabilities_max_bitrate(self, provider):
        """Test max bitrate from capabilities."""
        assert provider.capabilities.max_bitrate_kbps == 9216  # Hi-res

    @pytest.mark.unit
    def test_capabilities_supports_lossless(self, provider):
        """Test lossless support."""
        assert provider.capabilities.supports_lossless is True


class TestTidalProviderIsAvailable:
    """Tests for is_available method."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_is_available_with_endpoint(self, provider, mock_endpoint):
        """Test is_available returns True when endpoint exists."""
        provider._endpoint_manager.get_endpoint = AsyncMock(return_value=mock_endpoint)
        result = await provider.is_available()
        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_is_available_without_endpoint(self, provider):
        """Test is_available returns False when no endpoint."""
        provider._endpoint_manager.get_endpoint = AsyncMock(return_value=None)
        result = await provider.is_available()
        assert result is False


class TestTidalProviderSearch:
    """Tests for search_track method."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_finds_match(
        self, provider, mock_endpoint, sample_search_response
    ):
        """Test successful track search."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        mock_response = MagicMock()
        mock_response.json.return_value = sample_search_response
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = await provider.search_track(
                title="Blinding Lights",
                artist="The Weeknd",
            )

        assert result is not None
        assert result.title == "Blinding Lights"
        assert result.artist == "The Weeknd"
        assert result.provider_track_id == "123456"
        assert result.isrc == "USUG11904206"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_uses_isrc_for_confidence(
        self, provider, mock_endpoint, sample_search_response
    ):
        """Test that ISRC is used for confidence calculation."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        mock_response = MagicMock()
        mock_response.json.return_value = sample_search_response
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = await provider.search_track(
                title="Blinding Lights",
                artist="The Weeknd",
                isrc="USUG11904206",  # Matching ISRC
            )

        assert result is not None
        assert result.confidence > 0.9

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_no_endpoint(self, provider):
        """Test search returns None when no endpoint available."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[]
        )
        result = await provider.search_track(
            title="Test",
            artist="Artist",
        )
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_no_results(self, provider, mock_endpoint):
        """Test search returns None when no results."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"version": "2.0", "data": {"items": []}}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = await provider.search_track(
                title="Nonexistent Song",
                artist="Unknown Artist",
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_low_confidence(self, provider, mock_endpoint):
        """Test search returns None when confidence is too low."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "version": "2.0",
            "data": {
                "items": [
                    {
                        "id": 999,
                        "title": "Completely Different Song",
                        "duration": 300,
                        "artists": [{"name": "Other Artist"}],
                        "album": {"title": "Other Album"},
                    }
                ]
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = await provider.search_track(
                title="Blinding Lights",
                artist="The Weeknd",
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track_api_error(self, provider, mock_endpoint):
        """Test search handles API errors and retries with other endpoints."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        with patch(
            "downloader.providers.tidal.requests.get",
            side_effect=requests.RequestException("API Error"),
        ):
            result = await provider.search_track(
                title="Test",
                artist="Artist",
            )

        assert result is None
        provider._endpoint_manager.mark_endpoint_failure.assert_called_once()


class TestTidalProviderDownload:
    """Tests for download_track method."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_track_success(
        self, provider, mock_endpoint, sample_stream_response, tmp_path
    ):
        """Test successful track download."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        output_path = tmp_path / "test.m4a"
        track_match = TrackMatch(
            provider="tidal",
            provider_track_id="123456",
            title="Test",
            artist="Artist",
            album="Album",
            duration_ms=200000,
            confidence=0.95,
        )

        # Mock stream info response
        stream_response = MagicMock()
        stream_response.json.return_value = sample_stream_response
        stream_response.raise_for_status = MagicMock()

        # Mock file download response
        download_response = MagicMock()
        download_response.iter_content = MagicMock(return_value=[b"audio data"])
        download_response.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "/track/" in url:
                return stream_response
            return download_response

        with patch("downloader.providers.tidal.requests.get", side_effect=mock_get):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.HIGH,
            )

        assert result.success is True
        assert result.provider == "tidal"
        assert result.file_path == output_path
        assert result.format == "aac"
        assert result.bitrate_kbps == 320
        assert result.metadata_embedded is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_track_lossless(
        self, provider, mock_endpoint, sample_lossless_stream_response, tmp_path
    ):
        """Test lossless track download."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        output_path = tmp_path / "test.flac"
        track_match = TrackMatch(
            provider="tidal",
            provider_track_id="123456",
            title="Test",
            artist="Artist",
            album="Album",
            duration_ms=200000,
            confidence=0.95,
        )

        stream_response = MagicMock()
        stream_response.json.return_value = sample_lossless_stream_response
        stream_response.raise_for_status = MagicMock()

        download_response = MagicMock()
        download_response.iter_content = MagicMock(return_value=[b"flac data"])
        download_response.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "/track/" in url:
                return stream_response
            return download_response

        with patch("downloader.providers.tidal.requests.get", side_effect=mock_get):
            result = await provider.download_track(
                track_match=track_match,
                output_path=output_path,
                quality=QualityPreference.LOSSLESS,
            )

        assert result.success is True
        assert result.format == "flac"
        assert result.bitrate_kbps == 1411

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_track_no_endpoint(self, provider, tmp_path):
        """Test download fails when no endpoint available."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[]
        )

        track_match = TrackMatch(
            provider="tidal",
            provider_track_id="123456",
            title="Test",
            artist="Artist",
            album="Album",
            duration_ms=200000,
            confidence=0.95,
        )

        result = await provider.download_track(
            track_match=track_match,
            output_path=tmp_path / "test.m4a",
            quality=QualityPreference.HIGH,
        )

        assert result.success is False
        assert "No healthy" in result.error

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_track_stream_error(self, provider, mock_endpoint, tmp_path):
        """Test download handles stream API errors by trying all endpoints."""
        provider._endpoint_manager.get_all_healthy_endpoints = AsyncMock(
            return_value=[mock_endpoint]
        )

        track_match = TrackMatch(
            provider="tidal",
            provider_track_id="123456",
            title="Test",
            artist="Artist",
            album="Album",
            duration_ms=200000,
            confidence=0.95,
        )

        with patch(
            "downloader.providers.tidal.requests.get",
            side_effect=requests.RequestException("API Error"),
        ):
            result = await provider.download_track(
                track_match=track_match,
                output_path=tmp_path / "test.m4a",
                quality=QualityPreference.HIGH,
            )

        assert result.success is False
        assert result.error_retryable is True


class TestTidalProviderGetTrackInfo:
    """Tests for get_track_info method."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_track_info_success(
        self, provider, mock_endpoint, sample_track_response
    ):
        """Test successful track info retrieval."""
        provider._endpoint_manager.get_endpoint = AsyncMock(return_value=mock_endpoint)

        mock_response = MagicMock()
        mock_response.json.return_value = sample_track_response
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = await provider.get_track_info("123456")

        assert result is not None
        assert result.title == "Blinding Lights"
        assert result.artist == "The Weeknd"
        assert result.album == "After Hours"
        assert result.confidence == 1.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_track_info_no_endpoint(self, provider):
        """Test get_track_info returns None when no endpoint."""
        provider._endpoint_manager.get_endpoint = AsyncMock(return_value=None)
        result = await provider.get_track_info("123456")
        assert result is None


class TestTidalProviderParseTrackResult:
    """Tests for _parse_track_result method."""

    @pytest.mark.unit
    def test_parse_track_result_full(self, provider):
        """Test parsing a full track result."""
        result = {
            "id": 123456,
            "title": "Test Song",
            "duration": 240,
            "isrc": "TEST12345678",
            "trackNumber": 5,
            "artists": [{"name": "Test Artist"}],
            "album": {
                "title": "Test Album",
                "cover": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "numberOfTracks": 12,
                "releaseDate": "2024-01-15",
            },
        }

        match = provider._parse_track_result(result, confidence=0.8)

        assert match is not None
        assert match.provider == "tidal"
        assert match.provider_track_id == "123456"
        assert match.title == "Test Song"
        assert match.artist == "Test Artist"
        assert match.album == "Test Album"
        assert match.duration_ms == 240000  # seconds to ms
        assert match.isrc == "TEST12345678"
        assert match.confidence == 0.8
        assert match.track_number == 5
        assert match.total_tracks == 12
        assert match.release_date == "2024-01-15"
        assert "640x640.jpg" in match.cover_url

    @pytest.mark.unit
    def test_parse_track_result_minimal(self, provider):
        """Test parsing a minimal track result."""
        result = {
            "id": 123,
            "title": "Song",
            "duration": 180,
            "artists": [{"name": "Artist"}],
            "album": {},
        }

        match = provider._parse_track_result(result, confidence=0.5)

        assert match is not None
        assert match.title == "Song"
        assert match.artist == "Artist"
        assert match.album == ""
        assert match.cover_url is None

    @pytest.mark.unit
    def test_parse_track_result_invalid(self, provider):
        """Test parsing invalid result returns None."""
        # Missing required fields
        result = {"title": "Song"}

        match = provider._parse_track_result(result, confidence=0.5)

        # Should handle gracefully
        assert match is None or match.artist == "Unknown"


class TestTidalProviderManifestDecoding:
    """Tests for manifest decoding in stream info."""

    @pytest.mark.unit
    def test_decode_json_manifest(self, provider, mock_endpoint):
        """Test decoding a JSON manifest."""
        manifest = {"urls": ["https://cdn.example.com/track.m4a"]}
        manifest_b64 = base64.b64encode(json.dumps(manifest).encode()).decode()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "manifest": manifest_b64,
                "mimeType": "audio/mp4",
                "audioQuality": "HIGH",
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = provider._get_stream_info_sync(
                mock_endpoint, "123", QualityPreference.HIGH
            )

        assert result is not None
        assert result["url"] == "https://cdn.example.com/track.m4a"
        assert result["format"] == "aac"
        assert result["bitrate_kbps"] == 320

    @pytest.mark.unit
    def test_decode_direct_url_manifest(self, provider, mock_endpoint):
        """Test decoding a direct URL manifest."""
        url = "https://cdn.example.com/direct.m4a"
        manifest_b64 = base64.b64encode(url.encode()).decode()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "manifest": manifest_b64,
                "mimeType": "audio/mp4",
                "audioQuality": "HIGH",
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "downloader.providers.tidal.requests.get", return_value=mock_response
        ):
            result = provider._get_stream_info_sync(
                mock_endpoint, "123", QualityPreference.HIGH
            )

        assert result is not None
        assert result["url"] == url


class TestTidalProviderSelectQuality:
    """Tests for quality selection via base class."""

    @pytest.mark.unit
    def test_select_high_quality(self, provider):
        """Test selecting HIGH quality."""
        quality = provider.select_quality(
            QualityPreference.HIGH,
            max_bitrate_kbps=320,
        )

        assert quality is not None
        assert quality.quality == QualityPreference.HIGH
        assert quality.bitrate_kbps == 320
        assert quality.format == "aac"

    @pytest.mark.unit
    def test_select_lossless_quality(self, provider):
        """Test selecting LOSSLESS quality."""
        quality = provider.select_quality(QualityPreference.LOSSLESS)

        assert quality is not None
        assert quality.quality == QualityPreference.LOSSLESS
        assert quality.lossless is True
        assert quality.format == "flac"

    @pytest.mark.unit
    def test_select_quality_with_format_priority(self, provider):
        """Test selecting quality with format priority."""
        quality = provider.select_quality(
            QualityPreference.HIGH,
            format_priority=["aac", "mp3"],
        )

        assert quality is not None
        assert quality.format == "aac"
