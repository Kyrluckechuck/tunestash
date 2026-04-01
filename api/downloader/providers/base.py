"""
Base classes for download providers.

This module defines the abstract interface that all download providers must
implement, along with data classes for representing tracks, download results,
and provider capabilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class ProviderType(Enum):
    """Type of provider implementation."""

    REST_API = "rest_api"
    SELF_HOSTED = "self_hosted"
    BROWSER_AUTOMATION = "browser"


class QualityPreference(Enum):
    """Audio quality preference levels."""

    LOW = "low"  # ~96-128kbps
    MEDIUM = "medium"  # ~192-256kbps
    HIGH = "high"  # ~320kbps
    LOSSLESS = "lossless"  # CD quality (16-bit/44.1kHz)
    HI_RES = "hi_res"  # Hi-res (24-bit/96kHz+)


@dataclass(frozen=True)
class QualityOption:
    """Represents an available quality option from a provider."""

    quality: QualityPreference
    bitrate_kbps: int
    format: str  # "aac", "mp3", "opus", "flac"
    lossless: bool
    sample_rate: Optional[int] = None  # Hz, e.g., 44100, 96000
    bit_depth: Optional[int] = None  # e.g., 16, 24

    def __str__(self) -> str:
        if self.lossless:
            depth = f"{self.bit_depth}-bit/" if self.bit_depth else ""
            rate = f"{self.sample_rate // 1000}kHz" if self.sample_rate else ""
            return f"{depth}{rate} {self.format.upper()}"
        return f"{self.bitrate_kbps}kbps {self.format.upper()}"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Describes what a provider can do."""

    provider_type: ProviderType
    supports_search: bool
    supports_isrc_lookup: bool
    embeds_metadata: bool
    available_qualities: tuple[QualityOption, ...]
    formats: tuple[str, ...]  # ("aac", "flac", "mp3", "opus")

    @property
    def max_bitrate_kbps(self) -> int:
        """Return the maximum available bitrate."""
        if not self.available_qualities:
            return 0
        return max(q.bitrate_kbps for q in self.available_qualities)

    @property
    def supports_lossless(self) -> bool:
        """Check if provider supports lossless quality."""
        return any(q.lossless for q in self.available_qualities)


@dataclass
class TrackMatch:
    """Represents a matched track from a provider's catalog."""

    provider: str
    provider_track_id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    isrc: Optional[str] = None
    confidence: float = 0.0  # 0.0 - 1.0 match confidence
    cover_url: Optional[str] = None
    track_number: Optional[int] = None
    total_tracks: Optional[int] = None
    release_date: Optional[str] = None
    extra_metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate confidence is in valid range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )


@dataclass
class DownloadResult:
    """Result of a download attempt."""

    success: bool
    provider: str
    file_path: Optional[Path] = None
    bitrate_kbps: Optional[int] = None
    format: Optional[str] = None
    duration_ms: Optional[int] = None
    metadata_embedded: bool = False
    error: Optional[str] = None
    error_retryable: bool = True

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.success and self.file_path is None:
            raise ValueError("Successful download must have a file_path")
        if not self.success and self.error is None:
            raise ValueError("Failed download must have an error message")


@dataclass
class TrackMetadata:
    """Metadata for a track we want to download.

    Originally Spotify-specific, now provider-agnostic. The spotify_id field
    is empty string for tracks sourced from non-Spotify providers.
    """

    spotify_id: str
    title: str
    artist: str
    album: str
    album_artist: str
    duration_ms: int
    isrc: Optional[str] = None
    track_number: Optional[int] = None
    total_tracks: Optional[int] = None
    disc_number: Optional[int] = None
    total_discs: Optional[int] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None
    copyright: Optional[str] = None
    genres: tuple[str, ...] = ()


SpotifyTrackMetadata = TrackMetadata


class DownloadProvider(ABC):
    """
    Abstract base class for download providers.

    Each provider implementation handles downloading audio from a specific
    service (YouTube Music, Tidal, Qobuz).

    Implementations must be:
    - Async-compatible (all methods are async)
    - Stateless (no instance state between calls, except configuration)
    - Thread-safe (may be called from multiple workers)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this provider.

        Used in logs, configuration, and download results.
        Example: "tidal", "qobuz"
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable name for this provider.

        Used in UI and error messages.
        Example: "Tidal", "Qobuz"
        """
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """
        Describe what this provider can do.

        Returns information about supported features, quality options,
        and formats. This is used by the orchestrator to make decisions
        about which provider to try.
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if the provider is currently operational.

        Should perform a lightweight health check (e.g., ping the API).
        This is called before attempting to use the provider.

        Returns:
            True if the provider is ready to accept requests.
        """
        pass

    @abstractmethod
    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """
        Search for a track in the provider's catalog.

        Attempts to find the best match for the given track metadata.
        The implementation should:
        1. Search by title + artist (required)
        2. Use ISRC to verify match if available
        3. Use duration to verify match if available
        4. Return None if no confident match is found

        Args:
            title: Track title (required)
            artist: Artist name (required)
            album: Album name (optional, helps disambiguation)
            isrc: International Standard Recording Code (optional, for verification)
            duration_ms: Track duration in milliseconds (optional, for verification)

        Returns:
            TrackMatch if a confident match is found, None otherwise.
        """
        pass

    @abstractmethod
    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """
        Download a track to the specified path.

        The implementation should:
        1. Request the audio at the specified quality (or best available)
        2. Save to output_path (creating parent directories if needed)
        3. Return detailed result including actual bitrate/format

        Args:
            track_match: The track to download (from search_track)
            output_path: Where to save the downloaded file
            quality: Preferred quality level

        Returns:
            DownloadResult with success status and file details.
        """
        pass

    async def get_track_info(self, provider_track_id: str) -> Optional[TrackMatch]:
        """
        Get detailed information about a specific track.

        Optional method - not all providers may support direct track lookup.
        Default implementation returns None.

        Args:
            provider_track_id: The provider's internal track ID

        Returns:
            TrackMatch with full metadata, or None if not supported/found.
        """
        return None

    def select_quality(
        self,
        preferred: QualityPreference,
        max_bitrate_kbps: Optional[int] = None,
        format_priority: Optional[list[str]] = None,
    ) -> Optional[QualityOption]:
        """
        Select the best available quality based on preferences.

        Args:
            preferred: Desired quality level
            max_bitrate_kbps: Maximum bitrate to allow (e.g., 320 for lossy only)
            format_priority: Preferred formats in order (e.g., ["aac", "opus", "mp3"])

        Returns:
            Best matching QualityOption, or None if no suitable option.
        """
        available = list(self.capabilities.available_qualities)

        if not available:
            return None

        # Filter by max bitrate if specified
        if max_bitrate_kbps is not None:
            available = [q for q in available if q.bitrate_kbps <= max_bitrate_kbps]

        if not available:
            return None

        # Sort by preference
        def quality_score(q: QualityOption) -> tuple:
            # Score based on how close to preferred quality
            quality_order = [
                QualityPreference.LOW,
                QualityPreference.MEDIUM,
                QualityPreference.HIGH,
                QualityPreference.LOSSLESS,
                QualityPreference.HI_RES,
            ]
            preferred_idx = quality_order.index(preferred)
            actual_idx = quality_order.index(q.quality)
            quality_diff = abs(preferred_idx - actual_idx)

            # Format priority score (lower is better)
            format_score = 999
            if format_priority and q.format in format_priority:
                format_score = format_priority.index(q.format)

            # Prefer higher bitrate within same quality level
            bitrate_score = -q.bitrate_kbps

            return (quality_diff, format_score, bitrate_score)

        available.sort(key=quality_score)
        return available[0]


def calculate_match_confidence(
    search_title: str,
    search_artist: str,
    result_title: str,
    result_artist: str,
    search_duration_ms: Optional[int] = None,
    result_duration_ms: Optional[int] = None,
    search_isrc: Optional[str] = None,
    result_isrc: Optional[str] = None,
    duration_tolerance_ms: int = 5000,
) -> float:
    """Calculate confidence score for a track match.

    Delegates to the shared track_matcher module.
    """
    from downloader.track_matcher import score_track_match

    return score_track_match(
        search_title=search_title,
        search_artist=search_artist,
        result_title=result_title,
        result_artist=result_artist,
        search_isrc=search_isrc,
        result_isrc=result_isrc,
        search_duration_s=search_duration_ms / 1000.0 if search_duration_ms else None,
        result_duration_s=result_duration_ms / 1000.0 if result_duration_ms else None,
        duration_tolerance_s=duration_tolerance_ms / 1000.0,
    )


def _string_similarity(s1: str, s2: str) -> float:
    """Calculate similarity between two strings.

    Delegates to the shared track_matcher module.
    Kept for backwards compatibility with tests.
    """
    from difflib import SequenceMatcher as SM

    from downloader.track_matcher import normalize_for_matching

    n1 = normalize_for_matching(s1)
    n2 = normalize_for_matching(s2)
    if not n1 or not n2:
        return 0.0
    return SM(None, n1, n2).ratio()
