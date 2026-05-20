"""Apple Music resolution — anonymous Amp-API access.

VERIFIED (Phase 0 spec): Apple Music web pages embed an `AMPWebPlay` JWT in their JS
bundle; with it, amp-api.music.apple.com returns playlist/song data with no developer
account. The bundle filename hash changes per Apple deploy, so the bundle URL is parsed
from the page every time; the token is cached and re-scraped on 401 / near-expiry.

This module is the only brittle surface in Phase 0 — keep it isolated.
"""

from __future__ import annotations

import re
import time
from typing import Optional, TypedDict

import httpx  # pylint: disable=import-error

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import (
    AppleResolverError,
    PlaylistNotFoundError,
    ResolutionError,
    TrackNotFoundError,
)

_AMP_BASE = "https://amp-api.music.apple.com"
_MUSIC_ORIGIN = "https://music.apple.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_BUNDLE_URL_RE = re.compile(r"/assets/index~[A-Za-z0-9]+\.js")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 14  # proactively refresh every 14 days


class _TokenCache(TypedDict):
    token: str | None
    fetched_at: float


_TOKEN_CACHE: _TokenCache = {"token": None, "fetched_at": 0.0}


def _fetch_token(page_url: str) -> str:
    """Scrape a fresh Amp-API bearer token from an Apple Music web page."""
    try:
        with httpx.Client(
            timeout=20.0, headers={"User-Agent": _UA}, follow_redirects=True
        ) as client:
            page = client.get(page_url)
            page.raise_for_status()
            bundle_match = _BUNDLE_URL_RE.search(page.text)
            if not bundle_match:
                raise AppleResolverError(
                    "Apple Music bundle URL not found — page structure changed"
                )
            bundle = client.get(f"{_MUSIC_ORIGIN}{bundle_match.group(0)}")
            bundle.raise_for_status()
            token_match = _JWT_RE.search(bundle.text)
            if not token_match:
                raise AppleResolverError(
                    "Apple Music API token not found in bundle — structure changed"
                )
            return token_match.group(0)
    except httpx.HTTPStatusError as exc:
        raise AppleResolverError(
            f"Apple Music HTTP {exc.response.status_code} fetching token"
        ) from exc
    except httpx.RequestError as exc:
        raise AppleResolverError(
            f"Apple Music network error fetching token: {exc}"
        ) from exc


def get_token(page_url: str, force_refresh: bool = False) -> str:
    """Return a cached Amp-API token, scraping a fresh one when stale or forced."""
    now = time.time()
    stale = now - _TOKEN_CACHE["fetched_at"] > _TOKEN_TTL_SECONDS
    if force_refresh or _TOKEN_CACHE["token"] is None or stale:
        _TOKEN_CACHE["token"] = _fetch_token(page_url)
        _TOKEN_CACHE["fetched_at"] = now
    token = _TOKEN_CACHE["token"]
    assert token is not None  # set unconditionally in the branch above
    return token


_PLAYLIST_PATH_RE = re.compile(
    r"music\.apple\.com/([a-z]{2})/playlist/[^/]+/(pl\.[A-Za-z0-9-]+)"
)
_STOREFRONT_RE = re.compile(r"music\.apple\.com/([a-z]{2})/")
_SONG_URL_RE = re.compile(r"music\.apple\.com/[a-z]{2}/song/[^/]+/(\d+)")
_ALBUM_TRACK_RE = re.compile(r"[?&]i=(\d+)")


def _amp_get(
    path: str,
    page_url: str,
    not_found_exc: type[ResolutionError] = PlaylistNotFoundError,
) -> dict:
    """GET an Amp-API path, refreshing the token once on a 401."""
    for attempt in (1, 2):
        token = get_token(page_url, force_refresh=attempt == 2)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(
                    f"{_AMP_BASE}{path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Origin": _MUSIC_ORIGIN,
                        "User-Agent": _UA,
                    },
                )
        except httpx.RequestError as exc:
            raise AppleResolverError(f"Apple Music network error: {exc}") from exc
        if resp.status_code == 401 and attempt == 1:
            continue
        if resp.status_code == 404:
            raise not_found_exc(
                "Apple Music resource not found — check the URL is public"
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AppleResolverError(f"Apple Music HTTP {resp.status_code}") from exc
        return dict(resp.json())
    raise AppleResolverError("Apple Amp-API auth failed after token refresh")


def _candidate_from_apple(item: dict) -> TrackCandidate:
    attrs = item.get("attributes", {})
    artist = attrs.get("artistName", "Unknown Artist")
    return TrackCandidate(
        track_name=attrs.get("name", "Unknown Track"),
        artist_name=artist,
        source="apple",
        isrc=attrs.get("isrc"),
        source_id=str(item.get("id")) if item.get("id") else None,
        # Apple's tracks endpoint returns `artistName` as a single (possibly joined)
        # string — there is no per-artist list — so all_artists holds one element
        # and must NOT be split on `&`/`,`.
        all_artists=[artist],
    )


def resolve_apple_playlist(url: str) -> list[TrackCandidate]:
    match = _PLAYLIST_PATH_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not an Apple Music playlist URL: {url}")
    storefront, playlist_id = match.group(1), match.group(2)
    path: Optional[str] = (
        f"/v1/catalog/{storefront}/playlists/{playlist_id}/tracks?limit=100"
    )
    candidates: list[TrackCandidate] = []
    while path:
        body = _amp_get(path, url)
        candidates.extend(_candidate_from_apple(t) for t in body.get("data", []))
        nxt: Optional[str] = body.get(
            "next"
        )  # relative path; `limit` is intentionally dropped
        path = nxt or None
    return candidates


def resolve_apple_track(url: str) -> TrackCandidate:
    sf_match = _STOREFRONT_RE.search(url)
    album_track_match = _ALBUM_TRACK_RE.search(url)
    song_match = _SONG_URL_RE.search(url)
    storefront = sf_match.group(1) if sf_match else None
    song_id = (
        album_track_match.group(1)
        if album_track_match
        else song_match.group(1) if song_match else None
    )
    if not storefront or not song_id:
        raise TrackNotFoundError(f"Not an Apple Music song URL: {url}")
    body = _amp_get(
        f"/v1/catalog/{storefront}/songs/{song_id}",
        url,
        not_found_exc=TrackNotFoundError,
    )
    data = body.get("data", [])
    if not data:
        raise TrackNotFoundError(f"Apple Music song not found: {url}")
    return _candidate_from_apple(data[0])
