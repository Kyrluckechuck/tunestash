import re
from typing import List, Optional
from urllib.parse import urlparse

import strawberry
from asgiref.sync import sync_to_async

from ..graphql_types.models import (
    Album,
    Artist,
    ExternalListType,
    MetadataCheckResult,
    MutationResult,
    PeriodicTask,
    Playlist,
    TrackPlaylistInput,
    UpdateAlbumInput,
    UpdateArtistInput,
)
from ..graphql_types.settings import (
    CookieUploadResult,
    UpdateSettingResult,
    YamlMigrationResult,
    dict_to_setting_type,
)
from ..services import services


# pylint: disable-next=too-many-return-statements
def validate_url(
    url: str,
) -> MutationResult:
    """Validate URL format and scheme. Accepts both HTTP URLs and Spotify URIs."""
    if not url or not url.strip():
        return MutationResult(success=False, message="URL cannot be empty")

    url = url.strip()

    # Accept Spotify URIs in format: spotify:type:id
    # Valid types: artist, album, track, playlist
    if url.startswith("spotify:"):
        spotify_uri_pattern = r"^spotify:(artist|album|track|playlist):[a-zA-Z0-9]+$"
        if re.match(spotify_uri_pattern, url):
            return MutationResult(success=True, message="URL valid")
        return MutationResult(
            success=False,
            message="Invalid Spotify URI format. Expected: spotify:type:id",
        )

    # Accept HTTP/HTTPS URLs
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return MutationResult(success=False, message="Invalid URL format")
        if parsed.scheme not in ("http", "https"):
            return MutationResult(
                success=False, message="URL must use http or https scheme"
            )
        return MutationResult(success=True, message="URL valid")
    except Exception:
        return MutationResult(success=False, message="Invalid URL format")


def validate_name(name: str, field_name: str = "Name") -> MutationResult:
    """Validate name length and content."""
    if not name or not name.strip():
        return MutationResult(success=False, message=f"{field_name} cannot be empty")

    name = name.strip()
    if len(name) > 255:
        return MutationResult(
            success=False, message=f"{field_name} cannot exceed 255 characters"
        )

    return MutationResult(success=True, message=f"{field_name} valid")


def validate_task_name(task_name: str) -> MutationResult:
    """Validate task name format."""
    if not task_name or not task_name.strip():
        return MutationResult(success=False, message="Task name cannot be empty")

    task_name = task_name.strip()
    # Allow alphanumeric, dots, underscores, and hyphens
    if not re.match(r"^[a-zA-Z0-9._-]+$", task_name):
        return MutationResult(
            success=False,
            message="Task name can only contain letters, numbers, dots, underscores, and hyphens",
        )

    return MutationResult(success=True, message="Task name valid")


