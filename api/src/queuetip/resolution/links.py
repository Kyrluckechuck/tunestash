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
