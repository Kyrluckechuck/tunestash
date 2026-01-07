"""
Download providers package.

This package contains pluggable download providers that can source audio
from different services (Tidal, Qobuz, etc.) as fallbacks to spotdl.
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
    calculate_match_confidence,
)
from .fallback import FallbackDownloader, FallbackDownloadResult
from .metadata import MetadataEmbedder, create_spotify_metadata_from_match
from .tidal import TidalProvider
from .tidal_endpoints import TidalEndpoint, TidalEndpointManager
from .validation import AudioFormat, AudioInfo, AudioValidator, ValidationResult

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
    "calculate_match_confidence",
    # Metadata embedding
    "MetadataEmbedder",
    "create_spotify_metadata_from_match",
    # Tidal provider
    "TidalEndpoint",
    "TidalEndpointManager",
    "TidalProvider",
    # Validation
    "AudioFormat",
    "AudioInfo",
    "AudioValidator",
    "ValidationResult",
    # Fallback orchestrator
    "FallbackDownloader",
    "FallbackDownloadResult",
]
