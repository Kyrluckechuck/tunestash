"""
Metadata change detection utilities.

Provides functions to detect when artist, album, or song names have changed
on Spotify compared to what's stored locally, and to create/update
PendingMetadataUpdate records for user review.

The detection follows a superset hierarchy:
- If an artist name changes, we don't create separate entries for their albums/songs
- If an album name changes, we don't create separate entries for its songs
This prevents overwhelming the user with hundreds of entries when an artist renames.
"""

import logging
from typing import Optional

from django.contrib.contenttypes.models import ContentType

from library_manager.models import (
    Album,
    Artist,
    MetadataUpdateStatus,
    PendingMetadataUpdate,
    Song,
)

logger = logging.getLogger(__name__)


def has_pending_artist_change(artist_id: int) -> bool:
    """
    Check if there's already a pending metadata update for this artist.

    Used for superset logic: if an artist has a pending name change,
    we don't need to create separate album/song change entries.

    Args:
        artist_id: The database ID of the artist

    Returns:
        True if there's a pending update for this artist
    """
    content_type = ContentType.objects.get_for_model(Artist)
    return PendingMetadataUpdate.objects.filter(
        content_type=content_type,
        object_id=artist_id,
        field_name="name",
        status=MetadataUpdateStatus.PENDING,
    ).exists()


def has_pending_album_change(album_id: int) -> bool:
    """
    Check if there's already a pending metadata update for this album.

    Used for superset logic: if an album has a pending name change,
    we don't need to create separate song change entries.

    Args:
        album_id: The database ID of the album

    Returns:
        True if there's a pending update for this album
    """
    content_type = ContentType.objects.get_for_model(Album)
    return PendingMetadataUpdate.objects.filter(
        content_type=content_type,
        object_id=album_id,
        field_name="name",
        status=MetadataUpdateStatus.PENDING,
    ).exists()


def _create_or_update_pending_change(
    entity: Artist | Album | Song,
    field_name: str,
    old_value: str,
    new_value: str,
) -> Optional[PendingMetadataUpdate]:
    """
    Create or update a pending metadata change record.

    If a pending record already exists for this entity+field, update it with
    the new value. If the new value matches the old value (change reverted),
    dismiss the existing pending record.

    Args:
        entity: The Artist, Album, or Song instance
        field_name: The field that changed (e.g., 'name')
        old_value: The value stored in our database
        new_value: The current value from Spotify

    Returns:
        The PendingMetadataUpdate instance, or None if change was reverted
    """
    content_type = ContentType.objects.get_for_model(entity)

    try:
        existing = PendingMetadataUpdate.objects.get(
            content_type=content_type,
            object_id=entity.id,
            field_name=field_name,
        )

        # If the Spotify value now matches our DB, the change was reverted
        if new_value == old_value:
            existing.mark_dismissed()
            logger.info(
                f"Metadata change reverted for {content_type.model} #{entity.id}: "
                f"'{existing.old_value}' (dismissing pending update)"
            )
            return None

        # Update the pending record with new Spotify value
        if existing.status == MetadataUpdateStatus.PENDING:
            existing.new_value = new_value
            existing.save()
            logger.info(
                f"Updated pending metadata change for {content_type.model} #{entity.id}: "
                f"'{existing.old_value}' → '{new_value}'"
            )
            return existing

        # Was previously applied/dismissed, but now detected again
        # Reset to pending with new values
        existing.old_value = old_value
        existing.new_value = new_value
        existing.status = MetadataUpdateStatus.PENDING
        existing.resolved_at = None
        existing.save()
        logger.info(
            f"Re-detected metadata change for {content_type.model} #{entity.id}: "
            f"'{old_value}' → '{new_value}'"
        )
        return existing

    except PendingMetadataUpdate.DoesNotExist:
        # Create new pending record
        pending = PendingMetadataUpdate.objects.create(
            content_type=content_type,
            object_id=entity.id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            status=MetadataUpdateStatus.PENDING,
        )
        logger.info(
            f"Detected new metadata change for {content_type.model} #{entity.id}: "
            f"'{old_value}' → '{new_value}'"
        )
        return pending


def detect_artist_name_change(
    artist: Artist,
    spotify_name: str,
) -> bool:
    """
    Detect if an artist's name has changed on Spotify.

    Compares the artist's stored name with the name from Spotify metadata.
    If different, creates or updates a PendingMetadataUpdate record.

    Args:
        artist: The Artist model instance
        spotify_name: The artist's current name from Spotify API

    Returns:
        True if a change was detected, False otherwise
    """
    if artist.name == spotify_name:
        return False

    _create_or_update_pending_change(
        entity=artist,
        field_name="name",
        old_value=artist.name,
        new_value=spotify_name,
    )
    return True


