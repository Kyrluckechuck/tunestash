"""
Tests for fallback download orchestrator.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from downloader.providers.base import (
    DownloadResult,
    QualityPreference,
    TrackMatch,
    TrackMetadata,
)
from downloader.providers.fallback import FallbackDownloader, FallbackDownloadResult
from downloader.providers.validation import ValidationResult


@pytest.fixture
def spotify_metadata():
    """Create sample Spotify metadata."""
    return TrackMetadata(
        spotify_id="abc123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        album_artist="Test Artist",
        duration_ms=180000,
        isrc="USRC12345678",
        track_number=1,
        total_tracks=10,
        release_date="2024-01-15",
        cover_url="https://example.com/cover.jpg",
    )


@pytest.fixture
def track_match():
    """Create sample track match."""
    return TrackMatch(
        provider="tidal",
        provider_track_id="tidal_123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration_ms=180500,
        confidence=0.95,
        isrc="USRC12345678",
    )


@pytest.fixture
def downloader():
    """Create a FallbackDownloader instance."""
    return FallbackDownloader(
        quality_preference=QualityPreference.HIGH,
        output_dir=Path("/test/output"),
    )


class TestFallbackDownloadResult:
    """Tests for FallbackDownloadResult dataclass."""

    def test_success_result(self, track_match):
        """Test creating a successful result."""
        result = FallbackDownloadResult(
            success=True,
            file_path=Path("/test/song.m4a"),
            provider_used="tidal",
            error_message=None,
            track_match=track_match,
            validation_result=None,
        )
        assert result.success is True
        assert result.file_path == Path("/test/song.m4a")
        assert result.provider_used == "tidal"
        assert result.error_message is None

    def test_failure_result(self):
        """Test creating a failure result."""
        result = FallbackDownloadResult(
            success=False,
            file_path=None,
            provider_used="tidal",
            error_message="Track not found",
            track_match=None,
            validation_result=None,
        )
        assert result.success is False
        assert result.file_path is None
        assert result.error_message == "Track not found"


class TestFallbackDownloaderInit:
    """Tests for FallbackDownloader initialization."""

    def test_default_init(self):
        """Test default initialization."""
        downloader = FallbackDownloader()
        assert downloader._quality_preference == QualityPreference.HIGH
        assert downloader._output_dir == Path("/music")
        assert downloader._initialized == set()
        assert downloader._provider_order == ["youtube", "tidal", "qobuz"]

    def test_custom_init(self):
        """Test custom initialization."""
        quality = QualityPreference.LOSSLESS
        output = Path("/custom/output")
        downloader = FallbackDownloader(
            quality_preference=quality,
            output_dir=output,
        )
        assert downloader._quality_preference == quality
        assert downloader._output_dir == output

    def test_custom_provider_order(self):
        """Test custom provider order."""
        downloader = FallbackDownloader(
            provider_order=["qobuz", "tidal"],
        )
        assert downloader._provider_order == ["qobuz", "tidal"]

    def test_provider_order_filters_unsupported(self):
        """Test that unsupported providers are filtered from order."""
        downloader = FallbackDownloader(
            provider_order=["spotdl", "tidal", "invalid", "qobuz"],
        )
        # "spotdl" and "invalid" should be filtered out (not valid providers)
        assert downloader._provider_order == ["tidal", "qobuz"]

    def test_empty_provider_order(self):
        """Test empty provider order."""
        downloader = FallbackDownloader(
            provider_order=[],
        )
        assert downloader._provider_order == []


class TestFallbackDownloaderSanitizeFilename:
    """Tests for filename sanitization."""

    def test_basic_sanitization(self, downloader):
        """Test basic filename sanitization."""
        assert downloader._sanitize_filename("normal name") == "normal name"
        assert downloader._sanitize_filename("with/slash") == "with-slash"
        assert downloader._sanitize_filename("with\\backslash") == "with-backslash"
        assert downloader._sanitize_filename("with:colon") == "with-colon"
        assert downloader._sanitize_filename("with*star") == "withstar"
        assert downloader._sanitize_filename("with?question") == "withquestion"
        assert downloader._sanitize_filename('with"quote') == "with'quote"
        assert downloader._sanitize_filename("with<less") == "withless"
        assert downloader._sanitize_filename("with>greater") == "withgreater"
        assert downloader._sanitize_filename("with|pipe") == "with-pipe"

    def test_length_limit(self, downloader):
        """Test filename length limiting."""
        long_name = "a" * 150
        result = downloader._sanitize_filename(long_name)
        assert len(result) == 100

    def test_strip_whitespace(self, downloader):
        """Test whitespace stripping."""
        assert downloader._sanitize_filename("  name  ") == "name"


class TestFallbackDownloaderEnsureProviderInitialized:
    """Tests for provider initialization logic."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_tidal_success(self, downloader):
        """Test successful Tidal initialization."""
        mock_tidal_provider = AsyncMock()
        mock_tidal_provider.is_available = AsyncMock(return_value=True)

        with patch(
            "downloader.providers.fallback.TidalProvider",
            return_value=mock_tidal_provider,
        ):
            result = await downloader._ensure_provider_initialized("tidal")

            assert result is True
            assert "tidal" in downloader._initialized
            assert "tidal" in downloader._providers
            mock_tidal_provider.is_available.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_qobuz_success(self, downloader):
        """Test successful Qobuz initialization."""
        mock_qobuz_provider = AsyncMock()
        mock_qobuz_provider.is_available = AsyncMock(return_value=True)

        with patch(
            "downloader.providers.fallback.QobuzProvider",
            return_value=mock_qobuz_provider,
        ):
            result = await downloader._ensure_provider_initialized("qobuz")

            assert result is True
            assert "qobuz" in downloader._initialized
            assert "qobuz" in downloader._providers
            mock_qobuz_provider.is_available.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_already_initialized(self, downloader):
        """Test that initialization is skipped if already done."""
        downloader._initialized.add("tidal")

        result = await downloader._ensure_provider_initialized("tidal")

        assert result is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_failure(self, downloader):
        """Test handling provider unavailable."""
        mock_provider = AsyncMock()
        mock_provider.is_available = AsyncMock(return_value=False)

        with patch(
            "downloader.providers.fallback.TidalProvider",
            return_value=mock_provider,
        ):
            result = await downloader._ensure_provider_initialized("tidal")

            assert result is False
            assert "tidal" not in downloader._initialized

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_exception(self, downloader):
        """Test handling exception during initialization."""
        with patch(
            "downloader.providers.fallback.TidalProvider",
            side_effect=Exception("Network error"),
        ):
            result = await downloader._ensure_provider_initialized("tidal")

            assert result is False
            assert "tidal" not in downloader._initialized

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ensure_provider_initialized_unknown(self, downloader):
        """Test handling unknown provider."""
        result = await downloader._ensure_provider_initialized("unknown")

        assert result is False
        assert "unknown" not in downloader._initialized


