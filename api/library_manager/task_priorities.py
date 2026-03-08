"""
Task priority constants for Celery tasks.

This module is intentionally minimal with NO Django dependencies,
allowing it to be imported from celery_beat_schedule.py without
causing circular imports during Django settings initialization.

Priority values: Lower number = higher priority in Celery.
"""


class TaskPriority:
    """Celery task priority levels. Lower values = higher priority."""

    # User-initiated immediate operations
    PLAYLIST_DOWNLOAD = 1  # Playlist syncs - user expects these to complete first
    ALBUM_DOWNLOAD = 3  # Individual album downloads
    TRACK_DOWNLOAD = 3  # Individual track downloads

    # Background operations
    ARTIST_SYNC = 5  # Fetching album metadata from Spotify
    ARTIST_DOWNLOAD = 6  # Downloading missing albums for tracked artists
    MIGRATION = 7  # Deezer catalog migration (below resolve, above maintenance)

    # Maintenance and cleanup
    MAINTENANCE = 10  # Cleanup, validation, retry tasks
