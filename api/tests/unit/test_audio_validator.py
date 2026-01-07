"""
Tests for audio file validation.
"""

from unittest.mock import MagicMock, patch

import pytest
from downloader.providers.validation import (
    AudioFormat,
    AudioInfo,
    AudioValidator,
    ValidationResult,
)


@pytest.fixture
def validator():
    """Create a validator with default settings."""
    return AudioValidator()


@pytest.fixture
def custom_validator():
    """Create a validator with custom settings."""
    return AudioValidator(
        duration_tolerance_ms=1000,
        min_bitrate_kbps=256,
        min_duration_ms=5000,
    )


class TestAudioFormat:
    """Tests for AudioFormat enum."""

    def test_format_values(self):
        """Test that format values are correct."""
        assert AudioFormat.AAC.value == "aac"
        assert AudioFormat.FLAC.value == "flac"
        assert AudioFormat.MP3.value == "mp3"
        assert AudioFormat.OPUS.value == "opus"
        assert AudioFormat.UNKNOWN.value == "unknown"


class TestAudioInfo:
    """Tests for AudioInfo dataclass."""

    def test_audio_info_creation(self):
        """Test creating AudioInfo."""
        info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=7200000,
        )
        assert info.format == AudioFormat.AAC
        assert info.duration_ms == 180000
        assert info.bitrate_kbps == 320
        assert info.sample_rate == 44100
        assert info.channels == 2
        assert info.bits_per_sample is None
        assert info.file_size_bytes == 7200000

    def test_audio_info_flac(self):
        """Test AudioInfo for FLAC format."""
        info = AudioInfo(
            format=AudioFormat.FLAC,
            duration_ms=180000,
            bitrate_kbps=900,
            sample_rate=44100,
            channels=2,
            bits_per_sample=16,
            file_size_bytes=20000000,
        )
        assert info.format == AudioFormat.FLAC
        assert info.bits_per_sample == 16


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result(self):
        """Test a valid result."""
        info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=7200000,
        )
        result = ValidationResult(
            is_valid=True,
            audio_info=info,
            errors=[],
            warnings=[],
        )
        assert result.is_valid is True
        assert result.audio_info is not None
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_invalid_result(self):
        """Test an invalid result with errors."""
        result = ValidationResult(
            is_valid=False,
            audio_info=None,
            errors=["File does not exist"],
            warnings=[],
        )
        assert result.is_valid is False
        assert result.audio_info is None
        assert "File does not exist" in result.errors


class TestAudioValidatorInit:
    """Tests for AudioValidator initialization."""

    def test_default_settings(self, validator):
        """Test default settings."""
        assert validator.duration_tolerance_ms == 3000
        assert validator.min_bitrate_kbps == 128
        assert validator.min_duration_ms == 1000

    def test_custom_settings(self, custom_validator):
        """Test custom settings."""
        assert custom_validator.duration_tolerance_ms == 1000
        assert custom_validator.min_bitrate_kbps == 256
        assert custom_validator.min_duration_ms == 5000


