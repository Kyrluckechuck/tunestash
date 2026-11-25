"""Celery tasks for metadata update operations.

These tasks handle applying metadata updates detected from Spotify,
including migrating existing files and cleaning up old files.
"""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, cast

from django.conf import settings
from django.db import transaction

from downloader.filesystem_safety import (
    UnsafePathError,
    assert_within,
    is_safe_regular_file,
    is_within,
    safe_join,
    sanitize_component,
)
from downloader.providers.metadata import MetadataEmbedder

from library_manager.metadata_detection import dismiss_superseded_updates
from library_manager.models import (
    Album,
    Artist,
    FilePath,
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


def _sanitize_filename(name: str) -> str:
    """Match download path rules for metadata migrations.

    Delegates to the shared sanitizer so dot-only traversal components are
    rejected in both the download and migration code paths.
    """
    return sanitize_component(name)


def _metadata_destination(song: Song, current_path: Path) -> Path:
    """Return the canonical path for a song's current model names.

    Raises:
        UnsafePathError: if the computed destination resolves outside the
            configured output root (for example via ``..`` or a symlink).
    """
    output_root = Path(getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify"))
    artist_name = (
        cast(Artist, song.primary_artist).name
        if song.primary_artist is not None
        else "Unknown Artist"
    )
    album_name = (
        cast(Album, song.album).name if song.album is not None else "Unknown Album"
    )
    extension = current_path.suffix.lstrip(".") or "m4a"
    # Sanitize the semantic directory components once (AC/DC -> AC-DC), using
    # the 100-character component limit. The composed filename keeps the
    # extension; assert_within only checks it does not escape the directory.
    directory = safe_join(output_root, artist_name, album_name)
    filename = f"{_sanitize_filename(artist_name)} - {_sanitize_filename(song.name)}.{extension}"
    return assert_within(directory, filename)


# The validation steps intentionally use guard clauses so unsafe files fail closed.
# pylint: disable=too-many-return-statements,too-many-branches,too-many-locals
def _migrate_downloaded_song(song: Song) -> bool:
    """Rewrite tags and move one downloaded file without replacing its audio.

    Copy, tag the copy, CAS-update the DB, then unlink the original on commit:

    * A path change is published as an **independent inode** (secure stream
      copy + no-overwrite ``os.link``), so the original is never mutated.
    * Only the destination copy is tagged; the original keeps its old tags.
    * The DB update is a compare-and-swap inside a transaction.
    * ``transaction.on_commit`` re-checks the destination identity, the locked
      DB reference and all other references before unlinking the original. Any
      failed check keeps the file and logs why; the callback never raises.

    A rollback leaves the original valid at the DB path and never runs the
    unlink callback. Ambiguous cases reject without DB mutation.
    """
    if not song.file_path:
        return False

    current_path = Path(song.file_path)
    output_root = Path(getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")).resolve()

    try:
        destination = _metadata_destination(song, current_path)
    except (UnsafePathError, OSError, ValueError) as exc:
        logger.warning("Unsafe migration destination for song %s: %s", song.id, exc)
        return False

    if not is_within(destination, output_root):
        logger.warning("Migration destination outside library for song %s", song.id)
        return False

    if not current_path.is_file():
        logger.warning(
            "Cannot migrate missing file for song %s: %s", song.id, current_path
        )
        return False

    if not is_within(current_path, output_root):
        logger.warning("Leaving non-library file in place for song %s", song.id)
        return False

    if _is_shared_file(song):
        logger.warning(
            "Cannot migrate shared file for song %s: %s", song.id, current_path
        )
        return False

    path_changes = destination != current_path
    if path_changes and destination.exists():
        logger.warning(
            "Metadata migration collision for song %s: %s", song.id, destination
        )
        return False

    artist_name = (
        cast(Artist, song.primary_artist).name
        if song.primary_artist is not None
        else "Unknown Artist"
    )
    album_name = (
        cast(Album, song.album).name if song.album is not None else "Unknown Album"
    )

    try:
        source_identity = _identity(current_path)
        source_size = current_path.stat().st_size
    except OSError:
        logger.warning("Cannot stat migration source for song %s", song.id)
        return False

    published_identity: tuple[int, int] | None = None
    if path_changes:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Narrows (does not eliminate) the symlink TOCTOU window.
            if not is_within(destination, output_root) or destination.exists():
                logger.warning(
                    "Migration destination became unsafe or occupied for song %s",
                    song.id,
                )
                return False
            published_identity = _publish_copy(current_path, destination)
        except OSError as exc:
            logger.error(
                "Failed to publish migrated copy for song %s to %s: %s",
                song.id,
                destination,
                exc,
            )
            return False
        if published_identity is None:
            logger.warning("Migration destination occupied for song %s", song.id)
            return False
        tag_target = destination
    else:
        tag_target = current_path

    if not MetadataEmbedder().update_basic_metadata(
        tag_target,
        title=song.name,
        artist=artist_name,
        album=album_name,
    ):
        _remove_published_copy(destination, published_identity, path_changes)
        return False

    # Capture the destination identity only after tagging succeeds: a tag
    # writer may replace the inode, and a later replacement is what the
    # on_commit check must detect.
    tagged_identity = _safe_identity(tag_target)
    old_ref = cast(FilePath | None, song.file_path_ref)
    old_path = current_path
    song_pk = song.pk

    try:
        with transaction.atomic():
            _record_migrated_path(song, destination)
            new_ref = cast(FilePath | None, song.file_path_ref)
    except Exception:
        # Outer rollback may happen after we return; that case is handled by
        # the inert destination copy (the original is untouched). Here we only
        # clean up a copy we created for this attempt when its inode still
        # matches what we published.
        _remove_published_copy(destination, published_identity, path_changes)
        raise

    if path_changes:
        try:
            resolved_old_path = old_path.resolve()
        except OSError:
            resolved_old_path = old_path
        transaction.on_commit(
            lambda: _cleanup_migration_original(
                song_pk=song_pk,
                new_ref=new_ref,
                destination=destination,
                tagged_identity=tagged_identity,
                old_ref=old_ref,
                old_path=old_path,
                resolved_old_path=resolved_old_path,
                source_identity=source_identity,
                source_size=source_size,
                output_root=output_root,
            )
        )
    return True


def _identity(path: Path) -> tuple[int, int]:
    """Return the (device, inode) pair identifying a file's inode."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino


_DEFAULT_LINK_LOG = "/config/migration-links.jsonl"


def migration_link_log_path() -> Path:
    """Return the append-only migration link log path.

    The log lives under the config directory (never the music library), so a
    media server scanning the library cannot index it. Deployments can override
    the location with ``MIGRATION_LINK_LOG`` in settings.
    """
    return Path(getattr(settings, "MIGRATION_LINK_LOG", _DEFAULT_LINK_LOG))


def _append_link_record(record: dict[str, Any]) -> None:
    """Append one JSON line to the link log, process-safe and fsynced.

    A single ``os.write`` on an ``O_APPEND`` descriptor keeps concurrent workers
    from interleaving partial lines. The log is private (0600) and durable.
    """
    log = migration_link_log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        logger.info("Could not append migration link log %s", log)


def _record_migration_link(
    *,
    event: str,
    song_id: int,
    old_path: Path,
    old_identity: tuple[int, int] | None,
    old_size: int,
    new_path: Path,
    new_identity: tuple[int, int] | None,
    reason: str | None = None,
) -> None:
    """Record a retained original or a successful deletion in the link log."""
    _append_link_record(
        {
            "event": event,
            "song_id": song_id,
            "old_path": str(old_path),
            "old_identity": list(old_identity) if old_identity else None,
            "old_size": old_size,
            "new_path": str(new_path),
            "new_identity": list(new_identity) if new_identity else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
    )


def _publish_copy(source: Path, destination: Path) -> tuple[int, int] | None:
    """Publish an independent copy of ``source`` at ``destination``.

    Copies to a private random temp, preserves the source mode, fsyncs, then
    publishes with ``os.link`` so an existing destination is never replaced.
    Returns the published inode identity, or None on a refused publish.
    """
    fd = -1
    temp: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.ts-"
        )
        temp = Path(tmp_name)
        with os.fdopen(fd, "wb") as dst, source.open("rb") as src:
            fd = -1
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temp, source.stat().st_mode & 0o777)
        if destination.exists():
            return None
        os.link(temp, destination)
        return _identity(destination)
    except OSError:
        return None
    finally:
        if fd >= 0:
            os.close(fd)
        if temp is not None:
            temp.unlink(missing_ok=True)


def _remove_published_copy(
    destination: Path, identity: tuple[int, int] | None, path_changes: bool
) -> None:
    """Remove a destination copy only if it is the one this attempt created."""
    if not path_changes or identity is None:
        return
    try:
        if destination.is_file() and _identity(destination) == identity:
            destination.unlink()
    except OSError:
        logger.debug("Could not remove published copy %s", destination)


def _is_shared_file(song: Song) -> bool:
    """Return whether another downloaded song points at the same file record."""
    if song.file_path_ref is None:
        return False
    return (
        Song.objects.filter(file_path_ref=song.file_path_ref, downloaded=True)
        .exclude(pk=song.pk)
        .exists()
    )


def _safe_identity(path: Path) -> tuple[int, int] | None:
    """Return ``path``'s inode identity or None if it cannot be stat'ed."""
    try:
        return _identity(path)
    except OSError:
        return None


def _cleanup_migration_original(  # noqa: PLR0913, PLR0911  pylint: disable=too-many-arguments,too-many-return-statements,too-many-branches,too-many-locals
    *,
    song_pk: int,
    new_ref: FilePath | None,
    destination: Path,
    tagged_identity: tuple[int, int] | None,
    old_ref: FilePath | None,
    old_path: Path,
    resolved_old_path: Path,
    source_identity: tuple[int, int],
    source_size: int,
    output_root: Path,
) -> None:
    """Unlink the retained original after commit, only if every check holds.

    This callback runs outside the migration transaction and must never raise.
    Every failed check keeps the original, records why in the link log, and logs
    at info level. Successful deletions are recorded too, as audit history.
    """
    current_identity = _safe_identity(destination)

    def keep(reason: str, detail: str = "") -> None:
        logger.info("Keeping migration original %s: %s%s", old_path, reason, detail)
        _record_migration_link(
            event="retained",
            song_id=song_pk,
            old_path=old_path,
            old_identity=source_identity,
            old_size=source_size,
            new_path=destination,
            new_identity=current_identity,
            reason=reason,
        )

    try:
        with transaction.atomic():
            locked = Song.objects.select_for_update().filter(pk=song_pk).first()
            if locked is None:
                keep("song no longer exists", f" (id={song_pk})")
                return
            if locked.file_path_ref != new_ref or locked.downloaded is not True:
                keep(
                    "song no longer references the migrated path with downloaded=True",
                    f" (id={song_pk})",
                )
                return

        if not is_safe_regular_file(destination, output_root):
            keep(
                "migrated destination is missing, a symlink, or outside the library",
                f" ({destination})",
            )
            return
        if tagged_identity is None or current_identity != tagged_identity:
            keep("migrated destination inode changed")
            return

        # No Song, in any downloaded state, may still reference the old path.
        if old_ref is not None and Song.objects.filter(file_path_ref=old_ref).exists():
            keep("another Song still references the old FilePath")
            return
        same_path_refs = FilePath.objects.filter(path=str(old_path))
        if str(resolved_old_path) != str(old_path):
            same_path_refs = same_path_refs | FilePath.objects.filter(
                path=str(resolved_old_path)
            )
        if (
            same_path_refs.exists()
            and Song.objects.filter(file_path_ref__in=same_path_refs).exists()
        ):
            keep("another Song references FilePath with the old path")
            return

        if not is_safe_regular_file(old_path, output_root):
            keep("original is a symlink, missing, or outside the library")
            return
        if _safe_identity(old_path) != source_identity:
            keep("original inode changed since the copy")
            return
        try:
            if old_path.stat().st_size != source_size:
                keep("original size changed since the copy")
                return
        except OSError:
            keep("cannot stat original")
            return

        old_path.unlink()
        _record_migration_link(
            event="deleted",
            song_id=song_pk,
            old_path=old_path,
            old_identity=source_identity,
            old_size=source_size,
            new_path=destination,
            new_identity=current_identity,
        )
        logger.info(
            "Deleted retained migration original %s after successful migration to %s",
            old_path,
            destination,
        )
    except Exception:
        keep("unexpected cleanup error")


def _record_migrated_path(song: Song, destination: Path) -> None:
    """Point ``song`` at ``destination`` using compare-and-swap."""
    # Filter by the relation object rather than the Django-generated
    # ``file_path_ref_id`` attname, which mypy cannot see on the generic
    # ForeignKey annotation. This is the same SQL predicate and is type-safe.
    old_ref = song.file_path_ref
    file_path, _ = FilePath.objects.get_or_create(path=str(destination))
    updated = Song.objects.filter(
        pk=song.pk, file_path_ref=old_ref, downloaded=True
    ).update(file_path_ref=file_path, downloaded=True)
    if updated != 1:
        raise RuntimeError(
            f"Song {song.pk} changed concurrently during migration; aborting"
        )
    song.file_path_ref = file_path
    song.downloaded = True


@celery_app.task(bind=True, name="library_manager.tasks.apply_metadata_update")
def apply_metadata_update(self: Any, update_id: int) -> None:
    """
    Apply a single metadata update.

    This task:
    1. Gets the PendingMetadataUpdate record
    2. Updates the entity's name in the database
    3. Rewrites metadata and moves each downloaded file in place
    4. Queues only failed migrations for re-download
    5. Marks the update as APPLIED

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
    model_class = getattr(content_type, "model_class")()
    if model_class is None:
        complete_task(
            task_history,
            success=False,
            error_message="Invalid content type - cannot resolve model class",
        )
        return
    model_name = getattr(content_type, "model").lower()

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

        # Migrate existing files first; only failed migrations are redownloaded.
        affected_songs: List[Song] = []

        if model_name == "artist":
            affected_songs = list(
                Song.objects.filter(
                    primary_artist_id=entity.id, downloaded=True
                ).select_related("primary_artist", "album", "file_path_ref")
            )
        elif model_name == "album":
            affected_songs = list(
                Song.objects.filter(album_id=entity.id, downloaded=True).select_related(
                    "primary_artist", "album", "file_path_ref"
                )
            )
        elif model_name == "song" and entity.downloaded:
            affected_songs = [entity]

        songs_to_redownload: List[Song] = []
        migrated_count = 0
        for song in affected_songs:
            if _migrate_downloaded_song(song):
                migrated_count += 1
                continue
            songs_to_redownload.append(song)
            song.downloaded = False
            song.save(update_fields=["downloaded"])

        update_task_progress(
            task_history,
            0.3,
            f"Migrated {migrated_count} files; queued {len(songs_to_redownload)} for re-download...",
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

    output_root = Path(getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")).resolve()
    deleted_count = 0
    failed_count = 0

    for old_path in old_paths:
        try:
            path = Path(old_path)

            # Never delete outside the configured music root, including via a
            # symlinked parent directory.
            if not is_within(path, output_root):
                logger.warning("Refusing cleanup outside library root: %s", old_path)
                failed_count += 1
                continue

            # Only delete if file still exists
            if not path.is_file() or path.is_symlink():
                logger.debug(f"File already gone or not a regular file: {old_path}")
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
    output_root = Path(getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")).resolve()
    current = directory
    for _ in range(max_depth):
        if not is_within(current, output_root) or current.is_symlink():
            break
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
