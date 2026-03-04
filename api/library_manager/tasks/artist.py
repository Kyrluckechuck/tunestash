"""Artist tasks for the Spotify library manager."""

from typing import Any, Optional

from django.conf import settings
from django.db.models.functions import Now
from django.utils import timezone

from celery_app import app as celery_app

from .. import helpers
from ..models import (
    ALBUM_GROUPS_TO_IGNORE,
    ALBUM_TYPES_TO_DOWNLOAD,
    Artist,
    DownloadHistory,
)
from .core import (
    complete_task,
    create_task_history,
    logger,
    update_task_progress,
)
from .deezer import _fetch_albums_via_deezer


@celery_app.task(bind=True, name="library_manager.tasks.fetch_all_albums_for_artist")
def fetch_all_albums_for_artist(self: Any, artist_id: int) -> None:
    task_history = None
    try:
        try:
            artist = Artist.objects.get(id=artist_id)
        except Artist.DoesNotExist:
            logger.warning(f"Artist with ID {artist_id} does not exist. Skipping task.")
            return

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="FETCH",
            entity_id=str(artist.deezer_id or artist.gid or artist.id),
            entity_type="ARTIST",
            task_name="fetch_all_albums_for_artist",
        )
        update_task_progress(
            task_history, 0.0, f"Starting fetch for artist {artist.name}"
        )
        task_history.status = "RUNNING"
        task_history.save()

        if not artist.deezer_id:
            msg = (
                f"Artist {artist.name} (id={artist.id}) has no deezer_id. "
                f"Run catalog migration first."
            )
            logger.warning(msg)
            complete_task(task_history, success=False, error_message=msg)
            return

        update_task_progress(
            task_history, 25.0, f"Fetching albums for {artist.name} from Deezer"
        )

        created_count, linked_count = _fetch_albums_via_deezer(artist, task_history)

        artist.last_synced_at = Now()
        artist.save()

        msg = (
            f"Fetch complete for {artist.name}: "
            f"{created_count} new, {linked_count} linked"
        )
        logger.info(msg)
        complete_task(task_history, success=True)

    except Exception as e:
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


def fetch_all_albums_for_artist_sync(artist_id: int) -> None:
    """Synchronous wrapper for fetch_all_albums_for_artist - for direct calls."""
    fetch_all_albums_for_artist.delay(artist_id)


@celery_app.task(bind=True, name="library_manager.tasks.update_tracked_artists")
def update_tracked_artists(self: Any, task_id: Optional[str] = None) -> None:
    all_tracked_artists = Artist.objects.filter(tracked=True).order_by(
        "last_synced_at", "added_at", "id"
    )
    helpers.update_tracked_artists_albums(
        [],
        list(all_tracked_artists),
        priority=None,  # task.priority not available
    )


# Severely throttling automatic playlist download for tracked artists for the time being;
# There is a high likelyhood of being flagged due to high usage at the moment and a new scalable solution needs to be investigated.


@celery_app.task(
    bind=True, name="library_manager.tasks.download_missing_tracked_artists"
)
def download_missing_tracked_artists(self: Any, task_id: Optional[str] = None) -> None:
    if settings.disable_missing_tracked_artist_download:
        logger.info(
            "Skipping queued missing tracked artists due to disable_missing_tracked_artist_download setting"
        )
        return

    from datetime import timedelta

    twelve_hours_ago = timezone.now() - timedelta(hours=12)
    recently_downloaded_songs = DownloadHistory.objects.filter(
        added_at__gte=twelve_hours_ago
    )
    if recently_downloaded_songs.count() > 250:
        logger.info(
            f"Skipping queued missing tracked artists due to quantity of recent downloads ({recently_downloaded_songs.count()})"
        )
        return
    # Limit to only desired album types (ignoring `appears_on`), and limit results so this won't throttle
    all_tracked_artists = (
        Artist.objects.filter(
            tracked=True,
            album__downloaded=False,
            album__wanted=True,
            album__album_type__in=ALBUM_TYPES_TO_DOWNLOAD,
        )
        .exclude(album__album_group__in=ALBUM_GROUPS_TO_IGNORE)
        .distinct()
        .order_by("last_synced_at", "added_at", "id")[:150]
    )
    helpers.download_missing_tracked_artists(
        [], list(all_tracked_artists), priority=None
    )