class TestAudioValidatorValidate:
    """Tests for AudioValidator.validate()."""

    @pytest.mark.unit
    def test_file_not_exists(self, validator, tmp_path):
        """Test validation when file doesn't exist."""
        fake_path = tmp_path / "nonexistent.m4a"
        result = validator.validate(fake_path)

        assert result.is_valid is False
        assert result.audio_info is None
        assert "File does not exist" in result.errors

    @pytest.mark.unit
    def test_empty_file(self, validator, tmp_path):
        """Test validation of empty file."""
        empty_file = tmp_path / "empty.m4a"
        empty_file.write_bytes(b"")

        result = validator.validate(empty_file)

        assert result.is_valid is False
        assert result.audio_info is None
        assert "File is empty" in result.errors

    @pytest.mark.unit
    def test_corrupt_file(self, validator, tmp_path):
        """Test validation of corrupt file."""
        corrupt_file = tmp_path / "corrupt.m4a"
        corrupt_file.write_bytes(b"not a valid audio file")

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = None

            result = validator.validate(corrupt_file)

            assert result.is_valid is False
            assert "corrupt or unsupported" in result.errors[0]

    @pytest.mark.unit
    def test_valid_mp4_file(self, validator, tmp_path):
        """Test validation of valid MP4/M4A file."""
        test_file = tmp_path / "test.m4a"
        test_file.write_bytes(b"fake audio content")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is True
            assert result.audio_info == mock_info
            assert len(result.errors) == 0

    @pytest.mark.unit
    def test_duration_too_short(self, validator, tmp_path):
        """Test validation fails for very short files."""
        test_file = tmp_path / "short.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=500,  # Less than 1000ms minimum
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is False
            assert any("Duration too short" in e for e in result.errors)

    @pytest.mark.unit
    def test_duration_mismatch_error(self, validator, tmp_path):
        """Test validation fails when duration differs too much."""
        test_file = tmp_path / "wrong_duration.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            # Expected duration differs by more than tolerance
            result = validator.validate(test_file, expected_duration_ms=190000)

            assert result.is_valid is False
            assert any("Duration mismatch" in e for e in result.errors)

    @pytest.mark.unit
    def test_duration_within_tolerance(self, validator, tmp_path):
        """Test validation passes when duration is within tolerance."""
        test_file = tmp_path / "close_duration.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            # Expected duration within 3000ms tolerance
            result = validator.validate(test_file, expected_duration_ms=182000)

            assert result.is_valid is True
            assert len(result.errors) == 0

    @pytest.mark.unit
    def test_duration_slightly_off_warning(self, validator, tmp_path):
        """Test warning when duration is slightly off but within tolerance."""
        test_file = tmp_path / "slightly_off.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            # Difference of 2000ms (> tolerance/2 but <= tolerance)
            result = validator.validate(test_file, expected_duration_ms=182000)

            assert result.is_valid is True
            assert any("slightly off" in w for w in result.warnings)

    @pytest.mark.unit
    def test_format_mismatch(self, validator, tmp_path):
        """Test validation fails when format doesn't match expected."""
        test_file = tmp_path / "wrong_format.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file, expected_format=AudioFormat.FLAC)

            assert result.is_valid is False
            assert any("Format mismatch" in e for e in result.errors)

    @pytest.mark.unit
    def test_bitrate_too_low(self, validator, tmp_path):
        """Test validation fails when bitrate is below minimum."""
        test_file = tmp_path / "low_bitrate.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=64,  # Below 128kbps minimum
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is False
            assert any("Bitrate too low" in e for e in result.errors)

    @pytest.mark.unit
    def test_bitrate_unknown_warning(self, validator, tmp_path):
        """Test warning when bitrate cannot be determined."""
        test_file = tmp_path / "unknown_bitrate.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=None,  # Unknown bitrate
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is True  # Still valid
            assert any("Could not determine bitrate" in w for w in result.warnings)

    @pytest.mark.unit
    def test_flac_no_bitrate_check(self, validator, tmp_path):
        """Test that FLAC files don't fail bitrate check."""
        test_file = tmp_path / "lossless.flac"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.FLAC,
            duration_ms=180000,
            bitrate_kbps=900,  # Higher bitrate for lossless
            sample_rate=44100,
            channels=2,
            bits_per_sample=16,
            file_size_bytes=20000000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is True
            # FLAC is not checked for minimum lossy bitrate
            assert not any("Bitrate too low" in e for e in result.errors)

    @pytest.mark.unit
    def test_unknown_format_warning(self, validator, tmp_path):
        """Test warning when format cannot be determined."""
        test_file = tmp_path / "unknown.xyz"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.UNKNOWN,
            duration_ms=180000,
            bitrate_kbps=None,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(test_file)

            assert result.is_valid is True
            assert any("Could not determine audio format" in w for w in result.warnings)

    @pytest.mark.unit
    def test_multiple_errors(self, validator, tmp_path):
        """Test validation can report multiple errors."""
        test_file = tmp_path / "many_problems.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=500,  # Too short
            bitrate_kbps=64,  # Too low
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = validator.validate(
                test_file,
                expected_duration_ms=180000,  # Wrong duration
                expected_format=AudioFormat.FLAC,  # Wrong format
            )

            assert result.is_valid is False
            assert len(result.errors) >= 3  # At least 3 errors


