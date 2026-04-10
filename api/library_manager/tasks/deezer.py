"""Deezer album discovery and metadata fetching."""

from typing import Optional

from ..models import Album, Artist, TaskHistory
from .core import (
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
            total_tracks=album_data.total_tracks or 0,
            album_type=album_data.album_type,
            album_group=album_data.album_group or album_data.album_type,
            wanted=True,
        )
        existing_albums_by_norm.setdefault(normalize_name(album.name), album)
        created_count += 1

    return created_count, linked_count
