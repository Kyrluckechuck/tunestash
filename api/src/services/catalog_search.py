# mypy: disable-error-code=no-any-return
"""Catalog search service using Deezer for artist/album/track discovery."""

from dataclasses import dataclass
from typing import List, Optional

from django.db.models import Q

from asgiref.sync import sync_to_async

from library_manager.models import Album, Artist, Song

from ..providers.deezer import DeezerMetadataProvider
from ..providers.metadata_base import AlbumResult, ArtistResult, TrackResult


@dataclass
class CatalogSearchArtist:
    provider_id: str
    name: str
    image_url: Optional[str]
    external_url: Optional[str]
    in_library: bool = False
    local_id: Optional[int] = None
    tracking_tier: int = 0


@dataclass
class CatalogSearchAlbum:
    provider_id: str
    name: str
    image_url: Optional[str]
    external_url: Optional[str]
    artist_name: str
    artist_provider_id: str
    release_date: Optional[str]
    album_type: str
    total_tracks: int
    in_library: bool = False
    local_id: Optional[int] = None


@dataclass
class CatalogSearchTrack:
    provider_id: str
    name: str
    external_url: Optional[str]
    artist_name: str
    artist_provider_id: str
    album_name: str
    album_provider_id: str
    duration_ms: int
    in_library: bool = False
    local_id: Optional[int] = None


@dataclass
class CatalogSearchResults:
    artists: List[CatalogSearchArtist]
    albums: List[CatalogSearchAlbum]
    tracks: List[CatalogSearchTrack]


class CatalogSearchService:
    def __init__(self) -> None:
        self._provider = DeezerMetadataProvider()

    async def search(
        self,
        query: str,
        types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> CatalogSearchResults:
        if types is None:
            types = ["artist", "album", "track"]

        artists: List[CatalogSearchArtist] = []
        albums: List[CatalogSearchAlbum] = []
        tracks: List[CatalogSearchTrack] = []

        if "artist" in types:
            raw_artists = await sync_to_async(self._provider.search_artists)(
                query, limit=limit
            )
            artists = await self._enrich_artists(raw_artists)

        if "album" in types:
            raw_albums = await sync_to_async(self._provider.search_albums)(
                query, limit=limit
            )
            albums = await self._enrich_albums(raw_albums)

        if "track" in types:
            raw_tracks = await sync_to_async(self._provider.search_tracks)(
                query, limit=limit
            )
            tracks = await self._enrich_tracks(raw_tracks)

        return CatalogSearchResults(
            artists=artists,
            albums=albums,
            tracks=tracks,
        )

    async def _enrich_artists(
        self, raw: List[ArtistResult]
    ) -> List[CatalogSearchArtist]:
        results: List[CatalogSearchArtist] = []
        for a in raw:
            deezer_id = a.deezer_id
            if deezer_id is None:
                continue

            in_library = False
            local_id: Optional[int] = None
            tracking_tier = 0

            match = await sync_to_async(
                lambda did=deezer_id, name=a.name: Artist.objects.filter(
                    Q(deezer_id=did) | Q(name__iexact=name)
                ).first()
            )()

            if match:
                in_library = True
                local_id = match.id
                tracking_tier = match.tracking_tier

            results.append(
                CatalogSearchArtist(
                    provider_id=str(deezer_id),
                    name=a.name,
                    image_url=a.image_url,
                    external_url=f"https://www.deezer.com/artist/{deezer_id}",
                    in_library=in_library,
                    local_id=local_id,
                    tracking_tier=tracking_tier,
                )
            )
        return results

    async def _enrich_albums(self, raw: List[AlbumResult]) -> List[CatalogSearchAlbum]:
        results: List[CatalogSearchAlbum] = []
        for a in raw:
            deezer_id = a.deezer_id
            if deezer_id is None:
                continue

            in_library = False
            local_id: Optional[int] = None

            match = await sync_to_async(
                lambda did=deezer_id, name=a.name, artist=a.artist_name: (
                    Album.objects.select_related("artist")
                    .filter(
                        Q(deezer_id=did)
                        | Q(name__iexact=name, artist__name__iexact=artist)
                    )
                    .first()
                )
            )()

            if match:
                in_library = True
                local_id = match.id

            results.append(
                CatalogSearchAlbum(
                    provider_id=str(deezer_id),
                    name=a.name,
                    image_url=a.image_url,
                    external_url=f"https://www.deezer.com/album/{deezer_id}",
                    artist_name=a.artist_name,
                    artist_provider_id=str(a.artist_deezer_id or ""),
                    release_date=a.release_date,
                    album_type=a.album_type or "album",
                    total_tracks=a.total_tracks or 0,
                    in_library=in_library,
                    local_id=local_id,
                )
            )
        return results

    async def _enrich_tracks(self, raw: List[TrackResult]) -> List[CatalogSearchTrack]:
        results: List[CatalogSearchTrack] = []
        for t in raw:
            deezer_id = t.deezer_id
            if deezer_id is None:
                continue

            in_library = False
            local_id: Optional[int] = None

            match = await sync_to_async(
                lambda did=deezer_id, name=t.name, artist=t.artist_name: (
                    Song.objects.filter(
                        Q(deezer_id=did)
                        | Q(name__iexact=name, primary_artist__name__iexact=artist)
                    ).first()
                )
            )()

            if match:
                in_library = True
                local_id = match.id

            results.append(
                CatalogSearchTrack(
                    provider_id=str(deezer_id),
                    name=t.name,
                    external_url=f"https://www.deezer.com/track/{deezer_id}",
                    artist_name=t.artist_name,
                    artist_provider_id=str(t.artist_deezer_id or ""),
                    album_name=t.album_name or "",
                    album_provider_id=str(t.album_deezer_id or ""),
                    duration_ms=t.duration_ms,
                    in_library=in_library,
                    local_id=local_id,
                )
            )
        return results
