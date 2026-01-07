"""
Audio file validation for downloaded tracks.

This module validates audio files after download to ensure:
- File integrity (can be parsed correctly)
- Correct format/codec
- Duration matches expected value (within tolerance)
- Bitrate meets minimum requirements
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AudioFormat(Enum):
    """Supported audio formats."""

    AAC = "aac"
    FLAC = "flac"
    MP3 = "mp3"
    OPUS = "opus"
    UNKNOWN = "unknown"


@dataclass
class AudioInfo:
    """Information about an audio file."""

    format: AudioFormat
    duration_ms: int
    bitrate_kbps: Optional[int]
    sample_rate: Optional[int]
    channels: Optional[int]
    bits_per_sample: Optional[int]  # For lossless formats
    file_size_bytes: int


@dataclass
class ValidationResult:
    """Result of audio file validation."""

    is_valid: bool
    audio_info: Optional[AudioInfo]
    errors: list[str]
    warnings: list[str]


# Default validation parameters
DEFAULT_DURATION_TOLERANCE_MS = 3000  # 3 seconds
DEFAULT_MIN_BITRATE_KBPS = 128  # Minimum acceptable bitrate
DEFAULT_MIN_DURATION_MS = 1000  # Files shorter than 1s are likely corrupt


class AudioValidator:
    """
    Validates downloaded audio files.

    Checks for:
    - File integrity (parseable by mutagen)
    - Correct format detection
    - Duration within tolerance of expected
    - Minimum bitrate requirements
    """

    def __init__(
        self,
        duration_tolerance_ms: int = DEFAULT_DURATION_TOLERANCE_MS,
        min_bitrate_kbps: int = DEFAULT_MIN_BITRATE_KBPS,
        min_duration_ms: int = DEFAULT_MIN_DURATION_MS,
    ):
        """
        Initialize the validator.

        Args:
            duration_tolerance_ms: Allowed difference from expected duration
            min_bitrate_kbps: Minimum acceptable bitrate
            min_duration_ms: Minimum file duration (shorter files are suspect)
        """
        self.duration_tolerance_ms = duration_tolerance_ms
        self.min_bitrate_kbps = min_bitrate_kbps
        self.min_duration_ms = min_duration_ms

    def validate(
        self,
        file_path: Path,
        expected_duration_ms: Optional[int] = None,
        expected_format: Optional[AudioFormat] = None,
    ) -> ValidationResult:
        """
        Validate an audio file.

        Args:
            file_path: Path to the audio file
            expected_duration_ms: Expected duration (optional)
            expected_format: Expected format (optional)

        Returns:
            ValidationResult with validation status and details
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check file exists
        if not file_path.exists():
            return ValidationResult(
                is_valid=False,
                audio_info=None,
                errors=["File does not exist"],
                warnings=[],
            )

        # Check file size
        file_size = file_path.stat().st_size
        if file_size == 0:
            return ValidationResult(
                is_valid=False,
                audio_info=None,
                errors=["File is empty"],
                warnings=[],
            )

        # Try to parse the audio file
        audio_info = self._get_audio_info(file_path, file_size)
        if audio_info is None:
            return ValidationResult(
                is_valid=False,
                audio_info=None,
                errors=["Failed to parse audio file - may be corrupt or unsupported"],
                warnings=[],
            )

        # Check minimum duration
        if audio_info.duration_ms < self.min_duration_ms:
            errors.append(
                f"Duration too short: {audio_info.duration_ms}ms "
                f"(minimum: {self.min_duration_ms}ms)"
            )

        # Check expected duration if provided
        if expected_duration_ms is not None:
            duration_diff = abs(audio_info.duration_ms - expected_duration_ms)
            if duration_diff > self.duration_tolerance_ms:
                errors.append(
                    f"Duration mismatch: got {audio_info.duration_ms}ms, "
                    f"expected {expected_duration_ms}ms "
                    f"(tolerance: {self.duration_tolerance_ms}ms)"
                )
            elif duration_diff > self.duration_tolerance_ms // 2:
                warnings.append(
                    f"Duration slightly off: got {audio_info.duration_ms}ms, "
                    f"expected {expected_duration_ms}ms"
                )

        # Check expected format if provided
        if expected_format is not None and audio_info.format != expected_format:
            errors.append(
                f"Format mismatch: got {audio_info.format.value}, "
                f"expected {expected_format.value}"
            )

        # Check bitrate for lossy formats
        if audio_info.format in (AudioFormat.AAC, AudioFormat.MP3, AudioFormat.OPUS):
            if audio_info.bitrate_kbps is not None:
                if audio_info.bitrate_kbps < self.min_bitrate_kbps:
                    errors.append(
                        f"Bitrate too low: {audio_info.bitrate_kbps}kbps "
                        f"(minimum: {self.min_bitrate_kbps}kbps)"
                    )
            else:
                warnings.append("Could not determine bitrate")

        # Check for unknown format
        if audio_info.format == AudioFormat.UNKNOWN:
            warnings.append("Could not determine audio format")

        return ValidationResult(
            is_valid=len(errors) == 0,
            audio_info=audio_info,
            errors=errors,
            warnings=warnings,
        )

    def _get_audio_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """
        Extract audio information from a file.

        Args:
            file_path: Path to the audio file
            file_size: Size of the file in bytes

        Returns:
            AudioInfo if successful, None if parsing failed
        """
        suffix = file_path.suffix.lower()

        try:
            if suffix in (".m4a", ".mp4", ".aac"):
                return self._get_mp4_info(file_path, file_size)
            elif suffix == ".flac":
                return self._get_flac_info(file_path, file_size)
            elif suffix == ".mp3":
                return self._get_mp3_info(file_path, file_size)
            elif suffix in (".opus", ".ogg"):
                return self._get_opus_info(file_path, file_size)
            else:
                logger.warning(f"Unknown audio format: {suffix}")
                return self._get_generic_info(file_path, file_size)
        except Exception as e:
            logger.error(f"Failed to parse audio file {file_path}: {e}")
            return None

    def _get_mp4_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """Extract info from MP4/M4A files."""
        from mutagen.mp4 import MP4

        try:
            audio = MP4(str(file_path))
            info = audio.info

            # Duration in seconds -> milliseconds
            duration_ms = int(info.length * 1000)

            # Bitrate in bits/sec -> kbps
            bitrate_kbps = int(info.bitrate / 1000) if info.bitrate else None

            return AudioInfo(
                format=AudioFormat.AAC,
                duration_ms=duration_ms,
                bitrate_kbps=bitrate_kbps,
                sample_rate=info.sample_rate,
                channels=info.channels,
                bits_per_sample=info.bits_per_sample,
                file_size_bytes=file_size,
            )
        except Exception as e:
            logger.error(f"Failed to parse MP4 file: {e}")
            return None

    def _get_flac_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """Extract info from FLAC files."""
        from mutagen.flac import FLAC

        try:
            audio = FLAC(str(file_path))
            info = audio.info

            duration_ms = int(info.length * 1000)

            # FLAC is lossless - calculate effective bitrate from file size
            if info.length > 0:
                bitrate_kbps = int((file_size * 8) / info.length / 1000)
            else:
                bitrate_kbps = None

            return AudioInfo(
                format=AudioFormat.FLAC,
                duration_ms=duration_ms,
                bitrate_kbps=bitrate_kbps,
                sample_rate=info.sample_rate,
                channels=info.channels,
                bits_per_sample=info.bits_per_sample,
                file_size_bytes=file_size,
            )
        except Exception as e:
            logger.error(f"Failed to parse FLAC file: {e}")
            return None

    def _get_mp3_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """Extract info from MP3 files."""
        from mutagen.mp3 import MP3

        try:
            audio = MP3(str(file_path))
            info = audio.info

            duration_ms = int(info.length * 1000)
            bitrate_kbps = int(info.bitrate / 1000) if info.bitrate else None

            return AudioInfo(
                format=AudioFormat.MP3,
                duration_ms=duration_ms,
                bitrate_kbps=bitrate_kbps,
                sample_rate=info.sample_rate,
                channels=info.channels,
                bits_per_sample=None,  # MP3 doesn't have this concept
                file_size_bytes=file_size,
            )
        except Exception as e:
            logger.error(f"Failed to parse MP3 file: {e}")
            return None

    def _get_opus_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """Extract info from Opus/OGG files."""
        from mutagen.oggopus import OggOpus

        try:
            audio = OggOpus(str(file_path))
            info = audio.info

            duration_ms = int(info.length * 1000)

            # Calculate bitrate from file size for Opus
            if info.length > 0:
                bitrate_kbps = int((file_size * 8) / info.length / 1000)
            else:
                bitrate_kbps = None

            return AudioInfo(
                format=AudioFormat.OPUS,
                duration_ms=duration_ms,
                bitrate_kbps=bitrate_kbps,
                sample_rate=48000,  # Opus always uses 48kHz internally
                channels=info.channels,
                bits_per_sample=None,
                file_size_bytes=file_size,
            )
        except Exception as e:
            logger.error(f"Failed to parse Opus file: {e}")
            return None

    def _get_generic_info(self, file_path: Path, file_size: int) -> Optional[AudioInfo]:
        """Try to extract info using mutagen's generic file handler."""
        from mutagen import File as MutagenFile

        try:
            audio = MutagenFile(str(file_path))
            if audio is None or audio.info is None:
                return None

            info = audio.info
            duration_ms = int(info.length * 1000)

            # Try to get bitrate
            bitrate_kbps = None
            if hasattr(info, "bitrate") and info.bitrate:
                bitrate_kbps = int(info.bitrate / 1000)

            return AudioInfo(
                format=AudioFormat.UNKNOWN,
                duration_ms=duration_ms,
                bitrate_kbps=bitrate_kbps,
                sample_rate=getattr(info, "sample_rate", None),
                channels=getattr(info, "channels", None),
                bits_per_sample=getattr(info, "bits_per_sample", None),
                file_size_bytes=file_size,
            )
        except Exception as e:
            logger.error(f"Failed to parse audio file with generic handler: {e}")
            return None

    def quick_check(self, file_path: Path) -> bool:
        """
        Quick validation that just checks if the file is parseable.

        Useful for fast validation when full checks aren't needed.

        Args:
            file_path: Path to the audio file

        Returns:
            True if file can be parsed, False otherwise
        """
        if not file_path.exists():
            return False

        file_size = file_path.stat().st_size
        if file_size == 0:
            return False

        audio_info = self._get_audio_info(file_path, file_size)
        return audio_info is not None and audio_info.duration_ms >= self.min_duration_ms
