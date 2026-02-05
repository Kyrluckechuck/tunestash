"""Song quality upgrade service.

Provides functionality to upgrade low-quality songs (e.g., 128kbps from spotdl)
to higher quality versions from Tidal or Qobuz.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from django.db.models import Exists, OuterRef, Q, QuerySet

from asgiref.sync import sync_to_async

from library_manager.models import (
    DownloadProvider,
    FailureReason,
    Song,
    SongUpgradeAttempt,
    UpgradeAttemptResult,
)

logger = logging.getLogger(__name__)


@dataclass
class UpgradeStats:
    """Statistics about upgrade-eligible songs."""

    total_low_quality: int
    upgradeable: int  # Low quality with untried providers
    upgraded: int  # Successfully upgraded
    not_upgradeable: int  # All providers returned NOT_FOUND


@dataclass
class UpgradeResult:
    """Result of an upgrade attempt."""

    success: bool
    provider_used: Optional[str]
    original_bitrate: int
    new_bitrate: Optional[int]
    error_message: Optional[str]


class SongUpgradeService:
    """Service for upgrading low-quality songs to higher quality versions."""

    # Default bitrate threshold below which songs are considered "low quality"
    DEFAULT_MAX_BITRATE = 220

    # Providers to try for upgrades (in order)
    # spotdl is excluded since it's typically what gave us the low quality
    UPGRADE_PROVIDERS = [DownloadProvider.TIDAL, DownloadProvider.QOBUZ]

    def __init__(self, max_bitrate: int = DEFAULT_MAX_BITRATE):
        self._max_bitrate = max_bitrate

    async def get_low_quality_songs_queryset(self) -> QuerySet[Song]:
        """
        Get a queryset filter for low-quality songs eligible for upgrade.

        Excludes:
        - Songs that weren't found on YouTube Music initially (likely not available)
        - Songs that have exhausted all upgrade providers
        """

        def build_queryset() -> QuerySet[Song]:
            # Subquery to check if a song has a permanent failure (NOT_FOUND)
            # for a specific provider
            def has_permanent_failure_for_provider(
                provider: int,
            ) -> QuerySet[SongUpgradeAttempt]:
                return SongUpgradeAttempt.objects.filter(
                    song=OuterRef("pk"),
                    provider=provider,
                    result=UpgradeAttemptResult.NOT_FOUND,
                )

            # Base filter: downloaded, low quality, not originally unavailable
            base_filter = Q(
                downloaded=True,
                bitrate__gt=0,
                bitrate__lt=self._max_bitrate,
            )

            # Exclude songs that never found a YTM match initially
            # These are unlikely to be available on other services either
            exclude_ytm_not_found = ~Q(failure_reason=FailureReason.YTM_NO_MATCH)

            # Exclude songs that have permanent failures on ALL upgrade providers
            # (i.e., both Tidal and Qobuz returned NOT_FOUND)
            has_tidal_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.TIDAL)
            )
            has_qobuz_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.QOBUZ)
            )

            # Song is upgradeable if at least one provider hasn't returned NOT_FOUND
            return (
                Song.objects.filter(base_filter)
                .filter(exclude_ytm_not_found)
                .exclude(has_tidal_permanent & has_qobuz_permanent)
            )

        return await sync_to_async(build_queryset)()

    async def get_low_quality_songs(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Song]:
        """
        Get songs eligible for quality upgrade.

        Args:
            limit: Maximum number of songs to return
            offset: Number of songs to skip

        Returns:
            List of Song objects eligible for upgrade
        """

        def fetch() -> list[Song]:
            # Subquery to check for permanent failures
            def has_permanent_failure_for_provider(
                provider: int,
            ) -> QuerySet[SongUpgradeAttempt]:
                return SongUpgradeAttempt.objects.filter(
                    song=OuterRef("pk"),
                    provider=provider,
                    result=UpgradeAttemptResult.NOT_FOUND,
                )

            has_tidal_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.TIDAL)
            )
            has_qobuz_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.QOBUZ)
            )

            queryset = (
                Song.objects.filter(
                    downloaded=True,
                    bitrate__gt=0,
                    bitrate__lt=self._max_bitrate,
                )
                .exclude(failure_reason=FailureReason.YTM_NO_MATCH)
                .exclude(has_tidal_permanent & has_qobuz_permanent)
                .select_related("primary_artist", "album")
                .order_by("bitrate", "id")
            )

            return list(queryset[offset : offset + limit])

        return await sync_to_async(fetch)()

    async def get_upgrade_stats(self) -> UpgradeStats:
        """Get statistics about low-quality and upgradeable songs."""

        def calculate_stats() -> UpgradeStats:
            # Total low quality songs (regardless of upgrade status)
            total_low_quality = Song.objects.filter(
                downloaded=True,
                bitrate__gt=0,
                bitrate__lt=self._max_bitrate,
            ).count()

            # Subquery for permanent failures
            def has_permanent_failure_for_provider(
                provider: int,
            ) -> QuerySet[SongUpgradeAttempt]:
                return SongUpgradeAttempt.objects.filter(
                    song=OuterRef("pk"),
                    provider=provider,
                    result=UpgradeAttemptResult.NOT_FOUND,
                )

            has_tidal_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.TIDAL)
            )
            has_qobuz_permanent = Exists(
                has_permanent_failure_for_provider(DownloadProvider.QOBUZ)
            )

            # Upgradeable: low quality, not YTM_NO_MATCH, has untried providers
            upgradeable = (
                Song.objects.filter(
                    downloaded=True,
                    bitrate__gt=0,
                    bitrate__lt=self._max_bitrate,
                )
                .exclude(failure_reason=FailureReason.YTM_NO_MATCH)
                .exclude(has_tidal_permanent & has_qobuz_permanent)
                .count()
            )

            # Successfully upgraded (downloaded from Tidal/Qobuz with upgrade attempt)
            upgraded = SongUpgradeAttempt.objects.filter(
                result=UpgradeAttemptResult.SUCCESS
            ).count()

            # Not upgradeable: all providers returned NOT_FOUND
            not_upgradeable = (
                Song.objects.filter(
                    downloaded=True,
                    bitrate__gt=0,
                    bitrate__lt=self._max_bitrate,
                )
                .annotate(
                    has_tidal_perm=has_tidal_permanent,
                    has_qobuz_perm=has_qobuz_permanent,
                )
                .filter(has_tidal_perm=True, has_qobuz_perm=True)
                .count()
            )

            return UpgradeStats(
                total_low_quality=total_low_quality,
                upgradeable=upgradeable,
                upgraded=upgraded,
                not_upgradeable=not_upgradeable,
            )

        return await sync_to_async(calculate_stats)()

    async def attempt_upgrade(self, song_id: int) -> UpgradeResult:
        """
        Attempt to upgrade a single song to higher quality.

        Tries each provider in order, skipping those that have already
        returned NOT_FOUND for this song.

        Args:
            song_id: Database ID of the song to upgrade

        Returns:
            UpgradeResult with success status and details
        """
        from django.conf import settings as django_settings

        from downloader.providers.base import QualityPreference, SpotifyTrackMetadata
        from downloader.providers.fallback import FallbackDownloader
        from lib.config_class import Config
        from pymediainfo import MediaInfo

        # Get the song
        def fetch_song() -> Song:
            return Song.objects.select_related("primary_artist", "album").get(
                id=song_id
            )

        try:
            song: Song = await sync_to_async(fetch_song)()
        except Song.DoesNotExist:
            return UpgradeResult(
                success=False,
                provider_used=None,
                original_bitrate=0,
                new_bitrate=None,
                error_message=f"Song {song_id} not found",
            )

        original_bitrate = song.bitrate

        # Check if song is eligible
        if song.bitrate >= self._max_bitrate:
            return UpgradeResult(
                success=False,
                provider_used=None,
                original_bitrate=original_bitrate,
                new_bitrate=None,
                error_message=f"Song bitrate {song.bitrate} already >= {self._max_bitrate}",
            )

        # Get existing attempts to know which providers to skip
        existing_attempts = await sync_to_async(
            lambda: list(
                SongUpgradeAttempt.objects.filter(song=song).values_list(
                    "provider", "result"
                )
            )
        )()

        # Build set of providers with permanent failures
        providers_to_skip = {
            provider
            for provider, result in existing_attempts
            if result
            in (UpgradeAttemptResult.NOT_FOUND, UpgradeAttemptResult.NOT_AN_UPGRADE)
        }

        # Get config for quality preference
        config = Config()
        quality_map = {
            "high": QualityPreference.HIGH,
            "lossless": QualityPreference.LOSSLESS,
            "hi_res": QualityPreference.HI_RES,
        }
        quality = quality_map.get(config.fallback_quality, QualityPreference.HIGH)

        # Get output directory
        output_dir = Path(getattr(django_settings, "OUTPUT_PATH", "/music"))

        # Create metadata for the song - use sync_to_async to access related objects
        def get_song_metadata(db_song: Song) -> tuple[str, Optional[str]]:
            artist = str(db_song.primary_artist.name)  # type: ignore[attr-defined]
            album = str(db_song.album.name) if db_song.album else None  # type: ignore[attr-defined]
            return artist, album

        artist_name, album_name = await sync_to_async(get_song_metadata)(song)

        # Get file path (needs sync_to_async due to related object access)
        current_file_path = await sync_to_async(lambda: song.file_path)()

        # Get duration from existing file if available
        duration_ms = None
        if current_file_path:
            try:
                media_info = MediaInfo.parse(current_file_path)
                for track in media_info.tracks:
                    if track.track_type == "General":
                        duration_ms = int(track.duration)
                        break
            except Exception:
                pass

        spotify_metadata = SpotifyTrackMetadata(
            spotify_id=song.gid,
            title=song.name,
            artist=artist_name,
            album=album_name or "",
            album_artist=artist_name,  # Use primary artist as album artist fallback
            isrc=song.isrc,
            duration_ms=duration_ms or 0,
        )

        # Try each provider in order
        provider_name_map = {
            DownloadProvider.TIDAL: "tidal",
            DownloadProvider.QOBUZ: "qobuz",
        }

        for provider_enum in self.UPGRADE_PROVIDERS:
            if provider_enum in providers_to_skip:
                logger.debug(
                    f"[UPGRADE] Skipping {provider_enum.label} for song {song_id} "
                    f"(permanent failure recorded)"
                )
                continue

            provider_name = provider_name_map[provider_enum]
            logger.info(
                f"[UPGRADE] Trying {provider_enum.label} for "
                f"'{artist_name} - {song.name}'"
            )

            try:
                # Create fallback downloader for just this provider
                downloader = FallbackDownloader(
                    quality_preference=quality,
                    output_dir=output_dir,
                    provider_order=[provider_name],
                    qobuz_use_mp3=config.qobuz_use_mp3,
                )

                result = await downloader.download_track(spotify_metadata)

                if result.success and result.file_path:
                    # Get new bitrate
                    media_info = MediaInfo.parse(result.file_path)
                    new_bitrate = 0
                    for track in media_info.tracks:
                        if track.track_type == "Audio":
                            new_bitrate = int(track.bit_rate / 1000)
                            break

                    # Check if it's actually an upgrade
                    if new_bitrate <= original_bitrate:
                        logger.info(
                            f"[UPGRADE] {provider_enum.label} returned "
                            f"{new_bitrate}kbps, not an upgrade from {original_bitrate}kbps"
                        )

                        # Record NOT_AN_UPGRADE attempt
                        await sync_to_async(SongUpgradeAttempt.objects.create)(
                            song=song,
                            provider=provider_enum,
                            result=UpgradeAttemptResult.NOT_AN_UPGRADE,
                            original_bitrate=original_bitrate,
                            new_bitrate=new_bitrate,
                        )

                        # Clean up downloaded file
                        try:
                            result.file_path.unlink()
                        except Exception:
                            pass

                        continue  # Try next provider

                    # It's an upgrade! Replace the old file
                    old_path = await sync_to_async(lambda: song.file_path)()
                    await sync_to_async(song.mark_downloaded)(
                        bitrate=new_bitrate,
                        file_path=str(result.file_path),
                        provider=provider_enum,
                    )

                    # Record SUCCESS attempt
                    await sync_to_async(SongUpgradeAttempt.objects.create)(
                        song=song,
                        provider=provider_enum,
                        result=UpgradeAttemptResult.SUCCESS,
                        original_bitrate=original_bitrate,
                        new_bitrate=new_bitrate,
                    )

                    # Delete old file if different
                    if old_path and old_path != str(result.file_path):
                        try:
                            Path(old_path).unlink()
                        except Exception as e:
                            logger.warning(f"[UPGRADE] Failed to delete old file: {e}")

                    logger.info(
                        f"[UPGRADE] Successfully upgraded '{artist_name} - {song.name}' "
                        f"from {original_bitrate}kbps to {new_bitrate}kbps via {provider_enum.label}"
                    )

                    return UpgradeResult(
                        success=True,
                        provider_used=provider_name,
                        original_bitrate=original_bitrate,
                        new_bitrate=new_bitrate,
                        error_message=None,
                    )

                # Provider failed to find/download the track
                error_msg = result.error_message or "Unknown error"

                # Determine if this is an API error (temporary) or not found (permanent)
                is_api_error = any(
                    term in error_msg.lower()
                    for term in ["api", "timeout", "connection", "rate limit", "500"]
                )

                attempt_result = (
                    UpgradeAttemptResult.API_ERROR
                    if is_api_error
                    else UpgradeAttemptResult.NOT_FOUND
                )

                await sync_to_async(SongUpgradeAttempt.objects.create)(
                    song=song,
                    provider=provider_enum,
                    result=attempt_result,
                    original_bitrate=original_bitrate,
                    error_message=error_msg[:500],  # Truncate long errors
                )

                logger.info(
                    f"[UPGRADE] {provider_enum.label} failed for "
                    f"'{artist_name} - {song.name}': {error_msg}"
                )

                if is_api_error:
                    # API error - abort and allow retry later
                    return UpgradeResult(
                        success=False,
                        provider_used=provider_name,
                        original_bitrate=original_bitrate,
                        new_bitrate=None,
                        error_message=f"API error: {error_msg}",
                    )

            except Exception as e:
                logger.error(f"[UPGRADE] Exception trying {provider_enum.label}: {e}")

                # Record API_ERROR for exceptions (allows retry)
                await sync_to_async(SongUpgradeAttempt.objects.create)(
                    song=song,
                    provider=provider_enum,
                    result=UpgradeAttemptResult.API_ERROR,
                    original_bitrate=original_bitrate,
                    error_message=str(e)[:500],
                )

                # Don't continue to other providers on exception (might be connectivity)
                return UpgradeResult(
                    success=False,
                    provider_used=provider_name,
                    original_bitrate=original_bitrate,
                    new_bitrate=None,
                    error_message=f"Exception: {e}",
                )

        # All providers tried without success
        return UpgradeResult(
            success=False,
            provider_used=None,
            original_bitrate=original_bitrate,
            new_bitrate=None,
            error_message="All providers exhausted",
        )
