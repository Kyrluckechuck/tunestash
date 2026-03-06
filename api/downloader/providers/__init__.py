"""
Download providers package.

This package contains pluggable download providers that can source audio
from different services (YouTube Music, Tidal, Qobuz).
"""

from .base import (
    DownloadProvider,
    DownloadResult,
    ProviderCapabilities,
    ProviderType,
    QualityOption,
    QualityPreference,
    SpotifyTrackMetadata,
    TrackMatch,
    TrackMetadata,
    calculate_match_confidence,
)
from .fallback import FallbackDownloader, FallbackDownloadResult
from .metadata import MetadataEmbedder, create_metadata_from_match
from .qobuz import QobuzProvider
from .tidal import TidalProvider
from .tidal_endpoints import TidalEndpoint, TidalEndpointManager
from .validation import AudioFormat, AudioInfo, AudioValidator, ValidationResult
from .youtube import YouTubeMusicProvider

__all__ = [
    # Base classes and types
    "DownloadProvider",
    "DownloadResult",
    "ProviderCapabilities",
    "ProviderType",
    "QualityOption",
    "QualityPreference",
    "SpotifyTrackMetadata",
    "TrackMatch",
    "TrackMetadata",
    "calculate_match_confidence",
    # Metadata embedding
    "MetadataEmbedder",
    "create_metadata_from_match",
    # Providers
    "QobuzProvider",
    "TidalEndpoint",
    "TidalEndpointManager",
    "TidalProvider",
    # Validation
    "AudioFormat",
    "AudioInfo",
    "AudioValidator",
    "ValidationResult",
    # YouTube provider
    "YouTubeMusicProvider",
    # Fallback orchestrator
    "FallbackDownloader",
    "FallbackDownloadResult",
]
