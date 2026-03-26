"""Artist tasks for the Tunestash."""

from typing import Any

from django.db.models.functions import Now

from celery_app import app as celery_app

from ..models import Artist
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
