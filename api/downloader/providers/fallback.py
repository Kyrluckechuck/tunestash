"""
Download provider chain orchestrator.

This module provides a DownloadProviderChain (formerly FallbackDownloader) that
tries multiple download providers in sequence until one succeeds.
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
    TrackMatch,
    TrackMetadata,
)
from .metadata import MetadataEmbedder
from .monochrome import MonochromeProvider
from .qobuz import QobuzProvider
from .tidal import TidalProvider
from .tidal_endpoints import TidalEndpointManager
from .validation import AudioValidator, ValidationResult
from .youtube import YouTubeMusicProvider

logger = logging.getLogger(__name__)


@dataclass
class DownloadChainResult:
    """Result of a download chain attempt."""

    success: bool
    file_path: Optional[Path]
    provider_used: Optional[str]
    error_message: Optional[str]
    track_match: Optional[TrackMatch]
    validation_result: Optional[ValidationResult]


# Backward-compatible alias
FallbackDownloadResult = DownloadChainResult


class DownloadProviderChain:
    """
    Orchestrates downloads across multiple providers with fallback.

    Tries download providers in order until one succeeds.

    The download process for each provider:
    1. Search for the track using ISRC (most reliable) or metadata
    2. Download from the matching track
    3. Convert FLAC to M4A if needed (for HIGH quality preference)
    4. Embed metadata (providers don't include proper tags)
    5. Validate the downloaded file
    6. Fetch lyrics if enabled
    """

    SUPPORTED_PROVIDERS = {"youtube", "tidal", "qobuz", "monochrome"}

    def __init__(
        self,
        quality_preference: QualityPreference = QualityPreference.HIGH,
        output_dir: Optional[Path] = None,
        provider_order: Optional[list[str]] = None,
        qobuz_use_mp3: bool = False,
    ):
        self._quality_preference = quality_preference
        if output_dir:
            self._output_dir = output_dir
        else:
            from django.conf import settings as django_settings

            self._output_dir = Path(
                getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify")
            )
        self._qobuz_use_mp3 = qobuz_use_mp3

        if provider_order is not None:
            self._provider_order = [
                p for p in provider_order if p in self.SUPPORTED_PROVIDERS
            ]
        else:
            self._provider_order = ["youtube", "tidal", "qobuz", "monochrome"]

        self._tidal_endpoint_manager = TidalEndpointManager()
        self._providers: dict[str, DownloadProvider] = {}
        self._metadata_embedder = MetadataEmbedder()
        self._audio_validator = AudioValidator()

        self._initialized: set[str] = set()

    async def _ensure_provider_initialized(self, provider_name: str) -> bool:
        """Ensure a provider is initialized and available.

        Re-checks availability each time for providers that previously failed,
        since endpoint health can recover quickly. Per-endpoint cooldowns are
        handled internally by each provider's endpoint manager.
        """
        if provider_name in self._initialized:
            return True

        try:
            if provider_name == "youtube":
                provider = YouTubeMusicProvider()
                if not await provider.is_available():
                    logger.warning("YouTube Music provider is not available")
                    return False
                self._providers["youtube"] = provider

            elif provider_name == "tidal":
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

            elif provider_name == "monochrome":
                provider = MonochromeProvider()
                if not await provider.is_available():
                    logger.warning("Monochrome provider is not available")
                    return False
                self._providers["monochrome"] = provider

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
        track_metadata: TrackMetadata,
        output_filename: Optional[str] = None,
    ) -> DownloadChainResult:
        """
        Attempt to download a track using providers in order.

        Tries each provider in the configured order until one succeeds.
        """
        if not self._provider_order:
            return DownloadChainResult(
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
                f"'{track_metadata.artist} - {track_metadata.title}'"
            )

            if not await self._ensure_provider_initialized(provider_name):
                logger.warning(f"[{provider_name}] Provider not available, skipping")
                continue

            provider = self._providers.get(provider_name)
            if not provider:
                continue

            result = await self._try_provider(
                provider=provider,
                track_metadata=track_metadata,
                output_filename=output_filename,
            )

            if result.success:
                return result

            last_error = result.error_message or f"{provider_name} failed"
            logger.info(f"[{provider_name}] Failed: {last_error}")

        return DownloadChainResult(
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
        track_metadata: TrackMetadata,
        output_filename: Optional[str],
    ) -> DownloadChainResult:
        provider_name = provider.name

        # Step 1: Search for the track
        try:
            match = await provider.search_track(
                title=track_metadata.title,
                artist=track_metadata.artist,
                album=track_metadata.album,
                isrc=track_metadata.isrc,
                duration_ms=track_metadata.duration_ms,
            )
            if match is None:
                logger.info(
                    f"[{provider_name}] No match found for "
                    f"'{track_metadata.artist} - {track_metadata.title}'"
                )
                return DownloadChainResult(
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
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Search failed: {e}",
                track_match=None,
                validation_result=None,
            )

        # Step 2: Download the track
        try:
            safe_artist = self._sanitize_filename(track_metadata.artist)
            safe_album = self._sanitize_filename(
                track_metadata.album or "Unknown Album"
            )
            if output_filename:
                base_filename = output_filename
            else:
                safe_title = self._sanitize_filename(track_metadata.title)
                base_filename = f"{safe_artist} - {safe_title}"

            ext = self._get_expected_extension(provider_name)
            album_dir = self._output_dir / safe_artist / safe_album
            album_dir.mkdir(parents=True, exist_ok=True)
            output_path = album_dir / f"{base_filename}.{ext}"

            download_result = await provider.download_track(
                track_match=match,
                output_path=output_path,
                quality=self._quality_preference,
            )

            if not download_result.success or download_result.file_path is None:
                logger.error(
                    f"[{provider_name}] Download failed: {download_result.error}"
                )
                return DownloadChainResult(
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
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Download failed: {e}",
                track_match=match,
                validation_result=None,
            )

        # Step 3: Convert FLAC to M4A if user requested HIGH quality
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
                return DownloadChainResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=f"Format conversion failed: {e}",
                    track_match=match,
                    validation_result=None,
                )

        # Step 4: Embed metadata
        try:
            metadata_success = self._metadata_embedder.embed_metadata(
                file_path=file_path,
                track_metadata=track_metadata,
                track_match=match,
            )
            if not metadata_success:
                logger.warning(
                    f"[{provider_name}] Failed to embed metadata, file may lack tags"
                )
        except Exception as e:
            logger.warning(f"[{provider_name}] Metadata embedding failed: {e}")

        # Step 5: Validate the downloaded file
        validation_result: Optional[ValidationResult] = None
        try:
            validation_result = self._audio_validator.validate(
                file_path=file_path,
                expected_duration_ms=track_metadata.duration_ms or None,  # 0 = unknown
            )

            if not validation_result.is_valid:
                logger.warning(
                    f"[{provider_name}] Validation failed: {validation_result.errors}"
                )
        except Exception as e:
            logger.warning(f"[{provider_name}] Validation failed with exception: {e}")

        # Step 6: Fetch lyrics (non-blocking, failure never fails download)
        try:
            from downloader.lyrics import fetch_and_save_lyrics_if_enabled

            fetch_and_save_lyrics_if_enabled(
                file_path=file_path,
                track_name=track_metadata.title,
                artist_name=track_metadata.artist,
                album_name=track_metadata.album,
                duration_seconds=(
                    track_metadata.duration_ms // 1000
                    if track_metadata.duration_ms
                    else None
                ),
            )
        except Exception as e:
            logger.debug(f"[{provider_name}] Lyrics fetch failed (non-fatal): {e}")

        logger.info(
            f"[{provider_name}] Successfully downloaded and processed: "
            f"'{track_metadata.artist} - {track_metadata.title}'"
        )

        return DownloadChainResult(
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

        if provider_name == "qobuz":
            return "mp3" if self._qobuz_use_mp3 else "flac"
        elif provider_name == "youtube":
            return "m4a"
        elif provider_name == "monochrome":
            # Monochrome always returns FLAC (converted to M4A in step 3 for HIGH)
            return "flac"
        else:
            return "m4a"

    def _sanitize_filename(self, name: str) -> str:
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

        max_length = 100
        if len(result) > max_length:
            result = result[:max_length]

        return result.strip()

    async def close(self) -> None:
        """Clean up resources."""
        self._providers.clear()
        self._initialized.clear()


# Backward-compatible alias
FallbackDownloader = DownloadProviderChain
