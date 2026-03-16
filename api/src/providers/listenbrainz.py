"""ListenBrainz provider for external music lists."""

import logging
from typing import Any, Optional

from django.conf import settings

import requests

from .base import ExternalListProvider, ExternalListResult, ExternalTrack
from .rate_limit import check_api_rate_limit

logger = logging.getLogger(__name__)

LISTENBRAINZ_API_BASE = "https://api.listenbrainz.org"


def _get_user_token() -> Optional[str]:
    token = getattr(settings, "LISTENBRAINZ_USER_TOKEN", "") or ""
    return str(token) if token else None


def _lb_request(
    path: str,
    params: Optional[dict[str, Any]] = None,
    auth_required: bool = False,
) -> Any:
    """Make a rate-limited request to the ListenBrainz API."""
    check_api_rate_limit("listenbrainz", default_rate=2.0)

    headers: dict[str, str] = {}
    token = _get_user_token()
    if token:
        headers["Authorization"] = f"Token {token}"
    elif auth_required:
        raise ValueError(
            "ListenBrainz user token not configured. "
            "Set LISTENBRAINZ_USER_TOKEN in config/settings.yaml "
            "(get yours at https://listenbrainz.org/settings/)"
        )

    url = f"{LISTENBRAINZ_API_BASE}{path}"
    resp = requests.get(url, params=params or {}, headers=headers, timeout=30)
    resp.raise_for_status()
    if not resp.text.strip():
        return {}
    return resp.json()


def _extract_mbid_from_uri(uri: Optional[str]) -> Optional[str]:
    """Extract MusicBrainz recording MBID from a ListenBrainz URI.

    ListenBrainz uses URIs like:
    https://musicbrainz.org/recording/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    """
    if not uri:
        return None
    if "/recording/" in uri:
        parts = uri.rstrip("/").split("/")
        mbid = parts[-1]
        if len(mbid) == 36 and mbid.count("-") == 4:
            return mbid
    return None


class ListenBrainzProvider(ExternalListProvider):
    """ListenBrainz external list provider."""

    def validate_user(self, username: str) -> tuple[bool, Optional[str]]:
        try:
            _lb_request(f"/1/user/{username}/listen-count")
            return True, None
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return False, f"User '{username}' not found on ListenBrainz"
            return False, f"ListenBrainz API error: {e}"
        except requests.RequestException as e:
            return False, f"ListenBrainz API error: {e}"

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
            return self._fetch_top_tracks(username, period or "all_time", page, limit)
        if list_type == "playlist":
            if not list_identifier:
                raise ValueError("ListenBrainz playlist requires a playlist MBID")
            return self._fetch_playlist(list_identifier, page, limit)
        if list_type == "chart":
            return self._fetch_chart_tracks(page, limit)
        raise ValueError(f"Unsupported ListenBrainz list type: {list_type}")

    def _fetch_loved_tracks(
        self, username: str, page: int, limit: int
    ) -> ExternalListResult:
        offset = (page - 1) * limit
        data = _lb_request(
            f"/1/feedback/user/{username}/get-feedback",
            params={"score": 1, "offset": offset, "count": limit, "metadata": "true"},
        )

        feedback_list = data.get("feedback", [])
        tracks: list[ExternalTrack] = []
        for fb in feedback_list:
            meta = fb.get("track_metadata") or {}
            artist_name = meta.get("artist_name", "")
            track_name = meta.get("track_name", "")
            if not artist_name or not track_name:
                continue

            mbid = fb.get("recording_mbid") or None
            tracks.append(
                ExternalTrack(
                    artist_name=artist_name.strip(),
                    track_name=track_name.strip(),
                    musicbrainz_id=mbid,
                )
            )

        total = data.get("total_count", len(tracks))
        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_top_tracks(
        self, username: str, period: str, page: int, limit: int
    ) -> ExternalListResult:
        period_map = {
            "this_week": "this_week",
            "this_month": "this_month",
            "this_year": "this_year",
            "all_time": "all_time",
            "week": "this_week",
            "month": "this_month",
            "year": "this_year",
        }
        api_range = period_map.get(period, "all_time")
        offset = (page - 1) * limit

        data = _lb_request(
            f"/1/stats/user/{username}/recordings",
            params={"range": api_range, "offset": offset, "count": limit},
        )

        payload = data.get("payload", {})
        recordings = payload.get("recordings", [])
        tracks: list[ExternalTrack] = []
        for rec in recordings:
            artist_name = rec.get("artist_name", "")
            track_name = rec.get("track_name", "")
            if not artist_name or not track_name:
                continue

            mbid = rec.get("recording_mbid") or None
            tracks.append(
                ExternalTrack(
                    artist_name=artist_name.strip(),
                    track_name=track_name.strip(),
                    musicbrainz_id=mbid,
                )
            )

        total = payload.get("total_recording_count", len(tracks))
        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_playlist(
        self, playlist_mbid: str, page: int, limit: int
    ) -> ExternalListResult:
        data = _lb_request(f"/1/playlist/{playlist_mbid}")

        playlist = data.get("playlist", {})
        jspf_tracks = playlist.get("track", [])

        tracks: list[ExternalTrack] = []
        for t in jspf_tracks:
            track_name = t.get("title", "")
            artist_name = t.get("creator", "")
            if not track_name or not artist_name:
                continue

            mbid = _extract_mbid_from_uri(t.get("identifier"))
            tracks.append(
                ExternalTrack(
                    artist_name=artist_name.strip(),
                    track_name=track_name.strip(),
                    musicbrainz_id=mbid,
                )
            )

        # JSPF playlists return all tracks at once; apply pagination locally
        start = (page - 1) * limit
        page_tracks = tracks[start : start + limit]

        return ExternalListResult(
            tracks=page_tracks,
            total_count=len(tracks),
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_chart_tracks(self, page: int, limit: int) -> ExternalListResult:
        offset = (page - 1) * limit

        data = _lb_request(
            "/1/stats/sitewide/recordings",
            params={"range": "this_week", "offset": offset, "count": limit},
        )

        payload = data.get("payload", {})
        recordings = payload.get("recordings", [])
        tracks: list[ExternalTrack] = []
        for rec in recordings:
            artist_name = rec.get("artist_name", "")
            track_name = rec.get("track_name", "")
            if not artist_name or not track_name:
                continue

            mbid = rec.get("recording_mbid") or None
            tracks.append(
                ExternalTrack(
                    artist_name=artist_name.strip(),
                    track_name=track_name.strip(),
                    musicbrainz_id=mbid,
                )
            )

        total = payload.get("total_recording_count", len(tracks))
        return ExternalListResult(
            tracks=tracks,
            total_count=total,
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )
