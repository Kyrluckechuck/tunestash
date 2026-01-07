"""
Fallback download orchestrator.

This module provides a FallbackDownloader that tries multiple download providers
in sequence until one succeeds. The primary use case is falling back to Tidal
when spotdl fails to find a matching track on YouTube Music.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import (
    QualityPreference,
    SpotifyTrackMetadata,
    TrackMatch,
)
from .metadata import MetadataEmbedder
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
    to download the track using fallback providers like Tidal.

    The download process:
    1. Search for the track using ISRC (most reliable) or metadata
    2. Download from the matching track
    3. Embed Spotify metadata (providers don't include proper tags)
    4. Validate the downloaded file
    """

    def __init__(
        self,
        quality_preference: QualityPreference = QualityPreference.HIGH,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the fallback downloader.

        Args:
            quality_preference: Preferred quality level for downloads
            output_dir: Directory to save downloaded files
        """
        self._quality_preference = quality_preference
        self._output_dir = output_dir or Path("/music")

        # Initialize components
        self._endpoint_manager = TidalEndpointManager()
        self._tidal_provider: Optional[TidalProvider] = None
        self._metadata_embedder = MetadataEmbedder()
        self._audio_validator = AudioValidator()

        # Track initialization state
        self._initialized = False

    async def _ensure_initialized(self) -> bool:
        """
        Ensure the downloader is initialized.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True

        try:
            # Create Tidal provider (endpoint manager loads endpoints lazily)
            self._tidal_provider = TidalProvider(
                endpoint_manager=self._endpoint_manager,
            )

            # Verify Tidal API is available
            if not await self._tidal_provider.is_available():
                logger.error("Tidal API is not available")
                return False

            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize fallback downloader: {e}")
            return False

    async def download_track(
        self,
        spotify_metadata: SpotifyTrackMetadata,
        output_filename: Optional[str] = None,
    ) -> FallbackDownloadResult:
        """
        Attempt to download a track using fallback providers.

        Args:
            spotify_metadata: Metadata from Spotify for the track
            output_filename: Optional custom filename (without extension)

        Returns:
            FallbackDownloadResult with success status and file path
        """
        # Ensure we're initialized
        if not await self._ensure_initialized():
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used=None,
                error_message="Failed to initialize fallback providers",
                track_match=None,
                validation_result=None,
            )

        if self._tidal_provider is None:
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used=None,
                error_message="Tidal provider not available",
                track_match=None,
                validation_result=None,
            )

        # Try Tidal first (only provider for now)
        return await self._try_tidal(spotify_metadata, output_filename)

    async def _try_tidal(
        self,
        spotify_metadata: SpotifyTrackMetadata,
        output_filename: Optional[str],
    ) -> FallbackDownloadResult:
        """
        Attempt to download from Tidal.

        Args:
            spotify_metadata: Spotify track metadata
            output_filename: Optional custom filename

        Returns:
            FallbackDownloadResult with download status
        """
        if self._tidal_provider is None:
            return FallbackDownloadResult(
                success=False,
                file_path=None,
                provider_used="tidal",
                error_message="Tidal provider not initialized",
                track_match=None,
                validation_result=None,
            )

        provider_name = self._tidal_provider.name

        # Step 1: Search for the track
        try:
            match = await self._tidal_provider.search_track(
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

            # Determine file extension based on quality
            ext = (
                "flac"
                if self._quality_preference
                in (QualityPreference.LOSSLESS, QualityPreference.HI_RES)
                else "m4a"
            )
            output_path = self._output_dir / f"{base_filename}.{ext}"

            # Download
            download_result = await self._tidal_provider.download_track(
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

        # Step 3: Embed metadata (Tidal downloads don't have proper tags)
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

        # Step 4: Validate the downloaded file
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
                # The file might still be usable
        except Exception as e:
            logger.warning(f"[{provider_name}] Validation failed with exception: {e}")
            validation_result = None

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
        self._tidal_provider = None
        self._initialized = False
