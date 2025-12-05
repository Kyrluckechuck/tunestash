"""Playlist tasks for the Spotify library manager."""

from typing import Any, Optional

from celery_app import app as celery_app
from downloader.spotipy_tasks import track_artists_in_playlist

from ..models import TrackedPlaylist
from .core import logger


@celery_app.task(bind=True, name="library_manager.tasks.sync_tracked_playlist")
def sync_tracked_playlist(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """
    Sync a tracked playlist by downloading it directly.

    This task runs the download synchronously rather than re-queuing,
    which avoids task deduplication issues and unnecessary overhead.
    """
    # Use the Celery task ID if no task_id is provided
    if task_id is None:
        task_id = self.request.id

    # Get the playlist object from the ID
    try:
        tracked_playlist = TrackedPlaylist.objects.get(id=playlist_id)
    except TrackedPlaylist.DoesNotExist:
        logger.warning(
            f"TrackedPlaylist with ID {playlist_id} does not exist. Skipping task."
        )
        return

    # Import here to avoid circular imports
    from .download import download_playlist

    # Call download_playlist directly (synchronously) instead of re-queuing
    # Pass None for self since we're calling it as a regular function, not as a task
    # The task_id ensures TaskHistory tracking works correctly
    logger.info(
        f"[SYNC] Starting direct download for playlist: {tracked_playlist.name} "
        f"(url={tracked_playlist.url}, task_id={task_id})"
    )
    download_playlist.run(
        playlist_url=tracked_playlist.url,
        tracked=tracked_playlist.auto_track_artists,
        task_id=task_id,
    )


@celery_app.task(bind=True, name="library_manager.tasks.sync_tracked_playlist_artists")
def sync_tracked_playlist_artists(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """Track artists from a playlist without downloading it."""
    try:
        playlist = TrackedPlaylist.objects.get(id=playlist_id)
    except TrackedPlaylist.DoesNotExist:
        logger.warning(
            f"TrackedPlaylist with ID {playlist_id} does not exist. Skipping task."
        )
        return

    track_artists_in_playlist(playlist.url, task_id)
