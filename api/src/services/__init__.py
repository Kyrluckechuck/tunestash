from functools import cached_property
from typing import Optional

from .album import AlbumService
from .artist import ArtistService
from .downloader import DownloaderService
from .external_list import ExternalListService
from .history import DownloadHistoryService
from .library_stats import LibraryStatsService
from .metadata_update import MetadataUpdateService
from .one_off_task import OneOffTaskService
from .periodic_task import PeriodicTaskService
from .playlist import PlaylistService
from .song import SongService
from .spotify_search import SpotifySearchService
from .task_history import TaskHistoryService
from .task_management import TaskManagementService
from .track_mapping import TrackMappingService


class ServiceRegistry:
    _instance: Optional["ServiceRegistry"] = None

    def __new__(cls) -> "ServiceRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @cached_property
    def artist(self) -> ArtistService:
        return ArtistService()

    @cached_property
    def album(self) -> AlbumService:
        return AlbumService()

    @cached_property
    def playlist(self) -> PlaylistService:
        return PlaylistService()

    @cached_property
    def history(self) -> DownloadHistoryService:
        return DownloadHistoryService()

    @cached_property
    def task_history(self) -> TaskHistoryService:
        return TaskHistoryService()

    @cached_property
    def downloader(self) -> DownloaderService:
        return DownloaderService()

    @cached_property
    def song(self) -> SongService:
        return SongService()

    @cached_property
    def task_management(self) -> TaskManagementService:
        return TaskManagementService()

    @cached_property
    def periodic_task(self) -> PeriodicTaskService:
        return PeriodicTaskService()

    @cached_property
    def spotify_search(self) -> SpotifySearchService:
        return SpotifySearchService()

    @cached_property
    def one_off_task(self) -> OneOffTaskService:
        return OneOffTaskService()

    @cached_property
    def library_stats(self) -> LibraryStatsService:
        return LibraryStatsService()

    @cached_property
    def metadata_update(self) -> MetadataUpdateService:
        return MetadataUpdateService()

    @cached_property
    def external_list(self) -> ExternalListService:
        return ExternalListService()

    @cached_property
    def track_mapping(self) -> TrackMappingService:
        return TrackMappingService()


services = ServiceRegistry()