def detect_album_name_change(
    album: Album,
    spotify_name: str,
    skip_if_artist_pending: bool = True,
) -> bool:
    """
    Detect if an album's name has changed on Spotify.

    Compares the album's stored name with the name from Spotify metadata.
    If different, creates or updates a PendingMetadataUpdate record.

    By default, skips detection if the album's artist already has a pending
    name change (superset logic).

    Args:
        album: The Album model instance
        spotify_name: The album's current name from Spotify API
        skip_if_artist_pending: If True, skip if artist has pending change

    Returns:
        True if a change was detected, False otherwise
    """
    if album.name == spotify_name:
        return False

    # Superset logic: don't create album entry if artist has pending change
    if skip_if_artist_pending and album.artist:
        if has_pending_artist_change(album.artist.id):  # type: ignore[attr-defined]
            logger.debug(
                f"Skipping album name change detection for '{album.name}' - "
                f"artist has pending change"
            )
            return False

    _create_or_update_pending_change(
        entity=album,
        field_name="name",
        old_value=album.name,
        new_value=spotify_name,
    )
    return True


def detect_song_name_change(
    song: Song,
    spotify_name: str,
    skip_if_parent_pending: bool = True,
) -> bool:
    """
    Detect if a song's name has changed on Spotify.

    Compares the song's stored name with the name from Spotify metadata.
    If different, creates or updates a PendingMetadataUpdate record.

    By default, skips detection if the song's artist or album already has
    a pending name change (superset logic).

    Args:
        song: The Song model instance
        spotify_name: The song's current name from Spotify API
        skip_if_parent_pending: If True, skip if artist/album has pending change

    Returns:
        True if a change was detected, False otherwise
    """
    if song.name == spotify_name:
        return False

    # Superset logic: don't create song entry if artist or album has pending change
    if skip_if_parent_pending:
        if has_pending_artist_change(song.primary_artist.id):  # type: ignore[attr-defined]
            logger.debug(
                f"Skipping song name change detection for '{song.name}' - "
                f"artist has pending change"
            )
            return False

        if song.album and has_pending_album_change(song.album.id):  # type: ignore[attr-defined]
            logger.debug(
                f"Skipping song name change detection for '{song.name}' - "
                f"album has pending change"
            )
            return False

    _create_or_update_pending_change(
        entity=song,
        field_name="name",
        old_value=song.name,
        new_value=spotify_name,
    )
    return True


def dismiss_superseded_updates(
    artist_id: Optional[int] = None,
    album_id: Optional[int] = None,
) -> int:
    """
    Dismiss pending updates that are now superseded by a parent update being applied.

    When an artist rename is applied, any pending album/song renames for that
    artist should be checked - if they're now correct after re-download, dismiss them.

    This should be called after re-downloads complete to clean up any
    child updates that are no longer relevant.

    Args:
        artist_id: If provided, dismiss superseded album/song updates for this artist
        album_id: If provided, dismiss superseded song updates for this album

    Returns:
        Number of updates dismissed
    """
    dismissed_count = 0

    if artist_id:
        albums = Album.objects.filter(artist__id=artist_id)
        album_content_type = ContentType.objects.get_for_model(Album)

        # Check each album's pending updates
        for album in albums:
            pending = PendingMetadataUpdate.objects.filter(
                content_type=album_content_type,
                object_id=album.id,
                status=MetadataUpdateStatus.PENDING,
            )
            for update in pending:
                # If the album name now matches the new_value, the re-download fixed it
                if album.name == update.new_value:
                    update.mark_dismissed()
                    dismissed_count += 1
                    logger.info(
                        f"Auto-dismissed album update #{update.pk} - "
                        f"name now matches after artist rename"
                    )

        # Check songs for this artist
        songs = Song.objects.filter(primary_artist__id=artist_id)
        song_content_type = ContentType.objects.get_for_model(Song)

        for song in songs:
            pending = PendingMetadataUpdate.objects.filter(
                content_type=song_content_type,
                object_id=song.id,
                status=MetadataUpdateStatus.PENDING,
            )
            for update in pending:
                if song.name == update.new_value:
                    update.mark_dismissed()
                    dismissed_count += 1
                    logger.info(
                        f"Auto-dismissed song update #{update.pk} - "
                        f"name now matches after artist rename"
                    )

    if album_id:
        # Check songs for this album
        songs = Song.objects.filter(album_id=album_id)
        song_content_type = ContentType.objects.get_for_model(Song)

        for song in songs:
            pending = PendingMetadataUpdate.objects.filter(
                content_type=song_content_type,
                object_id=song.id,
                status=MetadataUpdateStatus.PENDING,
            )
            for update in pending:
                if song.name == update.new_value:
                    update.mark_dismissed()
                    dismissed_count += 1
                    logger.info(
                        f"Auto-dismissed song update #{update.pk} - "
                        f"name now matches after album rename"
                    )

    return dismissed_count
