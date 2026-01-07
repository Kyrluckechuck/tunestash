"""
Tidal download provider implementation.

This module implements the DownloadProvider interface for downloading audio
from Tidal via the squid.wtf API endpoints.
"""

from __future__ import annotations

import base64
import json
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
from .tidal_endpoints import TidalEndpoint, TidalEndpointManager

logger = logging.getLogger(__name__)

# Tidal quality levels mapped to our preferences
TIDAL_QUALITY_MAP = {
    QualityPreference.HIGH: "HIGH",  # 320kbps AAC
    QualityPreference.LOSSLESS: "LOSSLESS",  # 16-bit/44.1kHz FLAC
    QualityPreference.HI_RES: "HI_RES_LOSSLESS",  # 24-bit/96kHz+ FLAC
}

# Default capabilities for Tidal provider
TIDAL_CAPABILITIES = ProviderCapabilities(
    provider_type=ProviderType.REST_API,
    supports_search=True,
    supports_isrc_lookup=False,  # ISRC lookup doesn't work on this API
    embeds_metadata=False,  # Must embed metadata ourselves
    available_qualities=(
        QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=320,
            format="aac",
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
    formats=("aac", "flac"),
)

# Minimum confidence threshold for accepting a match
MIN_MATCH_CONFIDENCE = 0.7

# Request timeout in seconds
REQUEST_TIMEOUT = 30


class TidalProvider(DownloadProvider):
    """
    Download provider for Tidal via squid.wtf API.

    Uses community-pooled OAuth tokens to access Tidal's catalog.
    Supports search by title/artist and downloading in various qualities.
    """

    def __init__(
        self,
        endpoint_manager: Optional[TidalEndpointManager] = None,
        min_confidence: float = MIN_MATCH_CONFIDENCE,
    ) -> None:
        """
        Initialize the Tidal provider.

        Args:
            endpoint_manager: Manager for Tidal API endpoints. If None, creates default.
            min_confidence: Minimum confidence threshold for accepting matches.
        """
        self._endpoint_manager = endpoint_manager or TidalEndpointManager()
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        return "tidal"

    @property
    def display_name(self) -> str:
        return "Tidal"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return TIDAL_CAPABILITIES

    async def is_available(self) -> bool:
        """Check if Tidal API is available by getting a healthy endpoint."""
        endpoint = await self._endpoint_manager.get_endpoint()
        return endpoint is not None

    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """
        Search for a track on Tidal.

        Args:
            title: Track title
            artist: Artist name
            album: Album name (used for disambiguation)
            isrc: ISRC code (used for verification, not search)
            duration_ms: Expected duration (used for verification)

        Returns:
            Best matching track, or None if no confident match found.
        """
        # Get all healthy endpoints to try in sequence
        endpoints = await self._endpoint_manager.get_all_healthy_endpoints()
        if not endpoints:
            logger.warning("No healthy Tidal endpoints available for search")
            return None

        for endpoint in endpoints:
            try:
                results = await self._search_api(endpoint, title, artist)
                if not results:
                    # No results isn't an endpoint failure, just no matches
                    self._endpoint_manager.mark_endpoint_success(endpoint)
                    return None

                # Find best match
                best_match = self._find_best_match(
                    results,
                    title=title,
                    artist=artist,
                    isrc=isrc,
                    duration_ms=duration_ms,
                )

                self._endpoint_manager.mark_endpoint_success(endpoint)
                return best_match

            except requests.RequestException as e:
                logger.warning(f"Tidal search on {endpoint.name} failed: {e}")
                self._endpoint_manager.mark_endpoint_failure(endpoint)
                continue

        logger.error("All Tidal endpoints failed for search")
        return None

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """
        Download a track from Tidal.

        Args:
            track_match: The track to download (from search_track)
            output_path: Where to save the downloaded file
            quality: Preferred quality level

        Returns:
            DownloadResult with success status and file details.
        """
        # Get all healthy endpoints to try in sequence
        endpoints = await self._endpoint_manager.get_all_healthy_endpoints()
        if not endpoints:
            return DownloadResult(
                success=False,
                provider=self.name,
                error="No healthy Tidal endpoints available",
                error_retryable=True,
            )

        last_error: Optional[str] = None

        for endpoint in endpoints:
            try:
                # Get stream URL
                stream_info = await self._get_stream_info(
                    endpoint,
                    track_match.provider_track_id,
                    quality,
                )

                if not stream_info:
                    logger.warning(
                        f"Endpoint {endpoint.name} returned no stream info, trying next"
                    )
                    self._endpoint_manager.mark_endpoint_failure(endpoint)
                    continue

                # Download the audio
                download_url = stream_info.get("url")
                if not download_url:
                    logger.warning(
                        f"Endpoint {endpoint.name} returned no download URL, trying next"
                    )
                    self._endpoint_manager.mark_endpoint_failure(endpoint)
                    continue

                await self._download_file(download_url, output_path)

                self._endpoint_manager.mark_endpoint_success(endpoint)

                return DownloadResult(
                    success=True,
                    provider=self.name,
                    file_path=output_path,
                    bitrate_kbps=stream_info.get("bitrate_kbps"),
                    format=stream_info.get("format"),
                    duration_ms=track_match.duration_ms,
                    metadata_embedded=False,
                )

            except requests.RequestException as e:
                logger.warning(f"Tidal endpoint {endpoint.name} failed: {e}")
                self._endpoint_manager.mark_endpoint_failure(endpoint)
                last_error = str(e)
                continue

        # All endpoints failed
        logger.error(f"All Tidal endpoints failed. Last error: {last_error}")
        return DownloadResult(
            success=False,
            provider=self.name,
            error=last_error or "All Tidal endpoints failed",
            error_retryable=True,
        )

    async def get_track_info(self, provider_track_id: str) -> Optional[TrackMatch]:
        """Get detailed track information by ID."""
        endpoint = await self._endpoint_manager.get_endpoint()
        if not endpoint:
            return None

        try:
            info = await self._get_track_api(endpoint, provider_track_id)
            if info:
                self._endpoint_manager.mark_endpoint_success(endpoint)
                return self._parse_track_result(info, confidence=1.0)
            return None
        except requests.RequestException as e:
            logger.error(f"Tidal get_track_info failed: {e}")
            self._endpoint_manager.mark_endpoint_failure(endpoint)
            return None

    def _search_api_sync(
        self,
        endpoint: TidalEndpoint,
        title: str,
        artist: str,
    ) -> list[dict[str, Any]]:
        """Synchronous search API call."""
        query = f"{title} {artist}"
        url = f"{endpoint.base_url}/search/"
        # squid.wtf API uses 's' parameter for song search
        params = {"s": query}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        # Handle response structure: {"version": "X.X", "data": {"items": [...]}}
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if isinstance(data, dict) and "items" in data:
            return data["items"]

        return []

    async def _search_api(
        self,
        endpoint: TidalEndpoint,
        title: str,
        artist: str,
    ) -> list[dict[str, Any]]:
        """Search for tracks via the Tidal API."""
        return await sync_to_async(self._search_api_sync)(endpoint, title, artist)

    def _get_track_api_sync(
        self,
        endpoint: TidalEndpoint,
        track_id: str,
    ) -> Optional[dict[str, Any]]:
        """Synchronous track info API call."""
        url = f"{endpoint.base_url}/track/{track_id}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        # Handle nested response
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def _get_track_api(
        self,
        endpoint: TidalEndpoint,
        track_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get track info from the Tidal API."""
        return await sync_to_async(self._get_track_api_sync)(endpoint, track_id)

    def _get_stream_info_sync(
        self,
        endpoint: TidalEndpoint,
        track_id: str,
        quality: QualityPreference,
    ) -> Optional[dict[str, Any]]:
        """Synchronous stream info API call."""
        tidal_quality = TIDAL_QUALITY_MAP.get(quality, "HIGH")
        # squid.wtf API uses /track/?id={id}&quality={quality}
        url = f"{endpoint.base_url}/track/"
        params = {"id": track_id, "quality": tidal_quality}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        # Handle nested response
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        # Decode the manifest
        manifest_b64 = data.get("manifest")
        if not manifest_b64:
            logger.error("No manifest in stream response")
            return None

        try:
            manifest_str = base64.b64decode(manifest_b64).decode("utf-8")
            # Manifest might be JSON or a direct URL
            try:
                manifest = json.loads(manifest_str)
            except json.JSONDecodeError:
                # Direct URL
                manifest = {"urls": [manifest_str]}

            urls = manifest.get("urls", [])
            if not urls:
                logger.error("No URLs in manifest")
                return None

            # Determine actual format and bitrate
            mime_type = data.get("mimeType", "")
            audio_quality = data.get("audioQuality", "HIGH")

            if "flac" in mime_type.lower() or audio_quality in (
                "LOSSLESS",
                "HI_RES_LOSSLESS",
            ):
                fmt = "flac"
                bitrate = 1411 if audio_quality == "LOSSLESS" else 9216
            else:
                fmt = "aac"
                bitrate = 320

            return {
                "url": urls[0],
                "format": fmt,
                "bitrate_kbps": bitrate,
                "mime_type": mime_type,
            }

        except Exception as e:
            logger.error(f"Failed to decode manifest: {e}")
            return None

    async def _get_stream_info(
        self,
        endpoint: TidalEndpoint,
        track_id: str,
        quality: QualityPreference,
    ) -> Optional[dict[str, Any]]:
        """Get stream URL and info from Tidal."""
        return await sync_to_async(self._get_stream_info_sync)(
            endpoint, track_id, quality
        )

    def _download_file_sync(self, url: str, output_path: Path) -> None:
        """Synchronous file download."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    async def _download_file(self, url: str, output_path: Path) -> None:
        """Download a file to the given path."""
        await sync_to_async(self._download_file_sync)(url, output_path)

    def _find_best_match(
        self,
        results: list[dict[str, Any]],
        title: str,
        artist: str,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        """Find the best matching track from search results."""
        best: Optional[TrackMatch] = None
        best_confidence = 0.0

        for result in results:
            match = self._parse_track_result(result, confidence=0.0)
            if not match:
                continue

            # Calculate confidence
            confidence = calculate_match_confidence(
                search_title=title,
                search_artist=artist,
                result_title=match.title,
                result_artist=match.artist,
                search_isrc=isrc,
                result_isrc=match.isrc,
                search_duration_ms=duration_ms,
                result_duration_ms=match.duration_ms,
            )

            # Update confidence on the match
            match = TrackMatch(
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

            if confidence > best_confidence:
                best_confidence = confidence
                best = match

        # Only return if confidence meets threshold
        if best and best_confidence >= self._min_confidence:
            return best

        if best:
            logger.debug(
                f"Best match '{best.title}' by '{best.artist}' has confidence "
                f"{best_confidence:.2f} below threshold {self._min_confidence}"
            )
        return None

    def _parse_track_result(
        self,
        result: dict[str, Any],
        confidence: float,
    ) -> Optional[TrackMatch]:
        """Parse a track result from the API into a TrackMatch."""
        try:
            # Extract artist name(s)
            artists = result.get("artists", [])
            if artists and isinstance(artists[0], dict):
                artist_name = artists[0].get("name", "Unknown")
            else:
                artist_name = str(artists[0]) if artists else "Unknown"

            # Extract album info
            album = result.get("album", {})
            album_name = album.get("title", "") if isinstance(album, dict) else ""

            # Extract cover URL
            cover_url = None
            if isinstance(album, dict):
                cover = album.get("cover")
                if cover:
                    cover_path = cover.replace("-", "/")
                    cover_url = (
                        f"https://resources.tidal.com/images/{cover_path}/640x640.jpg"
                    )

            return TrackMatch(
                provider=self.name,
                provider_track_id=str(result.get("id", "")),
                title=result.get("title", ""),
                artist=artist_name,
                album=album_name,
                duration_ms=result.get("duration", 0) * 1000,  # API returns seconds
                isrc=result.get("isrc"),
                confidence=confidence,
                cover_url=cover_url,
                track_number=result.get("trackNumber"),
                total_tracks=(
                    album.get("numberOfTracks") if isinstance(album, dict) else None
                ),
                release_date=(
                    album.get("releaseDate") if isinstance(album, dict) else None
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to parse track result: {e}")
            return None
