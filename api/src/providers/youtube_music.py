"""YouTube Music provider for external music lists."""

import json
import logging
import re
import time
from http.cookiejar import MozillaCookieJar
from typing import Optional

from django.conf import settings

from ytmusicapi import YTMusic

from .base import ExternalListProvider, ExternalListResult, ExternalTrack

logger = logging.getLogger(__name__)

YOUTUBE_MUSIC_SENTINEL = "_youtube_music"

# Regex to strip YouTube-style video suffixes from track titles.
# Matches patterns like (Official Video), [Official Song], (Official HD Music Video),
# (Official Audio), (Official Lyric Video), (Official Visualizer), (4K), (HD), etc.
_YT_TITLE_JUNK_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:official\s+(?:(?:hd\s+)?(?:music\s+)?video|audio|lyric\s+video|visualizer|song)"
    r"|(?:hd|4k|lyrics?))"
    r"[\)\]]",
    re.IGNORECASE,
)


def _clean_youtube_title(title: str) -> str:
    """Strip YouTube-specific metadata from a track title."""
    # Remove everything after a pipe — typically unrelated metadata
    if "|" in title:
        title = title.split("|")[0]
    title = _YT_TITLE_JUNK_RE.sub("", title)
    return title.strip(" -")


def _get_cookies_path() -> Optional[str]:
    path = getattr(settings, "youtube_cookies_location", "") or ""
    return str(path) if path else None


