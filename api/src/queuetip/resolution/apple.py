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
from typing import TypedDict

import httpx

from src.queuetip.resolution.errors import (  # noqa: F401
    AppleResolverError,
    PlaylistNotFoundError,
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
    except AppleResolverError:
        raise
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
    return _TOKEN_CACHE["token"]
