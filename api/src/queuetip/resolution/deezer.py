"""Resolve Deezer album and playlist links into uniform track candidates."""

from __future__ import annotations

import re

import deezer
import httpx

from src.providers.deezer import DeezerMetadataProvider
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import PlaylistNotFoundError

_COLLECTION_RE = re.compile(r"deezer\.com/(?:[a-z]{2}/)?(album|playlist)/(\d+)", re.I)


def resolve_deezer_collection(url: str) -> list[TrackCandidate]:
    match = _COLLECTION_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not a Deezer album or playlist URL: {url}")
    resource, source_id = match.groups()
    provider = DeezerMetadataProvider()
    try:
        tracks = (
            provider.get_album_tracks(source_id)
            if resource.lower() == "album"
            else provider.get_playlist_tracks(source_id)
        )
    except (deezer.exceptions.DeezerAPIException, httpx.HTTPError) as exc:
        raise PlaylistNotFoundError(f"Deezer collection not found: {url}") from exc
    return [
        TrackCandidate(
            track_name=track.name,
            artist_name=track.artist_name,
            source="deezer",
            isrc=track.isrc,
            source_id=str(track.deezer_id) if track.deezer_id else None,
            all_artists=[track.artist_name],
        )
        for track in tracks
    ]
