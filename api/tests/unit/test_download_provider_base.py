"""
Tests for the download provider base classes and utilities.
"""

from pathlib import Path

import pytest
from downloader.providers.base import (
    DownloadProvider,
    DownloadResult,
    ProviderCapabilities,
    ProviderType,
    QualityOption,
    QualityPreference,
    TrackMatch,
    TrackMetadata,
    _string_similarity,
    calculate_match_confidence,
)


class TestQualityOption:
    """Tests for QualityOption dataclass."""

    @pytest.mark.unit
    def test_lossy_quality_str(self):
        """Test string representation of lossy quality."""
        option = QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=320,
            format="aac",
            lossless=False,
        )
        assert str(option) == "320kbps AAC"

    @pytest.mark.unit
    def test_lossless_quality_str(self):
        """Test string representation of lossless quality."""
        option = QualityOption(
            quality=QualityPreference.LOSSLESS,
            bitrate_kbps=1411,
            format="flac",
            lossless=True,
            sample_rate=44100,
            bit_depth=16,
        )
        assert str(option) == "16-bit/44kHz FLAC"

    @pytest.mark.unit
    def test_hires_quality_str(self):
        """Test string representation of hi-res quality."""
        option = QualityOption(
            quality=QualityPreference.HI_RES,
            bitrate_kbps=9216,
            format="flac",
            lossless=True,
            sample_rate=192000,
            bit_depth=24,
        )
        assert str(option) == "24-bit/192kHz FLAC"

    @pytest.mark.unit
    def test_quality_option_is_frozen(self):
        """Test that QualityOption is immutable."""
        option = QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=320,
            format="aac",
            lossless=False,
        )
        with pytest.raises(AttributeError):
            option.bitrate_kbps = 256


class TestProviderCapabilities:
    """Tests for ProviderCapabilities dataclass."""

    @pytest.fixture
    def sample_capabilities(self):
        """Create sample capabilities for testing."""
        return ProviderCapabilities(
            provider_type=ProviderType.REST_API,
            supports_search=True,
            supports_isrc_lookup=False,
            embeds_metadata=False,
            available_qualities=(
                QualityOption(QualityPreference.HIGH, 320, "aac", False),
                QualityOption(
                    QualityPreference.LOSSLESS, 1411, "flac", True, 44100, 16
                ),
                QualityOption(QualityPreference.HI_RES, 9216, "flac", True, 192000, 24),
            ),
            formats=("aac", "flac"),
        )

    @pytest.mark.unit
    def test_max_bitrate_kbps(self, sample_capabilities):
        """Test max bitrate calculation."""
        assert sample_capabilities.max_bitrate_kbps == 9216

    @pytest.mark.unit
    def test_max_bitrate_empty_qualities(self):
        """Test max bitrate with no qualities."""
        caps = ProviderCapabilities(
            provider_type=ProviderType.REST_API,
            supports_search=True,
            supports_isrc_lookup=False,
            embeds_metadata=False,
            available_qualities=(),
            formats=(),
        )
        assert caps.max_bitrate_kbps == 0

    @pytest.mark.unit
    def test_supports_lossless_true(self, sample_capabilities):
        """Test lossless support detection when available."""
        assert sample_capabilities.supports_lossless is True

    @pytest.mark.unit
    def test_supports_lossless_false(self):
        """Test lossless support detection when not available."""
        caps = ProviderCapabilities(
            provider_type=ProviderType.REST_API,
            supports_search=True,
            supports_isrc_lookup=False,
            embeds_metadata=False,
            available_qualities=(
                QualityOption(QualityPreference.HIGH, 320, "aac", False),
                QualityOption(QualityPreference.MEDIUM, 192, "mp3", False),
            ),
            formats=("aac", "mp3"),
        )
        assert caps.supports_lossless is False


