"""Deezer metadata provider using the deezer-python library.

Public API (no auth needed). Rate limit: ~50 req/s, we use 10/s conservatively.
"""

from __future__ import annotations

import logging
from typing import Any

import deezer  # pylint: disable=import-error
import deezer.exceptions  # pylint: disable=import-error
import httpx  # pylint: disable=import-error

from .metadata_base import (
    AlbumResult,
    ArtistResult,
    MetadataProvider,
    PlaylistResult,
    TrackResult,
)
from .rate_limit import check_api_rate_limit

logger = logging.getLogger(__name__)


class RateLimitedDeezerClient(deezer.Client):
    """Deezer API client with database-backed rate limiting."""

    def request(self, *args: Any, **kwargs: Any) -> Any:
        check_api_rate_limit("deezer", default_rate=10.0)
        return super().request(*args, **kwargs)


def _normalize_album_type(record_type: str | None) -> str | None:
    """Map Deezer record_type to our album_type values."""
    if not record_type:
        return None
    record_type = record_type.lower()
    if record_type == "ep":
        return "single"
    if record_type in ("album", "single", "compilation"):
        return record_type
    return record_type


def _to_artist_result(artist: deezer.Artist) -> ArtistResult:
    return ArtistResult(
        name=artist.name,
        deezer_id=artist.id,
        image_url=artist.picture_xl or artist.picture_big,
    )


def _to_album_result(album: deezer.Album) -> AlbumResult:
    # Check _fields to avoid triggering lazy loads for fields only present
    # on full album responses (label, genres are absent from search/list results)
    fields = album._fields

    artist_name = ""
    artist_deezer_id = None
    if "artist" in fields and album.artist:
        artist_name = album.artist.name
        artist_deezer_id = album.artist.id

    genres: list[str] = []
    if "genres" in fields and album.genres:
        genres = [g.name for g in album.genres]

    return AlbumResult(
        name=album.title,
        artist_name=artist_name,
        deezer_id=album.id,
        image_url=album.cover_xl or album.cover_big,
        total_tracks=album.nb_tracks if "nb_tracks" in fields else None,
        release_date=(
            str(album.release_date)
            if "release_date" in fields and album.release_date
            else None
        ),
        album_type=_normalize_album_type(
            album.record_type if "record_type" in fields else None
        ),
        artist_deezer_id=artist_deezer_id,
        label=album.label if "label" in fields else None,
        genres=genres,
    )


def _to_track_result(track: deezer.Track) -> TrackResult:
    # Check _fields to avoid triggering lazy loads for fields not in partial
    # responses (e.g. disk_number/track_position absent from search results,
    # album absent from album-track listings)
    fields = track._fields

    artist_name = ""
    artist_deezer_id = None
    if "artist" in fields and track.artist:
        artist_name = track.artist.name
        artist_deezer_id = track.artist.id

    album_name = None
    album_deezer_id = None
    if "album" in fields and track.album:
        album_name = track.album.title
        album_deezer_id = track.album.id

    return TrackResult(
        name=track.title,
        artist_name=artist_name,
        album_name=album_name,
        deezer_id=track.id,
        isrc=track.isrc if "isrc" in fields else None,
        duration_ms=(track.duration or 0) * 1000,
        track_number=(track.track_position if "track_position" in fields else None),
        disc_number=track.disk_number if "disk_number" in fields else None,
        artist_deezer_id=artist_deezer_id,
        album_deezer_id=album_deezer_id,
    )


def _to_playlist_result(playlist: deezer.Playlist) -> PlaylistResult:
    creator_name = None
    if "creator" in playlist._fields and playlist.creator:
        creator_name = playlist.creator.name

    return PlaylistResult(
        name=playlist.title,
        deezer_id=playlist.id,
        description=playlist.description if "description" in playlist._fields else None,
        creator_name=creator_name,
        track_count=playlist.nb_tracks if "nb_tracks" in playlist._fields else 0,
        checksum=playlist.checksum if "checksum" in playlist._fields else None,
        image_url=playlist.picture_xl or playlist.picture_big,
    )


class DeezerMetadataProvider(MetadataProvider):
    """Deezer metadata provider using deezer-python library.

    For bulk operations (e.g., migration), use `client` to access the
    underlying deezer-python Client directly — this avoids redundant API
    calls when you already have a deezer.Album or deezer.Artist object.
    """

    def __init__(self) -> None:
        self._client = RateLimitedDeezerClient()

    @property
    def client(self) -> RateLimitedDeezerClient:
        """Expose the underlying deezer-python client for direct API access."""
        return self._client

    @property
    def name(self) -> str:
        return "Deezer"

    def search_artists(self, query: str, limit: int = 10) -> list[ArtistResult]:
        try:
            results = self._client.search_artists(query)
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            logger.warning("Deezer search_artists failed for query=%s", query)
            return []
        return [_to_artist_result(a) for a in results[:limit]]

    def search_albums(self, query: str, limit: int = 10) -> list[AlbumResult]:
        try:
            results = self._client.search_albums(query)
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            logger.warning("Deezer search_albums failed for query=%s", query)
            return []
        return [_to_album_result(a) for a in results[:limit]]

    def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        try:
            results = self._client.search(query)
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            logger.warning("Deezer search_tracks failed for query=%s", query)
            return []
        return [_to_track_result(t) for t in results[:limit]]

    def get_artist(self, provider_id: int | str) -> ArtistResult | None:
        try:
            artist = self._client.get_artist(int(provider_id))
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return None
        return _to_artist_result(artist)

    def get_artist_albums(
        self, provider_id: int | str, limit: int = 100
    ) -> list[AlbumResult]:
        try:
            artist = self._client.get_artist(int(provider_id))
            albums = artist.get_albums()
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return []
        return [_to_album_result(a) for a in albums[:limit]]

    def get_album(self, provider_id: int | str) -> AlbumResult | None:
        try:
            album = self._client.get_album(int(provider_id))
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return None
        return _to_album_result(album)

    def get_album_tracks(self, provider_id: int | str) -> list[TrackResult]:
        """Get tracks for an album. Raises on API errors."""
        album = self._client.get_album(int(provider_id))
        return [_to_track_result(t) for t in album.get_tracks()]

    def get_track(self, provider_id: int | str) -> TrackResult | None:
        try:
            track = self._client.get_track(int(provider_id))
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return None
        return _to_track_result(track)

    def get_track_by_isrc(self, isrc: str) -> TrackResult | None:
        try:
            track = self._client.request(
                "GET", f"track/isrc:{isrc}", resource_type=deezer.Track
            )
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return None
        if not track or not getattr(track, "id", None):
            return None
        return _to_track_result(track)

    def get_playlist(self, playlist_id: int | str) -> PlaylistResult | None:
        try:
            playlist = self._client.get_playlist(int(playlist_id))
        except (deezer.exceptions.DeezerAPIException, httpx.HTTPError):
            return None
        return _to_playlist_result(playlist)

    def get_playlist_tracks(self, playlist_id: int | str) -> list[TrackResult]:
        """Get tracks for a playlist. Raises on API errors."""
        playlist = self._client.get_playlist(int(playlist_id))
        return [_to_track_result(t) for t in playlist.get_tracks()]
