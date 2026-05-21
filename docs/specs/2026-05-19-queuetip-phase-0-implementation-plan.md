# Queuetip Phase 0 — Resolution Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four resolution functions Queuetip's later phases depend on — `catalog_search`, `resolve_link`, `resolve_playlist`, `ingest_track` — as a pure Python package inside the TuneStash repo.

**Architecture:** A new package `api/src/queuetip/resolution/` with no Django models (the `queuetip` Django app proper arrives in Phase 1). Functions reuse TuneStash internals: `CatalogSearchService` (Deezer search), `DeezerMetadataProvider`, `spotify_validation`, and the `Song`/`Artist` models. Two external integrations — Spotify (client-credentials via TuneStash's existing app) and Apple Music (anonymous Amp-API token scraped from the web bundle) — both empirically validated in the Phase 0 spec.

**Tech Stack:** Python 3, Django ORM, `spotipy`, `httpx`, pytest + `pytest-asyncio`, factory_boy.

**Spec deviation (deliberate, flagged):** the Phase 0 spec lists a `TrackMappingService.map_track` fuzzy name-match as a last-resort matcher in `ingest_track`. This plan **defers** it: both validated sources (Spotify, Apple) supply ISRC on every track, so the fuzzy path is near-unreachable, and `map_track`'s return type is ambiguous (Spotify *or* Deezer id by method). `ingest_track` resolves by native id or ISRC→Deezer only; a track with neither is reported "unresolved." Revisit if real unresolved rates warrant.

**Conventions:** Tests live in `api/tests/unit/queuetip/`. Run pytest from the `api/` directory (`DJANGO_SETTINGS_MODULE=test_settings` is set by `pytest.ini`). DB access is automatic (`enable_db_access_for_all_tests` is `autouse=True` in `api/tests/conftest.py`). Commits use `--no-gpg-sign` (the GPG agent times out in this environment). All work happens on the existing `songboard-design` branch.

---

### Task 1: Package scaffold — `TrackCandidate` and error types

**Files:**
- Create: `api/src/queuetip/__init__.py` (empty)
- Create: `api/src/queuetip/resolution/__init__.py` (empty)
- Create: `api/src/queuetip/resolution/errors.py`
- Create: `api/src/queuetip/resolution/candidate.py`
- Test: `api/tests/unit/queuetip/__init__.py` (empty), `api/tests/unit/queuetip/test_candidate.py`

- [ ] **Step 1: Create the empty package init files**

Create `api/src/queuetip/__init__.py`, `api/src/queuetip/resolution/__init__.py`, and `api/tests/unit/queuetip/__init__.py`, each empty.

- [ ] **Step 2: Write `errors.py`**

```python
"""Exception hierarchy for Queuetip resolution."""


class ResolutionError(Exception):
    """Base for all Queuetip resolution failures."""


class UnsupportedURLError(ResolutionError):
    """The pasted URL is not a supported provider or resource type."""


class TrackNotFoundError(ResolutionError):
    """A URL or candidate was parsed but no track could be resolved."""


class PlaylistNotFoundError(ResolutionError):
    """A playlist URL is invalid, private, or does not exist."""


class EditorialPlaylistError(ResolutionError):
    """A Spotify editorial/algorithmic playlist — not readable via client credentials."""


class AppleResolverError(ResolutionError):
    """The Apple Music scrape resolver failed (page/bundle/token structure changed)."""
```

- [ ] **Step 3: Write the failing test for `TrackCandidate`**

Create `api/tests/unit/queuetip/test_candidate.py`:

```python
from src.queuetip.resolution.candidate import TrackCandidate
from src.services.catalog_search import CatalogSearchTrack


def test_track_candidate_defaults():
    c = TrackCandidate(track_name="Maps", artist_name="Maroon 5", source="spotify")
    assert c.isrc is None
    assert c.source_id is None
    assert c.all_artists == []


def test_track_candidate_from_catalog_track():
    track = CatalogSearchTrack(
        provider_id="123",
        name="Maps",
        external_url=None,
        artist_name="Maroon 5",
        artist_provider_id="a1",
        album_name="V",
        album_provider_id="b1",
        duration_ms=200000,
        in_library=False,
        local_id=None,
    )
    c = TrackCandidate.from_catalog_track(track)
    assert c.track_name == "Maps"
    assert c.artist_name == "Maroon 5"
    assert c.source == "deezer"
    assert c.source_id == "123"
    assert c.all_artists == ["Maroon 5"]
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_candidate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.candidate'`.

- [ ] **Step 5: Write `candidate.py`**

```python
"""The uniform track DTO emitted by every resolver."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.services.catalog_search import CatalogSearchTrack


@dataclass
class TrackCandidate:
    """A track identity, source-agnostic, ready for ingest.

    artist_name is the PRIMARY artist only — never a joined multi-artist string.
    Joined strings degrade TrackMappingService fuzzy scoring; all_artists keeps the
    full list for display only.
    """

    track_name: str
    artist_name: str
    source: str  # "spotify" | "apple" | "deezer"
    isrc: str | None = None
    source_id: str | None = None
    all_artists: list[str] = field(default_factory=list)

    @classmethod
    def from_catalog_track(cls, track: CatalogSearchTrack) -> "TrackCandidate":
        return cls(
            track_name=track.name,
            artist_name=track.artist_name,
            source="deezer",
            source_id=track.provider_id,
            all_artists=[track.artist_name],
        )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd api && python -m pytest tests/unit/queuetip/test_candidate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add api/src/queuetip api/tests/unit/queuetip
git commit --no-gpg-sign -m "feat(queuetip): resolution package scaffold — TrackCandidate + errors"
```

---

### Task 2: `catalog_search` — Deezer-backed track search

**Files:**
- Create: `api/src/queuetip/resolution/catalog.py`
- Test: `api/tests/unit/queuetip/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_catalog.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from src.queuetip.resolution.catalog import catalog_search
from src.services.catalog_search import CatalogSearchResults, CatalogSearchTrack


def _track(name: str) -> CatalogSearchTrack:
    return CatalogSearchTrack(
        provider_id="1",
        name=name,
        external_url=None,
        artist_name="Artist",
        artist_provider_id="a",
        album_name="Album",
        album_provider_id="b",
        duration_ms=1000,
    )


@pytest.mark.asyncio
async def test_catalog_search_returns_only_tracks():
    fake = CatalogSearchResults(artists=[], albums=[], tracks=[_track("Maps")])
    with patch(
        "src.queuetip.resolution.catalog.CatalogSearchService.search",
        new=AsyncMock(return_value=fake),
    ) as mock_search:
        result = await catalog_search("maps", limit=5)
    assert [t.name for t in result] == ["Maps"]
    mock_search.assert_awaited_once_with("maps", types=["track"], limit=5)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.catalog'`.

- [ ] **Step 3: Write `catalog.py`**

```python
"""Track search for the contribution box — wraps TuneStash's Deezer-backed search."""

from __future__ import annotations

from src.services.catalog_search import CatalogSearchService, CatalogSearchTrack


async def catalog_search(query: str, limit: int = 10) -> list[CatalogSearchTrack]:
    """Search for tracks. Returns CatalogSearchTrack rows, which carry `in_library`
    and `local_id` for UI display. Convert a chosen result to a TrackCandidate via
    TrackCandidate.from_catalog_track() before ingest.
    """
    service = CatalogSearchService()
    results = await service.search(query, types=["track"], limit=limit)
    return results.tracks
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd api && python -m pytest tests/unit/queuetip/test_catalog.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/catalog.py api/tests/unit/queuetip/test_catalog.py
git commit --no-gpg-sign -m "feat(queuetip): catalog_search wrapping CatalogSearchService"
```

---

### Task 3: Spotify client + Spotify playlist resolution

**Files:**
- Create: `api/src/queuetip/resolution/spotify.py`
- Test: `api/tests/unit/queuetip/test_spotify.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_spotify.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
import spotipy

from src.queuetip.resolution.errors import EditorialPlaylistError, PlaylistNotFoundError
from src.queuetip.resolution.spotify import resolve_spotify_playlist


def _items_page(tracks, next_url=None):
    return {
        "items": [{"track": t} for t in tracks],
        "next": next_url,
    }


def _track(name, artists, isrc, tid):
    return {
        "name": name,
        "id": tid,
        "artists": [{"name": a} for a in artists],
        "external_ids": {"isrc": isrc},
    }


@pytest.fixture
def fake_spotify():
    sp = MagicMock()
    yield sp


def test_resolve_spotify_playlist_paginates(fake_spotify):
    page1 = _items_page([_track("A", ["X"], "ISRC1", "t1")], next_url="page2")
    page2 = _items_page([_track("B", ["Y", "Z"], "ISRC2", "t2")], next_url=None)
    fake_spotify.playlist_items.return_value = page1
    fake_spotify.next.return_value = page2
    with patch(
        "src.queuetip.resolution.spotify._build_client", return_value=fake_spotify
    ):
        result = resolve_spotify_playlist(
            "https://open.spotify.com/playlist/abc123"
        )
    assert [c.track_name for c in result] == ["A", "B"]
    assert result[1].artist_name == "Y"          # primary artist only
    assert result[1].all_artists == ["Y", "Z"]
    assert result[0].isrc == "ISRC1"
    assert result[0].source == "spotify"


def test_resolve_spotify_playlist_editorial_404(fake_spotify):
    fake_spotify.playlist_items.side_effect = spotipy.SpotifyException(
        404, -1, "not found"
    )
    with patch(
        "src.queuetip.resolution.spotify._build_client", return_value=fake_spotify
    ):
        with pytest.raises((EditorialPlaylistError, PlaylistNotFoundError)):
            resolve_spotify_playlist(
                "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
            )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_spotify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.spotify'`.

- [ ] **Step 3: Write `spotify.py`**

```python
"""Spotify resolution — client-credentials reads of public tracks and playlists.

Uses TuneStash's existing registered Spotify app (DB settings spotipy_client_id /
spotipy_client_secret). Verified: client-credentials reads public USER playlists;
editorial/owner-`spotify` playlists return HTTP 404.
"""

from __future__ import annotations

import re

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from src.app_settings.registry import get_setting
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    TrackNotFoundError,
)

_PLAYLIST_ID_RE = re.compile(r"(?:playlist[:/])([A-Za-z0-9]+)")
_TRACK_ID_RE = re.compile(r"(?:track[:/])([A-Za-z0-9]+)")


def _build_client() -> spotipy.Spotify:
    client_id = get_setting("spotipy_client_id")
    client_secret = get_setting("spotipy_client_secret")
    if not client_id or not client_secret:
        raise TrackNotFoundError("Spotify app credentials are not configured")
    auth = SpotifyClientCredentials(
        client_id=client_id, client_secret=client_secret
    )
    return spotipy.Spotify(auth_manager=auth)


def _candidate_from_spotify_track(track: dict) -> TrackCandidate:
    artists = [a["name"] for a in track.get("artists", []) if a.get("name")]
    return TrackCandidate(
        track_name=track.get("name", "Unknown Track"),
        artist_name=artists[0] if artists else "Unknown Artist",
        source="spotify",
        isrc=(track.get("external_ids") or {}).get("isrc"),
        source_id=track.get("id"),
        all_artists=artists,
    )


def resolve_spotify_playlist(url: str) -> list[TrackCandidate]:
    match = _PLAYLIST_ID_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not a Spotify playlist URL: {url}")
    playlist_id = match.group(1)
    sp = _build_client()
    try:
        page = sp.playlist_items(playlist_id, limit=100)
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            raise EditorialPlaylistError(
                "This Spotify playlist is not readable — Spotify blocks API access "
                "to editorial playlists. Use a user-created public playlist."
            ) from exc
        raise PlaylistNotFoundError(str(exc)) from exc

    candidates: list[TrackCandidate] = []
    while page:
        for item in page.get("items", []):
            track = item.get("track")
            if track and track.get("id"):
                candidates.append(_candidate_from_spotify_track(track))
        page = sp.next(page) if page.get("next") else None
    return candidates


def resolve_spotify_track(url: str) -> TrackCandidate:
    match = _TRACK_ID_RE.search(url)
    if not match:
        raise TrackNotFoundError(f"Not a Spotify track URL: {url}")
    sp = _build_client()
    try:
        track = sp.track(match.group(1))
    except spotipy.SpotifyException as exc:
        raise TrackNotFoundError(str(exc)) from exc
    return _candidate_from_spotify_track(track)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_spotify.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/spotify.py api/tests/unit/queuetip/test_spotify.py
git commit --no-gpg-sign -m "feat(queuetip): Spotify playlist + track resolution"
```

---

### Task 4: Apple Music client — token acquisition

**Files:**
- Create: `api/src/queuetip/resolution/apple.py`
- Test: `api/tests/unit/queuetip/test_apple_token.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_apple_token.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution import apple
from src.queuetip.resolution.errors import AppleResolverError

PAGE_HTML = '<script type="module" src="/assets/index~deadbeef12.js"></script>'
BUNDLE_JS = 'var x="eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJBTVAifQ.SIGNATUREPART";'


def _resp(text, status=200):
    r = MagicMock()
    r.text = text
    r.status_code = status
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture(autouse=True)
def _clear_token_cache():
    apple._TOKEN_CACHE["token"] = None
    apple._TOKEN_CACHE["fetched_at"] = 0.0
    yield


def test_fetch_token_extracts_jwt_from_bundle():
    client = MagicMock()
    client.get.side_effect = [_resp(PAGE_HTML), _resp(BUNDLE_JS)]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        token = apple._fetch_token("https://music.apple.com/ca/playlist/x/pl.u-1")
    assert token.startswith("eyJ")
    # page fetched, then bundle at the discovered URL
    assert client.get.call_args_list[1].args[0].endswith("/assets/index~deadbeef12.js")


def test_fetch_token_raises_when_bundle_url_missing():
    client = MagicMock()
    client.get.side_effect = [_resp("<html>no bundle here</html>")]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(AppleResolverError):
            apple._fetch_token("https://music.apple.com/ca/playlist/x/pl.u-1")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_apple_token.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.apple'`.

- [ ] **Step 3: Write the token half of `apple.py`**

```python
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

import httpx

from src.queuetip.resolution.errors import AppleResolverError, PlaylistNotFoundError

_AMP_BASE = "https://amp-api.music.apple.com"
_MUSIC_ORIGIN = "https://music.apple.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_BUNDLE_URL_RE = re.compile(r"/assets/index~[A-Za-z0-9]+\.js")
_JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 14  # proactively refresh every 14 days

_TOKEN_CACHE: dict = {"token": None, "fetched_at": 0.0}


def _fetch_token(page_url: str) -> str:
    """Scrape a fresh Amp-API bearer token from an Apple Music web page."""
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


def get_token(page_url: str, force_refresh: bool = False) -> str:
    """Return a cached Amp-API token, scraping a fresh one when stale or forced."""
    now = time.time()
    stale = now - _TOKEN_CACHE["fetched_at"] > _TOKEN_TTL_SECONDS
    if force_refresh or _TOKEN_CACHE["token"] is None or stale:
        _TOKEN_CACHE["token"] = _fetch_token(page_url)
        _TOKEN_CACHE["fetched_at"] = now
    return _TOKEN_CACHE["token"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_apple_token.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/apple.py api/tests/unit/queuetip/test_apple_token.py
git commit --no-gpg-sign -m "feat(queuetip): Apple Music Amp-API token acquisition"
```

---

### Task 5: Apple Music client — Amp-API requests, playlist & song

**Files:**
- Modify: `api/src/queuetip/resolution/apple.py` (append)
- Test: `api/tests/unit/queuetip/test_apple_api.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_apple_api.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution import apple
from src.queuetip.resolution.errors import PlaylistNotFoundError

URL = "https://music.apple.com/ca/playlist/volleyball/pl.u-abc123"


def _amp_resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def _track(name, artist, isrc, tid):
    return {
        "id": tid,
        "attributes": {"name": name, "artistName": artist, "isrc": isrc},
    }


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(apple, "get_token", lambda *a, **k: "FAKE_TOKEN")


def test_resolve_apple_playlist_follows_pagination():
    page1 = {"data": [_track("A", "X", "I1", "1")], "next": "/v1/.../tracks?offset=1"}
    page2 = {"data": [_track("B", "Y", "I2", "2")]}
    client = MagicMock()
    client.get.side_effect = [_amp_resp(page1), _amp_resp(page2)]
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        result = apple.resolve_apple_playlist(URL)
    assert [c.track_name for c in result] == ["A", "B"]
    assert result[0].source == "apple"
    assert result[0].isrc == "I1"
    assert result[1].artist_name == "Y"


def test_resolve_apple_playlist_404():
    client = MagicMock()
    client.get.return_value = _amp_resp({}, status=404)
    with patch("src.queuetip.resolution.apple.httpx.Client") as ctor:
        ctor.return_value.__enter__.return_value = client
        with pytest.raises(PlaylistNotFoundError):
            apple.resolve_apple_playlist(URL)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_apple_api.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_apple_playlist'`.

- [ ] **Step 3: Append Amp-API logic to `apple.py`**

Append to `api/src/queuetip/resolution/apple.py`:

```python
from src.queuetip.resolution.candidate import TrackCandidate  # noqa: E402

_PLAYLIST_PATH_RE = re.compile(
    r"music\.apple\.com/([a-z]{2})/playlist/[^/]+/(pl\.[A-Za-z0-9-]+)"
)
_SONG_PATH_RE = re.compile(
    r"music\.apple\.com/([a-z]{2})/(?:song|album)/[^/]+/(\d+)"
)


def _amp_get(path: str, page_url: str) -> dict:
    """GET an Amp-API path, refreshing the token once on a 401."""
    for attempt in (1, 2):
        token = get_token(page_url, force_refresh=(attempt == 2))
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                f"{_AMP_BASE}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Origin": _MUSIC_ORIGIN,
                    "User-Agent": _UA,
                },
            )
        if resp.status_code == 401 and attempt == 1:
            continue
        if resp.status_code == 404:
            raise PlaylistNotFoundError(
                "Apple Music resource not found — check the URL is public"
            )
        resp.raise_for_status()
        return resp.json()
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
        all_artists=[artist],
    )


def resolve_apple_playlist(url: str) -> list[TrackCandidate]:
    match = _PLAYLIST_PATH_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not an Apple Music playlist URL: {url}")
    storefront, playlist_id = match.group(1), match.group(2)
    path = f"/v1/catalog/{storefront}/playlists/{playlist_id}/tracks?limit=100"
    candidates: list[TrackCandidate] = []
    while path:
        body = _amp_get(path, url)
        candidates.extend(_candidate_from_apple(t) for t in body.get("data", []))
        nxt = body.get("next")  # relative path; `limit` is intentionally dropped
        path = nxt or None
    return candidates


def resolve_apple_track(url: str) -> TrackCandidate:
    match = _SONG_PATH_RE.search(url)
    if not match:
        from src.queuetip.resolution.errors import TrackNotFoundError

        raise TrackNotFoundError(f"Not an Apple Music song URL: {url}")
    storefront, song_id = match.group(1), match.group(2)
    body = _amp_get(f"/v1/catalog/{storefront}/songs/{song_id}", url)
    data = body.get("data", [])
    if not data:
        from src.queuetip.resolution.errors import TrackNotFoundError

        raise TrackNotFoundError(f"Apple Music song not found: {url}")
    return _candidate_from_apple(data[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_apple_api.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/apple.py api/tests/unit/queuetip/test_apple_api.py
git commit --no-gpg-sign -m "feat(queuetip): Apple Music playlist + song Amp-API resolution"
```

---

### Task 6: `resolve_playlist` — host dispatch

**Files:**
- Create: `api/src/queuetip/resolution/playlists.py`
- Test: `api/tests/unit/queuetip/test_playlists.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_playlists.py`:

```python
from unittest.mock import patch

import pytest

from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.resolution.playlists import resolve_playlist


def test_resolve_playlist_dispatches_spotify():
    with patch(
        "src.queuetip.resolution.playlists.resolve_spotify_playlist",
        return_value=["spotify-result"],
    ) as mock:
        result = resolve_playlist("https://open.spotify.com/playlist/abc")
    assert result == ["spotify-result"]
    mock.assert_called_once()


def test_resolve_playlist_dispatches_apple():
    with patch(
        "src.queuetip.resolution.playlists.resolve_apple_playlist",
        return_value=["apple-result"],
    ) as mock:
        result = resolve_playlist(
            "https://music.apple.com/ca/playlist/x/pl.u-abc"
        )
    assert result == ["apple-result"]
    mock.assert_called_once()


def test_resolve_playlist_rejects_unknown_host():
    with pytest.raises(UnsupportedURLError):
        resolve_playlist("https://example.com/playlist/123")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_playlists.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.playlists'`.

- [ ] **Step 3: Write `playlists.py`**

```python
"""resolve_playlist — dispatch a playlist URL to its source-specific resolver."""

from __future__ import annotations

from src.queuetip.resolution.apple import resolve_apple_playlist
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.resolution.spotify import resolve_spotify_playlist


def resolve_playlist(url: str) -> list[TrackCandidate]:
    """Expand a public Spotify or Apple Music playlist URL into track candidates."""
    lowered = url.lower()
    if "open.spotify.com" in lowered or lowered.startswith("spotify:"):
        return resolve_spotify_playlist(url)
    if "music.apple.com" in lowered:
        return resolve_apple_playlist(url)
    raise UnsupportedURLError(
        "Only Spotify and Apple Music playlist URLs are supported."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_playlists.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/playlists.py api/tests/unit/queuetip/test_playlists.py
git commit --no-gpg-sign -m "feat(queuetip): resolve_playlist host dispatch"
```

---

### Task 7: `resolve_link` — single-track URL dispatch

**Files:**
- Create: `api/src/queuetip/resolution/links.py`
- Test: `api/tests/unit/queuetip/test_links.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_links.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError, UnsupportedURLError
from src.queuetip.resolution.links import resolve_link


def test_resolve_link_spotify():
    cand = TrackCandidate("A", "X", "spotify", source_id="t1")
    with patch(
        "src.queuetip.resolution.links.resolve_spotify_track", return_value=cand
    ):
        assert resolve_link("https://open.spotify.com/track/t1") is cand


def test_resolve_link_apple():
    cand = TrackCandidate("A", "X", "apple", source_id="9")
    with patch(
        "src.queuetip.resolution.links.resolve_apple_track", return_value=cand
    ):
        assert resolve_link("https://music.apple.com/ca/song/x/9") is cand


def test_resolve_link_deezer():
    fake_track = MagicMock(
        name="Maps", artist_name="Maroon 5", deezer_id=42, isrc="ISRCX"
    )
    fake_track.name = "Maps"
    provider = MagicMock()
    provider.get_track.return_value = fake_track
    with patch(
        "src.queuetip.resolution.links.DeezerMetadataProvider", return_value=provider
    ):
        result = resolve_link("https://www.deezer.com/track/42")
    assert result.source == "deezer"
    assert result.source_id == "42"
    assert result.isrc == "ISRCX"
    provider.get_track.assert_called_once_with("42")


def test_resolve_link_deezer_not_found():
    provider = MagicMock()
    provider.get_track.return_value = None
    with patch(
        "src.queuetip.resolution.links.DeezerMetadataProvider", return_value=provider
    ):
        with pytest.raises(TrackNotFoundError):
            resolve_link("https://www.deezer.com/track/999")


def test_resolve_link_youtube_unsupported():
    with pytest.raises(UnsupportedURLError):
        resolve_link("https://music.youtube.com/watch?v=abc")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_links.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.links'`.

- [ ] **Step 3: Write `links.py`**

```python
"""resolve_link — resolve a single pasted track URL to a TrackCandidate.

Supported: Spotify, Apple Music, Deezer track URLs. YouTube Music is intentionally
unsupported — it exposes no ISRC (verified), which would force unreliable name
matching; users paste those into the search box instead.
"""

from __future__ import annotations

import re

from src.providers.deezer import DeezerMetadataProvider
from src.queuetip.resolution.apple import resolve_apple_track
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError, UnsupportedURLError
from src.queuetip.resolution.spotify import resolve_spotify_track

_DEEZER_TRACK_RE = re.compile(r"deezer\.com/(?:\w+/)?track/(\d+)")


def _resolve_deezer_track(url: str) -> TrackCandidate:
    match = _DEEZER_TRACK_RE.search(url)
    if not match:
        raise TrackNotFoundError(f"Not a Deezer track URL: {url}")
    deezer_id = match.group(1)
    track = DeezerMetadataProvider().get_track(deezer_id)
    if track is None:
        raise TrackNotFoundError(f"Deezer track not found: {url}")
    return TrackCandidate(
        track_name=track.name,
        artist_name=track.artist_name,
        source="deezer",
        isrc=track.isrc,
        source_id=str(deezer_id),
        all_artists=[track.artist_name],
    )


def resolve_link(url: str) -> TrackCandidate:
    lowered = url.lower()
    if "music.youtube.com" in lowered or "youtu.be" in lowered:
        raise UnsupportedURLError(
            "YouTube Music links are not supported — search for the song instead."
        )
    if "open.spotify.com/track" in lowered or lowered.startswith("spotify:track"):
        return resolve_spotify_track(url)
    if "music.apple.com" in lowered:
        return resolve_apple_track(url)
    if "deezer.com" in lowered:
        return _resolve_deezer_track(url)
    raise UnsupportedURLError(f"Unsupported track URL: {url}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_links.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/resolution/links.py api/tests/unit/queuetip/test_links.py
git commit --no-gpg-sign -m "feat(queuetip): resolve_link single-track URL resolution"
```

---

### Task 8: `ingest_track` — candidate → `Song` + queued download

**Files:**
- Create: `api/src/queuetip/resolution/ingest.py`
- Test: `api/tests/unit/queuetip/test_ingest.py`

`ingest_track` is synchronous (it does Django ORM work and queues Celery tasks; call it
inside a Celery task, or wrap with `sync_to_async` from an async context). Matching
order: native id → ISRC → ISRC→Deezer resolution on the create path.

- [ ] **Step 1: Write the failing test**

Create `api/tests/unit/queuetip/test_ingest.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError
from src.queuetip.resolution.ingest import ingest_track
from tests.factories import ArtistFactory, SongFactory


@pytest.fixture(autouse=True)
def _no_real_downloads():
    with patch("src.queuetip.resolution.ingest.download_deezer_track") as dz, patch(
        "src.queuetip.resolution.ingest.download_track_by_spotify_gid"
    ) as sp:
        yield {"deezer": dz, "spotify": sp}


def test_ingest_matches_existing_song_by_gid(_no_real_downloads):
    artist = ArtistFactory()
    existing = SongFactory(primary_artist=artist, gid="spot123", downloaded=False)
    cand = TrackCandidate("Song", "Artist", "spotify", source_id="spot123")
    result = ingest_track(cand)
    assert result.id == existing.id
    _no_real_downloads["spotify"].delay.assert_called_once_with("spot123")


def test_ingest_matches_existing_song_by_isrc(_no_real_downloads):
    artist = ArtistFactory()
    existing = SongFactory(primary_artist=artist, isrc="ISRCMATCH", deezer_id=55)
    cand = TrackCandidate("Song", "Artist", "apple", isrc="ISRCMATCH", source_id="999")
    result = ingest_track(cand)
    assert result.id == existing.id


def test_ingest_creates_spotify_song(_no_real_downloads):
    cand = TrackCandidate(
        "New Song", "New Artist", "spotify", isrc="ISRCNEW", source_id="newgid1"
    )
    result = ingest_track(cand)
    assert result.gid == "newgid1"
    assert result.isrc == "ISRCNEW"
    assert result.primary_artist.name == "New Artist"
    _no_real_downloads["spotify"].delay.assert_called_once_with("newgid1")


def test_ingest_creates_apple_song_via_isrc_to_deezer(_no_real_downloads):
    deezer_result = MagicMock(deezer_id=7777, artist_deezer_id=12)
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = deezer_result
    cand = TrackCandidate("Apple Song", "Apple Artist", "apple", isrc="ISRCAPPLE")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        result = ingest_track(cand)
    assert result.deezer_id == 7777
    _no_real_downloads["deezer"].delay.assert_called_once_with(result.id)


def test_ingest_unresolvable_apple_song_raises(_no_real_downloads):
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = None
    cand = TrackCandidate("Ghost", "Nobody", "apple", isrc="NOISRC")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        with pytest.raises(TrackNotFoundError):
            ingest_track(cand)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && python -m pytest tests/unit/queuetip/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.resolution.ingest'`.

- [ ] **Step 3: Write `ingest.py`**

```python
"""ingest_track — turn a TrackCandidate into a persisted Song and queue its download.

Identity is created synchronously so callers get a Song at once; the audio download is
queued asynchronously and its success is NOT a gate. Matching is ISRC-first; the create
path resolves Apple/ISRC-only candidates to a Deezer id (the Song model has no Apple id
column — its CheckConstraint requires gid, deezer_id, or youtube_id).
"""

from __future__ import annotations

from library_manager.models import Artist, Song, TrackingTier
from library_manager.tasks import download_deezer_track, download_track_by_spotify_gid
from src.providers.deezer import DeezerMetadataProvider
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError


def _find_existing_song(candidate: TrackCandidate) -> Song | None:
    if candidate.source == "spotify" and candidate.source_id:
        song = Song.objects.filter(gid=candidate.source_id).first()
        if song:
            return song
    if candidate.source == "deezer" and candidate.source_id:
        song = Song.objects.filter(deezer_id=int(candidate.source_id)).first()
        if song:
            return song
    if candidate.isrc:
        song = Song.objects.filter(isrc=candidate.isrc).first()
        if song:
            return song
    return None


def _get_or_create_artist(
    candidate: TrackCandidate, fallback_external_id: str, artist_deezer_id: int | None
) -> Artist:
    if artist_deezer_id:
        existing = Artist.objects.filter(deezer_id=artist_deezer_id).first()
        if existing:
            return existing
    artist, _ = Artist.objects.get_or_create(
        gid=f"queuetip-unknown-{fallback_external_id}",
        defaults={
            "name": candidate.artist_name,
            "tracking_tier": TrackingTier.UNTRACKED,
        },
    )
    return artist


def _create_song(candidate: TrackCandidate) -> Song:
    gid: str | None = None
    deezer_id: int | None = None
    artist_deezer_id: int | None = None

    if candidate.source == "spotify" and candidate.source_id:
        gid = candidate.source_id
    elif candidate.source == "deezer" and candidate.source_id:
        deezer_id = int(candidate.source_id)
    else:
        # Apple (no Song-supported id) — resolve via ISRC -> Deezer.
        if candidate.isrc:
            result = DeezerMetadataProvider().get_track_by_isrc(candidate.isrc)
            if result and result.deezer_id:
                deezer_id = result.deezer_id
                artist_deezer_id = result.artist_deezer_id

    if gid is None and deezer_id is None:
        raise TrackNotFoundError(
            f"Could not resolve '{candidate.track_name}' to a storable track"
        )

    artist = _get_or_create_artist(
        candidate, str(gid or deezer_id), artist_deezer_id
    )
    return Song.objects.create(
        name=candidate.track_name,
        gid=gid,
        deezer_id=deezer_id,
        isrc=candidate.isrc,
        primary_artist=artist,
    )


def _queue_download(song: Song) -> None:
    if song.downloaded:
        return
    if song.deezer_id:
        download_deezer_track.delay(song.id)
    elif song.gid:
        download_track_by_spotify_gid.delay(song.gid)


def ingest_track(candidate: TrackCandidate) -> Song:
    """Match or create a Song for `candidate`, queue its download, return the Song."""
    song = _find_existing_song(candidate)
    if song is None:
        song = _create_song(candidate)
    _queue_download(song)
    return song
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && python -m pytest tests/unit/queuetip/test_ingest.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the full Phase 0 suite**

Run: `cd api && python -m pytest tests/unit/queuetip/ -v`
Expected: PASS — all tests across all eight test files green.

- [ ] **Step 6: Commit**

```bash
git add api/src/queuetip/resolution/ingest.py api/tests/unit/queuetip/test_ingest.py
git commit --no-gpg-sign -m "feat(queuetip): ingest_track — candidate to Song with queued download"
```

---

### Task 9: Public package surface + lint

**Files:**
- Modify: `api/src/queuetip/resolution/__init__.py`

- [ ] **Step 1: Export the public surface**

Replace the contents of `api/src/queuetip/resolution/__init__.py`:

```python
"""Queuetip Phase 0 — the resolution interface.

Public functions: catalog_search, resolve_link, resolve_playlist, ingest_track.
"""

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.catalog import catalog_search
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.links import resolve_link
from src.queuetip.resolution.playlists import resolve_playlist

__all__ = [
    "TrackCandidate",
    "catalog_search",
    "ingest_track",
    "resolve_link",
    "resolve_playlist",
]
```

- [ ] **Step 2: Run the full suite once more**

Run: `cd api && python -m pytest tests/unit/queuetip/ -v`
Expected: PASS — all green.

- [ ] **Step 3: Lint the new package**

Run: `make lint-api`
Expected: no flake8/black/isort/mypy/bandit/pylint errors in `src/queuetip/`. Fix any reported issues (run `make fix-lint` for formatting), then re-run.

- [ ] **Step 4: Commit**

```bash
git add api/src/queuetip/resolution/__init__.py
git commit --no-gpg-sign -m "feat(queuetip): export Phase 0 resolution public surface"
```

---

## Manual Verification (post-implementation, optional but recommended)

The unit tests mock all network calls. To confirm the live integrations still behave as
validated, run these against the container (read-only):

- **Spotify:** `docker compose exec -T web python manage.py shell_plus -c "from src.queuetip.resolution import resolve_playlist; print(len(resolve_playlist('https://open.spotify.com/playlist/4tFwfZE3huEB7e8LRnKwmY')))"` — expect a track count, no error.
- **Apple:** same with `resolve_playlist('https://music.apple.com/ca/playlist/volleyball-2/pl.u-b3b8VPNivj1Pp2')` — expect a track count.
- **Editorial guard:** `resolve_playlist('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M')` — expect `EditorialPlaylistError`.

## Spec Coverage Check

- `catalog_search` → Task 2. `resolve_link` (Spotify/Apple/Deezer, YouTube rejected) → Task 7. `resolve_playlist` (Spotify + Apple, host dispatch) → Tasks 3, 5, 6. `ingest_track` (ISRC-first, identity-sync + async download) → Task 8. `TrackCandidate` shape (primary artist only, `all_artists`) → Task 1. Apple token auto-refresh on 401 → Task 4/5. Editorial-404 handling → Task 3. `ExternalList` not used → satisfied by construction (no `ExternalList` import anywhere). `map_track` fuzzy fallback → **deliberately deferred**, see the header note.
