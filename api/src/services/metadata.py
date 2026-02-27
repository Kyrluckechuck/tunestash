"""Metadata service — async wrapper around MetadataProvider implementations."""

from typing import Optional, Union

from asgiref.sync import sync_to_async

from ..providers.deezer import DeezerMetadataProvider
from ..providers.metadata_base import (
    AlbumResult,
    ArtistResult,
    MetadataProvider,
    TrackResult,
)


class MetadataService:
    """Async service wrapping a synchronous MetadataProvider.

    All provider methods are sync (simple HTTP calls); this service adds
    the sync_to_async boundary needed by GraphQL resolvers and async services.
    """

    def __init__(self, provider: Optional[MetadataProvider] = None) -> None:
        self._provider = provider or DeezerMetadataProvider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def search_artists(self, query: str, limit: int = 10) -> list[ArtistResult]:
        return await sync_to_async(self._provider.search_artists)(query, limit)

    async def search_albums(self, query: str, limit: int = 10) -> list[AlbumResult]:
        return await sync_to_async(self._provider.search_albums)(query, limit)

    async def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        return await sync_to_async(self._provider.search_tracks)(query, limit)

    async def get_artist(self, provider_id: Union[int, str]) -> Optional[ArtistResult]:
        return await sync_to_async(self._provider.get_artist)(provider_id)

    async def get_artist_albums(
        self, provider_id: Union[int, str], limit: int = 100
    ) -> list[AlbumResult]:
        return await sync_to_async(self._provider.get_artist_albums)(provider_id, limit)

    async def get_album(self, provider_id: Union[int, str]) -> Optional[AlbumResult]:
        return await sync_to_async(self._provider.get_album)(provider_id)

    async def get_album_tracks(self, provider_id: Union[int, str]) -> list[TrackResult]:
        return await sync_to_async(self._provider.get_album_tracks)(provider_id)

    async def get_track(self, provider_id: Union[int, str]) -> Optional[TrackResult]:
        return await sync_to_async(self._provider.get_track)(provider_id)

    async def get_track_by_isrc(self, isrc: str) -> Optional[TrackResult]:
        return await sync_to_async(self._provider.get_track_by_isrc)(isrc)
