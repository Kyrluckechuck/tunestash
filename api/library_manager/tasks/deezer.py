"""Deezer-specific tasks for album discovery and metadata fetching."""

from typing import Any

from django.db.models import Q
from django.utils import timezone

from celery_app import app as celery_app

from ..models import Album, Artist
from .core import (
    complete_task,
    create_task_history,
    logger,
    update_task_progress,
)


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

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        deezer_albums = provider.get_artist_albums(artist.deezer_id)

        update_task_progress(
            task_history,
            50.0,
            f"Found {len(deezer_albums)} albums, processing...",
        )

        created_count = 0
        linked_count = 0

        for album_data in deezer_albums:
            if not album_data.deezer_id:
                continue

            existing = Album.objects.filter(
                Q(deezer_id=album_data.deezer_id)
                | Q(name__iexact=album_data.name, artist=artist)
            ).first()

            if existing:
                if not existing.deezer_id:
                    existing.deezer_id = album_data.deezer_id
                    existing.save(update_fields=["deezer_id"])
                    linked_count += 1
                continue

            Album.objects.create(
                name=album_data.name,
                deezer_id=album_data.deezer_id,
                artist=artist,
                spotify_uri="",
                total_tracks=album_data.total_tracks,
                album_type=album_data.album_type,
                wanted=True,
            )
            created_count += 1

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
            task_history.status = "FAILED"
            task_history.log_messages.append(str(e))
            task_history.save()
        raise