class TestTrackMatch:
    """Tests for TrackMatch dataclass."""

    @pytest.mark.unit
    def test_valid_track_match(self):
        """Test creating a valid track match."""
        match = TrackMatch(
            provider="tidal",
            provider_track_id="12345678",
            title="Blinding Lights",
            artist="The Weeknd",
            album="After Hours",
            duration_ms=200000,
            isrc="USUG11904206",
            confidence=0.95,
        )
        assert match.provider == "tidal"
        assert match.confidence == 0.95

    @pytest.mark.unit
    def test_confidence_validation_too_high(self):
        """Test that confidence > 1.0 raises error."""
        with pytest.raises(ValueError, match="Confidence must be between"):
            TrackMatch(
                provider="tidal",
                provider_track_id="12345",
                title="Test",
                artist="Test",
                album="Test",
                duration_ms=180000,
                confidence=1.5,
            )

    @pytest.mark.unit
    def test_confidence_validation_negative(self):
        """Test that negative confidence raises error."""
        with pytest.raises(ValueError, match="Confidence must be between"):
            TrackMatch(
                provider="tidal",
                provider_track_id="12345",
                title="Test",
                artist="Test",
                album="Test",
                duration_ms=180000,
                confidence=-0.1,
            )

    @pytest.mark.unit
    def test_default_extra_metadata(self):
        """Test that extra_metadata defaults to empty dict."""
        match = TrackMatch(
            provider="tidal",
            provider_track_id="12345",
            title="Test",
            artist="Test",
            album="Test",
            duration_ms=180000,
            confidence=0.8,
        )
        assert match.extra_metadata == {}


class TestDownloadResult:
    """Tests for DownloadResult dataclass."""

    @pytest.mark.unit
    def test_successful_result(self, tmp_path):
        """Test creating a successful download result."""
        file_path = tmp_path / "test.m4a"
        result = DownloadResult(
            success=True,
            provider="tidal",
            file_path=file_path,
            bitrate_kbps=320,
            format="aac",
            duration_ms=200000,
            metadata_embedded=False,
        )
        assert result.success is True
        assert result.file_path == file_path

    @pytest.mark.unit
    def test_failed_result(self):
        """Test creating a failed download result."""
        result = DownloadResult(
            success=False,
            provider="tidal",
            error="Track not found",
            error_retryable=True,
        )
        assert result.success is False
        assert result.error == "Track not found"

    @pytest.mark.unit
    def test_success_without_file_path_raises(self):
        """Test that success=True without file_path raises error."""
        with pytest.raises(
            ValueError, match="Successful download must have a file_path"
        ):
            DownloadResult(
                success=True,
                provider="tidal",
            )

    @pytest.mark.unit
    def test_failure_without_error_raises(self):
        """Test that success=False without error raises error."""
        with pytest.raises(
            ValueError, match="Failed download must have an error message"
        ):
            DownloadResult(
                success=False,
                provider="tidal",
            )


class TestTrackMetadata:
    """Tests for TrackMetadata dataclass."""

    @pytest.mark.unit
    def test_full_metadata(self):
        """Test creating full track metadata."""
        metadata = TrackMetadata(
            spotify_id="6rqhFgbbKwnb9MLmUQDhG6",
            title="Blinding Lights",
            artist="The Weeknd",
            album="After Hours",
            album_artist="The Weeknd",
            duration_ms=200040,
            isrc="USUG11904206",
            track_number=9,
            total_tracks=14,
            disc_number=1,
            total_discs=1,
            release_date="2020-03-20",
            cover_url="https://i.scdn.co/image/abc123",
            copyright="© 2020 Republic Records",
            genres=("pop", "r&b"),
        )
        assert metadata.spotify_id == "6rqhFgbbKwnb9MLmUQDhG6"
        assert metadata.genres == ("pop", "r&b")

    @pytest.mark.unit
    def test_minimal_metadata(self):
        """Test creating minimal required metadata."""
        metadata = TrackMetadata(
            spotify_id="abc123",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            album_artist="Test Artist",
            duration_ms=180000,
        )
        assert metadata.isrc is None
        assert metadata.genres == ()


class TestStringSimlarity:
    """Tests for the _string_similarity utility function."""

    @pytest.mark.unit
    def test_identical_strings(self):
        """Test similarity of identical strings."""
        assert _string_similarity("Hello World", "Hello World") == 1.0

    @pytest.mark.unit
    def test_case_insensitive(self):
        """Test that comparison is case insensitive."""
        assert _string_similarity("hello world", "HELLO WORLD") == 1.0

    @pytest.mark.unit
    def test_punctuation_ignored(self):
        """Test that punctuation is ignored."""
        assert _string_similarity("Hello, World!", "Hello World") == 1.0

    @pytest.mark.unit
    def test_partial_match(self):
        """Test partial word overlap."""
        # "hello" overlaps, "world" vs "there" doesn't
        similarity = _string_similarity("hello world", "hello there")
        assert 0.3 < similarity < 0.7  # Partial overlap

    @pytest.mark.unit
    def test_no_overlap(self):
        """Test strings with no word overlap."""
        assert _string_similarity("hello world", "foo bar") < 0.4

    @pytest.mark.unit
    def test_empty_string(self):
        """Test with empty strings."""
        assert _string_similarity("", "hello") == 0.0
        assert _string_similarity("hello", "") == 0.0
        assert _string_similarity("", "") == 0.0


class TestCalculateMatchConfidence:
    """Tests for the calculate_match_confidence function."""

    @pytest.mark.unit
    def test_perfect_match_with_isrc(self):
        """Test confidence for perfect match with ISRC."""
        confidence = calculate_match_confidence(
            search_title="Blinding Lights",
            search_artist="The Weeknd",
            result_title="Blinding Lights",
            result_artist="The Weeknd",
            search_isrc="USUG11904206",
            result_isrc="USUG11904206",
            search_duration_ms=200000,
            result_duration_ms=200000,
        )
        assert confidence >= 0.95

    @pytest.mark.unit
    def test_perfect_match_without_isrc(self):
        """Test confidence for perfect match without ISRC."""
        confidence = calculate_match_confidence(
            search_title="Blinding Lights",
            search_artist="The Weeknd",
            result_title="Blinding Lights",
            result_artist="The Weeknd",
        )
        assert confidence >= 0.9

    @pytest.mark.unit
    def test_isrc_mismatch_lowers_confidence(self):
        """Test that ISRC mismatch lowers confidence."""
        with_isrc_match = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_isrc="ABC123",
            result_isrc="ABC123",
        )
        with_isrc_mismatch = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_isrc="ABC123",
            result_isrc="XYZ789",
        )
        assert with_isrc_match > with_isrc_mismatch

    @pytest.mark.unit
    def test_duration_within_tolerance(self):
        """Test duration match within tolerance."""
        confidence = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_duration_ms=200000,
            result_duration_ms=202000,  # 2 seconds off
            duration_tolerance_ms=5000,
        )
        assert confidence > 0.8

    @pytest.mark.unit
    def test_duration_outside_tolerance(self):
        """Test duration match outside tolerance."""
        within_tolerance = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_duration_ms=200000,
            result_duration_ms=202000,
            duration_tolerance_ms=5000,
        )
        outside_tolerance = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_duration_ms=200000,
            result_duration_ms=210000,  # 10 seconds off
            duration_tolerance_ms=5000,
        )
        assert within_tolerance > outside_tolerance

    @pytest.mark.unit
    def test_title_mismatch_lowers_confidence(self):
        """Test that title mismatch significantly lowers confidence."""
        title_match = calculate_match_confidence(
            search_title="Blinding Lights",
            search_artist="The Weeknd",
            result_title="Blinding Lights",
            result_artist="The Weeknd",
        )
        title_mismatch = calculate_match_confidence(
            search_title="Blinding Lights",
            search_artist="The Weeknd",
            result_title="Save Your Tears",
            result_artist="The Weeknd",
        )
        assert title_match > title_mismatch

    @pytest.mark.unit
    def test_confidence_bounds(self):
        """Test that confidence is always between 0 and 1."""
        # Best case
        best = calculate_match_confidence(
            search_title="Test",
            search_artist="Artist",
            result_title="Test",
            result_artist="Artist",
            search_isrc="ABC",
            result_isrc="ABC",
            search_duration_ms=200000,
            result_duration_ms=200000,
        )
        assert 0.0 <= best <= 1.0

        # Worst case
        worst = calculate_match_confidence(
            search_title="Completely Different",
            search_artist="Unknown Artist",
            result_title="Something Else Entirely",
            result_artist="Another Person",
            search_isrc="ABC",
            result_isrc="XYZ",
            search_duration_ms=100000,
            result_duration_ms=500000,
        )
        assert 0.0 <= worst <= 1.0


class ConcreteProvider(DownloadProvider):
    """Concrete implementation for testing the ABC."""

    @property
    def name(self) -> str:
        return "test"

    @property
    def display_name(self) -> str:
        return "Test Provider"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type=ProviderType.REST_API,
            supports_search=True,
            supports_isrc_lookup=False,
            embeds_metadata=False,
            available_qualities=(
                QualityOption(QualityPreference.LOW, 96, "aac", False),
                QualityOption(QualityPreference.MEDIUM, 192, "mp3", False),
                QualityOption(QualityPreference.HIGH, 320, "aac", False),
                QualityOption(
                    QualityPreference.LOSSLESS, 1411, "flac", True, 44100, 16
                ),
            ),
            formats=("aac", "mp3", "flac"),
        )

    async def is_available(self) -> bool:
        return True

    async def search_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        isrc: str | None = None,
        duration_ms: int | None = None,
    ) -> TrackMatch | None:
        return TrackMatch(
            provider=self.name,
            provider_track_id="12345",
            title=title,
            artist=artist,
            album=album or "Unknown",
            duration_ms=duration_ms or 180000,
            confidence=0.9,
        )

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        return DownloadResult(
            success=True,
            provider=self.name,
            file_path=output_path,
            bitrate_kbps=320,
            format="aac",
        )


class TestDownloadProviderABC:
    """Tests for the DownloadProvider abstract base class."""

    @pytest.mark.unit
    def test_cannot_instantiate_abc(self):
        """Test that DownloadProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DownloadProvider()

    @pytest.mark.unit
    def test_concrete_implementation(self):
        """Test that concrete implementation can be instantiated."""
        provider = ConcreteProvider()
        assert provider.name == "test"
        assert provider.display_name == "Test Provider"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_is_available(self):
        """Test is_available method."""
        provider = ConcreteProvider()
        assert await provider.is_available() is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_track(self):
        """Test search_track method."""
        provider = ConcreteProvider()
        match = await provider.search_track(
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
        )
        assert match is not None
        assert match.title == "Test Song"
        assert match.confidence == 0.9

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_track(self, tmp_path):
        """Test download_track method."""
        provider = ConcreteProvider()
        match = TrackMatch(
            provider="test",
            provider_track_id="12345",
            title="Test",
            artist="Artist",
            album="Album",
            duration_ms=180000,
            confidence=0.9,
        )
        output_path = tmp_path / "test.m4a"
        result = await provider.download_track(match, output_path)
        assert result.success is True
        assert result.file_path == output_path

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_track_info_default(self):
        """Test default get_track_info returns None."""
        provider = ConcreteProvider()
        result = await provider.get_track_info("12345")
        assert result is None


class TestSelectQuality:
    """Tests for the select_quality method."""

    @pytest.fixture
    def provider(self):
        """Create provider for testing."""
        return ConcreteProvider()

    @pytest.mark.unit
    def test_select_preferred_quality(self, provider):
        """Test selecting preferred quality."""
        quality = provider.select_quality(QualityPreference.HIGH)
        assert quality is not None
        assert quality.quality == QualityPreference.HIGH
        assert quality.bitrate_kbps == 320

    @pytest.mark.unit
    def test_select_with_max_bitrate(self, provider):
        """Test selecting quality with max bitrate constraint."""
        quality = provider.select_quality(
            QualityPreference.LOSSLESS,
            max_bitrate_kbps=320,
        )
        assert quality is not None
        assert quality.bitrate_kbps <= 320
        assert quality.lossless is False

    @pytest.mark.unit
    def test_select_with_format_priority(self, provider):
        """Test selecting quality with format priority."""
        # Both HIGH (320 aac) and MEDIUM (192 mp3) are lossy
        # With mp3 priority, should prefer mp3 if quality allows
        quality = provider.select_quality(
            QualityPreference.MEDIUM,
            format_priority=["mp3", "aac"],
        )
        assert quality is not None
        assert quality.format == "mp3"

    @pytest.mark.unit
    def test_select_quality_no_match(self, provider):
        """Test selecting quality when no options match constraints."""
        # Request max 50kbps - nothing available that low
        quality = provider.select_quality(
            QualityPreference.HIGH,
            max_bitrate_kbps=50,
        )
        assert quality is None

    @pytest.mark.unit
    def test_select_lossless_quality(self, provider):
        """Test selecting lossless quality."""
        quality = provider.select_quality(QualityPreference.LOSSLESS)
        assert quality is not None
        assert quality.lossless is True
        assert quality.format == "flac"