class TestFallbackDownloaderDownloadTrack:
    """Tests for download_track method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_no_providers_configured(self, spotify_metadata):
        """Test download when no providers are configured."""
        downloader = FallbackDownloader(provider_order=[])
        result = await downloader.download_track(spotify_metadata)

        assert result.success is False
        assert "No fallback providers configured" in result.error_message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_all_providers_unavailable(
        self, downloader, spotify_metadata
    ):
        """Test download when all providers are unavailable."""
        with patch.object(
            downloader,
            "_ensure_provider_initialized",
            AsyncMock(return_value=False),
        ):
            result = await downloader.download_track(spotify_metadata)

            assert result.success is False
            assert "failed" in result.error_message.lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_success(
        self, downloader, spotify_metadata, track_match, tmp_path
    ):
        """Test successful download."""
        output_file = tmp_path / "Test Artist - Test Song.m4a"
        output_file.touch()

        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="tidal",
                file_path=output_file,
                format="AAC",
                bitrate_kbps=320,
            )
        )

        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=True,
                audio_info=None,
                errors=[],
                warnings=[],
            )
        )

        mock_embedder = MagicMock()
        mock_embedder.embed_metadata = MagicMock(return_value=True)

        # Set up the downloader with mocked components
        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._audio_validator = mock_validator
        downloader._metadata_embedder = mock_embedder
        downloader._output_dir = tmp_path

        result = await downloader.download_track(spotify_metadata)

        assert result.success is True
        assert result.provider_used == "tidal"
        assert result.track_match == track_match
        mock_provider.search_track.assert_called_once_with(
            title=spotify_metadata.title,
            artist=spotify_metadata.artist,
            album=spotify_metadata.album,
            isrc=spotify_metadata.isrc,
            duration_ms=spotify_metadata.duration_ms,
        )
        mock_embedder.embed_metadata.assert_called_once()
        mock_validator.validate.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_fallback_to_second_provider(
        self, downloader, spotify_metadata, track_match, tmp_path
    ):
        """Test that download falls back to second provider when first fails."""
        output_file = tmp_path / "Test Artist - Test Song.mp3"
        output_file.touch()

        # First provider (tidal) fails to find match
        mock_tidal = AsyncMock()
        mock_tidal.name = "tidal"
        mock_tidal.search_track = AsyncMock(return_value=None)

        # Second provider (qobuz) succeeds
        qobuz_match = TrackMatch(
            provider="qobuz",
            provider_track_id="qobuz_456",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            duration_ms=180500,
            confidence=0.95,
        )
        mock_qobuz = AsyncMock()
        mock_qobuz.name = "qobuz"
        mock_qobuz.search_track = AsyncMock(return_value=qobuz_match)
        mock_qobuz.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="qobuz",
                file_path=output_file,
                format="mp3",
                bitrate_kbps=320,
            )
        )

        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=True, audio_info=None, errors=[], warnings=[]
            )
        )

        mock_embedder = MagicMock()
        mock_embedder.embed_metadata = MagicMock(return_value=True)

        # Set up downloader with both providers
        downloader._providers["tidal"] = mock_tidal
        downloader._providers["qobuz"] = mock_qobuz
        downloader._initialized.add("tidal")
        downloader._initialized.add("qobuz")
        downloader._audio_validator = mock_validator
        downloader._metadata_embedder = mock_embedder
        downloader._output_dir = tmp_path

        result = await downloader.download_track(spotify_metadata)

        assert result.success is True
        assert result.provider_used == "qobuz"
        mock_tidal.search_track.assert_called_once()
        mock_qobuz.search_track.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_no_match(self, downloader, spotify_metadata):
        """Test download when no match found on any provider."""
        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=None)

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        # Only tidal configured
        downloader._provider_order = ["tidal"]

        result = await downloader.download_track(spotify_metadata)

        assert result.success is False
        assert "No matching track" in result.error_message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_search_exception(self, downloader, spotify_metadata):
        """Test download when search raises exception."""
        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(side_effect=Exception("API error"))

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._provider_order = ["tidal"]

        result = await downloader.download_track(spotify_metadata)

        assert result.success is False
        assert "Search failed" in result.error_message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_download_failure(
        self, downloader, spotify_metadata, track_match
    ):
        """Test download when download fails."""
        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=False,
                provider="tidal",
                file_path=None,
                error="Download timeout",
            )
        )

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._provider_order = ["tidal"]

        result = await downloader.download_track(spotify_metadata)

        assert result.success is False
        assert "Download timeout" in result.error_message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_download_exception(
        self, downloader, spotify_metadata, track_match
    ):
        """Test download when download raises exception."""
        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(side_effect=Exception("IO error"))

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._provider_order = ["tidal"]

        result = await downloader.download_track(spotify_metadata)

        assert result.success is False
        assert "Download failed" in result.error_message

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_metadata_failure_continues(
        self, downloader, spotify_metadata, track_match, tmp_path
    ):
        """Test that metadata failure doesn't fail the download."""
        output_file = tmp_path / "song.m4a"
        output_file.touch()

        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="tidal",
                file_path=output_file,
                format="AAC",
                bitrate_kbps=320,
            )
        )

        mock_embedder = MagicMock()
        mock_embedder.embed_metadata = MagicMock(return_value=False)

        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=True, audio_info=None, errors=[], warnings=[]
            )
        )

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._metadata_embedder = mock_embedder
        downloader._audio_validator = mock_validator
        downloader._output_dir = tmp_path

        result = await downloader.download_track(spotify_metadata)

        assert result.success is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_validation_failure_continues(
        self, downloader, spotify_metadata, track_match, tmp_path
    ):
        """Test that validation failure doesn't fail the download."""
        output_file = tmp_path / "song.m4a"
        output_file.touch()

        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="tidal",
                file_path=output_file,
                format="AAC",
                bitrate_kbps=320,
            )
        )

        mock_embedder = MagicMock()
        mock_embedder.embed_metadata = MagicMock(return_value=True)

        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=False,
                audio_info=None,
                errors=["Duration mismatch"],
                warnings=[],
            )
        )

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._metadata_embedder = mock_embedder
        downloader._audio_validator = mock_validator
        downloader._output_dir = tmp_path

        result = await downloader.download_track(spotify_metadata)

        assert result.success is True
        assert result.validation_result is not None
        assert not result.validation_result.is_valid

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_track_custom_filename(
        self, downloader, spotify_metadata, track_match, tmp_path
    ):
        """Test download with custom filename."""
        output_file = tmp_path / "custom_name.m4a"
        output_file.touch()

        mock_provider = AsyncMock()
        mock_provider.name = "tidal"
        mock_provider.search_track = AsyncMock(return_value=track_match)
        mock_provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="tidal",
                file_path=output_file,
                format="AAC",
                bitrate_kbps=320,
            )
        )

        mock_embedder = MagicMock()
        mock_embedder.embed_metadata = MagicMock(return_value=True)

        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=True, audio_info=None, errors=[], warnings=[]
            )
        )

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")
        downloader._metadata_embedder = mock_embedder
        downloader._audio_validator = mock_validator
        downloader._output_dir = tmp_path

        result = await downloader.download_track(
            spotify_metadata, output_filename="custom_name"
        )

        assert result.success is True
        call_args = mock_provider.download_track.call_args
        output_path = call_args.kwargs.get("output_path")
        assert output_path is not None
        assert "custom_name" in str(output_path)


class TestFallbackDownloaderClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_close(self, downloader):
        """Test closing the downloader."""
        mock_provider = MagicMock()

        downloader._providers["tidal"] = mock_provider
        downloader._initialized.add("tidal")

        await downloader.close()

        assert len(downloader._providers) == 0
        assert len(downloader._initialized) == 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_close_no_provider(self, downloader):
        """Test closing when no provider initialized."""
        await downloader.close()

        assert len(downloader._initialized) == 0
