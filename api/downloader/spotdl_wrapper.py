"""
SpotDL wrapper for downloading music from Spotify playlists and albums.

Handles:
- Creating and saving artists that contributed to playlist/album
- Marking songs as downloaded
- Album download tracking
- Playlist sync validation
"""

from __future__ import annotations, division

import asyncio
import logging
import os
import signal
import time
import traceback
from argparse import Namespace
from pathlib import Path
from typing import Any

from django.db.models.functions import Now

from lib.config_class import Config
from pymediainfo import MediaInfo
from spotdl import Spotdl
from spotdl.download.downloader import Downloader as SpotdlDownloader
from spotdl.utils.config import create_settings
from spotdl.utils.logging import init_logging
from spotdl.utils.spotify import SpotifyClient
from spotipy.exceptions import SpotifyException

from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    DownloadHistory,
    FailureReason,
    Song,
    TrackedPlaylist,
)
from library_manager.validators import extract_spotify_id_from_uri

from . import __version__, spotdl_override, utils
from .default_download_settings import DEFAULT_DOWNLOAD_SETTINGS
from .downloader import Downloader
from .premium_detector import PremiumDetector, PremiumStatus
from .spotdl_override import (
    DownloadTimeoutError,
    _malloc_trim,
    song_from_track_data,
)
from .spotipy_tasks import SpotifyRateLimitError

# Memory management thresholds (in MB) - must match celery_app.py
_MEMORY_WARNING_THRESHOLD_MB = 600
_MEMORY_CHECK_INTERVAL_TRACKS = (
    10  # Check memory every N tracks (reduced for better visibility)
)

# Container-level memory threshold for requesting restart (percentage of cgroup limit)
# When container memory exceeds this, request graceful shutdown so Docker restarts us
# This catches main Celery process memory leaks that --max-tasks-per-child doesn't fix
_CONTAINER_RESTART_PERCENT = 85

# Reinitialize spotdl every N songs as a fallback for any remaining yt-dlp leaks
# The primary fix is AudioProvider.close() patch in spotdl_override.py
# See: https://github.com/yt-dlp/yt-dlp/issues/1949
_SPOTDL_REINIT_INTERVAL_TRACKS = (
    200  # Increased since AudioProvider patch handles most cleanup
)

# Rate limiting: delay between consecutive song downloads (in seconds)
# This helps avoid hitting Spotify/YouTube rate limits during bulk operations
_DOWNLOAD_DELAY_SECONDS = 1.0


def _get_container_memory_mb() -> tuple[float, float]:
    """
    Get total memory usage for all processes in the container.

    In Docker, /sys/fs/cgroup/memory.current shows total cgroup memory usage.
    Falls back to summing all process RSS if cgroup info unavailable.

    Returns:
        Tuple of (container_memory_mb, cgroup_limit_mb or 0 if unknown)
    """
    try:
        # Try cgroup v2 first (modern Docker)
        with open("/sys/fs/cgroup/memory.current", encoding="utf-8") as f:
            container_bytes = int(f.read().strip())
        container_mb = container_bytes / 1024 / 1024

        # Get cgroup limit
        try:
            with open("/sys/fs/cgroup/memory.max", encoding="utf-8") as f:
                limit_str = f.read().strip()
                limit_mb = int(limit_str) / 1024 / 1024 if limit_str != "max" else 0
        except Exception:
            limit_mb = 0

        return container_mb, limit_mb
    except FileNotFoundError:
        pass

    try:
        # Try cgroup v1 (older Docker)
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", encoding="utf-8") as f:
            container_bytes = int(f.read().strip())
        container_mb = container_bytes / 1024 / 1024

        try:
            with open(
                "/sys/fs/cgroup/memory/memory.limit_in_bytes", encoding="utf-8"
            ) as f:
                limit_mb = int(f.read().strip()) / 1024 / 1024
        except Exception:
            limit_mb = 0

        return container_mb, limit_mb
    except FileNotFoundError:
        pass

    # Fallback: sum all process memory (less accurate but works outside containers)
    try:
        import psutil

        total_mb = sum(p.memory_info().rss for p in psutil.process_iter()) / 1024 / 1024
        return total_mb, 0
    except Exception:
        return 0, 0


def _request_main_process_shutdown(logger: logging.Logger) -> bool:
    """
    Request graceful shutdown of the main Celery process.

    Sends SIGTERM to the parent process (main Celery process in Docker), triggering
    a graceful shutdown. Docker's restart policy will then restart the container
    with fresh memory.

    Returns:
        True if signal was sent, False otherwise
    """
    try:
        parent_pid = os.getppid()
        logger.warning(
            f"[MEMORY] Requesting main process shutdown (parent PID: {parent_pid})"
        )
        os.kill(parent_pid, signal.SIGTERM)
        return True
    except Exception as e:
        logger.error(f"[MEMORY] Failed to signal parent process: {e}")
        return False


def _drop_page_cache(logger: logging.Logger) -> bool:
    """
    Attempt to drop Linux page cache to free memory.

    Downloaded audio files get cached by the kernel, consuming cgroup memory budget.
    The OOM killer can target the worker process even though the memory is just cache.

    Returns:
        True if cache was dropped, False otherwise
    """
    try:
        # sync first to flush dirty pages
        os.sync()
        # Drop page cache (requires root or CAP_SYS_ADMIN)
        with open("/proc/sys/vm/drop_caches", "w", encoding="utf-8") as f:
            f.write("1")  # 1 = page cache only, 2 = dentries/inodes, 3 = both
        return True
    except (PermissionError, FileNotFoundError, OSError) as e:
        logger.warning(f"[MEMORY] Failed to drop page cache: {e}")
        return False


