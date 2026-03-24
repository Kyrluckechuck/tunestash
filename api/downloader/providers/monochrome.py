"""
Monochrome download provider implementation.

Monochrome is a community API frontend for Tidal's Hi-Fi CDN that provides
direct lossless FLAC streaming. Unlike TidalProvider (which uses squid.wtf
endpoints), Monochrome accesses the Hi-Fi tier with guaranteed lossless quality.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
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

MONOCHROME_CAPABILITIES = ProviderCapabilities(
    provider_type=ProviderType.REST_API,
    supports_search=True,
    supports_isrc_lookup=False,
    embeds_metadata=False,
    available_qualities=(
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
    formats=("flac",),
)

# Minimum confidence threshold for accepting a match
MIN_MATCH_CONFIDENCE = 0.7

REQUEST_TIMEOUT = 30

# How long to mark a failed endpoint as unavailable (seconds)
ENDPOINT_COOLDOWN_SECONDS = 300  # 5 minutes


@dataclass
class MonochromeEndpoint:
    """Tracks health state for a Monochrome API endpoint."""

    url: str
    last_failure: float = 0.0
    consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        if self.consecutive_failures == 0:
            return True
        return (time.time() - self.last_failure) > ENDPOINT_COOLDOWN_SECONDS

    def mark_success(self) -> None:
        self.consecutive_failures = 0

    def mark_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure = time.time()


@dataclass
class MonochromeEndpointManager:
    """Simple ordered endpoint management with cooldown tracking."""

    endpoints: list[MonochromeEndpoint] = field(default_factory=list)

    @classmethod
    def from_urls(cls, urls: list[str]) -> MonochromeEndpointManager:
        return cls(endpoints=[MonochromeEndpoint(url=u.rstrip("/")) for u in urls])

    def get_healthy_endpoints(self) -> list[MonochromeEndpoint]:
        return [ep for ep in self.endpoints if ep.is_healthy]


# Monochrome quality levels mapped to our preferences
MONOCHROME_QUALITY_MAP = {
    QualityPreference.HIGH: "LOSSLESS",
    QualityPreference.LOSSLESS: "LOSSLESS",
    QualityPreference.HI_RES: "HI_RES_LOSSLESS",
}


class MonochromeProvider(DownloadProvider):
    """
    Download provider for Tidal CDN via Monochrome API.

    Provides guaranteed lossless FLAC downloads from Tidal's CDN through
    community-hosted Monochrome instances. Supports search by title/artist
    and downloading in lossless or hi-res quality.
    """

    def __init__(
        self,
        api_urls: Optional[list[str]] = None,
        min_confidence: float = MIN_MATCH_CONFIDENCE,
    ) -> None:
        if api_urls is None:
            from django.conf import settings as django_settings

            api_urls = getattr(
                django_settings,
                "MONOCHROME_API_URLS",
                ["https://api.monochrome.tf"],
            )
        self._endpoint_manager = MonochromeEndpointManager.from_urls(api_urls)
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        return "monochrome"

    @property
    def display_name(self) -> str:
        return "Monochrome (Tidal CDN)"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return MONOCHROME_CAPABILITIES

    async def is_available(self) -> bool:
        endpoints = self._endpoint_manager.get_healthy_endpoints()
        if not endpoints:
            return False
        # Quick health check on first healthy endpoint
        try:
            result = await sync_to_async(self._health_check)(endpoints[0])
            return result
        except Exception:
            return False

    def _health_check(self, endpoint: MonochromeEndpoint) -> bool:
        try:
            response = requests.get(
                f"{endpoint.url}/search/",
                params={"s": "test"},
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException:
            endpoint.mark_failure()
            return False

    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        endpoints = self._endpoint_manager.get_healthy_endpoints()
        if not endpoints:
            logger.warning("No healthy Monochrome endpoints available for search")
            return None

        for endpoint in endpoints:
            try:
                results = await sync_to_async(self._search_api)(endpoint, title, artist)
                if not results:
                    endpoint.mark_success()
                    return None

                best_match = self._find_best_match(
                    results,
                    title=title,
                    artist=artist,
                    isrc=isrc,
                    duration_ms=duration_ms,
                )

                endpoint.mark_success()
                return best_match

            except requests.RequestException as e:
                logger.warning(f"Monochrome search on {endpoint.url} failed: {e}")
                endpoint.mark_failure()
                continue

        logger.error("All Monochrome endpoints failed for search")
        return None

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        endpoints = self._endpoint_manager.get_healthy_endpoints()
        if not endpoints:
            return DownloadResult(
                success=False,
                provider=self.name,
                error="No healthy Monochrome endpoints available",
                error_retryable=True,
            )

        last_error: Optional[str] = None

        for endpoint in endpoints:
            try:
                stream_info = await sync_to_async(self._get_stream_info)(
                    endpoint,
                    track_match.provider_track_id,
                    quality,
                )

                if not stream_info:
                    logger.warning(
                        f"Monochrome {endpoint.url} returned no stream info, trying next"
                    )
                    endpoint.mark_failure()
                    continue

                if not stream_info.get("url") and not stream_info.get("mpd_content"):
                    logger.warning(
                        f"Monochrome {endpoint.url} returned no download URL, trying next"
                    )
                    endpoint.mark_failure()
                    continue

                await sync_to_async(self._download_file)(stream_info, output_path)

                endpoint.mark_success()

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
                logger.warning(f"Monochrome endpoint {endpoint.url} failed: {e}")
                endpoint.mark_failure()
                last_error = str(e)
                continue

        logger.error(f"All Monochrome endpoints failed. Last error: {last_error}")
        return DownloadResult(
            success=False,
            provider=self.name,
            error=last_error or "All Monochrome endpoints failed",
            error_retryable=True,
        )

    def _search_api(
        self,
        endpoint: MonochromeEndpoint,
        title: str,
        artist: str,
    ) -> list[dict[str, Any]]:
        query = f"{title} {artist}"
        url = f"{endpoint.url}/search/"
        params = {"s": query}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if isinstance(data, dict) and "items" in data:
            return data["items"]

        return []

    def _get_stream_info(
        self,
        endpoint: MonochromeEndpoint,
        track_id: str,
        quality: QualityPreference,
    ) -> Optional[dict[str, Any]]:
        monochrome_quality = MONOCHROME_QUALITY_MAP.get(quality, "LOSSLESS")
        url = f"{endpoint.url}/track/"
        params = {"id": track_id, "quality": monochrome_quality}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        manifest_b64 = data.get("manifest")
        if not manifest_b64:
            logger.error("No manifest in Monochrome stream response")
            return None

        try:
            manifest_str = base64.b64decode(manifest_b64).decode("utf-8")
            audio_quality = data.get("audioQuality", "LOSSLESS")

            if audio_quality == "HI_RES_LOSSLESS":
                fmt = "flac"
                bitrate = 9216
            else:
                fmt = "flac"
                bitrate = 1411

            # DASH MPD manifest (XML) — requires ffmpeg to download
            if manifest_str.lstrip().startswith("<"):
                return {
                    "mpd_content": manifest_str,
                    "format": fmt,
                    "bitrate_kbps": bitrate,
                }

            # JSON manifest with direct CDN URLs
            try:
                manifest = json.loads(manifest_str)
            except json.JSONDecodeError:
                manifest = {"urls": [manifest_str]}

            urls = manifest.get("urls", [])
            if not urls:
                logger.error("No URLs in Monochrome manifest")
                return None

            return {
                "url": urls[0],
                "format": fmt,
                "bitrate_kbps": bitrate,
            }

        except Exception as e:
            logger.error(f"Failed to decode Monochrome manifest: {e}")
            return None

    def _download_file(self, url_or_info: dict, output_path: Path) -> None:
        """Download audio to output_path.

        Handles both direct URL downloads and DASH MPD manifests (via ffmpeg).
        """
        import subprocess
        import tempfile

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if "mpd_content" in url_or_info:
            # DASH MPD — write manifest to temp file, use ffmpeg to download
            with tempfile.NamedTemporaryFile(
                suffix=".mpd", mode="w", delete=False
            ) as mpd_file:
                mpd_file.write(url_or_info["mpd_content"])
                mpd_path = mpd_file.name

            try:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-protocol_whitelist",
                    "file,https,tls,tcp,http,crypto",
                    "-i",
                    mpd_path,
                    "-map",
                    "0:a:0",
                    "-c:a",
                    "copy",
                    str(output_path),
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    # Retry with re-encoding if stream copy fails
                    cmd[-1:] = ["-c:a", "flac", str(output_path)]
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300
                    )
                    if result.returncode != 0:
                        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
            finally:
                Path(mpd_path).unlink(missing_ok=True)
            return

        # Direct URL download
        url = url_or_info["url"]
        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def _find_best_match(
        self,
        results: list[dict[str, Any]],
        title: str,
        artist: str,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[TrackMatch]:
        best: Optional[TrackMatch] = None
        best_confidence = 0.0

        for result in results:
            match = self._parse_track_result(result, confidence=0.0)
            if not match:
                continue

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

        if best and best_confidence >= self._min_confidence:
            return best

        if best:
            logger.debug(
                f"Monochrome best match '{best.title}' by '{best.artist}' has "
                f"confidence {best_confidence:.2f} below threshold "
                f"{self._min_confidence}"
            )
        return None

    def _parse_track_result(
        self,
        result: dict[str, Any],
        confidence: float,
    ) -> Optional[TrackMatch]:
        try:
            artists = result.get("artists", [])
            if artists and isinstance(artists[0], dict):
                artist_name = artists[0].get("name", "Unknown")
            else:
                artist_name = str(artists[0]) if artists else "Unknown"

            album = result.get("album", {})
            album_name = album.get("title", "") if isinstance(album, dict) else ""

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
                duration_ms=result.get("duration", 0) * 1000,
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
            logger.warning(f"Failed to parse Monochrome track result: {e}")
            return None