class TestAudioValidatorGetInfo:
    """Tests for AudioValidator._get_audio_info()."""

    @pytest.mark.unit
    def test_get_mp4_info(self, validator, tmp_path):
        """Test getting info from MP4 file."""
        test_file = tmp_path / "test.m4a"
        test_file.write_bytes(b"fake")

        mock_mp4_info = MagicMock()
        mock_mp4_info.length = 180.5
        mock_mp4_info.bitrate = 320000
        mock_mp4_info.sample_rate = 44100
        mock_mp4_info.channels = 2
        mock_mp4_info.bits_per_sample = None

        mock_mp4 = MagicMock()
        mock_mp4.info = mock_mp4_info

        with patch("mutagen.mp4.MP4", return_value=mock_mp4):
            info = validator._get_mp4_info(test_file, 1000)

            assert info is not None
            assert info.format == AudioFormat.AAC
            assert info.duration_ms == 180500
            assert info.bitrate_kbps == 320
            assert info.sample_rate == 44100

    @pytest.mark.unit
    def test_get_mp4_info_parse_error(self, validator, tmp_path):
        """Test handling MP4 parse error."""
        test_file = tmp_path / "bad.m4a"
        test_file.write_bytes(b"not mp4")

        with patch("mutagen.mp4.MP4", side_effect=Exception("Parse error")):
            info = validator._get_mp4_info(test_file, 1000)
            assert info is None

    @pytest.mark.unit
    def test_get_flac_info(self, validator, tmp_path):
        """Test getting info from FLAC file."""
        test_file = tmp_path / "test.flac"
        test_file.write_bytes(b"fake")

        mock_flac_info = MagicMock()
        mock_flac_info.length = 180.0
        mock_flac_info.sample_rate = 44100
        mock_flac_info.channels = 2
        mock_flac_info.bits_per_sample = 16

        mock_flac = MagicMock()
        mock_flac.info = mock_flac_info

        with patch("mutagen.flac.FLAC", return_value=mock_flac):
            # File size of 4,050,000 bytes / 180 seconds = 180,000 bits/sec = 180 kbps
            info = validator._get_flac_info(test_file, 4050000)

            assert info is not None
            assert info.format == AudioFormat.FLAC
            assert info.duration_ms == 180000
            assert info.bits_per_sample == 16
            assert info.bitrate_kbps == 180  # Calculated from file size

    @pytest.mark.unit
    def test_get_mp3_info(self, validator, tmp_path):
        """Test getting info from MP3 file."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake")

        mock_mp3_info = MagicMock()
        mock_mp3_info.length = 240.0
        mock_mp3_info.bitrate = 256000
        mock_mp3_info.sample_rate = 44100
        mock_mp3_info.channels = 2

        mock_mp3 = MagicMock()
        mock_mp3.info = mock_mp3_info

        with patch("mutagen.mp3.MP3", return_value=mock_mp3):
            info = validator._get_mp3_info(test_file, 7680000)

            assert info is not None
            assert info.format == AudioFormat.MP3
            assert info.duration_ms == 240000
            assert info.bitrate_kbps == 256
            assert info.bits_per_sample is None  # MP3 doesn't have this

    @pytest.mark.unit
    def test_get_opus_info(self, validator, tmp_path):
        """Test getting info from Opus file."""
        test_file = tmp_path / "test.opus"
        test_file.write_bytes(b"fake")

        mock_opus_info = MagicMock()
        mock_opus_info.length = 200.0
        mock_opus_info.channels = 2

        mock_opus = MagicMock()
        mock_opus.info = mock_opus_info

        with patch("mutagen.oggopus.OggOpus", return_value=mock_opus):
            info = validator._get_opus_info(test_file, 2000000)

            assert info is not None
            assert info.format == AudioFormat.OPUS
            assert info.duration_ms == 200000
            assert info.sample_rate == 48000  # Opus always 48kHz
            assert info.bitrate_kbps == 80  # Calculated from file size

    @pytest.mark.unit
    def test_get_generic_info(self, validator, tmp_path):
        """Test getting info using generic handler."""
        test_file = tmp_path / "test.xyz"
        test_file.write_bytes(b"fake")

        mock_info = MagicMock()
        mock_info.length = 120.0
        mock_info.bitrate = 192000
        mock_info.sample_rate = 48000
        mock_info.channels = 2

        mock_audio = MagicMock()
        mock_audio.info = mock_info

        with patch("mutagen.File", return_value=mock_audio):
            info = validator._get_generic_info(test_file, 1000)

            assert info is not None
            assert info.format == AudioFormat.UNKNOWN
            assert info.duration_ms == 120000
            assert info.bitrate_kbps == 192

    @pytest.mark.unit
    def test_get_generic_info_none(self, validator, tmp_path):
        """Test generic handler returns None for unparseable file."""
        test_file = tmp_path / "test.xyz"
        test_file.write_bytes(b"fake")

        with patch("mutagen.File", return_value=None):
            info = validator._get_generic_info(test_file, 1000)
            assert info is None

    @pytest.mark.unit
    def test_get_audio_info_routes_by_extension(self, validator, tmp_path):
        """Test that _get_audio_info routes to correct handler."""
        m4a_file = tmp_path / "test.m4a"
        flac_file = tmp_path / "test.flac"
        mp3_file = tmp_path / "test.mp3"
        opus_file = tmp_path / "test.opus"

        for f in [m4a_file, flac_file, mp3_file, opus_file]:
            f.write_bytes(b"fake")

        with (
            patch.object(validator, "_get_mp4_info") as mock_mp4,
            patch.object(validator, "_get_flac_info") as mock_flac,
            patch.object(validator, "_get_mp3_info") as mock_mp3,
            patch.object(validator, "_get_opus_info") as mock_opus,
        ):

            validator._get_audio_info(m4a_file, 1000)
            mock_mp4.assert_called_once()

            validator._get_audio_info(flac_file, 1000)
            mock_flac.assert_called_once()

            validator._get_audio_info(mp3_file, 1000)
            mock_mp3.assert_called_once()

            validator._get_audio_info(opus_file, 1000)
            mock_opus.assert_called_once()


class TestAudioValidatorQuickCheck:
    """Tests for AudioValidator.quick_check()."""

    @pytest.mark.unit
    def test_quick_check_nonexistent(self, validator, tmp_path):
        """Test quick check on nonexistent file."""
        fake_path = tmp_path / "nonexistent.m4a"
        assert validator.quick_check(fake_path) is False

    @pytest.mark.unit
    def test_quick_check_empty(self, validator, tmp_path):
        """Test quick check on empty file."""
        empty_file = tmp_path / "empty.m4a"
        empty_file.write_bytes(b"")
        assert validator.quick_check(empty_file) is False

    @pytest.mark.unit
    def test_quick_check_valid(self, validator, tmp_path):
        """Test quick check on valid file."""
        test_file = tmp_path / "valid.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info
            assert validator.quick_check(test_file) is True

    @pytest.mark.unit
    def test_quick_check_too_short(self, validator, tmp_path):
        """Test quick check fails for short files."""
        test_file = tmp_path / "short.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=500,  # Below minimum
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info
            assert validator.quick_check(test_file) is False

    @pytest.mark.unit
    def test_quick_check_unparseable(self, validator, tmp_path):
        """Test quick check fails for unparseable files."""
        test_file = tmp_path / "corrupt.m4a"
        test_file.write_bytes(b"corrupt data")

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = None
            assert validator.quick_check(test_file) is False


class TestCustomValidator:
    """Tests with custom validator settings."""

    @pytest.mark.unit
    def test_custom_duration_tolerance(self, custom_validator, tmp_path):
        """Test custom duration tolerance."""
        test_file = tmp_path / "test.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            # 1500ms difference with 1000ms tolerance should fail
            result = custom_validator.validate(test_file, expected_duration_ms=181500)
            assert result.is_valid is False

    @pytest.mark.unit
    def test_custom_min_bitrate(self, custom_validator, tmp_path):
        """Test custom minimum bitrate."""
        test_file = tmp_path / "test.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=180000,
            bitrate_kbps=192,  # Above default 128 but below custom 256
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = custom_validator.validate(test_file)
            assert result.is_valid is False
            assert any("Bitrate too low" in e for e in result.errors)

    @pytest.mark.unit
    def test_custom_min_duration(self, custom_validator, tmp_path):
        """Test custom minimum duration."""
        test_file = tmp_path / "test.m4a"
        test_file.write_bytes(b"fake audio")

        mock_info = AudioInfo(
            format=AudioFormat.AAC,
            duration_ms=3000,  # Above default 1000 but below custom 5000
            bitrate_kbps=320,
            sample_rate=44100,
            channels=2,
            bits_per_sample=None,
            file_size_bytes=1000,
        )

        with patch(
            "downloader.providers.validation.AudioValidator._get_audio_info"
        ) as mock_get_info:
            mock_get_info.return_value = mock_info

            result = custom_validator.validate(test_file)
            assert result.is_valid is False
            assert any("Duration too short" in e for e in result.errors)