def _check_and_release_memory(
    logger: logging.Logger,
    track_index: int,
) -> None:
    """
    Periodically release memory back to OS during long downloads.

    Uses malloc_trim() on Linux to return freed memory to the OS.
    Only runs every _MEMORY_CHECK_INTERVAL_TRACKS tracks to minimize overhead.
    """
    if track_index % _MEMORY_CHECK_INTERVAL_TRACKS != 0:
        return

    try:
        import psutil

        process = psutil.Process(os.getpid())
        rss_mb = process.memory_info().rss / 1024 / 1024

        # Always log memory status at checkpoints for visibility
        initial_rss = rss_mb

        # Always try to release memory, not just when above threshold
        _malloc_trim()
        final_rss = process.memory_info().rss / 1024 / 1024
        released = initial_rss - final_rss

        # Get parent (main Celery) process memory to track the leak
        parent_rss_mb = 0.0
        try:
            parent = psutil.Process(os.getppid())
            parent_rss_mb = parent.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Get container-level memory (all processes in cgroup)
        container_mb, limit_mb = _get_container_memory_mb()
        limit_str = f"/{limit_mb:.0f}MB" if limit_mb > 0 else ""
        container_percent = (container_mb / limit_mb * 100) if limit_mb > 0 else 0

        # Determine log level based on memory usage
        if final_rss >= _MEMORY_WARNING_THRESHOLD_MB:
            logger.warning(
                f"[MEMORY MID-TASK] Track {track_index}: "
                f"worker={final_rss:.0f}MB (freed {released:.1f}MB), "
                f"parent={parent_rss_mb:.0f}MB, "
                f"container={container_mb:.0f}MB{limit_str} ({container_percent:.0f}%) "
                f"⚠️ ABOVE THRESHOLD"
            )
        else:
            logger.info(
                f"[MEMORY MID-TASK] Track {track_index}: "
                f"worker={final_rss:.0f}MB (freed {released:.1f}MB), "
                f"parent={parent_rss_mb:.0f}MB, "
                f"container={container_mb:.0f}MB{limit_str} ({container_percent:.0f}%)"
            )

        # Try to drop page cache when container memory is elevated (>70%)
        # Page cache from downloaded files consumes cgroup memory and can trigger OOM
        cache_dropped = False
        if limit_mb > 0 and container_percent >= 70:
            pre_drop = container_mb
            cache_dropped = _drop_page_cache(logger)
            if cache_dropped:
                # Re-read container memory after dropping cache
                container_mb, _ = _get_container_memory_mb()
                dropped_mb = pre_drop - container_mb
                container_percent = (
                    (container_mb / limit_mb * 100) if limit_mb > 0 else 0
                )
                logger.info(
                    f"[MEMORY MID-TASK] Dropped {dropped_mb:.0f}MB page cache, "
                    f"container now {container_mb:.0f}MB ({container_percent:.0f}%)"
                )

        # Check container memory and request restart if still critical after cache drop
        if limit_mb > 0 and container_percent >= _CONTAINER_RESTART_PERCENT:
            logger.critical(
                f"[MEMORY MID-TASK] CONTAINER CRITICAL - "
                f"{container_mb:.0f}/{limit_mb:.0f}MB ({container_percent:.0f}%). "
                f"Requesting main process restart to prevent OOM kill."
            )
            _request_main_process_shutdown(logger)
    except Exception:
        pass  # Don't let memory checks break downloads


class BitrateException(Exception):
    pass


class SpotdlDownloadError(Exception):
    """Raised when spotdl fails to download a song."""

    def __init__(self, message: str, spotdl_errors: list | None = None):
        super().__init__(message)
        self.spotdl_errors = spotdl_errors or []


class PremiumExpiredException(Exception):
    """Raised when premium status expires during download operation."""

    pass


