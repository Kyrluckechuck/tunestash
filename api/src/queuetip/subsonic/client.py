"""Outbound Subsonic REST client.

Implements just enough of the Subsonic API to:
  * verify a connection (ping)
  * search tracks (search3)
  * read a playlist's current contents (getPlaylist)
  * create / update / delete a playlist

Auth is salted-MD5 — the lowest common denominator that works against every
Subsonic-compatible server. The password lives encrypted at rest (Fernet);
this client takes the *plaintext* and computes a fresh salt + token per
request, so the password never leaves memory in long-lived form.

Response format: we always request `f=json` so callers can work in dicts
rather than juggling Subsonic's quirky XML namespace.

Error model:
  * SubsonicError — anything that fails (HTTP, auth, server returns code).
  * SubsonicAuthError — credentials rejected (Subsonic code 40 / 41).
  * SubsonicNotFoundError — server returned code 70 (data not found). The
    sync service maps this to STATUS_REMOTE_DELETED for the affected target.

The client is sync (httpx, not httpx.AsyncClient) because Celery tasks call
into it — wrapping a sync client in sync_to_async at the service boundary is
simpler than auditing every call site for async-context safety.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_VERSION = "1.16.1"
CLIENT_NAME = "queuetip"
DEFAULT_TIMEOUT = 15.0


class SubsonicError(Exception):
    """Base class for any Subsonic API failure."""


class SubsonicAuthError(SubsonicError):
    """Credentials rejected by the server (codes 40, 41)."""


class SubsonicNotFoundError(SubsonicError):
    """Server returned code 70 — the resource (e.g. a playlist) is gone.

    The sync service treats this as REMOTE_DELETED per lifecycle Principle 2.
    """


@dataclass
class SubsonicTrack:
    """A subset of <song> response fields useful for queuetip matching."""

    id: str
    title: str
    artist: str
    isrc: str | None = None


class SubsonicClient:
    """Thin wrapper around the Subsonic REST endpoints we call.

    Instantiate per-sync with the user's credentials. The instance does NOT
    cache responses — short-lived by design.
    """

    def __init__(
        self,
        *,
        server_url: str,
        username: str,
        password: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        # Trim a trailing slash so callers can write `<base>/rest/...` without
        # producing double slashes that some Subsonic servers reject.
        self.server_url = server_url.rstrip("/")
        self.username = username
        self._password = password
        self._timeout = timeout

    # ── Public endpoints ────────────────────────────────────────────────────

    def ping(self) -> None:
        """Verify the connection. Raises on any failure."""
        self._get("ping")

    def get_open_subsonic_extensions(self) -> list[str]:
        """Probe for OpenSubsonic extensions.

        Returns a list of extension names the server advertises. An empty
        list means either "classic Subsonic" or "server doesn't expose the
        endpoint." Either way, the rest of the client falls back to the
        baseline Subsonic API.

        Never raises — this is a best-effort capability probe. Any failure
        returns []. Classic Subsonic servers respond with code 30 ("required
        parameter missing") or a 404; both are treated as "no extensions."
        """
        try:
            data = self._get("getOpenSubsonicExtensions")
        except SubsonicError:
            return []
        extensions = data.get("openSubsonicExtensions") or []
        if isinstance(extensions, dict):
            extensions = [extensions]
        # Each entry is {"name": "<ext>", "versions": [1, 2, ...]}.
        return [str(e.get("name", "")) for e in extensions if e.get("name")]

    def search_tracks(self, query: str, *, song_count: int = 20) -> list[SubsonicTrack]:
        """Search3 limited to <song> results — what queuetip needs.

        Subsonic's `query` is matched fuzzily by the server against title,
        artist, album, etc. Caller controls the strictness via the query they
        construct (ISRC, "title", "title artist", etc.).
        """
        data = self._get(
            "search3",
            params={
                "query": query,
                "songCount": str(song_count),
                "artistCount": "0",
                "albumCount": "0",
            },
        )
        result = data.get("searchResult3") or {}
        songs_raw = result.get("song") or []
        # Some servers return a single dict when there's one match; normalize.
        if isinstance(songs_raw, dict):
            songs_raw = [songs_raw]
        return [
            SubsonicTrack(
                id=str(s.get("id", "")),
                title=str(s.get("title", "")),
                artist=str(s.get("artist", "")),
                # Subsonic exposes ISRC in some implementations under "isrc"
                # (modern OpenSubsonic), others not at all. None when absent.
                isrc=(s.get("isrc") or None),
            )
            for s in songs_raw
            if s.get("id")
        ]

    def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Fetch playlist metadata and entry list. Raises SubsonicNotFoundError
        on code 70 (user deleted it on the server)."""
        return self._get("getPlaylist", params={"id": playlist_id}).get("playlist", {})

    def create_playlist(self, name: str, song_ids: list[str]) -> str:
        """Create a new playlist and return its server-assigned id.

        Subsonic's createPlaylist accepts repeated `songId` parameters.
        """
        params: list[tuple[str, str]] = [("name", name)]
        params.extend(("songId", sid) for sid in song_ids)
        data = self._get("createPlaylist", params=params)
        playlist = data.get("playlist") or {}
        playlist_id = str(playlist.get("id", ""))
        if not playlist_id:
            raise SubsonicError(f"createPlaylist returned no id (got {data!r})")
        return playlist_id

    def overwrite_playlist(self, playlist_id: str, song_ids: list[str]) -> None:
        """Replace ALL tracks on an existing playlist with `song_ids`.

        Subsonic's updatePlaylist is incremental (add/remove by index). To
        avoid drift if the user manually edited the playlist server-side,
        we first read its current length then send a single update that
        removes everything and adds the new list in order.

        Raises SubsonicNotFoundError on code 70 (user deleted the playlist).
        """
        # Read current contents so we know how many indices to remove.
        playlist = self.get_playlist(playlist_id)
        current_entries = playlist.get("entry") or []
        if isinstance(current_entries, dict):
            current_entries = [current_entries]
        current_count = len(current_entries)

        params: list[tuple[str, str]] = [("playlistId", playlist_id)]
        # Remove existing entries by index (must list each index explicitly).
        for i in range(current_count):
            params.append(("songIndexToRemove", str(i)))
        # Add the new tracks in order.
        for sid in song_ids:
            params.append(("songIdToAdd", sid))
        self._get("updatePlaylist", params=params)

    def delete_playlist(self, playlist_id: str) -> None:
        """Remove a playlist from the server.

        Used when the user removes a sync target — we tidy up the remote
        side so they don't have an orphan playlist sitting in Navidrome.
        """
        try:
            self._get("deletePlaylist", params={"id": playlist_id})
        except SubsonicNotFoundError:
            # Already gone — that's fine, treat as idempotent.
            return

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get(
        self,
        endpoint: str,
        *,
        params: list[tuple[str, str]] | dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Perform a Subsonic REST call, decode JSON, validate the envelope."""
        salt = secrets.token_hex(8)
        token = hashlib.md5(  # nosec: B324 — Subsonic protocol mandates MD5
            (self._password + salt).encode("utf-8")
        ).hexdigest()

        query: list[tuple[str, str]] = [
            ("u", self.username),
            ("t", token),
            ("s", salt),
            ("v", API_VERSION),
            ("c", CLIENT_NAME),
            ("f", "json"),
        ]
        if isinstance(params, dict):
            query.extend(params.items())
        elif params is not None:
            query.extend(params)

        url = f"{self.server_url}/rest/{endpoint}.view"
        try:
            response = httpx.get(url, params=query, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise SubsonicError(f"HTTP error calling {endpoint}: {exc}") from exc

        if response.status_code != 200:
            raise SubsonicError(
                f"{endpoint} HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SubsonicError(
                f"{endpoint} returned non-JSON: {response.text[:200]}"
            ) from exc

        envelope = payload.get("subsonic-response") or {}
        status = envelope.get("status")
        if status != "ok":
            error = envelope.get("error") or {}
            code = int(error.get("code", 0))
            message = error.get("message") or "Unknown Subsonic error"
            if code in (40, 41):
                # 40 = wrong credentials, 41 = token authentication not supported
                # for old plaintext-password users (rare; surfaced same way).
                raise SubsonicAuthError(f"{endpoint}: {message}")
            if code == 70:
                raise SubsonicNotFoundError(f"{endpoint}: {message}")
            raise SubsonicError(f"{endpoint} (code {code}): {message}")

        return envelope
