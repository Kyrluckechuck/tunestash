"""
YouTube Music download provider using yt-dlp.

Downloads audio from YouTube Music without requiring Spotify URIs.
Uses yt-dlp's Python API for search and download operations.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from pathlib import Path
from typing import Optional

from .base import (
    DownloadProvider,
    DownloadResult,
    ProviderCapabilities,
    ProviderType,
    QualityOption,
    QualityPreference,
    TrackMatch,
    calculate_match_confidence,
)

logger = logging.getLogger(__name__)

# Minimum confidence threshold for accepting a match
MIN_MATCH_CONFIDENCE = 0.6

# Duration tolerance for matching (10 seconds)
DURATION_TOLERANCE_MS = 10000

# Request timeout for yt-dlp operations
YTDLP_TIMEOUT = 60

YOUTUBE_CAPABILITIES = ProviderCapabilities(
    provider_type=ProviderType.REST_API,
    supports_search=True,
    supports_isrc_lookup=False,
    embeds_metadata=False,
    available_qualities=(
        QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=256,
            format="m4a",
            lossless=False,
        ),
    ),
    formats=("m4a",),
)


def _get_cookies_path() -> Optional[str]:
    """Get the YouTube cookies path (hardcoded, managed via UI)."""
    default_path = Path("/config/youtube_music_cookies.txt")
    if default_path.exists():
        return str(default_path)
    return None


def _build_ydl_opts(cookies_path: Optional[str] = None) -> dict:
    """Build base yt-dlp options."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": YTDLP_TIMEOUT,
        "retries": 2,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    return opts


class YouTubeMusicProvider(DownloadProvider):
    """Download provider using yt-dlp for YouTube Music."""

    def __init__(self) -> None:
        self._cookies_path = _get_cookies_path()

    @property
    def name(self) -> str:
        return "youtube"

    @property
    def display_name(self) -> str:
        return "YouTube Music"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return YOUTUBE_CAPABILITIES

    async def is_available(self) -> bool:
        """Check if yt-dlp is importable."""
        try:
            import yt_dlp  # noqa: F401

            return True
        except ImportError:
            logger.warning("yt-dlp is not installed")
            return False

    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """Search YouTube Music for a track."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self._search_track_sync,
                title=title,
                artist=artist,
                album=album,
                isrc=isrc,
                duration_ms=duration_ms,
            ),
        )

    def _search_track_sync(  # pylint: disable=too-many-return-statements
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """Synchronous search implementation."""
        import yt_dlp

        search_query = f"ytsearch1:{artist} - {title}"
        opts = _build_ydl_opts(self._cookies_path)
        opts["extract_flat"] = False
        opts["default_search"] = "ytsearch"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)

            if not info:
                return None

            # ytsearch returns entries list
            entries = info.get("entries", [info])
            entry = entries[0] if entries else None
            if not entry or not entry.get("id"):
                return None

            result_title = entry.get("title", "")
            result_artist = entry.get("uploader", entry.get("channel", ""))
            result_duration_ms = int(entry.get("duration", 0) * 1000)
            video_id = entry["id"]

            # Duration validation
            if duration_ms and result_duration_ms:
                duration_diff = abs(duration_ms - result_duration_ms)
                if duration_diff > DURATION_TOLERANCE_MS:
                    logger.debug(
                        f"[youtube] Duration mismatch for '{title}': "
                        f"expected {duration_ms}ms, got {result_duration_ms}ms "
                        f"(diff: {duration_diff}ms)"
                    )
                    return None

            confidence = calculate_match_confidence(
                search_title=title,
                search_artist=artist,
                result_title=result_title,
                result_artist=result_artist,
                search_duration_ms=duration_ms,
                result_duration_ms=result_duration_ms,
                duration_tolerance_ms=DURATION_TOLERANCE_MS,
            )

            if confidence < MIN_MATCH_CONFIDENCE:
                logger.debug(
                    f"[youtube] Low confidence ({confidence:.2f}) for "
                    f"'{artist} - {title}' -> '{result_artist} - {result_title}'"
                )
                return None

            return TrackMatch(
                provider="youtube",
                provider_track_id=video_id,
                title=result_title,
                artist=result_artist,
                album=album or "",
                duration_ms=result_duration_ms,
                confidence=confidence,
                cover_url=entry.get("thumbnail"),
            )

        except Exception as e:
            logger.error(f"[youtube] Search failed for '{artist} - {title}': {e}")
            return None

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """Download a track from YouTube."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self._download_track_sync,
                track_match=track_match,
                output_path=output_path,
                quality=quality,
            ),
        )

    def _download_track_sync(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """Synchronous download implementation."""
        import yt_dlp

        url = f"https://www.youtube.com/watch?v={track_match.provider_track_id}"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Output template without extension — yt-dlp adds it via post-processor
        output_template = str(output_path.with_suffix(""))

        opts = _build_ydl_opts(self._cookies_path)
        opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": output_template + ".%(ext)s",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                        "preferredquality": "256",
                    }
                ],
            }
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # Find the output file — yt-dlp may add .m4a extension
            final_path = output_path.with_suffix(".m4a")
            if not final_path.exists():
                # Check if file exists with original path
                if output_path.exists():
                    final_path = output_path
                else:
                    return DownloadResult(
                        success=False,
                        provider="youtube",
                        error="Downloaded file not found",
                    )

            return DownloadResult(
                success=True,
                provider="youtube",
                file_path=final_path,
                bitrate_kbps=256,
                format="m4a",
                duration_ms=track_match.duration_ms,
            )

        except Exception as e:
            logger.error(
                f"[youtube] Download failed for {track_match.provider_track_id}: {e}"
            )
            return DownloadResult(
                success=False,
                provider="youtube",
                error=str(e),
            )
