"""Deezer album discovery and metadata fetching."""

from typing import Optional

from ..models import Album, Artist, TaskHistory
from ..release_ids import (
    ALBUM_CREATE,
    ALBUM_EXISTS,
    ALBUM_LINK,
    classify_deezer_album,
    link_album_deezer_id,
)
from .core import normalize_name, raise_if_cancelled, update_task_progress


def _fetch_albums_via_deezer(
    artist: Artist, task_history: Optional[TaskHistory] = None
) -> tuple[int, int]:
    """Fetch all albums for an artist from Deezer and create/link DB records.

    Returns:
        (created_count, linked_count) tuple.
    """
    from src.providers.deezer import DeezerMetadataProvider

    if task_history:
        raise_if_cancelled(task_history)

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

    for album_data in deezer_albums:
        if task_history:
            raise_if_cancelled(task_history)
        if not album_data.deezer_id:
            continue

        # A same-titled row is the same release only when a UPC proves it:
        # editions share titles, and a shared id would pull the wrong
        # release's track ids into the album.
        action, existing = classify_deezer_album(
            artist, album_data.deezer_id, album_data.name, normalize_name
        )
        if action == ALBUM_EXISTS:
            continue
        if action == ALBUM_LINK and existing is not None:
            if link_album_deezer_id(existing, album_data.deezer_id):
                linked_count += 1
            continue
        if action != ALBUM_CREATE:
            continue  # ALBUM_SKIP: unproven same-titled row, neither link nor duplicate

        Album.objects.create(
            name=album_data.name,
            deezer_id=album_data.deezer_id,
            artist=artist,
            spotify_uri="",
            total_tracks=album_data.total_tracks or 0,
            album_type=album_data.album_type,
            album_group=album_data.album_group or album_data.album_type,
            wanted=True,
        )
        created_count += 1

    return created_count, linked_count
