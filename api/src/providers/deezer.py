"""Deezer metadata provider.

Public API (no auth needed). Rate limit: ~50 req/s, we use 10/s conservatively.
"""

import logging
import time
from typing import Any, Optional, Union

import requests

from .metadata_base import (
    AlbumResult,
    ArtistResult,
    MetadataProvider,
    TrackResult,
)

logger = logging.getLogger(__name__)

DEEZER_API_BASE = "https://api.deezer.com"


def _check_rate_limit() -> None:
    """Respect Deezer API rate limit using the shared APIRateLimitState model."""
    from library_manager.models import APIRateLimitState

    try:
        state, _ = APIRateLimitState.objects.get_or_create(
            api_name="deezer",
            defaults={"max_requests_per_second": 10.0},
        )
        now_ts = time.time()
        window_start_ts = state.window_start.timestamp() if state.window_start else 0

        if now_ts - window_start_ts >= 1.0:
            from django.utils import timezone

            state.request_count = 1
            state.window_start = timezone.now()
            state.save(update_fields=["request_count", "window_start"])
        elif state.request_count >= state.max_requests_per_second:
            sleep_time = 1.0 - (now_ts - window_start_ts)
            if sleep_time > 0:
                time.sleep(sleep_time)
            from django.utils import timezone

            state.request_count = 1
            state.window_start = timezone.now()
            state.save(update_fields=["request_count", "window_start"])
        else:
            state.request_count += 1
            state.save(update_fields=["request_count"])
    except Exception:
        pass


def _deezer_request(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    """Make a rate-limited GET request to the Deezer API."""
    _check_rate_limit()

    url = f"{DEEZER_API_BASE}/{path.lstrip('/')}"
    resp = requests.get(url, params=params or {}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise ValueError(
            f"Deezer API error: {err.get('type', 'unknown')} - "
            f"{err.get('message', '')}"
        )

    return data


def _normalize_album_type(record_type: Optional[str]) -> Optional[str]:
    """Map Deezer record_type to our album_type values."""
    if not record_type:
        return None
    record_type = record_type.lower()
    if record_type == "ep":
        return "single"
    if record_type in ("album", "single", "compilation"):
        return record_type
    return record_type


def _parse_artist(data: dict[str, Any]) -> ArtistResult:
    return ArtistResult(
        name=data.get("name", ""),
        deezer_id=data.get("id"),
        image_url=data.get("picture_xl") or data.get("picture_big"),
    )


def _parse_album(data: dict[str, Any]) -> AlbumResult:
    artist_name = ""
    if isinstance(data.get("artist"), dict):
        artist_name = data["artist"].get("name", "")
    elif isinstance(data.get("artist"), str):
        artist_name = data["artist"]

    return AlbumResult(
        name=data.get("title", ""),
        artist_name=artist_name,
        deezer_id=data.get("id"),
        image_url=data.get("cover_xl") or data.get("cover_big"),
        total_tracks=data.get("nb_tracks", 0),
        release_date=data.get("release_date"),
        album_type=_normalize_album_type(data.get("record_type")),
    )


def _parse_track(data: dict[str, Any]) -> TrackResult:
    artist_name = ""
    if isinstance(data.get("artist"), dict):
        artist_name = data["artist"].get("name", "")
    elif isinstance(data.get("artist"), str):
        artist_name = data["artist"]

    album_name = None
    if isinstance(data.get("album"), dict):
        album_name = data["album"].get("title")

    duration_seconds = data.get("duration", 0)

    return TrackResult(
        name=data.get("title", ""),
        artist_name=artist_name,
        album_name=album_name,
        deezer_id=data.get("id"),
        isrc=data.get("isrc"),
        duration_ms=duration_seconds * 1000,
        track_number=data.get("track_position"),
        disc_number=data.get("disk_number"),
    )


class DeezerMetadataProvider(MetadataProvider):
    """Deezer metadata provider using their public API."""

    @property
    def name(self) -> str:
        return "Deezer"

    def search_artists(self, query: str, limit: int = 10) -> list[ArtistResult]:
        data = _deezer_request("search/artist", {"q": query, "limit": limit})
        return [_parse_artist(item) for item in data.get("data", [])]

    def search_albums(self, query: str, limit: int = 10) -> list[AlbumResult]:
        data = _deezer_request("search/album", {"q": query, "limit": limit})
        return [_parse_album(item) for item in data.get("data", [])]

    def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        data = _deezer_request("search/track", {"q": query, "limit": limit})
        return [_parse_track(item) for item in data.get("data", [])]

    def get_artist(self, provider_id: Union[int, str]) -> Optional[ArtistResult]:
        try:
            data = _deezer_request(f"artist/{provider_id}")
        except ValueError:
            return None
        if not isinstance(data, dict) or "id" not in data:
            return None
        return _parse_artist(data)

    def get_artist_albums(
        self, provider_id: Union[int, str], limit: int = 100
    ) -> list[AlbumResult]:
        albums: list[AlbumResult] = []
        url = f"artist/{provider_id}/albums"
        params: dict[str, Any] = {"limit": min(limit, 100)}

        while url and len(albums) < limit:
            data = _deezer_request(url, params)
            for item in data.get("data", []):
                albums.append(_parse_album(item))

            next_url = data.get("next")
            if next_url and len(albums) < limit:
                # Deezer returns full URL for pagination — extract path
                url = next_url.replace(DEEZER_API_BASE + "/", "")
                params = {}
            else:
                break

        return albums[:limit]

    def get_album(self, provider_id: Union[int, str]) -> Optional[AlbumResult]:
        try:
            data = _deezer_request(f"album/{provider_id}")
        except ValueError:
            return None
        if not isinstance(data, dict) or "id" not in data:
            return None
        return _parse_album(data)

    def get_album_tracks(self, provider_id: Union[int, str]) -> list[TrackResult]:
        data = _deezer_request(f"album/{provider_id}/tracks")
        return [_parse_track(item) for item in data.get("data", [])]

    def get_track(self, provider_id: Union[int, str]) -> Optional[TrackResult]:
        try:
            data = _deezer_request(f"track/{provider_id}")
        except ValueError:
            return None
        if not isinstance(data, dict) or "id" not in data:
            return None
        return _parse_track(data)

    def get_track_by_isrc(self, isrc: str) -> Optional[TrackResult]:
        try:
            data = _deezer_request(f"track/isrc:{isrc}")
        except ValueError:
            return None
        if not isinstance(data, dict) or "id" not in data:
            return None
        return _parse_track(data)