@strawberry.type
class Mutation:  # pylint: disable=too-many-public-methods
    @strawberry.mutation
    async def link_artist_to_deezer(
        self, artist_id: int, deezer_id: int
    ) -> "MutationResult":
        return await services.artist.link_to_deezer(
            artist_id=artist_id, deezer_id=deezer_id
        )

    @strawberry.mutation
    async def import_artist(self, deezer_id: int, name: str) -> "MutationResult":
        """Import an artist from Deezer search and start tracking."""
        return await services.artist.import_from_deezer(deezer_id=deezer_id, name=name)

    @strawberry.mutation
    async def import_album(self, deezer_id: int) -> "MutationResult":
        """Import an album from Deezer search into the library."""
        return await services.album.import_from_deezer(deezer_id=deezer_id)

    @strawberry.mutation
    async def track_artist(self, artist_id: int) -> "MutationResult":
        return await services.artist.track_artist(artist_id=artist_id)

    @strawberry.mutation
    async def untrack_artist(self, artist_id: int) -> "MutationResult":
        return await services.artist.untrack_artist(artist_id=artist_id)

    @strawberry.mutation
    async def update_artist(self, input: UpdateArtistInput) -> Artist:
        return await services.artist.update_artist(
            artist_id=input.artist_id,
            tracking_tier=input.tracking_tier,
            auto_download=input.auto_download,
        )

    @strawberry.mutation
    async def set_album_wanted(self, album_id: int, wanted: bool) -> "MutationResult":
        return await services.album.set_album_wanted(album_id=album_id, wanted=wanted)

    @strawberry.mutation
    async def update_album(self, input: UpdateAlbumInput) -> Album:
        return await services.album.update_album(
            album_id=input.album_id, is_wanted=input.is_wanted
        )

    @strawberry.mutation
    async def toggle_playlist(self, playlist_id: int) -> "MutationResult":
        return await services.playlist.toggle_playlist(playlist_id=playlist_id)

    @strawberry.mutation
    async def toggle_playlist_auto_track(self, playlist_id: int) -> "MutationResult":
        return await services.playlist.toggle_playlist_auto_track(
            playlist_id=playlist_id
        )

    @strawberry.mutation
    async def toggle_playlist_m3u(self, playlist_id: int) -> "MutationResult":
        return await services.playlist.toggle_playlist_m3u(playlist_id=playlist_id)

    @strawberry.mutation
    async def delete_playlist(self, playlist_id: int) -> "MutationResult":
        """Delete a tracked playlist from the database."""
        return await services.playlist.delete_playlist(playlist_id=playlist_id)

    @strawberry.mutation
    async def track_playlist(self, input: TrackPlaylistInput) -> Playlist:
        return await services.playlist.track_playlist(
            playlist_id=input.playlist_id, auto_track_tier=input.auto_track_tier
        )

    @strawberry.mutation
    async def update_playlist(
        self,
        playlist_id: int,
        name: str,
        url: str,
        auto_track_tier: Optional[int] = None,
    ) -> "MutationResult":
        name_validation = validate_name(name, "Playlist name")
        if not name_validation.success:
            return name_validation

        url_validation = validate_url(url)
        if not url_validation.success:
            return url_validation

        return await services.playlist.update_playlist(
            playlist_id=playlist_id,
            name=name.strip(),
            url=url.strip(),
            auto_track_tier=auto_track_tier,
        )

    @strawberry.mutation
    async def sync_artist(self, artist_id: str) -> Artist:
        return await services.artist.sync_artist(artist_id)

    @strawberry.mutation
    async def download_artist(self, artist_id: str) -> "MutationResult":
        return await services.artist.download_artist(artist_id)

    @strawberry.mutation
    async def retry_failed_songs(self, artist_id: str) -> "MutationResult":
        """Retry downloading failed songs for an artist, ignoring backoff periods."""
        return await services.artist.retry_failed_songs(artist_id)

    @strawberry.mutation
    async def sync_playlist(
        self, playlist_id: int, force: bool = False, recheck: bool = False
    ) -> "MutationResult":
        return await services.playlist.sync_playlist(
            playlist_id, force=force, recheck=recheck
        )

    @strawberry.mutation
    async def download_album(self, album_id: str) -> Album:
        return await services.album.download_album(album_id)

    @strawberry.mutation
    async def download_url(
        self, url: str, auto_track_tier: Optional[int] = None
    ) -> "MutationResult":
        validation_result = validate_url(url)
        if not validation_result.success:
            return validation_result

        return await services.downloader.download_url(
            url=url.strip(), auto_track_tier=auto_track_tier
        )

    @strawberry.mutation
    async def create_playlist(
        self, name: str, url: str, auto_track_tier: Optional[int] = None
    ) -> Playlist:
        name_validation = validate_name(name, "Playlist name")
        if not name_validation.success:
            # Return a failure result as a Playlist-like response (this will need error handling)
            raise ValueError(name_validation.message)

        url_validation = validate_url(url)
        if not url_validation.success:
            raise ValueError(url_validation.message)

        return await services.playlist.create_playlist(
            name=name.strip(), url=url.strip(), auto_track_tier=auto_track_tier
        )

    @strawberry.mutation
    async def save_deezer_playlist(
        self, deezer_id: str, auto_track_tier: Optional[int] = None
    ) -> Playlist:
        """Save a playlist by its Deezer ID for ongoing tracking."""
        return await services.playlist.save_playlist_by_deezer_id(
            deezer_id=deezer_id.strip(), auto_track_tier=auto_track_tier
        )

    @strawberry.mutation
    async def cancel_all_pending_tasks(self) -> "MutationResult":
        """Cancel all pending tasks in the Celery queue."""
        return await services.task_management.cancel_all_pending_tasks()

    @strawberry.mutation
    async def cancel_tasks_by_name(self, task_name: str) -> "MutationResult":
        """Cancel all pending tasks with a specific name."""
        validation_result = validate_task_name(task_name)
        if not validation_result.success:
            return validation_result

        return await services.task_management.cancel_tasks_by_name(
            task_name=task_name.strip()
        )

    @strawberry.mutation
    async def cancel_running_tasks_by_name(self, task_name: str) -> "MutationResult":
        """Cancel running tasks with a specific name."""
        validation_result = validate_task_name(task_name)
        if not validation_result.success:
            return validation_result

        return await services.task_management.cancel_running_tasks_by_name(
            task_name=task_name.strip()
        )

    @strawberry.mutation
    async def cancel_all_tasks(self) -> "MutationResult":
        """Cancel both pending and running tasks."""
        return await services.task_management.cancel_all_tasks()

    @strawberry.mutation
    async def cancel_task_by_id(self, task_id: str) -> "MutationResult":
        """Cancel a single task by its ID."""
        if not task_id or not task_id.strip():
            return MutationResult(success=False, message="Task ID cannot be empty")
        return await services.task_management.cancel_task_by_id(task_id.strip())

    @strawberry.mutation
    async def sync_all_tracked_artists(self) -> "MutationResult":
        """Sync all tracked artists in batch."""
        try:
            from library_manager.helpers import enqueue_artist_sync_with_download
            from library_manager.models import Artist

            tracked_artists: list = await sync_to_async(list)(
                Artist.objects.filter(tracking_tier__gte=1)
            )

            if not tracked_artists:
                return MutationResult(
                    success=True, message="No tracked artists found to sync"
                )

            # Use database IDs for batch operations with sync_to_async
            operation_counts = await sync_to_async(enqueue_artist_sync_with_download)(
                Artist.objects.filter(tracking_tier__gte=1),
                auto_download=False,  # Only sync album info, no downloads
                delay_seconds=0,
            )

            total_operations = sum(operation_counts.values())
            return MutationResult(
                success=True,
                message=f"Enqueued {total_operations} operations for {len(tracked_artists)} tracked artists",
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to sync tracked artists: {str(e)}"
            )

    @strawberry.mutation
    async def batch_artist_operations(
        self, artist_ids: List[int], operations: Optional[List[str]] = None
    ) -> "MutationResult":
        """Perform batch operations on multiple artists using database IDs."""
        try:
            from library_manager.helpers import enqueue_batch_artist_operations
            from library_manager.models import Artist

            if not artist_ids:
                return MutationResult(success=False, message="No artist IDs provided")

            # Get artists by database IDs
            artists: list = await sync_to_async(list)(
                Artist.objects.filter(id__in=artist_ids)
            )

            if not artists:
                return MutationResult(
                    success=False, message="No artists found with provided IDs"
                )

            # Default operations if none specified
            if operations is None:
                operations = ["fetch", "download"]

            # Use database IDs for batch operations with sync_to_async
            operation_counts = await sync_to_async(enqueue_batch_artist_operations)(
                Artist.objects.filter(id__in=artist_ids), operations=operations
            )

            total_operations = sum(operation_counts.values())
            return MutationResult(
                success=True,
                message=f"Enqueued {total_operations} operations for {len(artists)} artists",
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to enqueue batch operations: {str(e)}"
            )

    @strawberry.mutation
    async def download_all_tracked_artists(self) -> "MutationResult":
        """Download all missing albums for all tracked artists."""
        try:
            from library_manager.helpers import download_missing_tracked_artists
            from library_manager.models import Artist

            tracked_artists: list = await sync_to_async(list)(
                Artist.objects.filter(tracking_tier__gte=1)
            )

            if not tracked_artists:
                return MutationResult(
                    success=True, message="No tracked artists found to download"
                )

            # Enqueue download tasks for all tracked artists
            # (uses TaskPriority.ARTIST_DOWNLOAD by default)
            await sync_to_async(download_missing_tracked_artists)(
                already_enqueued_artists=[],
                artists_to_enqueue=tracked_artists,
            )

            return MutationResult(
                success=True,
                message=f"Enqueued download tasks for {len(tracked_artists)} tracked artists",
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to download tracked artists: {str(e)}"
            )

    @strawberry.mutation
    async def download_all_playlists(self) -> "MutationResult":
        """Download all enabled tracked playlists."""
        try:
            from library_manager.helpers import enqueue_playlists
            from library_manager.models import TrackedPlaylist

            enabled_playlists: list = await sync_to_async(list)(
                TrackedPlaylist.objects.filter(enabled=True)
            )

            if not enabled_playlists:
                return MutationResult(
                    success=True, message="No enabled playlists found to download"
                )

            # Enqueue download tasks for all enabled playlists
            # (uses TaskPriority.PLAYLIST_DOWNLOAD by default - higher priority)
            await sync_to_async(enqueue_playlists)(
                playlists_to_enqueue=enabled_playlists
            )

            return MutationResult(
                success=True,
                message=f"Enqueued download tasks for {len(enabled_playlists)} playlists",
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to download playlists: {str(e)}"
            )

    @strawberry.mutation
    async def disconnect_spotify(self) -> MutationResult:
        """Disconnect Spotify OAuth account by removing stored tokens."""
        try:
            from library_manager.models import SpotifyOAuthToken

            await sync_to_async(SpotifyOAuthToken.objects.filter(id=1).delete)()
            return MutationResult(
                success=True, message="Spotify account disconnected successfully"
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to disconnect: {str(e)}"
            )

    @strawberry.mutation
    async def set_periodic_task_enabled(
        self, task_id: int, enabled: bool
    ) -> PeriodicTask:
        """Enable or disable a periodic task.

        Core tasks (cleanup, stale task detection) cannot be disabled.
        """
        result = await services.periodic_task.toggle_enabled(task_id, enabled)
        if result is None:
            raise ValueError("Task not found or is a core task that cannot be toggled")
        return result

    @strawberry.mutation
    async def run_periodic_task_now(self, task_id: int) -> MutationResult:
        """Queue a periodic task to run immediately."""
        success = await services.periodic_task.run_now(task_id)
        if success:
            return MutationResult(
                success=True, message="Task queued for immediate execution"
            )
        return MutationResult(
            success=False, message="Task not found or could not be queued"
        )

    @strawberry.mutation
    async def run_one_off_task(self, task_id: str) -> MutationResult:
        """Queue a one-off maintenance task for execution."""
        if not task_id or not task_id.strip():
            return MutationResult(success=False, message="Task ID cannot be empty")
        return await services.one_off_task.run_task(task_id.strip())

    # =========================================================================
    # Metadata Update Mutations
    # =========================================================================

    @strawberry.mutation
    async def apply_metadata_update(self, update_id: int) -> MutationResult:
        """
        Apply a pending metadata update.

        This queues re-downloads for all affected songs and updates the
        entity's name in the database. Old files will be cleaned up after
        the new files are downloaded.
        """
        success, message = await services.metadata_update.apply_update(update_id)
        return MutationResult(success=success, message=message)

    @strawberry.mutation
    async def dismiss_metadata_update(self, update_id: int) -> MutationResult:
        """
        Dismiss a pending metadata update.

        This marks the update as dismissed. The user has chosen not to apply
        this change. If detected again later (e.g., Spotify changed again),
        the update will be re-shown.
        """
        success, message = await services.metadata_update.dismiss_update(update_id)
        return MutationResult(success=success, message=message)

    @strawberry.mutation
    async def apply_all_metadata_updates(self) -> MutationResult:
        """
        Apply all pending metadata updates.

        This queues re-downloads for all affected songs across all pending
        updates. Use with caution as this may trigger many re-downloads.
        """
        success, message, _ = await services.metadata_update.apply_all_pending()
        return MutationResult(success=success, message=message)

    @strawberry.mutation
    async def check_artist_metadata(self, artist_id: int) -> MetadataCheckResult:
        """
        Check if an artist's metadata has changed on Spotify.

        Makes an API call to Spotify to get the current artist name and
        compares it to the stored value. If different, creates a pending
        metadata update.
        """
        return await services.metadata_update.check_artist_metadata(artist_id)

    @strawberry.mutation
    async def check_album_metadata(self, album_id: int) -> MetadataCheckResult:
        """
        Check if an album's metadata has changed on Spotify.

        Makes an API call to Spotify to get the current album name and
        compares it to the stored value. If different, creates a pending
        metadata update.
        """
        return await services.metadata_update.check_album_metadata(album_id)

    # =========================================================================
    # External List Mutations
    # =========================================================================

    @strawberry.mutation
    async def create_external_list(
        self,
        source: str,
        list_type: str,
        username: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        auto_track_tier: Optional[int] = None,
    ) -> ExternalListType:
        """Create a new external music list (Last.fm or ListenBrainz)."""
        return await services.external_list.create_external_list(
            source=source.strip(),
            list_type=list_type.strip(),
            username=username.strip(),
            period=period,
            list_identifier=list_identifier,
            auto_track_tier=auto_track_tier,
        )

    @strawberry.mutation
    async def update_external_list(
        self,
        list_id: int,
        name: Optional[str] = None,
        username: Optional[str] = None,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
    ) -> MutationResult:
        """Update an external list's editable fields (source and type are immutable)."""
        return await services.external_list.update_external_list(
            list_id,
            name=name,
            username=username,
            period=period,
            list_identifier=list_identifier,
        )

    @strawberry.mutation
    async def delete_external_list(self, list_id: int) -> MutationResult:
        """Delete an external list and its track records."""
        return await services.external_list.delete_external_list(list_id)

    @strawberry.mutation
    async def toggle_external_list(self, list_id: int) -> MutationResult:
        """Toggle an external list between active and disabled."""
        return await services.external_list.toggle_external_list(list_id)

    @strawberry.mutation
    async def toggle_external_list_auto_track(self, list_id: int) -> MutationResult:
        """Toggle auto-track artists for an external list."""
        return await services.external_list.toggle_auto_track(list_id)

    @strawberry.mutation
    async def sync_external_list(
        self, list_id: int, force: bool = False
    ) -> MutationResult:
        """Queue a sync for an external list."""
        return await services.external_list.sync_external_list(list_id, force=force)

    @strawberry.mutation
    async def sync_all_external_lists(self) -> MutationResult:
        """Queue sync for all active external lists."""
        return await services.external_list.sync_all_external_lists()

    @strawberry.mutation
    async def check_song_metadata(self, song_id: int) -> MetadataCheckResult:
        """
        Check if a song's metadata has changed on Spotify.

        Makes an API call to Spotify to get the current song name and
        compares it to the stored value. If different, creates a pending
        metadata update.
        """
        return await services.metadata_update.check_song_metadata(song_id)

    # =========================================================================
    # Settings Mutations
    # =========================================================================

    @strawberry.mutation
    async def update_app_setting(self, key: str, value: str) -> UpdateSettingResult:
        """Update an application setting."""
        try:
            result = await services.settings.update_setting(key, value)
            return UpdateSettingResult(
                success=True,
                message="Setting updated",
                setting=dict_to_setting_type(result),
            )
        except ValueError as e:
            return UpdateSettingResult(success=False, message=str(e))

    @strawberry.mutation
    async def reset_app_setting(self, key: str) -> UpdateSettingResult:
        """Reset an application setting to its default value."""
        try:
            result = await services.settings.reset_setting(key)
            return UpdateSettingResult(
                success=True,
                message="Setting reset to default",
                setting=dict_to_setting_type(result),
            )
        except ValueError as e:
            return UpdateSettingResult(success=False, message=str(e))

    @strawberry.mutation
    async def upload_cookie_file(self, content: str) -> CookieUploadResult:
        """Upload YouTube Music cookie file content."""
        result = await services.settings.upload_cookie_file(content)
        if result.get("success"):
            return CookieUploadResult(
                success=True, message="Cookie file uploaded successfully"
            )
        return CookieUploadResult(
            success=False,
            message=result.get("error", "Failed to upload cookie file"),
        )

    @strawberry.mutation
    async def migrate_settings_from_yaml(self) -> YamlMigrationResult:
        """Migrate settings from settings.yaml to the database."""
        result = await services.settings.migrate_from_yaml()
        return YamlMigrationResult(
            success=result.get("success", False),
            migrated=result.get("migrated", 0),
            skipped=result.get("skipped", 0),
            message=result.get("message", result.get("error", "Unknown error")),
        )
