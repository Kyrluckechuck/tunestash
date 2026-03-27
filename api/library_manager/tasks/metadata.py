"""Celery tasks for metadata update operations.

These tasks handle applying metadata updates detected from Spotify,
including re-downloading songs and cleaning up old files.
"""

import logging
from pathlib import Path
from typing import Any, List

from library_manager.metadata_detection import dismiss_superseded_updates
from library_manager.models import (
    MetadataUpdateStatus,
    PendingMetadataUpdate,
    Song,
)

from .core import (
    celery_app,
    check_task_cancellation,
    complete_task,
    create_task_history,
    update_task_progress,
)

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="library_manager.tasks.apply_metadata_update")
def apply_metadata_update(self: Any, update_id: int) -> None:
    """
    Apply a single metadata update.

    This task:
    1. Gets the PendingMetadataUpdate record
    2. Updates the entity's name in the database
    3. For each downloaded song affected:
       a. Stores the old file path
       b. Marks song as downloaded=False
       c. Queues for re-download
    4. Marks the update as APPLIED
    5. Queues cleanup for the old files after re-downloads

    Args:
        update_id: ID of the PendingMetadataUpdate to apply
    """
    task_history = create_task_history(
        task_id=self.request.id,
        task_type="SYNC",
        entity_id=str(update_id),
        entity_type="metadata_update",
        task_name="apply_metadata_update",
    )

    try:
        update = PendingMetadataUpdate.objects.get(pk=update_id)
    except PendingMetadataUpdate.DoesNotExist:
        complete_task(
            task_history,
            success=False,
            error_message=f"Metadata update #{update_id} not found",
        )
        return

    if update.status != MetadataUpdateStatus.PENDING:
        complete_task(
            task_history,
            success=False,
            error_message=f"Update #{update_id} is not pending (status: {update.status})",
        )
        return

    update_task_progress(task_history, 0.1, "Processing metadata update...")

    if check_task_cancellation(task_history):
        return

    content_type = update.content_type
    model_class = content_type.model_class()  # type: ignore[attr-defined]
    if model_class is None:
        complete_task(
            task_history,
            success=False,
            error_message="Invalid content type - cannot resolve model class",
        )
        return
    model_name = content_type.model.lower()  # type: ignore[attr-defined]

    try:
        entity = model_class.objects.get(id=update.object_id)
    except model_class.DoesNotExist:
        update.mark_dismissed()
        complete_task(
            task_history,
            success=False,
            error_message="Entity no longer exists - dismissed update",
        )
        return

    try:
        # Update the entity's name in the database
        old_name = entity.name
        entity.name = update.new_value
        entity.save()
        logger.info(
            f"Updated {model_name} #{entity.id} name: "
            f"'{old_name}' → '{update.new_value}'"
        )

        update_task_progress(task_history, 0.2, "Collecting affected songs...")

        # Collect songs that need re-downloading
        songs_to_redownload: List[Song] = []
        old_file_paths: List[str] = []

        if model_name == "artist":
            songs_to_redownload = list(
                Song.objects.filter(
                    primary_artist_id=entity.id,
                    downloaded=True,
                )
            )
        elif model_name == "album":
            songs_to_redownload = list(
                Song.objects.filter(
                    album_id=entity.id,
                    downloaded=True,
                )
            )
        elif model_name == "song":
            if entity.downloaded:
                songs_to_redownload = [entity]

        # Store old paths and mark songs for re-download
        for song in songs_to_redownload:
            if song.file_path:
                old_file_paths.append(song.file_path)
            song.downloaded = False
            song.save()

        update_task_progress(
            task_history,
            0.3,
            f"Marked {len(songs_to_redownload)} songs for re-download...",
        )

        if check_task_cancellation(task_history):
            return

        # Queue re-downloads
        if songs_to_redownload:
            if model_name == "artist":
                from library_manager.tasks import download_missing_albums_for_artist

                download_missing_albums_for_artist.delay(entity.id)
                logger.info(
                    f"Queued download_missing_albums_for_artist for artist #{entity.id}"
                )
            elif model_name == "album":
                from library_manager.tasks import download_single_album

                download_single_album.delay(entity.id)
                logger.info(f"Queued download_single_album for album #{entity.id}")
            elif model_name == "song":
                if entity.deezer_id:
                    from library_manager.tasks import download_deezer_track

                    download_deezer_track.delay(entity.id)
                    logger.info(f"Queued download_deezer_track for song #{entity.id}")
                elif entity.gid:
                    from library_manager.tasks import download_track_by_spotify_gid

                    download_track_by_spotify_gid.delay(entity.gid)
                    logger.info(
                        f"Queued download_track_by_spotify_gid for song #{entity.id}"
                    )

        update_task_progress(task_history, 0.7, "Scheduling file cleanup...")

        # Queue cleanup of old files (after a delay to allow re-downloads to complete)
        if old_file_paths:
            cleanup_old_files.apply_async(
                args=[old_file_paths],
                countdown=300,  # 5 minute delay
            )
            logger.info(f"Scheduled cleanup of {len(old_file_paths)} old files")

        # Mark update as applied
        update.mark_applied()

        update_task_progress(task_history, 0.9, "Cleaning up superseded updates...")

        # Dismiss any superseded child updates
        if model_name == "artist":
            dismissed = dismiss_superseded_updates(artist_id=entity.id)
            if dismissed > 0:
                logger.info(f"Auto-dismissed {dismissed} superseded updates")
        elif model_name == "album":
            dismissed = dismiss_superseded_updates(album_id=entity.id)
            if dismissed > 0:
                logger.info(f"Auto-dismissed {dismissed} superseded updates")

        logger.info(
            f"Applied metadata update: '{old_name}' → '{update.new_value}' "
            f"({len(songs_to_redownload)} songs queued for re-download)"
        )
        complete_task(task_history, success=True)
    except Exception as e:
        logger.error(f"Error applying metadata update #{update_id}: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(bind=True, name="library_manager.tasks.cleanup_old_files")
def cleanup_old_files(self: Any, old_paths: List[str]) -> None:
    """
    Clean up old files after metadata update re-downloads.

    This task:
    1. Checks if each old file still exists
    2. Deletes files that are no longer needed
    3. Removes empty parent directories (album → artist)

    Args:
        old_paths: List of old file paths to clean up
    """
    logger.info(f"Starting cleanup of {len(old_paths)} old files")

    deleted_count = 0
    failed_count = 0

    for old_path in old_paths:
        try:
            path = Path(old_path)

            # Only delete if file still exists
            if not path.exists():
                logger.debug(f"File already gone: {old_path}")
                continue

            # Check if any song still references this path
            from library_manager.models import FilePath, Song

            file_path_obj = FilePath.objects.filter(path=old_path).first()

            if file_path_obj:
                # Check if any song is using this path
                if Song.objects.filter(
                    file_path_ref=file_path_obj, downloaded=True
                ).exists():
                    logger.debug(
                        f"File still in use by downloaded song, skipping: {old_path}"
                    )
                    continue

            # Delete the file
            path.unlink()
            deleted_count += 1
            logger.info(f"Deleted old file: {old_path}")

            # Try to remove empty parent directories
            _cleanup_empty_parents(path.parent)

        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to delete {old_path}: {e}")

    logger.info(f"Cleanup complete: {deleted_count} deleted, {failed_count} failed")


def _cleanup_empty_parents(directory: Path, max_depth: int = 3) -> None:
    """
    Remove empty parent directories up to max_depth levels.

    Uses rmdir which only removes empty directories (safe).

    Args:
        directory: Starting directory
        max_depth: Maximum number of parent levels to check
    """
    current = directory
    for _ in range(max_depth):
        if not current.exists():
            current = current.parent
            continue

        try:
            # rmdir only works on empty directories
            current.rmdir()
            logger.info(f"Removed empty directory: {current}")
            current = current.parent
        except OSError:
            # Directory not empty or other error - stop here
            break
