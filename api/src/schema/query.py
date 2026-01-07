from typing import List, Optional

import strawberry

from ..graphql_types.models import (
    Album,
    AlbumConnection,
    Artist,
    ArtistConnection,
    AuthenticationStatus,
    FailureReasonCount,
    FallbackMetrics,
    HistoryConnection,
    HistoryEdge,
    LibraryStats,
    MetadataEntityType,
    MetadataUpdateConnection,
    MetadataUpdateStatus,
    MetricTimePoint,
    OneOffTask,
    PageInfo,
    PendingTask,
    PeriodicTask,
    Playlist,
    PlaylistConnection,
    QueueStatus,
    Song,
    SongConnection,
    SpotifyPlaylistInfo,
    SpotifyRateLimitStatus,
    SpotifySearchAlbum,
    SpotifySearchArtist,
    SpotifySearchPlaylist,
    SpotifySearchResults,
    SpotifySearchTrack,
    StorageStatus,
    SystemHealth,
    TaskCount,
    TaskHistoryConnection,
    TaskHistoryEdge,
)
from ..services import services


@strawberry.type
class Query:
    @strawberry.field
    async def artists(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        is_tracked: Optional[bool] = None,
        has_undownloaded: Optional[bool] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        search: Optional[str] = None,
    ) -> ArtistConnection:
        from ..services.artist import ArtistConnectionResult

        first_int: int = int(first or 20)
        result = await services.artist.get_connection(
            first=first_int,
            after=after,
            is_tracked=is_tracked,
            has_undownloaded=has_undownloaded,
            sort_by=sort_by,
            sort_direction=sort_direction,
            search=search,
        )

        # Handle both return types (tuple for ID sorting, dataclass for custom)
        end_cursor: Optional[str] = None
        if isinstance(result, ArtistConnectionResult):
            edges = result.items
            has_next_page = result.has_next_page
            total_count = result.total_count
            # For offset-based pagination, encode the offset as the cursor
            if result.end_cursor_offset is not None:
                end_cursor = services.artist.create_cursor_from_offset(
                    result.end_cursor_offset
                )
            elif edges:
                end_cursor = services.artist.create_cursor(edges[-1])
        else:
            edges, has_next_page, total_count = result
            end_cursor = services.artist.create_cursor(edges[-1]) if edges else None

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=services.artist.create_cursor(edges[0]) if edges else None,
            end_cursor=end_cursor,
        )

        return ArtistConnection(
            edges=edges, page_info=page_info, total_count=total_count
        )

    @strawberry.field
    async def artist(self, id: str) -> Optional[Artist]:
        return await services.artist.get_by_id(id)

    @strawberry.field
    async def albums(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        artist_id: Optional[int] = None,
        downloaded: Optional[bool] = None,
        wanted: Optional[bool] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        search: Optional[str] = None,
    ) -> AlbumConnection:
        first_int: int = int(first or 20)
        items, has_next_page, total_count = await services.album.get_connection(
            first=first_int,
            after=after,
            artist_id=artist_id,
            downloaded=downloaded,
            wanted=wanted,
            sort_by=sort_by,
            sort_direction=sort_direction,
            search=search,
        )

        edges = items

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=services.album.create_cursor(edges[0]) if edges else None,
            end_cursor=services.album.create_cursor(edges[-1]) if edges else None,
        )

        return AlbumConnection(
            edges=edges, page_info=page_info, total_count=total_count
        )

    @strawberry.field
    async def album(self, id: str) -> Optional[Album]:
        return await services.album.get_by_id(id)

    @strawberry.field
    async def songs(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        artist_id: Optional[int] = None,
        downloaded: Optional[bool] = None,
        unavailable: Optional[bool] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        search: Optional[str] = None,
    ) -> SongConnection:
        first_int: int = int(first or 20)
        items, has_next_page, total_count = await services.song.get_connection(
            first=first_int,
            after=after,
            artist_id=artist_id,
            downloaded=downloaded,
            unavailable=unavailable,
            sort_by=sort_by,
            sort_direction=sort_direction,
            search=search,
        )

        edges = items

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=services.song.create_cursor(edges[0]) if edges else None,
            end_cursor=services.song.create_cursor(edges[-1]) if edges else None,
        )

        return SongConnection(edges=edges, page_info=page_info, total_count=total_count)

    @strawberry.field
    async def song(self, id: str) -> Optional[Song]:
        return await services.song.get_by_id(id)

    @strawberry.field
    async def playlists(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        enabled: Optional[bool] = None,
        status: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        search: Optional[str] = None,
    ) -> PlaylistConnection:
        first_int: int = int(first or 20)
        items, has_next_page, total_count = await services.playlist.get_connection(
            first=first_int,
            after=after,
            enabled=enabled,
            status=status,
            sort_by=sort_by,
            sort_direction=sort_direction,
            search=search,
        )

        edges = items

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=None,
            end_cursor=None,
        )

        return PlaylistConnection(
            edges=edges, page_info=page_info, total_count=total_count
        )

    @strawberry.field
    async def playlist(self, id: str) -> Optional[Playlist]:
        return await services.playlist.get_by_id(id)

    @strawberry.field
    async def download_history(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        entity_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> HistoryConnection:
        first_int: int = int(first or 20)
        items, has_next_page, total_count = await services.history.get_connection(
            first=first_int, after=after, entity_type=entity_type, status=status
        )

        edges: list[HistoryEdge] = [
            HistoryEdge(node=item, cursor=services.history.create_cursor(item))
            for item in items
        ]

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
        )

        return HistoryConnection(
            edges=edges, page_info=page_info, total_count=total_count
        )

    @strawberry.field
    async def task_history(
        self,
        first: Optional[int] = 20,
        after: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        entity_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> TaskHistoryConnection:
        first_int: int = int(first or 20)
        items, has_next_page, total_count = await services.task_history.get_connection(
            first=first_int,
            after=after,
            status=status,
            type=type,
            entity_type=entity_type,
            search=search,
        )

        edges = [
            TaskHistoryEdge(node=item, cursor=services.task_history.create_cursor(item))
            for item in items
        ]

        page_info = PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
        )

        return TaskHistoryConnection(
            edges=edges, page_info=page_info, total_count=total_count
        )

    @strawberry.field
    async def queue_status(self) -> QueueStatus:
        """Get the current status of the Celery task queue."""
        status = await services.task_management.get_queue_status()

        # Convert the task_counts dict to a list of TaskCount objects
        # Filter out any null or empty task names as an additional safety measure
        task_counts = [
            TaskCount(task_name=name, count=count)
            for name, count in status["task_counts"].items()
            if name  # Skip null or empty names
        ]

        # Get pending tasks with resolved entity details
        pending_task_infos = (
            await services.task_management.get_pending_tasks_with_details()
        )
        pending_tasks = [
            PendingTask(
                task_id=t.task_id,
                task_name=t.task_name,
                display_name=t.display_name,
                entity_type=t.entity_type,
                entity_id=t.entity_id,
                entity_name=t.entity_name,
                status=t.status,
                created_at=t.created_at,
            )
            for t in pending_task_infos
        ]

        return QueueStatus(
            total_pending_tasks=status["total_pending_tasks"],
            task_counts=task_counts,
            pending_tasks=pending_tasks,
            queue_size=status["queue_size"],
        )

    @strawberry.field
    async def periodic_tasks(
        self, enabled_only: Optional[bool] = False
    ) -> List[PeriodicTask]:
        """Get all scheduled periodic tasks from Celery Beat."""
        if enabled_only:
            return await services.periodic_task.get_enabled()
        return await services.periodic_task.get_all()

    @strawberry.field
    def one_off_tasks(self) -> List[OneOffTask]:
        """Get all available one-off maintenance tasks."""
        return services.one_off_task.get_all()

    @strawberry.field
    async def system_health(self) -> SystemHealth:
        """Get overall system health including authentication status."""
        from asgiref.sync import sync_to_async

        from library_manager.models import SpotifyRateLimitState

        from ..services.system_health import SystemHealthService

        # Use thread_sensitive=True to ensure Django ORM access works correctly
        auth_status = await sync_to_async(
            SystemHealthService.check_authentication_status, thread_sensitive=True
        )()
        can_download, reason = await sync_to_async(
            SystemHealthService.is_download_capable
        )()

        # Get rate limit status and current delay
        rate_limit_data = await sync_to_async(SpotifyRateLimitState.get_status)()
        current_delay = await sync_to_async(SpotifyRateLimitState.get_delay_seconds)()

        # Get storage status
        storage_data = await sync_to_async(SystemHealthService.check_storage_status)()

        return SystemHealth(
            can_download=can_download,
            download_blocker_reason=reason,
            authentication=AuthenticationStatus(
                cookies_valid=auth_status.cookies_valid,
                cookies_error_type=auth_status.cookies_error_type,
                cookies_error_message=auth_status.cookies_error_message,
                cookies_expire_in_days=auth_status.cookies_expire_in_days,
                po_token_configured=auth_status.po_token_configured,
                po_token_valid=auth_status.po_token_valid,
                po_token_error_message=auth_status.po_token_error_message,
                spotify_user_auth_enabled=auth_status.spotify_user_auth_enabled,
                spotify_auth_mode=auth_status.spotify_auth_mode,
                spotify_token_valid=auth_status.spotify_token_valid,
                spotify_token_expired=auth_status.spotify_token_expired,
                spotify_token_expires_in_hours=auth_status.spotify_token_expires_in_hours,
                spotify_token_error_message=auth_status.spotify_token_error_message,
            ),
            spotify_rate_limit=SpotifyRateLimitStatus(
                is_rate_limited=rate_limit_data["is_rate_limited"],
                rate_limited_until=rate_limit_data["rate_limited_until"],
                seconds_until_clear=rate_limit_data["seconds_until_clear"],
                is_throttling=current_delay > 0,
                current_delay_seconds=current_delay,
                window_call_count=rate_limit_data["window_call_count"],
                window_max_calls=rate_limit_data["window_max_calls"],
                window_usage_percent=rate_limit_data["window_usage_percent"],
                burst_calls=rate_limit_data.get("burst_calls", 0),
                burst_max=rate_limit_data.get("burst_max", 25),
                sustained_calls=rate_limit_data.get("sustained_calls", 0),
                sustained_max=rate_limit_data.get("sustained_max", 100),
                hourly_calls=rate_limit_data.get("hourly_calls", 0),
                hourly_max=rate_limit_data.get("hourly_max", 600),
            ),
            storage=StorageStatus(
                path=storage_data.path,
                exists=storage_data.exists,
                is_writable=storage_data.is_writable,
                total_gb=storage_data.total_gb,
                used_gb=storage_data.used_gb,
                available_gb=storage_data.available_gb,
                usage_percent=storage_data.usage_percent,
                is_low=storage_data.is_low,
                is_critically_low=storage_data.is_critically_low,
                error_message=storage_data.error_message,
            ),
        )

    @strawberry.field
    async def spotify_search(
        self,
        query: str,
        types: Optional[List[str]] = None,
        limit: Optional[int] = 10,
    ) -> SpotifySearchResults:
        """
        Search Spotify's catalog for artists, albums, tracks, and playlists.

        This searches the Spotify API directly, not the local database.
        Results include an 'in_library' flag to indicate if items already exist locally.

        Args:
            query: Search query string
            types: List of types to search ('artist', 'album', 'track', 'playlist').
                   Defaults to all types.
            limit: Max results per type (default 10, max 50)
        """
        results = await services.spotify_search.search(
            query=query,
            types=types,
            limit=limit or 10,
        )

        # Convert service dataclasses to GraphQL types
        return SpotifySearchResults(
            artists=[
                SpotifySearchArtist(
                    id=a.id,
                    name=a.name,
                    spotify_uri=a.spotify_uri,
                    image_url=a.image_url,
                    follower_count=a.follower_count,
                    genres=a.genres,
                    in_library=a.in_library,
                    local_id=a.local_id,
                    is_tracked=a.is_tracked,
                )
                for a in results.artists
            ],
            albums=[
                SpotifySearchAlbum(
                    id=a.id,
                    name=a.name,
                    spotify_uri=a.spotify_uri,
                    image_url=a.image_url,
                    artist_name=a.artist_name,
                    artist_id=a.artist_id,
                    release_date=a.release_date,
                    album_type=a.album_type,
                    total_tracks=a.total_tracks,
                    in_library=a.in_library,
                    local_id=a.local_id,
                )
                for a in results.albums
            ],
            tracks=[
                SpotifySearchTrack(
                    id=t.id,
                    name=t.name,
                    spotify_uri=t.spotify_uri,
                    artist_name=t.artist_name,
                    artist_id=t.artist_id,
                    album_name=t.album_name,
                    album_id=t.album_id,
                    duration_ms=t.duration_ms,
                    in_library=t.in_library,
                    local_id=t.local_id,
                )
                for t in results.tracks
            ],
            playlists=[
                SpotifySearchPlaylist(
                    id=p.id,
                    name=p.name,
                    spotify_uri=p.spotify_uri,
                    image_url=p.image_url,
                    owner_name=p.owner_name,
                    track_count=p.track_count,
                    description=p.description,
                    in_library=p.in_library,
                    local_id=p.local_id,
                )
                for p in results.playlists
            ],
        )

    @strawberry.field
    async def spotify_playlist_info(self, url: str) -> Optional[SpotifyPlaylistInfo]:
        """
        Fetch playlist metadata from Spotify by URL or URI.

        Used by the frontend to auto-populate playlist name when creating a new playlist.
        Does not create any database records.

        Args:
            url: Spotify playlist URL or URI (e.g., "spotify:playlist:..." or
                 "https://open.spotify.com/playlist/...")

        Returns:
            Playlist info (name, owner, track count, image) or null if not found
        """
        result = await services.playlist.get_spotify_playlist_info(url)
        if result is None:
            return None

        return SpotifyPlaylistInfo(
            name=result["name"],
            owner_name=result.get("owner_name"),
            track_count=result.get("track_count", 0),
            image_url=result.get("image_url"),
        )

    @strawberry.field
    async def library_stats(self) -> LibraryStats:
        """
        Get aggregate statistics for the music library.

        Returns counts of songs, albums, and artists with download completion metrics.
        Includes "desired" metrics based on tracked artists.
        """
        stats = await services.library_stats.get_stats()

        return LibraryStats(
            total_songs=stats.total_songs,
            downloaded_songs=stats.downloaded_songs,
            missing_songs=stats.missing_songs,
            failed_songs=stats.failed_songs,
            unavailable_songs=stats.unavailable_songs,
            total_albums=stats.total_albums,
            downloaded_albums=stats.downloaded_albums,
            partial_albums=stats.partial_albums,
            missing_albums=stats.missing_albums,
            total_artists=stats.total_artists,
            tracked_artists=stats.tracked_artists,
            song_completion_percentage=stats.song_completion_percentage,
            album_completion_percentage=stats.album_completion_percentage,
            desired_songs=stats.desired_songs,
            desired_downloaded=stats.desired_downloaded,
            desired_missing=stats.desired_missing,
            desired_failed=stats.desired_failed,
            desired_unavailable=stats.desired_unavailable,
            desired_completion_percentage=stats.desired_completion_percentage,
            desired_albums=stats.desired_albums,
            desired_albums_downloaded=stats.desired_albums_downloaded,
            desired_albums_partial=stats.desired_albums_partial,
            desired_albums_missing=stats.desired_albums_missing,
            desired_album_completion_percentage=stats.desired_album_completion_percentage,
        )

    @strawberry.field
    async def pending_metadata_updates(
        self,
        entity_type: Optional[MetadataEntityType] = None,
        status: Optional[MetadataUpdateStatus] = None,
        include_resolved: bool = False,
    ) -> MetadataUpdateConnection:
        """
        Get pending metadata updates detected from Spotify.

        Returns a list of detected name changes for artists, albums, and songs
        that the user can choose to apply or dismiss.

        Args:
            entity_type: Filter by entity type (ARTIST, ALBUM, SONG)
            status: Filter by status (PENDING, APPLIED, DISMISSED)
            include_resolved: If True, include applied/dismissed updates; if False, only pending
        """
        return await services.metadata_update.get_pending_updates(
            entity_type=entity_type,
            status=status,
            include_resolved=include_resolved,
        )

    @strawberry.field
    async def fallback_metrics(self, days: Optional[int] = 7) -> FallbackMetrics:
        """
        Get aggregated metrics for the fallback download provider (Tidal).

        Returns success/failure counts, success rate percentage, time series
        data for charting, and breakdown of failure reasons.

        Args:
            days: Number of days to look back (default 7)
        """
        from asgiref.sync import sync_to_async

        from src.services.metrics import MetricsService

        data = await sync_to_async(MetricsService.get_fallback_metrics)(days or 7)

        return FallbackMetrics(
            total_attempts=data["total_attempts"],
            total_successes=data["total_successes"],
            total_failures=data["total_failures"],
            success_rate=data["success_rate"],
            time_series=[
                MetricTimePoint(
                    timestamp=point["timestamp"],
                    value=point["value"],
                    count=point["count"],
                )
                for point in data["time_series"]
            ],
            failure_reasons=[
                FailureReasonCount(reason=r["reason"], count=r["count"])
                for r in data["failure_reasons"]
            ],
        )
