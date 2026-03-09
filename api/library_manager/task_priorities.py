"""
Task priority constants for Celery tasks.

This module is intentionally minimal with NO Django dependencies,
allowing it to be imported from celery_beat_schedule.py without
causing circular imports during Django settings initialization.

Priority values: Lower number = higher priority in Celery.

NOTE: The PostgreSQL broker (kombu Django transport) uses FIFO ordering,
so these priorities are NOT enforced at the broker level. Instead, they
serve as documentation of intended ordering and are used for application-
level decisions (e.g., queuing tracked artists before untracked ones).
"""


class TaskPriority:
    """Celery task priority levels. Lower values = higher priority."""

    # User-initiated immediate operations
    PLAYLIST_DOWNLOAD = 1  # Playlist syncs - user expects these to complete first
    ALBUM_DOWNLOAD = 3  # Individual album downloads
    TRACK_DOWNLOAD = 3  # Individual track downloads

    # Migration operations
    RESOLVE = 4  # Artist deezer_id linking

    # Background operations
    ARTIST_SYNC = 5  # Fetching album metadata
    ARTIST_DOWNLOAD = 6  # Downloading missing albums for tracked artists
    MIGRATION = 7  # Deezer catalog migration (tracked queued first via FIFO)

    # Maintenance and cleanup
    MAINTENANCE = 10  # Cleanup, validation, retry tasks
