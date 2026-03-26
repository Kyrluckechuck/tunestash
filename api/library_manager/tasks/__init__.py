"""Celery tasks for the Tunestash.

This package contains all Celery tasks organized by functionality:
- artist: Artist synchronization and fetching
- playlist: Playlist synchronization
- download: Album and song download operations
- maintenance: Cleanup, retry, and validation tasks
- periodic: Scheduled periodic tasks
- core: Shared utilities and helper functions

All tasks are re-exported here for backwards compatibility.
"""

# Re-export artist tasks
from .artist import (
    fetch_all_albums_for_artist,
)

# Re-export core utilities
from .core import (
    TaskPriority,
    celery_app,
    check_and_update_progress,
    check_task_cancellation,
    complete_task,
    create_task_history,
    log_memory_usage,
    logger,
    normalize_name,
    require_download_capability,
    update_task_heartbeat,
    update_task_progress,
)

# Re-export Deezer tasks
from .deezer import (
    fetch_artist_albums_from_deezer,
)

# Re-export diagnostic tasks
from .diagnostics import (
    memory_compare_before_after,
    memory_profile_after_init,
    memory_profile_worker,
    periodic_memory_health_check,
    profile_parent_process,
)

# Re-export download tasks
from .download import (
    download_album_by_deezer_id,
    download_album_by_spotify_id,
    download_deezer_track,
    download_extra_album_types_for_artist,
    download_missing_albums_for_artist,
    download_playlist,
    download_single_album,
    download_single_track,
    download_track_by_spotify_gid,
)

# Re-export external list tasks
from .external_list import (
    cleanup_mapping_cache,
    map_external_list_tracks,
    retry_failed_external_mappings,
    sync_all_external_lists,
    sync_external_list,
)

# Re-export maintenance tasks
from .maintenance import (
    backfill_album_tracks,
    backfill_lyrics_status,
    backfill_song_album,
    backfill_song_isrc,
    cleanup_app_metrics,
    cleanup_appears_on_albums,
    cleanup_celery_history,
    cleanup_orphaned_albums,
    cleanup_stuck_tasks_periodic,
    merge_duplicate_songs,
    repair_misassigned_songs,
    retry_all_missing_known_songs,
    retry_failed_songs,
    retry_failed_songs_for_artist,
    validate_undownloaded_songs,
)

# Re-export metadata tasks
from .metadata import (
    apply_metadata_update,
    cleanup_old_files,
)

# Re-export migration tasks
from .migration import (
    migrate_artist_to_deezer,
    resolve_all_artists_to_deezer,
)

# Re-export notification tasks
from .notification import (
    check_notifications,
    send_test_notification,
)

# Re-export periodic tasks
from .periodic import (
    queue_missing_albums_for_tracked_artists,
    retry_missing_lyrics,
    scan_new_releases_for_tracked_artists,
    sync_tracked_artists_metadata,
    sync_tracked_playlists,
    trigger_navidrome_rescan,
)

# Re-export playlist tasks
from .playlist import (
    _sync_tracked_playlist_internal,
    sync_deezer_playlist,
    sync_tracked_playlist,
    sync_tracked_playlist_artists,
)

# Re-export upgrade tasks
from .upgrade import (
    upgrade_low_quality_songs,
)

__all__ = [
    # Core utilities
    "TaskPriority",
    "celery_app",
    "check_and_update_progress",
    "check_task_cancellation",
    "complete_task",
    "create_task_history",
    "log_memory_usage",
    "logger",
    "normalize_name",
    "require_download_capability",
    "update_task_heartbeat",
    "update_task_progress",
    # Artist tasks
    "fetch_all_albums_for_artist",
    # Playlist tasks
    "_sync_tracked_playlist_internal",
    "sync_deezer_playlist",
    "sync_tracked_playlist",
    "sync_tracked_playlist_artists",
    # Download tasks
    "download_album_by_deezer_id",
    "download_album_by_spotify_id",
    "download_deezer_track",
    "download_extra_album_types_for_artist",
    "download_missing_albums_for_artist",
    "download_playlist",
    "download_single_album",
    "download_single_track",
    "download_track_by_spotify_gid",
    # Maintenance tasks
    "backfill_album_tracks",
    "backfill_lyrics_status",
    "backfill_song_album",
    "backfill_song_isrc",
    "cleanup_app_metrics",
    "cleanup_appears_on_albums",
    "cleanup_celery_history",
    "cleanup_orphaned_albums",
    "cleanup_stuck_tasks_periodic",
    "merge_duplicate_songs",
    "repair_misassigned_songs",
    "retry_all_missing_known_songs",
    "retry_failed_songs",
    "retry_failed_songs_for_artist",
    "validate_undownloaded_songs",
    # Periodic tasks
    "queue_missing_albums_for_tracked_artists",
    "retry_missing_lyrics",
    "scan_new_releases_for_tracked_artists",
    "sync_tracked_artists_metadata",
    "sync_tracked_playlists",
    "trigger_navidrome_rescan",
    # Metadata tasks
    "apply_metadata_update",
    "cleanup_old_files",
    # Diagnostic tasks
    "memory_compare_before_after",
    "memory_profile_after_init",
    "memory_profile_worker",
    "periodic_memory_health_check",
    "profile_parent_process",
    # Notification tasks
    "check_notifications",
    "send_test_notification",
    # External list tasks
    "cleanup_mapping_cache",
    "map_external_list_tracks",
    "retry_failed_external_mappings",
    "sync_all_external_lists",
    "sync_external_list",
    # Migration tasks
    "migrate_artist_to_deezer",
    "resolve_all_artists_to_deezer",
    # Deezer tasks
    "fetch_artist_albums_from_deezer",
    # Upgrade tasks
    "upgrade_low_quality_songs",
]