def _check_rate_limit() -> None:
    """Check and respect API rate limit for YouTube Music."""
    from library_manager.models import APIRateLimitState

    try:
        state, _ = APIRateLimitState.objects.get_or_create(
            api_name="youtube_music",
            defaults={"max_requests_per_second": 2.0},
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


def _is_json_auth_file(file_path: str) -> bool:
    """Check if the file is a JSON authentication file (not Netscape cookies)."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content.startswith("# Netscape HTTP Cookie File"):
                return False
            json.loads(content)
            return True
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return False


def _convert_cookies_to_ytmusic_headers(cookies_file: str) -> Optional[str]:
    """Convert Netscape cookies to YTMusic-compatible headers."""
    try:
        from ytmusicapi.auth.browser import (
            get_authorization,
            sapisid_from_cookie,
            setup_browser,
        )

        cookie_jar = MozillaCookieJar(cookies_file)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        cookie_header = "; ".join([f"{c.name}={c.value}" for c in cookie_jar])

        if not cookie_header:
            return None

        headers_raw = (
            "Host: music.youtube.com\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) "
            "Gecko/20100101 Firefox/72.0\n"
            "Accept: */*\n"
            "Accept-Language: en-US,en;q=0.5\n"
            "Accept-Encoding: gzip, deflate, br\n"
            "Content-Type: application/json\n"
            "x-goog-authuser: 0\n"
            "x-origin: https://music.youtube.com\n"
            f"Cookie: {cookie_header}\n"
            "Connection: keep-alive"
        )

        auth_file_content = setup_browser(headers_raw=headers_raw)
        auth_data = json.loads(auth_file_content)

        try:
            sapisid = sapisid_from_cookie(cookie_header)
            auth_header = get_authorization(f"{sapisid} https://music.youtube.com")
            auth_data["authorization"] = auth_header
            return json.dumps(auth_data)
        except Exception:
            return auth_file_content

    except Exception as e:
        logger.warning("Failed to convert cookies to YTMusic headers: %s", e)
        return None


def _get_ytmusic_client(require_auth: bool = False) -> YTMusic:
    """Get a YTMusic client, optionally requiring authentication.

    Uses the same cookie auth pipeline as the download system.
    """
    cookies_file = _get_cookies_path()

    if cookies_file:
        # JSON auth file
        if _is_json_auth_file(cookies_file):
            return YTMusic(auth=cookies_file)

        # Netscape cookies — convert to ytmusicapi headers
        auth_content = _convert_cookies_to_ytmusic_headers(cookies_file)
        if auth_content:
            return YTMusic(auth=auth_content)

    if require_auth:
        raise ValueError(
            "YouTube Music authentication required but no valid cookies found. "
            "Ensure youtube_cookies_location is set in config/settings.yaml "
            "and the cookies file is valid."
        )

    return YTMusic()


class YouTubeMusicProvider(ExternalListProvider):
    """YouTube Music external list provider."""

    def validate_user(self, username: str) -> tuple[bool, Optional[str]]:
        if username != YOUTUBE_MUSIC_SENTINEL:
            return False, "YouTube Music uses cookie auth, not usernames"
        try:
            _get_ytmusic_client(require_auth=True)
            return True, None
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"YouTube Music auth error: {e}"

    def fetch_tracks(
        self,
        username: str,
        list_type: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        page: int = 1,
        limit: int = 200,
    ) -> ExternalListResult:
        if list_type == "playlist":
            if not list_identifier:
                raise ValueError("YouTube Music playlist requires a playlist ID")
            return self._fetch_playlist(list_identifier, page, limit)
        if list_type == "loved":
            return self._fetch_liked_tracks(page, limit)
        raise ValueError(f"Unsupported YouTube Music list type: {list_type}")

    def fetch_all_tracks(
        self,
        username: str,
        list_type: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        max_tracks: int = 5000,
    ) -> ExternalListResult:
        # ytmusicapi returns all tracks at once (no server-side pagination),
        # so we override to avoid unnecessary repeat calls.
        if list_type == "playlist":
            if not list_identifier:
                raise ValueError("YouTube Music playlist requires a playlist ID")
            return self._fetch_playlist(list_identifier, page=1, limit=max_tracks)
        if list_type == "loved":
            return self._fetch_liked_tracks(page=1, limit=max_tracks)
        raise ValueError(f"Unsupported YouTube Music list type: {list_type}")

    @staticmethod
    def _fetch_playlist_raw(client: YTMusic, playlist_id: str) -> list[ExternalTrack]:
        """Parse tracks from a playlist's raw browse response.

        Handles OLAK (album-style) playlists where get_playlist() crashes
        due to missing album metadata in ytmusicapi's parser.
        """
        try:
            body = {"browseId": "VL" + playlist_id}
            response = client._send_request(  # pylint: disable=protected-access
                "browse", body
            )

            two_col = response.get("contents", {}).get(
                "twoColumnBrowseResultsRenderer", {}
            )
            section = (
                two_col.get("secondaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [{}])[0]
            )
            items = section.get("musicPlaylistShelfRenderer", {}).get("contents", [])

            tracks: list[ExternalTrack] = []
            for item in items:
                renderer = item.get("musicResponsiveListItemRenderer", {})
                cols = renderer.get("flexColumns", [])
                if len(cols) < 2:
                    continue

                title_runs = (
                    cols[0]
                    .get("musicResponsiveListItemFlexColumnRenderer", {})
                    .get("text", {})
                    .get("runs", [])
                )
                artist_runs = (
                    cols[1]
                    .get("musicResponsiveListItemFlexColumnRenderer", {})
                    .get("text", {})
                    .get("runs", [])
                )

                raw_title = title_runs[0].get("text", "") if title_runs else ""
                title = _clean_youtube_title(raw_title)
                artist_parts = [
                    r.get("text", "")
                    for r in artist_runs
                    if r.get("text", "").strip() not in (",", "&", " & ", " , ")
                ]
                artist_name = ", ".join(p.strip() for p in artist_parts if p.strip())

                if title and artist_name:
                    tracks.append(
                        ExternalTrack(
                            artist_name=artist_name,
                            track_name=title,
                        )
                    )

            return tracks
        except Exception as e:
            logger.warning("Raw browse parse failed for %s: %s", playlist_id, e)
            return []

    def _fetch_playlist(
        self, playlist_id: str, page: int, limit: int
    ) -> ExternalListResult:
        _check_rate_limit()
        client = _get_ytmusic_client()
        playlist_data = client.get_playlist(playlist_id, limit=limit)

        items = playlist_data.get("tracks", [])
        tracks = self._parse_items(items)

        start = (page - 1) * limit
        page_tracks = tracks[start : start + limit]

        return ExternalListResult(
            tracks=page_tracks,
            total_count=len(tracks),
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    def _fetch_liked_tracks(self, page: int, limit: int) -> ExternalListResult:
        _check_rate_limit()
        client = _get_ytmusic_client(require_auth=True)
        liked_data = client.get_liked_songs(limit=limit)

        items = liked_data.get("tracks", [])
        tracks = self._parse_items(items)

        start = (page - 1) * limit
        page_tracks = tracks[start : start + limit]

        return ExternalListResult(
            tracks=page_tracks,
            total_count=len(tracks),
            content_hash=ExternalListResult.compute_content_hash(tracks),
        )

    @staticmethod
    def _parse_items(items: list[dict]) -> list[ExternalTrack]:
        """Parse ytmusicapi track items into ExternalTrack list."""
        tracks: list[ExternalTrack] = []
        for item in items:
            title = item.get("title", "")
            artists = item.get("artists")
            if not title or not artists:
                continue

            title = _clean_youtube_title(title)
            if not title:
                continue

            artist_name = ", ".join(a.get("name", "") for a in artists if a.get("name"))
            if not artist_name:
                continue

            tracks.append(
                ExternalTrack(
                    artist_name=artist_name.strip(),
                    track_name=title.strip(),
                )
            )
        return tracks
