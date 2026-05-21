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
