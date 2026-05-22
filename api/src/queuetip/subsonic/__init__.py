"""Outbound Subsonic API client + queuetip-song resolution.

Subsonic is the *protocol*, not just the original server — Navidrome, Airsonic,
Gonic, Funkwhale, LMS, and others implement the same REST API. Queuetip pushes
playlists into the user's own Subsonic-compatible server; it never proxies.

Public surface:
  * SubsonicClient — typed wrapper around the handful of REST endpoints we call.
  * SubsonicError — surfaced for any non-success response.
  * resolve_song_to_subsonic_id — track-matching ladder
    (ISRC → title+artist exact → title fuzzy + artist exact).
"""

from .client import (
    SubsonicAuthError,
    SubsonicClient,
    SubsonicError,
    SubsonicNotFoundError,
)
from .resolution import resolve_song_to_subsonic_id

__all__ = [
    "SubsonicAuthError",
    "SubsonicClient",
    "SubsonicError",
    "SubsonicNotFoundError",
    "resolve_song_to_subsonic_id",
]
