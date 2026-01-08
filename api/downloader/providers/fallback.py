"""
Fallback download orchestrator.

This module provides a FallbackDownloader that tries multiple download providers
in sequence until one succeeds. The primary use case is falling back to Tidal
or Qobuz when spotdl fails to find a matching track on YouTube Music.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .audio_converter import AudioConversionError, convert_flac_to_m4a
from .base import (
    DownloadProvider,
    QualityPreference,
    SpotifyTrackMetadata,
    TrackMatch,
)
from .metadata import MetadataEmbedder
from .qobuz import QobuzProvider
from .tidal import TidalProvider
from .tidal_endpoints import TidalEndpointManager
from .validation import AudioValidator, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class FallbackDownloadResult:
    """Result of a fallback download attempt."""

    success: bool
    file_path: Optional[Path]
    provider_used: Optional[str]
    error_message: Optional[str]
    track_match: Optional[TrackMatch]
    validation_result: Optional[ValidationResult]


class FallbackDownloader:
    """
    Orchestrates fallback downloads using alternative providers.

    When the primary download method (spotdl) fails, this class attempts
    to download the track using fallback providers like Tidal or Qobuz.

    The download process for each provider:
    1. Search for the track using ISRC (most reliable) or metadata
    2. Download from the matching track
    3. Convert FLAC to M4A if needed (for HIGH quality preference)
    4. Embed Spotify metadata (providers don't include proper tags)
    5. Validate the downloaded file
    """

    # Supported provider names
    SUPPORTED_PROVIDERS = {"tidal", "qobuz"}

    def __init__(
        self,
        quality_preference: QualityPreference = QualityPreference.HIGH,
        output_dir: Optional[Path] = None,
        provider_order: Optional[list[str]] = None,
        qobuz_use_mp3: bool = False,
    ):
        """
        Initialize the fallback downloader.

        Args:
            quality_preference: Preferred quality level for downloads
            output_dir: Directory to save downloaded files
            provider_order: List of provider names to try in order.
                          Defaults to ["tidal", "qobuz"].
            qobuz_use_mp3: If True, Qobuz downloads MP3 directly for HIGH quality
                          instead of FLAC (which gets converted to M4A).
        """
        self._quality_preference = quality_preference
        self._output_dir = output_dir or Path("/music")
        self._qobuz_use_mp3 = qobuz_use_mp3

        # Parse provider order - filter to only fallback providers (not spotdl)
        if provider_order is not None:
            self._provider_order = [
                p for p in provider_order if p in self.SUPPORTED_PROVIDERS
            ]
        else:
            self._provider_order = ["tidal", "qobuz"]

        # Initialize components
        self._tidal_endpoint_manager = TidalEndpointManager()
        self._providers: dict[str, DownloadProvider] = {}
        self._metadata_embedder = MetadataEmbedder()
        self._audio_validator = AudioValidator()

        # Track initialization state per provider
        self._initialized: set[str] = set()

    async def _ensure_provider_initialized(self, provider_name: str) -> bool:
        """
        Ensure a specific provider is initialized.

        Args:
            provider_name: Name of the provider to initialize

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if provider_name in self._initialized:
            return True

        try:
            if provider_name == "tidal":
                provider = TidalProvider(
                    endpoint_manager=self._tidal_endpoint_manager,
                )
                if not await provider.is_available():
                    logger.warning("Tidal API is not available")
                    return False
                self._providers["tidal"] = provider

            elif provider_name == "qobuz":
                provider = QobuzProvider(use_mp3=self._qobuz_use_mp3)
                if not await provider.is_available():
                    logger.warning("Qobuz API is not available")
                    return False
                self._providers["qobuz"] = provider

            else:
                logger.warning(f"Unknown provider: {provider_name}")
                return False

            self._initialized.add(provider_name)
            return True

        except Exception as e:
            logger.error(f"Failed to initialize {provider_name}: {e}")
            return False

    async def download_track(
        self,
        spotify_metadata: SpotifyTrackMetadata,
        output_filename: Optional[str] = None,
    ) -> FallbackDownloadResult:
        """
        Attempt to download a track using fallback providers.

        Tries each provider in the configured order until one succeeds.

        Args:
            spotify_metadata: Metadata from Spotify for the track
            output_filename: Optional custom filename (without extension)

        Returns:
            FallbackDownloadResult with success status and file path
        """
        if not self._provider_order:
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used=None,
                error_message="No fallback providers configured",
                track_match=None,
                validation_result=None,
            )

        last_error = "All providers failed"

        for provider_name in self._provider_order:
            logger.info(
                f"[{provider_name}] Trying to download: "
                f"'{spotify_metadata.artist} - {spotify_metadata.title}'"
            )

            # Initialize provider if needed
            if not await self._ensure_provider_initialized(provider_name):
                logger.warning(f"[{provider_name}] Provider not available, skipping")
                continue

            provider = self._providers.get(provider_name)
            if not provider:
                continue

            # Try this provider
            result = await self._try_provider(
                provider=provider,
                spotify_metadata=spotify_metadata,
                output_filename=output_filename,
            )

            if result.success:
                return result

            # Record error for logging
            last_error = result.error_message or f"{provider_name} failed"
            logger.info(f"[{provider_name}] Failed: {last_error}")

        return FallbackDownloadResult(
            success=False,
            file_path=None,
            provider_used=None,
            error_message=last_error,
            track_match=None,
            validation_result=None,
        )

    async def _try_provider(
        self,
        provider: DownloadProvider,
        spotify_metadata: SpotifyTrackMetadata,
        output_filename: Optional[str],
    ) -> FallbackDownloadResult:
        """
        Attempt to download from a specific provider.

        Args:
            provider: The download provider to use
            spotify_metadata: Spotify track metadata
            output_filename: Optional custom filename

        Returns:
            FallbackDownloadResult with download status
        """
        provider_name = provider.name

        # Step 1: Search for the track
        try:
            match = await provider.search_track(
                title=spotify_metadata.title,
                artist=spotify_metadata.artist,
                album=spotify_metadata.album,
                isrc=spotify_metadata.isrc,
                duration_ms=spotify_metadata.duration_ms,
            )
            if match is None:
                logger.info(
                    f"[{provider_name}] No match found for "
                    f"'{spotify_metadata.artist} - {spotify_metadata.title}'"
                )
                return FallbackDownloadResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message="No matching track found",
                    track_match=None,
                    validation_result=None,
                )

            logger.info(
                f"[{provider_name}] Found match: '{match.artist} - {match.title}' "
                f"(confidence: {match.confidence:.2f})"
            )
        except Exception as e:
            logger.error(f"[{provider_name}] Search failed: {e}")
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Search failed: {e}",
                track_match=None,
                validation_result=None,
            )

        # Step 2: Download the track
        try:
            # Generate output path
            if output_filename:
                base_filename = output_filename
            else:
                # Create filename from metadata
                safe_artist = self._sanitize_filename(spotify_metadata.artist)
                safe_title = self._sanitize_filename(spotify_metadata.title)
                base_filename = f"{safe_artist} - {safe_title}"

            # Determine file extension based on quality and provider
            ext = self._get_expected_extension(provider_name)
            output_path = self._output_dir / f"{base_filename}.{ext}"

            # Download
            download_result = await provider.download_track(
                track_match=match,
                output_path=output_path,
                quality=self._quality_preference,
            )

            if not download_result.success or download_result.file_path is None:
                logger.error(
                    f"[{provider_name}] Download failed: {download_result.error}"
                )
                return FallbackDownloadResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=download_result.error or "Download failed",
                    track_match=match,
                    validation_result=None,
                )

            file_path = download_result.file_path
            logger.info(f"[{provider_name}] Downloaded to: {file_path}")
        except Exception as e:
            logger.error(f"[{provider_name}] Download failed with exception: {e}")
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Download failed: {e}",
                track_match=match,
                validation_result=None,
            )

        # Step 3: Convert FLAC/MP3 to M4A if user requested HIGH quality
        # (Keep FLAC as-is for LOSSLESS/HI_RES quality preferences)
        if (
            self._quality_preference == QualityPreference.HIGH
            and file_path.suffix.lower() == ".flac"
        ):
            try:
                logger.info(
                    f"[{provider_name}] Converting FLAC to M4A for HIGH quality"
                )
                file_path = convert_flac_to_m4a(
                    input_path=file_path,
                    bitrate_kbps=256,
                    delete_original=True,
                )
                logger.info(f"[{provider_name}] Converted to: {file_path}")
            except AudioConversionError as e:
                logger.error(f"[{provider_name}] FLAC to M4A conversion failed: {e}")
                return FallbackDownloadResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=f"Format conversion failed: {e}",
                    track_match=match,
                    validation_result=None,
                )

        # Step 4: Embed metadata (providers don't have proper tags)
        try:
            metadata_success = self._metadata_embedder.embed_metadata(
                file_path=file_path,
                spotify_metadata=spotify_metadata,
                track_match=match,
            )
            if not metadata_success:
                logger.warning(
                    f"[{provider_name}] Failed to embed metadata, file may lack tags"
                )
        except Exception as e:
            logger.warning(f"[{provider_name}] Metadata embedding failed: {e}")
            # Continue - file is still valid, just without metadata

        # Step 5: Validate the downloaded file
        validation_result: Optional[ValidationResult] = None
        try:
            validation_result = self._audio_validator.validate(
                file_path=file_path,
                expected_duration_ms=spotify_metadata.duration_ms,
            )

            if not validation_result.is_valid:
                logger.warning(
                    f"[{provider_name}] Validation failed: {validation_result.errors}"
                )
                # Don't fail the download, just log the warning
        except Exception as e:
            logger.warning(f"[{provider_name}] Validation failed with exception: {e}")

        logger.info(
            f"[{provider_name}] Successfully downloaded and processed: "
            f"'{spotify_metadata.artist} - {spotify_metadata.title}'"
        )

        return FallbackDownloadResult(
            success=True,
            file_path=file_path,
            provider_used=provider_name,
            error_message=None,
            track_match=match,
            validation_result=validation_result,
        )

    def _get_expected_extension(self, provider_name: str) -> str:
        """Get expected file extension based on provider and quality."""
        if self._quality_preference in (
            QualityPreference.LOSSLESS,
            QualityPreference.HI_RES,
        ):
            return "flac"

        # For HIGH quality
        if provider_name == "qobuz":
            # Qobuz HIGH: returns MP3 if use_mp3=True, else FLAC (to be converted to M4A)
            return "mp3" if self._qobuz_use_mp3 else "flac"
        else:
            # Tidal returns M4A for HIGH quality
            return "m4a"

    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize a string for use in filenames.

        Args:
            name: The string to sanitize

        Returns:
            Sanitized string safe for use in filenames
        """
        # Replace problematic characters
        replacements = {
            "/": "-",
            "\\": "-",
            ":": "-",
            "*": "",
            "?": "",
            '"': "'",
            "<": "",
            ">": "",
            "|": "-",
        }
        result = name
        for old, new in replacements.items():
            result = result.replace(old, new)

        # Limit length
        max_length = 100
        if len(result) > max_length:
            result = result[:max_length]

        return result.strip()

    async def close(self) -> None:
        """Clean up resources."""
        self._providers.clear()
        self._initialized.clear()