class PlaylistSyncError(Exception):
    """Raised for non-retryable playlist sync errors (429, 401, 404).

    These errors should fail fast without retrying - the next scheduled sync
    will attempt the operation again. This prevents wasting API quota on
    operations that are likely to fail repeatedly.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class YouTubeRateLimitError(Exception):
    """Raised when YouTube rate-limits download requests.

    This error signals that the download task should release its lock and
    reschedule itself for later. YouTube rate limits are typically long
    (hours), so holding resources while waiting is wasteful.
    """

    def __init__(self, message: str, retry_after_seconds: int = 1800):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _is_fail_fast_error(exception: Exception) -> tuple[bool, int | None]:
    """Check if an exception should trigger fail-fast behavior (no retries).

    Fail-fast errors are:
    - 429 (Rate Limited): Retrying immediately won't help
    - 401 (Unauthorized): Token issues won't resolve with retries
    - 404 (Not Found): Resource doesn't exist, retries won't help

    Args:
        exception: The exception to check

    Returns:
        Tuple of (is_fail_fast, status_code)
    """
    err_str = str(exception).lower()

    # Check for rate limiting (429)
    if "429" in err_str or "rate limit" in err_str or "too many requests" in err_str:
        return True, 429

    # Check for authentication errors (401)
    if (
        "401" in err_str
        or "unauthorized" in err_str
        or "access token expired" in err_str
    ):
        return True, 401

    # Check for not found errors (404)
    if "404" in err_str or "not found" in err_str or "max retries" in err_str.lower():
        return True, 404

    return False, None


# Minimum acceptable bitrate for downloaded songs (in kbps)
# Songs below this threshold will be re-downloaded for quality upgrade
MIN_ACCEPTABLE_BITRATE_KBPS = 192


def _get_songs_needing_download(
    track_gids: list[str],
    logger: logging.Logger,
    check_file_exists: bool = True,
    min_bitrate: int = MIN_ACCEPTABLE_BITRATE_KBPS,
) -> tuple[set[str], dict[str, str]]:
    """
    Batch-query songs that need downloading from a list of track GIDs.

    A song needs downloading if ANY of these conditions are true:
    1. Not in database at all (new song)
    2. In database but downloaded=False
    3. In database, downloaded=True, but file doesn't exist (missing file)
    4. In database, downloaded=True, but bitrate < min_bitrate (quality upgrade)

    Args:
        track_gids: List of Spotify track GIDs to check
        logger: Logger for debug output
        check_file_exists: Whether to verify files exist on disk (can be slow for large sets)
        min_bitrate: Minimum acceptable bitrate in kbps (default 192)

    Returns:
        Tuple of:
        - Set of GIDs that need downloading
        - Dict mapping GID -> reason (for logging)
    """
    if not track_gids:
        return set(), {}

    needs_download: set[str] = set()
    reasons: dict[str, str] = {}

    # Query all songs with these GIDs in one batch
    existing_songs = Song.objects.filter(gid__in=track_gids).select_related(
        "file_path_ref"
    )
    existing_by_gid = {song.gid: song for song in existing_songs}

    for gid in track_gids:
        if gid not in existing_by_gid:
            # Case 1: New song not in database
            needs_download.add(gid)
            reasons[gid] = "new"
            continue

        song = existing_by_gid[gid]

        if not song.downloaded:
            # Case 2: In database but not downloaded
            needs_download.add(gid)
            reasons[gid] = "not_downloaded"
            continue

        # Song is marked as downloaded - check quality and file existence
        if song.bitrate > 0 and song.bitrate < min_bitrate:
            # Case 4: Quality upgrade needed
            needs_download.add(gid)
            reasons[gid] = f"low_bitrate_{song.bitrate}"
            continue

        if check_file_exists and song.file_path_ref:
            file_path = Path(song.file_path_ref.path)
            if not file_path.exists():
                # Case 3: File missing from disk
                needs_download.add(gid)
                reasons[gid] = "missing_file"
                logger.debug(
                    f"Song '{song.name}' marked downloaded but file missing: {file_path}"
                )
                continue

    return needs_download, reasons


# Apply monkeypatches to Spotdl for compatibility
# See spotdl_override module for more information
Spotdl.__init__ = spotdl_override.__init__
SpotdlDownloader.download_song = spotdl_override.download_song
SpotdlDownloader.download_multiple_songs = spotdl_override.download_multiple_songs


def generate_spotdl_settings(config: Config) -> Any:
    spotify_settings, downloader_settings, _ = create_settings(Namespace(config=False))

    # OAuth tokens are now fetched directly in spotdl_override.py during initialization
    # Remove auth_token from settings as it's no longer needed
    if "auth_token" in spotify_settings:
        del spotify_settings["auth_token"]

    if config.spotify_user_auth_enabled:
        # Config enabled - enable user auth for initial setup
        spotify_settings["user_auth"] = True
        spotify_settings["headless"] = True

    del spotify_settings["max_retries"]
    del spotify_settings["use_cache_file"]
    spotify_settings["downloader_settings"] = downloader_settings

    spotify_settings["downloader_settings"]["log_level"] = config.spotdl_log_level

    for key in DEFAULT_DOWNLOAD_SETTINGS.keys():
        if key in spotify_settings:
            spotify_settings[key] = DEFAULT_DOWNLOAD_SETTINGS[key]

    for key in DEFAULT_DOWNLOAD_SETTINGS.keys():
        if key in spotify_settings["downloader_settings"]:
            spotify_settings["downloader_settings"][key] = DEFAULT_DOWNLOAD_SETTINGS[
                key
            ]

    # Use YouTube cookies for audio downloads
    if config.youtube_cookies_location:
        spotify_settings["downloader_settings"][
            "cookie_file"
        ] = config.youtube_cookies_location

    if config.po_token:
        spotify_settings["downloader_settings"][
            "yt_dlp_args"
        ] = f'--extractor-args "youtube:player_client=web_music,default;po_token=web_music+{config.po_token}"'

    return spotify_settings


def initiate_logger(app_log_level: str, spotdl_log_level: str) -> logging.Logger:
    logging.basicConfig(
        format="[%(levelname)-8s %(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(app_log_level)
    # Initialize spotdl's internal loggers with separate (typically quieter) log level
    init_logging(spotdl_log_level)

    return logger


class SpotdlWrapper:
    def __init__(self, config: Config):
        # Store config for potential reinitialization
        self._config = config

        app_log_level = config.log_level or "INFO"
        spotdl_log_level = config.spotdl_log_level or "INFO"
        self.logger = initiate_logger(app_log_level, spotdl_log_level)
        self.logger.info(f"SpotdlWrapper Version: {__version__}")

        spotdl_settings = generate_spotdl_settings(config)

        # Ensure we have a valid event loop and reuse an existing set loop when present
        try:
            # Prefer the currently running loop when available
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; try to reuse a previously set loop without emitting deprecation warnings
            try:
                import warnings

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    loop = asyncio.get_event_loop_policy().get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except Exception:
                # No valid loop exists; create and set a fresh one for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        # Pass the event loop to Spotdl initialization
        spotdl_settings["loop"] = loop
        self.spotdl = Spotdl(**spotdl_settings)

        # Initialize dual Spotify clients for separate rate limit buckets
        # SpotDL's SpotifyClient is the primary client (gets OAuth from spotdl_override)
        self.spotipy_client = SpotifyClient()

        # Public client uses Client Credentials flow (separate rate limit bucket)
        from .spotipy_tasks import PublicSpotifyClient

        self.public_spotipy_client = PublicSpotifyClient()

        # Pass both clients to Downloader - routes operations to appropriate client
        # SpotDL's SpotifyClient is the Spotipy client itself (not a wrapper)
        self.downloader = Downloader(
            self.spotipy_client, public_client=self.public_spotipy_client.sp
        )

        # Initialize premium detector for quality validation
        self.premium_detector = PremiumDetector(
            cookies_file=config.youtube_cookies_location, po_token=config.po_token
        )
        try:
            self.premium_status = self.premium_detector.detect_premium_status()
        except Exception as e:
            self.logger.warning(f"Premium detection failed during initialization: {e}")
            # Create a default free status if detection fails
            self.premium_status = PremiumStatus(
                is_premium=False,
                confidence=0.0,
                detection_method="initialization_failed",
            )

        # Verify premium access at startup to catch expired credentials early
        try:
            has_access, message, _ = (
                self.premium_detector.verify_premium_access_at_startup()
            )
            if has_access:
                self.logger.info(f"✓ Premium access verified: {message}")
            else:
                self.logger.warning(f"⚠ Premium access verification failed: {message}")
                # Update premium status based on startup verification
                if not has_access:
                    self.premium_status = PremiumStatus(
                        is_premium=False,
                        confidence=0.9,
                        detection_method="startup_verification_failed",
                        error_message=message,
                    )
        except Exception as e:
            self.logger.warning(f"Startup premium verification failed: {e}")

        self.logger.debug("Completed SpotdlWrapper Initialization")

    def refresh_spotify_client(self) -> bool:
        """
        Reset the SpotifyClient singleton and reinitialize with current OAuth credentials.

        Called reactively when a 401 error indicates token expiration.

        Returns:
            bool: True if refresh was successful, False otherwise
        """
        try:
            from django.conf import settings as django_settings

            from downloader.spotify_auth_helper import get_spotify_oauth_credentials

            self.logger.info("Attempting to refresh Spotify OAuth token...")

            # Force refresh - we got a 401 so the token is invalid regardless of expiration time
            oauth_creds = get_spotify_oauth_credentials(force_refresh=True)

            if not oauth_creds:
                self.logger.error(
                    "Failed to refresh Spotify OAuth token - no credentials available"
                )
                return False

            # Reset the SpotifyClient singleton to force re-initialization
            SpotifyClient._instance = None
            self.logger.info("Reset SpotifyClient singleton")

            # Get client credentials from Django settings
            client_id = getattr(django_settings, "SPOTIPY_CLIENT_ID", "")
            client_secret = getattr(django_settings, "SPOTIPY_CLIENT_SECRET", "")

            # Reinitialize with the fresh token and client credentials
            SpotifyClient.init(
                client_id=client_id,
                client_secret=client_secret,
                user_auth=False,
                auth_token=oauth_creds["access_token"],
            )

            # Update our reference to the new client instance
            # SpotDL's SpotifyClient is the Spotipy client itself
            self.spotipy_client = SpotifyClient()
            self.downloader.spotipy_client = self.spotipy_client

            self.logger.info("✓ Successfully refreshed Spotify OAuth token")
            return True

        except Exception as e:
            self.logger.error(f"Failed to refresh Spotify OAuth token: {e}")
            return False

    def reinitialize_spotdl(self) -> bool:
        """
        Reinitialize the Spotdl instance to release yt-dlp native memory.

        yt-dlp has known memory leaks (https://github.com/yt-dlp/yt-dlp/issues/1949)
        that can't be freed by Python's garbage collector. The only reliable way
        to release this memory is to destroy the entire Spotdl instance and create
        a new one.

        This method:
        1. Logs memory before reinitialization
        2. Destroys the old Spotdl instance
        3. Forces garbage collection and malloc_trim
        4. Creates a fresh Spotdl instance
        5. Logs memory after to verify release

        Returns:
            bool: True if reinitialization succeeded, False otherwise
        """
        import gc
        import os

        import psutil

        try:
            process = psutil.Process(os.getpid())
            memory_before = process.memory_info().rss / 1024 / 1024

            self.logger.info(
                f"[SPOTDL REINIT] Starting reinitialization... "
                f"Memory before: {memory_before:.0f}MB"
            )

            # Destroy the old spotdl instance
            old_spotdl = self.spotdl
            self.spotdl = None

            # Try to close/cleanup the old downloader if it has cleanup methods
            if hasattr(old_spotdl, "downloader"):
                if hasattr(old_spotdl.downloader, "audio_providers"):
                    # Clear audio providers which hold YoutubeDL instances
                    old_spotdl.downloader.audio_providers.clear()
                if hasattr(old_spotdl.downloader, "progress_handler"):
                    old_spotdl.downloader.progress_handler = None

            # Delete references
            del old_spotdl

            # Force garbage collection
            gc.collect()

            # Release memory to OS
            _malloc_trim()

            memory_after_gc = process.memory_info().rss / 1024 / 1024

            # Reinitialize spotdl with stored config
            spotdl_settings = generate_spotdl_settings(self._config)

            # Get or create event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    import warnings

                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        loop = asyncio.get_event_loop_policy().get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Event loop is closed")
                except Exception:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

            spotdl_settings["loop"] = loop
            self.spotdl = Spotdl(**spotdl_settings)

            memory_after = process.memory_info().rss / 1024 / 1024
            released = memory_before - memory_after_gc
            new_overhead = memory_after - memory_after_gc

            self.logger.info(
                f"[SPOTDL REINIT] ✓ Complete! "
                f"Released: {released:.0f}MB, "
                f"New instance: +{new_overhead:.0f}MB, "
                f"Net: {memory_before - memory_after:.0f}MB freed "
                f"({memory_before:.0f}MB → {memory_after:.0f}MB)"
            )

            return True

        except Exception as e:
            self.logger.error(f"[SPOTDL REINIT] Failed to reinitialize: {e}")
            # Try to recover by creating a new instance anyway
            try:
                spotdl_settings = generate_spotdl_settings(self._config)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                spotdl_settings["loop"] = loop
                self.spotdl = Spotdl(**spotdl_settings)
                self.logger.info("[SPOTDL REINIT] Recovery successful")
                return True
            except Exception as recovery_error:
                self.logger.error(f"[SPOTDL REINIT] Recovery failed: {recovery_error}")
                return False

    def _update_playlist_status_on_error(self, url: str) -> None:
        """
        Update playlist status when a 404 error indicates the playlist is inaccessible.

        This handles both Spotify-generated playlists (Discover Weekly, Daily Mix, etc.)
        which cannot be accessed via the API, and regular playlists that have been
        deleted or made private.

        Args:
            url: The Spotify playlist URL or URI that failed
        """
        from library_manager.models import PlaylistStatus
        from library_manager.validators import is_spotify_owned_playlist

        # Extract playlist ID from URL
        if "spotify:playlist:" in url:
            playlist_id = url.split("spotify:playlist:", 1)[1]
        else:
            playlist_id = url.split("/playlist/", 1)[1].split("?")[0]

        # Determine the appropriate status based on playlist type
        if is_spotify_owned_playlist(playlist_id):
            new_status = PlaylistStatus.SPOTIFY_API_RESTRICTED
            status_message = (
                "Spotify-generated playlists (Discover Weekly, Daily Mix, etc.) "
                "cannot be accessed via the API"
            )
            self.logger.warning(
                f"Playlist is a Spotify-generated playlist (API restricted): {playlist_id}"
            )
        else:
            new_status = PlaylistStatus.NOT_FOUND
            status_message = (
                "Playlist not found - may have been deleted or made private"
            )
            self.logger.warning(
                f"Playlist appears to be inaccessible (private or deleted): {playlist_id}"
            )

        # Try to find and update the playlist status
        try:
            playlist = TrackedPlaylist.objects.get(url__contains=playlist_id)
            # Update status if playlist is active OR disabled by user
            # (user-disabled playlists should still get updated to reflect
            # the actual reason they can't be synced)
            if playlist.status in (
                PlaylistStatus.ACTIVE,
                PlaylistStatus.DISABLED_BY_USER,
            ):
                self.logger.warning(
                    f"Setting playlist status to {new_status}: {playlist.name} ({playlist_id})"
                )
                playlist.status = new_status
                playlist.status_message = status_message
                playlist.save()
        except TrackedPlaylist.DoesNotExist:
            self.logger.warning(f"Playlist not found in database: {playlist_id}")

    def execute(self, config: Config, task_progress_callback=None) -> int:
        download_queue = []
        download_queue_urls: list[str] = []
        download_queue_metadata: dict[str, dict] = (
            {}
        )  # URL -> metadata (e.g., snapshot_id)
        error_count = 0

        # Check if all URLs are tracks - if so, use batch API for efficiency
        # This is common for retry_failed_songs which passes 100 track URIs
        all_tracks = all(
            "track" in url or url.startswith("spotify:track:") for url in config.urls
        )
        if all_tracks and len(config.urls) > 1:
            self.logger.info(
                f"Batch fetching {len(config.urls)} tracks using optimized API"
            )
            try:
                queues, metadata = self.downloader.get_download_queue_batch(config.urls)
                # Filter out empty queues (failed fetches)
                for url, queue in zip(config.urls, queues):
                    if queue:
                        download_queue.append(queue)
                        download_queue_urls.append(url)
                        if url in metadata:
                            download_queue_metadata[url] = metadata[url]
                self.logger.info(
                    f"Batch fetch complete: {len(download_queue)} tracks retrieved "
                    f"({len(config.urls) - len(download_queue)} failed/missing)"
                )
            except SpotifyException as spotify_exception:
                is_fail_fast, status_code = _is_fail_fast_error(spotify_exception)

                # For 429 (rate limit), fail fast - don't fall back to individual fetching
                if status_code == 429:
                    self.logger.error(
                        f"Rate limited (429) during batch fetch - failing fast. "
                        f"Will retry on next sync. Error: {spotify_exception}"
                    )
                    raise PlaylistSyncError(
                        f"Rate limited during batch fetch: {spotify_exception}",
                        status_code=429,
                    )

                # For 401, try token refresh once
                if status_code == 401:
                    self.logger.warning(
                        "Spotify OAuth token expired during batch fetch, attempting refresh..."
                    )
                    if self.refresh_spotify_client():
                        try:
                            queues, metadata = self.downloader.get_download_queue_batch(
                                config.urls
                            )
                            for url, queue in zip(config.urls, queues):
                                if queue:
                                    download_queue.append(queue)
                                    download_queue_urls.append(url)
                                    if url in metadata:
                                        download_queue_metadata[url] = metadata[url]
                        except Exception as retry_exception:
                            # Token refresh worked but retry still failed - fail fast
                            self.logger.error(
                                f"Batch fetch failed after token refresh (failing fast): {retry_exception}"
                            )
                            raise PlaylistSyncError(
                                f"Batch fetch failed after token refresh: {retry_exception}",
                                status_code=401,
                            )
                    else:
                        # Token refresh failed - fail fast
                        self.logger.error(
                            "Failed to refresh Spotify OAuth token - failing fast"
                        )
                        raise PlaylistSyncError(
                            "Token refresh failed during batch fetch",
                            status_code=401,
                        )
                else:
                    self.logger.error(f"Batch fetch failed: {spotify_exception}")
                    # Fall back to individual fetching for non-fail-fast errors
            except PlaylistSyncError:
                # Re-raise fail-fast errors
                raise
            except Exception as e:
                self.logger.error(f"Batch fetch failed: {e}")
                # Fall back to individual fetching below

        if config.artist_to_fetch is not None:
            # Do not track the artist if it's mass downloaded
            try:
                albums = self.downloader.get_artist_albums(config.artist_to_fetch)
                self.logger.info(
                    f"Fetched latest {len(albums)} album(s) for this artist"
                )
                return 0
            except SpotifyException as spotify_exception:
                # Check if this is a 401 Unauthorized error (expired token)
                if (
                    "401" in str(spotify_exception)
                    or "access token expired" in str(spotify_exception).lower()
                ):
                    self.logger.warning(
                        "Spotify OAuth token expired while fetching artist albums, attempting refresh..."
                    )

                    # Try to refresh the token
                    if self.refresh_spotify_client():
                        # Retry the operation once with the refreshed token
                        try:
                            albums = self.downloader.get_artist_albums(
                                config.artist_to_fetch
                            )
                            self.logger.info(
                                f"Fetched latest {len(albums)} album(s) for this artist after token refresh"
                            )
                            return 0
                        except Exception as retry_exception:
                            self.logger.error(
                                f"Failed to fetch artist albums after token refresh: {retry_exception}"
                            )
                            raise
                    else:
                        self.logger.error("Failed to refresh Spotify OAuth token")
                        raise
                else:
                    # Not a 401 error, re-raise
                    raise
        # Skip individual URL fetching if we already batch-fetched all tracks
        urls_already_fetched = set(download_queue_urls)

        for url_index, url in enumerate(config.urls, start=1):
            # Skip URLs already processed by batch fetch
            if url in urls_already_fetched:
                continue

            current_url = f"URL {url_index}/{len(config.urls)}"
            try:
                # For playlists, check snapshot_id first to avoid unnecessary API calls
                if (
                    url.startswith("spotify:playlist:")
                    or url.startswith("https://open.spotify.com/playlist")
                    or "/playlist/" in url
                ):
                    playlist_id = (
                        url.split("spotify:playlist:", 1)[1]
                        if "spotify:playlist:" in url
                        else url.split("/playlist/", 1)[1].split("?")[0]
                    )

                    # Try to find the tracked playlist and check snapshot_id
                    normalized_url = utils.normalize_spotify_url(url)
                    try:
                        tracked_playlist = TrackedPlaylist.objects.get(
                            url=normalized_url
                        )
                        if (
                            tracked_playlist.snapshot_id
                            and tracked_playlist.last_synced_at
                            and not config.force_playlist_resync
                        ):
                            # Check if playlist has changed using lightweight API call
                            current_snapshot = self.downloader.get_playlist_snapshot_id(
                                playlist_id
                            )
                            if current_snapshot == tracked_playlist.snapshot_id:
                                self.logger.info(
                                    f"({current_url}) Playlist unchanged (snapshot_id match), skipping"
                                )
                                continue
                            else:
                                self.logger.info(
                                    f"({current_url}) Playlist changed (snapshot_id mismatch), syncing"
                                )
                    except TrackedPlaylist.DoesNotExist:
                        pass  # Not a tracked playlist, proceed with normal flow

                self.logger.info(f'({current_url}) Checking "{url}"')
                # Use include_metadata=True to get snapshot_id for playlists
                result = self.downloader.get_download_queue(
                    url=url, include_metadata=True
                )
                if isinstance(result, tuple):
                    queue_items, metadata = result
                    download_queue.append(queue_items)
                    download_queue_metadata[url] = metadata
                else:
                    download_queue.append(result)
                download_queue_urls.append(url)
            except SpotifyException as spotify_exception:
                is_fail_fast, status_code = _is_fail_fast_error(spotify_exception)
                is_playlist_url = (
                    url.startswith("spotify:playlist:")
                    or url.startswith("https://open.spotify.com/playlist")
                    or "/playlist/" in url
                )

                # For 429 (rate limit) on playlist sync, fail fast entirely
                if status_code == 429 and is_playlist_url:
                    self.logger.error(
                        f"({current_url}) Rate limited (429) during playlist sync - "
                        f"failing fast. Will retry on next sync."
                    )
                    self._update_playlist_status_on_error(url)
                    raise PlaylistSyncError(
                        f"Rate limited during playlist sync: {spotify_exception}",
                        status_code=429,
                    )

                # For 401, try token refresh once (this often works)
                if status_code == 401:
                    self.logger.warning(
                        f"({current_url}) Spotify OAuth token expired, attempting refresh..."
                    )

                    if self.refresh_spotify_client():
                        try:
                            self.logger.info(
                                f'({current_url}) Retrying after token refresh: "{url}"'
                            )
                            result = self.downloader.get_download_queue(
                                url=url, include_metadata=True
                            )
                            if isinstance(result, tuple):
                                queue_items, metadata = result
                                download_queue.append(queue_items)
                                download_queue_metadata[url] = metadata
                            else:
                                download_queue.append(result)
                            download_queue_urls.append(url)
                            continue  # Success, move to next URL
                        except Exception as retry_exception:
                            # Token refresh worked but retry still failed - fail fast for playlists
                            error_count += 1
                            self.logger.error(
                                f"({current_url}) Failed after token refresh (failing fast): {retry_exception}"
                            )
                            if is_playlist_url:
                                raise PlaylistSyncError(
                                    f"Playlist sync failed after token refresh: {retry_exception}",
                                    status_code=401,
                                )
                            if config.print_exceptions:
                                self.logger.error(traceback.format_exc())
                            continue
                    else:
                        # Token refresh failed - fail fast for playlists
                        error_count += 1
                        self.logger.error(
                            f"({current_url}) Failed to refresh Spotify OAuth token"
                        )
                        if is_playlist_url:
                            raise PlaylistSyncError(
                                "Token refresh failed during playlist sync",
                                status_code=401,
                            )
                        continue

                # For 404 errors on playlists, update status and continue (not fatal)
                if status_code == 404 and is_playlist_url:
                    error_count += 1
                    self.logger.warning(
                        f"({current_url}) Playlist not found (404) - marking as inaccessible"
                    )
                    self._update_playlist_status_on_error(url)
                    continue  # Move to next URL, don't fail entire sync

                # Other errors - log and continue
                error_count += 1
                self.logger.error(f'({current_url}) Failed to check "{url}"')
                self.logger.error(f"Spotify exception: {spotify_exception}")
                if config.print_exceptions:
                    self.logger.error(traceback.format_exc())

            except PlaylistSyncError:
                # Re-raise fail-fast errors
                raise

            except Exception as general_exception:
                is_fail_fast, status_code = _is_fail_fast_error(general_exception)
                is_playlist_url = (
                    url.startswith("spotify:playlist:")
                    or url.startswith("https://open.spotify.com/playlist")
                    or "/playlist/" in url
                )

                # For 429 on playlist sync, fail fast
                if status_code == 429 and is_playlist_url:
                    self.logger.error(
                        f"({current_url}) Rate limited (429) - failing fast. "
                        f"Will retry on next sync."
                    )
                    self._update_playlist_status_on_error(url)
                    raise PlaylistSyncError(
                        f"Rate limited: {general_exception}",
                        status_code=429,
                    )

                # For 404 on playlists, mark as inaccessible
                if status_code == 404 and is_playlist_url:
                    error_count += 1
                    self.logger.warning(
                        f"({current_url}) Playlist not found - marking as inaccessible"
                    )
                    self._update_playlist_status_on_error(url)
                    continue

                error_count += 1
                self.logger.error(f'({current_url}) Failed to check "{url}"')
                self.logger.error(f"exception: {general_exception}")
                if config.print_exceptions:
                    self.logger.error(traceback.format_exc())

                # Handle (gracefully) songs that no longer exist (at all) with Spotify
                if (
                    "too many 404 error responses" in str(general_exception)
                    or "Track no longer exists" in str(general_exception)
                ) and (
                    url.startswith("spotify:track:")
                    or url.startswith("https://open.spotify.com/track")
                ):
                    # Extract Spotify ID from URL
                    track_uri = (
                        url.split("spotify:track:", 1)[1]
                        if "spotify:track:" in url
                        else url.split("/track/", 1)[1].split("?")[0]
                    )
                    song_gid = extract_spotify_id_from_uri(track_uri)

                    if not song_gid:
                        self.logger.warning(
                            f"Failed to extract Spotify ID from URL: {url}"
                        )
                        continue

                    try:
                        db_song = Song.objects.get(gid=song_gid)
                        db_song.increment_failed_count(FailureReason.SPOTIFY_NOT_FOUND)
                        self.logger.info(
                            f"Song '{db_song.name}' not found on Spotify, "
                            f"next retry in {db_song.get_retry_backoff_days()} days"
                        )
                    except Song.DoesNotExist:
                        self.logger.warning(f"Song not found in database: {song_gid}")
                        continue

        # Note: Metadata enrichment is now done per-queue-item after filtering
        # This ensures we only fetch metadata for tracks we'll actually download

        if len(download_queue) > 0:
            one_queue_increment = (1 / len(download_queue)) * 1000

        for queue_item_index, queue_item in enumerate(download_queue, start=1):
            download_queue_url = download_queue_urls[queue_item_index - 1]
            download_queue_item = DownloadHistory.objects.get_or_create(
                url=download_queue_url,
                completed_at=None,
                defaults={
                    "url": download_queue_url,
                },
            )[0]

            try:
                # Normalize URL to match database format (strips ?si= parameters and converts to URI format)
                normalized_url = utils.normalize_spotify_url(download_queue_url)
                tracked_playlist = TrackedPlaylist.objects.get(url=normalized_url)

                if config.force_playlist_resync:
                    tracked_playlist.last_synced_at = None
                    tracked_playlist.save()
            except TrackedPlaylist.DoesNotExist:
                tracked_playlist = None

            # Filter out local files first
            from library_manager.validators import is_local_track

            queue_item = [track for track in queue_item if not is_local_track(track)]

            # Batch-check which songs actually need downloading
            # This handles: new songs, not downloaded, missing files, low bitrate
            track_gids = [
                gid
                for track in queue_item
                if (gid := extract_spotify_id_from_uri(track["id"]))
            ]

            gids_needing_download, download_reasons = _get_songs_needing_download(
                track_gids,
                self.logger,
                check_file_exists=True,
                min_bitrate=MIN_ACCEPTABLE_BITRATE_KBPS,
            )

            # Filter queue_item to only tracks that need downloading
            original_count = len(queue_item)
            queue_item = [
                track
                for track in queue_item
                if extract_spotify_id_from_uri(track["id"]) in gids_needing_download
            ]

            # Log filtering results
            skipped_count = original_count - len(queue_item)
            if skipped_count > 0:
                self.logger.info(
                    f"Filtered {original_count} tracks → {len(queue_item)} to download "
                    f"({skipped_count} already downloaded with valid files)"
                )

            # Log reasons for downloads (summarized)
            if download_reasons:
                reason_counts: dict[str, int] = {}
                for reason in download_reasons.values():
                    base_reason = (
                        reason.split("_")[0]
                        if reason.startswith("low_bitrate")
                        else reason
                    )
                    reason_counts[base_reason] = reason_counts.get(base_reason, 0) + 1
                reason_summary = ", ".join(
                    f"{count} {reason}" for reason, count in reason_counts.items()
                )
                self.logger.debug(f"Download reasons: {reason_summary}")

            if not queue_item:
                self.logger.info(
                    f"All tracks already downloaded for URL {queue_item_index}/{len(download_queue)}, skipping"
                )
                # Update last_synced_at and snapshot_id even when skipping
                if tracked_playlist is not None:
                    tracked_playlist.last_synced_at = Now()
                    url_metadata = download_queue_metadata.get(download_queue_url, {})
                    if url_metadata.get("snapshot_id"):
                        tracked_playlist.snapshot_id = url_metadata["snapshot_id"]
                    tracked_playlist.save()
                continue

            # Enrich metadata only for tracks we're actually downloading
            # This batch-fetches album and artist data efficiently
            self.logger.info(
                f"Enriching metadata for {len(queue_item)} tracks (batch fetching genres, etc.)"
            )
            try:
                self.downloader.enrich_tracks_metadata(queue_item)
            except Exception as e:
                self.logger.warning(
                    f"Failed to enrich track metadata (will continue without): {e}"
                )

            main_queue_progress = ((queue_item_index - 1) / len(download_queue)) * 1000

            for track_index, track in enumerate(queue_item, start=1):
                # No need for per-track filtering - already done above

                current_track = f"Track {track_index}/{len(queue_item)} from URL {queue_item_index}/{len(download_queue)}"
                download_queue_item.progress = round(
                    track_index / len(queue_item) * 1000, 1
                )
                download_queue_item.save()

                # Periodic task progress updates every 5 songs
                if task_progress_callback and track_index % 5 == 0:
                    progress_pct = (
                        main_queue_progress
                        + (track_index / len(queue_item)) * one_queue_increment
                    ) / 10
                    task_progress_callback(
                        progress_pct,
                        f"Downloaded {track_index}/{len(queue_item)} songs from queue {queue_item_index}/{len(download_queue)}",
                    )

                # Periodic memory release to prevent OOM during long downloads
                _check_and_release_memory(self.logger, track_index)

                # Periodically reinitialize spotdl to release yt-dlp native memory leaks
                # This is the only reliable way to free memory held by yt-dlp's C libraries
                if (
                    track_index > 0
                    and track_index % _SPOTDL_REINIT_INTERVAL_TRACKS == 0
                ):
                    self.reinitialize_spotdl()

                # Initialize db_song to None so exception handlers can check if it was created
                db_song = None
                try:
                    self.logger.info(f'({current_track}) Downloading "{track["name"]}"')
                    primary_artist = track["artists"][0]
                    other_artists = track["artists"][1:]
                    song = self.downloader.get_song_core_info(track)

                    # Extract base62 Spotify ID from URI/URL (avoids hex encoding)
                    primary_artist_gid = extract_spotify_id_from_uri(
                        primary_artist["id"]
                    )
                    if not primary_artist_gid:
                        raise ValueError(
                            f"Invalid Spotify artist ID format: {primary_artist['id']}"
                        )

                    # Get or create artist
                    try:
                        db_artist = Artist.objects.get(gid=primary_artist_gid)
                    except Artist.DoesNotExist:
                        primary_artist_defaults = {
                            "name": primary_artist["name"],
                            "gid": primary_artist_gid,
                        }
                        if config.track_artists:
                            primary_artist_defaults["tracked"] = True
                        db_artist = Artist.objects.create(**primary_artist_defaults)

                    db_extra_artists = [db_artist]

                    for artist in other_artists:
                        # Extract base62 Spotify ID from URI/URL
                        artist_gid = extract_spotify_id_from_uri(artist["id"])
                        if not artist_gid:
                            raise ValueError(
                                f"Invalid Spotify artist ID format: {artist['id']}"
                            )

                        # Get or create artist
                        try:
                            db_extra_artist = Artist.objects.get(gid=artist_gid)
                        except Artist.DoesNotExist:
                            db_extra_artist = Artist.objects.create(
                                name=artist["name"],
                                gid=artist_gid,
                            )

                        db_extra_artists.append(db_extra_artist)

                    # Get or create song
                    song_gid = song["song_gid"]
                    song_isrc = song.get("isrc")
                    try:
                        db_song = Song.objects.get(gid=song_gid)
                        # Update existing song (including ISRC if we have it now)
                        db_song.primary_artist = db_artist
                        db_song.name = song["song_name"]
                        if song_isrc and not db_song.isrc:
                            db_song.isrc = song_isrc
                        db_song.save()
                    except Song.DoesNotExist:
                        db_song = Song.objects.create(
                            gid=song_gid,
                            primary_artist=db_artist,
                            name=song["song_name"],
                            isrc=song_isrc,
                        )

                    for artist in db_extra_artists:
                        ContributingArtist.objects.get_or_create(
                            artist=artist, song=db_song
                        )

                    # Use song_from_track_data() to avoid 3 extra API calls per song
                    # that SpotdlSong.from_url() would make (track, artist, album)
                    spotdl_song = song_from_track_data(track)
                    song_success, output_path = self.spotdl.download(spotdl_song)

                    # Log memory after each download to catch spikes during yt-dlp processing
                    try:
                        import os

                        import psutil

                        rss_mb = (
                            psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
                        )
                        container_mb, limit_mb = _get_container_memory_mb()
                        limit_str = f"/{limit_mb:.0f}" if limit_mb > 0 else ""
                        self.logger.info(
                            f"[MEMORY POST-DOWNLOAD] Track {track_index}: "
                            f"worker={rss_mb:.0f}MB, container={container_mb:.0f}{limit_str}MB"
                        )
                    except Exception:
                        pass

                    if song_success is None or output_path is None:
                        self.logger.debug(song_success)
                        self.logger.debug(f"output_path: {output_path}")
                        # Capture spotdl error details for debugging
                        spotdl_errors = list(self.spotdl.downloader.errors)
                        raise SpotdlDownloadError(
                            "Failed to download correctly", spotdl_errors=spotdl_errors
                        )

                    # Validate the song is in the correct audio bitrate using premium detection
                    spotify_url = track["external_urls"]["spotify"]

                    # Get actual available qualities for this specific song
                    available_qualities = (
                        self.premium_detector.get_song_available_qualities(spotify_url)
                    )
                    max_available = (
                        max([q[0] for q in available_qualities])
                        if available_qualities
                        else 128
                    )

                    # Set expectation based on premium status AND song availability
                    if (
                        self.premium_status.is_premium
                        and self.premium_status.confidence > 0.7
                    ):
                        expected_bitrate = min(
                            255, max_available
                        )  # Premium: up to 256kbps or song max
                    else:
                        expected_bitrate = min(
                            127, max_available
                        )  # Free: up to 128kbps or song max

                    media_info = MediaInfo.parse(output_path)
                    audio_track = None
                    bit_rate = 0
                    for media_track in media_info.tracks:
                        if media_track.track_type == "Audio":
                            audio_track = media_track
                            bit_rate = audio_track.bit_rate / 1000
                            break

                    if audio_track is not None and bit_rate > 0:
                        db_song.mark_downloaded(
                            bitrate=int(bit_rate), file_path=output_path
                        )
                    if audio_track is None or bit_rate < expected_bitrate:
                        # pathlib.Path.unlink(output_path)
                        if audio_track is None:
                            raise BitrateException(
                                f"File was downloaded successfully, but no audio track existed | output_path: {output_path}"
                            )
                        # Check if this indicates premium expiry
                        # Uses 240kbps threshold (default) and re-validates account status if low
                        is_expired, expiry_reason = (
                            self.premium_detector.is_premium_expired(
                                downloaded_bitrate=int(bit_rate),
                            )
                        )

                        error_msg = (
                            f"File was downloaded successfully but not in the correct bitrate "
                            f"({bit_rate} found, but {expected_bitrate} is minimum expected) | "
                            f"output_path: {output_path}"
                        )

                        if is_expired:
                            error_message = (
                                f"🚨 PREMIUM EXPIRED: {expiry_reason} | "
                                f"Available qualities for this song: {available_qualities} | "
                                f"Your YouTube Music cookies or po_token have expired. "
                                f"Please refresh your authentication to continue downloading."
                            )
                            self.logger.error(error_message)
                            # Abort the entire task - don't continue with degraded quality
                            raise PremiumExpiredException(error_message)
                        else:
                            self.logger.error(error_msg)
                            self.logger.info(
                                f"Premium status: {self.premium_status.is_premium} "
                                f"(confidence: {self.premium_status.confidence}) | "
                                f"Available qualities: {available_qualities}"
                            )
                except PremiumExpiredException:
                    # Re-raise to abort the entire download task
                    raise
                except DownloadTimeoutError as timeout_error:
                    # YouTube rate limit detected - fail fast and reschedule
                    # Don't increment failed_count as this is a transient issue
                    self.logger.error(
                        f"({current_track}) YouTube rate limit detected: {timeout_error}"
                    )
                    self.logger.warning(
                        "Aborting download task to release resources. "
                        "Task will be rescheduled automatically."
                    )
                    # Wrap in YouTubeRateLimitError with retry suggestion
                    raise YouTubeRateLimitError(
                        f"YouTube rate limit hit at track {track_index}/{len(queue_item)}. "
                        f"Task should be rescheduled.",
                        retry_after_seconds=1800,  # 30 minutes
                    ) from timeout_error
                except SpotifyRateLimitError as rate_limit_error:
                    # Spotify rate limit exceeded our max wait threshold
                    self.logger.error(
                        f"({current_track}) Spotify rate limit exceeded threshold: "
                        f"{rate_limit_error}"
                    )
                    self.logger.warning(
                        "Aborting download task to release resources. "
                        "Task will be rescheduled automatically."
                    )
                    # Re-raise wrapped in YouTubeRateLimitError for consistent handling
                    # (despite the name, this handles both YouTube and Spotify rate limits)
                    raise YouTubeRateLimitError(
                        f"Spotify rate limit ({rate_limit_error.retry_after_seconds}s) "
                        f"hit at track {track_index}/{len(queue_item)}. "
                        f"Task should be rescheduled.",
                        retry_after_seconds=min(
                            rate_limit_error.retry_after_seconds, 3600
                        ),  # Cap at 1 hour
                    ) from rate_limit_error
                except SpotifyException as spotify_exception:
                    # Check if this is a 401 Unauthorized error (expired token)
                    if (
                        "401" in str(spotify_exception)
                        or "access token expired" in str(spotify_exception).lower()
                    ):
                        self.logger.warning(
                            f"({current_track}) Spotify OAuth token expired during download, attempting refresh..."
                        )

                        # Try to refresh the token
                        if self.refresh_spotify_client():
                            # Retry the download once with the refreshed token
                            try:
                                self.logger.info(
                                    f'({current_track}) Retrying download after token refresh: "{track["name"]}"'
                                )
                                # Reuse the spotdl_song we already created
                                song_success, output_path = self.spotdl.download(
                                    spotdl_song
                                )
                                if song_success is None or output_path is None:
                                    spotdl_errors = list(self.spotdl.downloader.errors)
                                    raise SpotdlDownloadError(
                                        "Failed to download correctly after token refresh",
                                        spotdl_errors=spotdl_errors,
                                    )

                                # Success! Continue with bitrate validation...
                                # (Reuse the same validation logic)
                                media_info = MediaInfo.parse(output_path)
                                audio_track = None
                                bit_rate = 0
                                for media_track in media_info.tracks:
                                    if media_track.track_type == "Audio":
                                        audio_track = media_track
                                        bit_rate = audio_track.bit_rate / 1000
                                        break

                                if audio_track is not None and bit_rate > 0:
                                    db_song.mark_downloaded(
                                        bitrate=int(bit_rate), file_path=output_path
                                    )
                                    self.logger.info(
                                        f"({current_track}) Successfully downloaded after token refresh"
                                    )
                                continue  # Success, move to next track

                            except Exception as retry_exception:
                                # Retry failed - log but DON'T increment failed_count
                                # This allows automatic retry later
                                error_count += 1
                                self.logger.error(
                                    f"({current_track}) Failed to download after token refresh: {retry_exception}"
                                )
                                self.logger.warning(
                                    f"({current_track}) Not incrementing failed_count - will retry later"
                                )
                                if config.print_exceptions:
                                    self.logger.error(traceback.format_exc())
                                continue  # Move to next track
                        else:
                            # Token refresh failed - log but DON'T increment failed_count
                            error_count += 1
                            self.logger.error(
                                f"({current_track}) Failed to refresh Spotify OAuth token during download"
                            )
                            self.logger.warning(
                                f"({current_track}) Not incrementing failed_count - will retry later"
                            )
                            continue  # Move to next track

                    # Not a 401 error, treat as general exception
                    error_count += 1
                    self.logger.error(
                        f"({current_track}) Spotify exception during download: {spotify_exception}"
                    )
                    if config.print_exceptions:
                        self.logger.error(traceback.format_exc())
                    # Increment failed_count for non-401 Spotify errors (if song was created)
                    if db_song is not None:
                        # Categorize the Spotify error
                        err_str = str(spotify_exception).lower()
                        if "404" in err_str or "not found" in err_str:
                            reason = FailureReason.SPOTIFY_NOT_FOUND
                        else:
                            reason = FailureReason.TEMPORARY_ERROR
                        db_song.increment_failed_count(reason)
                except SpotdlDownloadError as spotdl_download_exception:
                    error_count += 1
                    song_name = db_song.name if db_song is not None else track["name"]
                    self.logger.error(
                        f'({current_track}) Failed to download "{song_name}"'
                    )
                    self.logger.error(f"Exception: {spotdl_download_exception}")
                    self.logger.error(
                        "This track is possibly not available in your region"
                    )
                    # Log detailed spotdl errors at debug level for troubleshooting
                    if spotdl_download_exception.spotdl_errors:
                        for err in spotdl_download_exception.spotdl_errors:
                            self.logger.debug(f"Spotdl error detail: {err}")
                    # Don't infinitely retry missing songs (if song was created)
                    if db_song is not None:
                        # SpotDL errors typically mean YTM couldn't find a match
                        # Check the error message to categorize
                        err_str = str(spotdl_download_exception).lower()
                        spotdl_err_strs = [
                            str(e).lower()
                            for e in (spotdl_download_exception.spotdl_errors or [])
                        ]
                        all_errors = err_str + " ".join(spotdl_err_strs)

                        if (
                            "no results found" in all_errors
                            or "no suitable match" in all_errors
                            or "couldn't find" in all_errors
                        ):
                            reason = FailureReason.YTM_NO_MATCH
                        else:
                            reason = FailureReason.TEMPORARY_ERROR
                        db_song.increment_failed_count(reason)
                except Exception as general_exception:
                    error_count += 1
                    song_name = db_song.name if db_song is not None else track["name"]
                    self.logger.error(
                        f'({current_track}) Failed to download "{song_name}"'
                    )
                    self.logger.error(f"General Exception: {general_exception}")
                    if db_song is not None:
                        # General exceptions are typically temporary
                        db_song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
                    if config.print_exceptions:
                        self.logger.error(traceback.format_exc())
                finally:
                    # Clear any errors from the persisted object, otherwise it will continue printing old failures
                    if len(self.spotdl.downloader.errors) > 0:
                        self.spotdl.downloader.errors.clear()

                    # Rate limiting: add delay between downloads to avoid hitting API limits
                    # This runs after every track attempt (success or failure)
                    if _DOWNLOAD_DELAY_SECONDS > 0:
                        time.sleep(_DOWNLOAD_DELAY_SECONDS)

                if track_index == len(queue_item):
                    download_queue_item.completed_at = Now()
                    download_queue_item.save()

                    # Final progress update for this queue
                    if task_progress_callback:
                        progress_pct = (main_queue_progress + one_queue_increment) / 10
                        task_progress_callback(
                            progress_pct,
                            f"Completed queue {queue_item_index}/{len(download_queue)} ({len(queue_item)} songs)",
                        )

                    if download_queue_url.startswith("spotify:album:"):
                        try:
                            album = Album.objects.get(spotify_uri=download_queue_url)
                        except Album.DoesNotExist:
                            album = None
                        if album is not None:
                            album.downloaded = True
                            album.save()
                        else:
                            self.logger.warning(
                                "Spotify album downloaded but was not expected and could not be created"
                            )

            # Update last_synced_at and snapshot_id after processing all tracks
            # This should happen regardless of whether tracks were skipped or downloaded
            if tracked_playlist is not None:
                tracked_playlist.last_synced_at = Now()
                # Update snapshot_id from the metadata if available
                url_metadata = download_queue_metadata.get(download_queue_url, {})
                if url_metadata.get("snapshot_id"):
                    tracked_playlist.snapshot_id = url_metadata["snapshot_id"]
                tracked_playlist.save()

        self.logger.info(f"Done ({error_count} error(s))")
        return error_count
