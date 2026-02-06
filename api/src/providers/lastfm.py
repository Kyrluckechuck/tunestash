"""Last.fm provider for external music lists."""

import logging
import time
from typing import Any, Optional

from django.conf import settings

import requests

from .base import ExternalListProvider, ExternalListResult, ExternalTrack

logger = logging.getLogger(__name__)

LASTFM_API_BASE = "https://ws.audioscrobbler.com/2.0/"


def _get_api_key() -> str:
    key = getattr(settings, "LASTFM_API_KEY", "") or ""
    if not key:
        raise ValueError(
            "Last.fm API key not configured. "
            "Set LASTFM_API_KEY in config/settings.yaml "
            "(free key from https://www.last.fm/api/account/create)"
        )
    return str(key)


def _check_rate_limit() -> None:
    """Check and respect API rate limit for Last.fm."""
    from library_manager.models import APIRateLimitState

    try:
        state, _ = APIRateLimitState.objects.get_or_create(
            api_name="lastfm",
            defaults={"max_requests_per_second": 5.0},
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


def _lastfm_request(params: dict[str, Any]) -> dict[str, Any]:
    """Make a rate-limited request to the Last.fm API."""
    _check_rate_limit()

    params.setdefault("api_key", _get_api_key())
    params["format"] = "json"

    resp = requests.get(LASTFM_API_BASE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise ValueError(
            f"Last.fm API error {data['error']}: {data.get('message', '')}"
        )

    return dict(data)


def _parse_lastfm_tracks(
    tracks_data: list[dict[str, Any]],
) -> list[ExternalTrack]:
    """Parse Last.fm track objects into ExternalTrack list."""
    result = []
    for track in tracks_data:
        artist_name = ""
        if isinstance(track.get("artist"), dict):
            artist_name = track["artist"].get("name", "") or track["artist"].get(
                "#text", ""
            )
        elif isinstance(track.get("artist"), str):
            artist_name = track["artist"]

        track_name = track.get("name", "")
        if not artist_name or not track_name:
            continue

        mbid = track.get("mbid") or None
        if mbid == "":
            mbid = None

        result.append(
            ExternalTrack(
                artist_name=artist_name.strip(),
                track_name=track_name.strip(),
                musicbrainz_id=mbid,
            )
        )
    return result


class LastFMProvider(ExternalListProvider):
    """Last.fm external list provider."""

    def validate_user(self, username: str) -> tuple[bool, Optional[str]]:
        try:
            data = _lastfm_request(
                {
                    "method": "user.getInfo",
                    "user": username,
                }
            )
            if "user" in data:
                return True, None
            return False, "User not found on Last.fm"
        except ValueError as e:
            error_msg = str(e)
            if "6:" in error_msg:
                return False, f"User '{username}' not found on Last.fm"
            return False, error_msg
        except requests.RequestException as e:
            return False, f"Last.fm API error: {e}"

    def fetch_tracks(
        self,
        username: str,
        list_type: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        page: int = 1,
        limit: int = 200,
    ) -> ExternalListResult:
        if list_type == "loved":
            return self._fetch_loved_tracks(username, page, limit)
        if list_type == "top":
            return self._fetch_top_tracks(username, period or "overall", page, limit)
        if list_type == "chart":
            return self._fetch_chart_tracks(list_identifier, page, limit)
        raise ValueError(f"Unsupported Last.fm list type: {list_type}")

    def _fetch_loved_tracks(
        self, username: str, page: int, limit: int
    ) -> ExternalListResult:
        data = _lastfm_request(
            {
                "method": "user.getLovedTracks",
                "user": username,
                "page": page,
                "limit": limit,
            }
        )

        loved = data.get("lovedtracks", {})
        tracks_data = loved.get("track", [])
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data]

        tracks = _parse_lastfm_tracks(tracks_data)
        total = int(loved.get("@attr", {}).get("total", len(tracks)))

        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_top_tracks(
        self, username: str, period: str, page: int, limit: int
    ) -> ExternalListResult:
        period_map = {
            "7d": "7day",
            "1m": "1month",
            "3m": "3month",
            "6m": "6month",
            "12m": "12month",
            "overall": "overall",
            # Also accept Last.fm native period names
            "7day": "7day",
            "1month": "1month",
            "3month": "3month",
            "6month": "6month",
            "12month": "12month",
        }
        api_period = period_map.get(period, "overall")

        data = _lastfm_request(
            {
                "method": "user.getTopTracks",
                "user": username,
                "period": api_period,
                "page": page,
                "limit": limit,
            }
        )

        top = data.get("toptracks", {})
        tracks_data = top.get("track", [])
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data]

        tracks = _parse_lastfm_tracks(tracks_data)
        total = int(top.get("@attr", {}).get("total", len(tracks)))

        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_chart_tracks(
        self, list_identifier: Optional[str], page: int, limit: int
    ) -> ExternalListResult:
        identifier = (list_identifier or "global").lower().strip()

        if identifier == "global":
            return self._fetch_global_chart(page, limit)
        if len(identifier) == 2 and identifier.isalpha():
            return self._fetch_geo_chart(identifier, page, limit)
        return self._fetch_tag_chart(identifier, page, limit)

    def _fetch_global_chart(self, page: int, limit: int) -> ExternalListResult:
        data = _lastfm_request(
            {
                "method": "chart.getTopTracks",
                "page": page,
                "limit": limit,
            }
        )

        chart = data.get("tracks", {})
        tracks_data = chart.get("track", [])
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data]

        tracks = _parse_lastfm_tracks(tracks_data)
        total = int(chart.get("@attr", {}).get("total", len(tracks)))

        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_geo_chart(
        self, country: str, page: int, limit: int
    ) -> ExternalListResult:
        data = _lastfm_request(
            {
                "method": "geo.getTopTracks",
                "country": country.upper(),
                "page": page,
                "limit": limit,
            }
        )

        chart = data.get("tracks", {})
        tracks_data = chart.get("track", [])
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data]

        tracks = _parse_lastfm_tracks(tracks_data)
        total = int(chart.get("@attr", {}).get("total", len(tracks)))

        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_tag_chart(self, tag: str, page: int, limit: int) -> ExternalListResult:
        data = _lastfm_request(
            {
                "method": "tag.getTopTracks",
                "tag": tag,
                "page": page,
                "limit": limit,
            }
        )

        chart = data.get("tracks", {})
        tracks_data = chart.get("track", [])
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data]

        tracks = _parse_lastfm_tracks(tracks_data)
        total = int(chart.get("@attr", {}).get("total", len(tracks)))

        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )
