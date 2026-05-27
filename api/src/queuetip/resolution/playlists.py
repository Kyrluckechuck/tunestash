"""Dispatch album and playlist sources to provider-specific resolvers."""

from __future__ import annotations

from src.queuetip.resolution.apple import resolve_apple_album, resolve_apple_playlist
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.deezer import resolve_deezer_collection
from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.resolution.spotify import (
    resolve_spotify_album,
    resolve_spotify_playlist,
)


def resolve_collection(url: str) -> list[TrackCandidate]:
    """Expand a supported provider album or playlist into track candidates."""
    lowered = url.lower()
    if (
        "open.spotify.com" in lowered and "/playlist/" in lowered
    ) or lowered.startswith("spotify:playlist:"):
        return resolve_spotify_playlist(url)
    if ("open.spotify.com" in lowered and "/album/" in lowered) or lowered.startswith(
        "spotify:album:"
    ):
        return resolve_spotify_album(url)
    if "music.apple.com" in lowered and "/playlist/" in lowered:
        return resolve_apple_playlist(url)
    is_apple_album = "music.apple.com" in lowered and "/album/" in lowered
    is_apple_track = "?i=" in lowered or "&i=" in lowered
    if is_apple_album and not is_apple_track:
        return resolve_apple_album(url)
    if "deezer.com" in lowered and ("/album/" in lowered or "/playlist/" in lowered):
        return resolve_deezer_collection(url)
    raise UnsupportedURLError(
        "Only Spotify, Apple Music, and Deezer album or playlist sources are supported."
    )


def resolve_playlist(url: str) -> list[TrackCandidate]:
    """Backward-compatible playlist import entry point."""
    return resolve_collection(url)
