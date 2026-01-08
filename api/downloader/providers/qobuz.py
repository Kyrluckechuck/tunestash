"""
Qobuz download provider implementation.

This module implements the DownloadProvider interface for downloading audio
from Qobuz via the squid.wtf API endpoints.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import requests
from asgiref.sync import sync_to_async

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

# Qobuz API base URL (via squid.wtf proxy)
QOBUZ_API_BASE = "https://qobuz.squid.wtf/api"

# Qobuz quality levels mapped to our preferences
# Quality 5 = MP3 320kbps
# Quality 6/7 = FLAC 16-bit 44.1kHz
# Quality 27 = FLAC 24-bit hi-res
#
# For HIGH quality: We download FLAC and convert to M4A/AAC for library consistency.
# Users can set qobuz_use_mp3=true to get MP3 directly instead.
QOBUZ_QUALITY_MAP = {
    QualityPreference.HIGH: 6,  # FLAC 16-bit (converted to M4A by fallback orchestrator)
    QualityPreference.LOSSLESS: 6,  # FLAC 16-bit
    QualityPreference.HI_RES: 27,  # FLAC 24-bit
}

# Alternative quality for direct MP3 (when qobuz_use_mp3=true)
QOBUZ_MP3_QUALITY = 5  # MP3 320kbps

# Default capabilities for Qobuz provider
QOBUZ_CAPABILITIES = ProviderCapabilities(
    provider_type=ProviderType.REST_API,
    supports_search=True,
    supports_isrc_lookup=False,
    embeds_metadata=False,
    available_qualities=(
        QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=320,
            format="mp3",
            lossless=False,
        ),
        QualityOption(
            quality=QualityPreference.LOSSLESS,
            bitrate_kbps=1411,
            format="flac",
            lossless=True,
            sample_rate=44100,
            bit_depth=16,
        ),
        QualityOption(
            quality=QualityPreference.HI_RES,
            bitrate_kbps=9216,
            format="flac",
            lossless=True,
            sample_rate=192000,
            bit_depth=24,
        ),
    ),
    formats=("mp3", "flac"),
)

# Minimum confidence threshold for accepting a match
MIN_MATCH_CONFIDENCE = 0.7

# Request timeout in seconds
REQUEST_TIMEOUT = 30


class QobuzProvider(DownloadProvider):
    """
    Download provider for Qobuz via squid.wtf API.

    Uses the community squid.wtf proxy to access Qobuz's catalog.
    Supports search by title/artist and downloading in various qualities.

    Unlike Tidal, Qobuz:
    - Returns albums from search, not tracks directly
    - Provides direct CDN URLs (no manifest decoding needed)
    - For HIGH quality: downloads FLAC and converts to M4A (or MP3 if use_mp3=True)
    """

    def __init__(
        self,
        min_confidence: float = MIN_MATCH_CONFIDENCE,
        use_mp3: bool = False,
    ) -> None:
        """
        Initialize the Qobuz provider.

        Args:
            min_confidence: Minimum confidence threshold for accepting matches.
            use_mp3: If True, download MP3 directly for HIGH quality instead of
                    FLAC (which gets converted to M4A). Default False.
        """
        self._min_confidence = min_confidence
        self._use_mp3 = use_mp3
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "qobuz"

    @property
    def display_name(self) -> str:
        return "Qobuz"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return QOBUZ_CAPABILITIES

    async def is_available(self) -> bool:
        """Check if Qobuz API is available by making a test search."""
        try:
            # Simple search to check API availability
            result = await self._search_music("test")
            return result is not None
        except Exception as e:
            logger.warning(f"Qobuz availability check failed: {e}")
            return False

    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """
        Search for a track on Qobuz.

        Qobuz search returns albums, so we:
        1. Search for albums matching artist + title
        2. Get album details to find tracks
        3. Find best matching track in the album

        Args:
            title: Track title
            artist: Artist name
            album: Album name (used for disambiguation)
            isrc: ISRC code (used for verification)
            duration_ms: Expected duration (used for verification)

        Returns:
            Best matching track, or None if no confident match found.
        """
        try:
            # Search for albums (Qobuz returns albums, not tracks)
            query = f"{artist} {title}"
            search_results = await self._search_music(query)

            if not search_results:
                logger.debug(f"[qobuz] No search results for '{query}'")
                return None

            data = search_results.get("data", search_results)
            albums = data.get("albums", {}).get("items", [])

            if not albums:
                logger.debug(f"[qobuz] No albums found for '{query}'")
                return None

            # Try to find track in the top albums
            for album_item in albums[:5]:  # Check top 5 albums
                album_id = album_item.get("id")
                if not album_id:
                    continue

                # Get album details with tracks
                album_info = await self._get_album(str(album_id))
                if not album_info:
                    continue

                album_data = album_info.get("data", album_info)
                tracks = album_data.get("tracks", {}).get("items", [])

                if not tracks:
                    continue

                # Find best matching track in this album
                match = self._find_best_track_match(
                    tracks=tracks,
                    album_data=album_data,
                    search_title=title,
                    search_artist=artist,
                    search_isrc=isrc,
                    search_duration_ms=duration_ms,
                )

                if match and match.confidence >= self._min_confidence:
                    return match

            logger.debug(
                f"[qobuz] No confident match found for "
                f"'{artist} - {title}' (threshold: {self._min_confidence})"
            )
            return None

        except Exception as e:
            logger.error(f"[qobuz] Search failed: {e}")
            return None

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """
        Download a track from Qobuz.

        Args:
            track_match: The track to download (from search_track)
            output_path: Where to save the downloaded file
            quality: Preferred quality level

        Returns:
            DownloadResult with success status and file details.
        """
        try:
            # Determine Qobuz quality level
            # For HIGH quality with use_mp3=True, get MP3 directly
            # Otherwise use the standard mapping (FLAC for HIGH, which gets converted)
            if quality == QualityPreference.HIGH and self._use_mp3:
                qobuz_quality = QOBUZ_MP3_QUALITY  # MP3 320kbps
            else:
                qobuz_quality = QOBUZ_QUALITY_MAP.get(quality, 6)

            download_info = await self._get_download_url(
                track_match.provider_track_id, qobuz_quality
            )

            if not download_info:
                return DownloadResult(
                    success=False,
                    provider=self.name,
                    error="Failed to get download URL",
                    error_retryable=True,
                )

            download_data = download_info.get("data", download_info)
            download_url = download_data.get("url")

            if not download_url:
                return DownloadResult(
                    success=False,
                    provider=self.name,
                    error="No download URL in response",
                    error_retryable=True,
                )

            # Download the file
            await self._download_file(download_url, output_path)

            # Determine format and bitrate based on quality
            if qobuz_quality == 5:
                fmt = "mp3"
                bitrate = 320
            else:
                fmt = "flac"
                bitrate = 1411 if qobuz_quality in (6, 7) else 9216

            return DownloadResult(
                success=True,
                provider=self.name,
                file_path=output_path,
                bitrate_kbps=bitrate,
                format=fmt,
                duration_ms=track_match.duration_ms,
                metadata_embedded=False,
            )

        except requests.RequestException as e:
            logger.error(f"[qobuz] Download failed: {e}")
            return DownloadResult(
                success=False,
                provider=self.name,
                error=str(e),
                error_retryable=True,
            )
        except Exception as e:
            logger.error(f"[qobuz] Download failed with exception: {e}")
            return DownloadResult(
                success=False,
                provider=self.name,
                error=str(e),
                error_retryable=False,
            )

    def _search_music_sync(self, query: str, offset: int = 0) -> Optional[dict]:
        """Synchronous search API call."""
        url = f"{QOBUZ_API_BASE}/get-music"
        params = {"q": query, "offset": offset}

        response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    async def _search_music(self, query: str, offset: int = 0) -> Optional[dict]:
        """Search for music on Qobuz."""
        return await sync_to_async(self._search_music_sync)(query, offset)

    def _get_album_sync(self, album_id: str) -> Optional[dict]:
        """Synchronous album info API call."""
        url = f"{QOBUZ_API_BASE}/get-album"
        params = {"album_id": album_id}

        response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    async def _get_album(self, album_id: str) -> Optional[dict]:
        """Get album information including tracks."""
        return await sync_to_async(self._get_album_sync)(album_id)

    def _get_download_url_sync(self, track_id: str, quality: int = 5) -> Optional[dict]:
        """Synchronous download URL API call."""
        url = f"{QOBUZ_API_BASE}/download-music"
        params = {"track_id": track_id, "quality": quality}

        response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    async def _get_download_url(
        self, track_id: str, quality: int = 5
    ) -> Optional[dict]:
        """Get download URL for a track."""
        return await sync_to_async(self._get_download_url_sync)(track_id, quality)

    def _download_file_sync(self, url: str, output_path: Path) -> None:
        """Synchronous file download."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response = self._session.get(url, stream=True, timeout=120)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    async def _download_file(self, url: str, output_path: Path) -> None:
        """Download a file to the given path."""
        await sync_to_async(self._download_file_sync)(url, output_path)

    def _find_best_track_match(
        self,
        tracks: list[dict[str, Any]],
        album_data: dict[str, Any],
        search_title: str,
        search_artist: str,
        search_isrc: Optional[str] = None,
        search_duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """Find the best matching track from album tracks."""
        best: Optional[TrackMatch] = None
        best_confidence = 0.0

        for track in tracks:
            match = self._parse_track_result(track, album_data, confidence=0.0)
            if not match:
                continue

            # Calculate confidence
            confidence = calculate_match_confidence(
                search_title=search_title,
                search_artist=search_artist,
                result_title=match.title,
                result_artist=match.artist,
                search_isrc=search_isrc,
                result_isrc=match.isrc,
                search_duration_ms=search_duration_ms,
                result_duration_ms=match.duration_ms,
            )

            if confidence > best_confidence:
                best_confidence = confidence
                best = TrackMatch(
                    provider=match.provider,
                    provider_track_id=match.provider_track_id,
                    title=match.title,
                    artist=match.artist,
                    album=match.album,
                    duration_ms=match.duration_ms,
                    isrc=match.isrc,
                    confidence=confidence,
                    cover_url=match.cover_url,
                    track_number=match.track_number,
                    total_tracks=match.total_tracks,
                    release_date=match.release_date,
                    extra_metadata=match.extra_metadata,
                )

        return best

    def _parse_track_result(
        self,
        track: dict[str, Any],
        album_data: dict[str, Any],
        confidence: float,
    ) -> Optional[TrackMatch]:
        """Parse a track result from the API into a TrackMatch."""
        try:
            # Extract artist name
            performer = track.get("performer", {})
            artist_name = performer.get("name", "") if performer else ""
            if not artist_name:
                # Fall back to album artist
                album_artist = album_data.get("artist", {})
                artist_name = album_artist.get("name", "Unknown")

            # Extract album info
            album_title = album_data.get("title", "")

            # Extract cover URL
            cover_url = None
            image = album_data.get("image", {})
            if image:
                cover_url = image.get("large") or image.get("small")

            # Duration in seconds from API, convert to ms
            duration_seconds = track.get("duration", 0)
            duration_ms = duration_seconds * 1000

            return TrackMatch(
                provider=self.name,
                provider_track_id=str(track.get("id", "")),
                title=track.get("title", ""),
                artist=artist_name,
                album=album_title,
                duration_ms=duration_ms,
                isrc=track.get("isrc"),
                confidence=confidence,
                cover_url=cover_url,
                track_number=track.get("track_number"),
                total_tracks=album_data.get("tracks_count"),
                release_date=album_data.get("release_date_original"),
            )
        except Exception as e:
            logger.warning(f"[qobuz] Failed to parse track result: {e}")
            return None
