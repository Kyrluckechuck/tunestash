"""Deezer-specific tasks for album discovery and metadata fetching."""

from typing import Any, Optional

from django.utils import timezone

from celery_app import app as celery_app

from ..models import Album, Artist, TaskHistory
from .core import (
    complete_task,
    create_task_history,
    logger,
    normalize_name,
    update_task_progress,
)


def _fetch_albums_via_deezer(
    artist: Artist, task_history: Optional[TaskHistory] = None
) -> tuple[int, int]:
    """Fetch all albums for an artist from Deezer and create/link DB records.

    Returns:
        (created_count, linked_count) tuple.
    """
    from src.providers.deezer import DeezerMetadataProvider

    provider = DeezerMetadataProvider()
    deezer_albums = provider.get_artist_albums(artist.deezer_id)

    if task_history:
        update_task_progress(
            task_history,
            50.0,
            f"Found {len(deezer_albums)} albums, processing...",
        )

    created_count = 0
    linked_count = 0

    # Build normalized name → album lookup for accent/case-insensitive matching
    existing_albums_by_norm: dict[str, Album] = {}
    for db_album in Album.objects.filter(artist=artist):
        existing_albums_by_norm.setdefault(normalize_name(db_album.name), db_album)

    for album_data in deezer_albums:
        if not album_data.deezer_id:
            continue

        # Check by deezer_id first, then by normalized name
        existing = Album.objects.filter(deezer_id=album_data.deezer_id).first()
        if not existing:
            existing = existing_albums_by_norm.get(normalize_name(album_data.name))

        if existing:
            if not existing.deezer_id:
                # Guard against another album already having this deezer_id
                if not Album.objects.filter(deezer_id=album_data.deezer_id).exists():
                    existing.deezer_id = album_data.deezer_id
                    existing.save(update_fields=["deezer_id"])
                    linked_count += 1
            continue

        album = Album.objects.create(
            name=album_data.name,
            deezer_id=album_data.deezer_id,
            artist=artist,
            spotify_uri="",
            total_tracks=album_data.total_tracks,
            album_type=album_data.album_type,
            album_group=album_data.album_group or album_data.album_type,
            wanted=True,
        )
        existing_albums_by_norm.setdefault(normalize_name(album.name), album)
        created_count += 1

    return created_count, linked_count


@celery_app.task(
    bind=True,
    name="library_manager.tasks.fetch_artist_albums_from_deezer",
)
def fetch_artist_albums_from_deezer(self: Any, artist_id: int) -> None:
    """Fetch all albums for an artist from Deezer and create DB records."""
    task_history = None
    try:
        try:
            artist = Artist.objects.get(id=artist_id)
        except Artist.DoesNotExist:
            logger.warning(f"Artist with ID {artist_id} does not exist. Skipping.")
            return

        if not artist.deezer_id:
            logger.warning(
                f"Artist {artist.name} has no deezer_id. Skipping Deezer fetch."
            )
            return

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="FETCH",
            entity_id=str(artist.id),
            entity_type="ARTIST",
            task_name="fetch_artist_albums_from_deezer",
        )
        task_history.status = "RUNNING"
        task_history.save()
        update_task_progress(
            task_history, 0.0, f"Fetching albums for {artist.name} from Deezer"
        )

        created_count, linked_count = _fetch_albums_via_deezer(artist, task_history)

        artist.last_synced_at = timezone.now()
        artist.save(update_fields=["last_synced_at"])

        msg = (
            f"Deezer fetch complete for {artist.name}: "
            f"{created_count} new, {linked_count} linked"
        )
        logger.info(msg)
        update_task_progress(task_history, 100.0, msg)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error fetching Deezer albums for artist_id={artist_id}")
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise
