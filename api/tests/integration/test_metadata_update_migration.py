"""Regression tests for metadata-only updates of downloaded files."""

from pathlib import Path
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

import pytest

from library_manager.models import (
    Album,
    Artist,
    FilePath,
    PendingMetadataUpdate,
    Song,
)
from library_manager.tasks.metadata import (
    _migrate_downloaded_song,
    apply_metadata_update,
)


def _make_downloaded_song(
    tmp_path: Path, *, artist: Artist, album: Album, name: str = "Old Song"
) -> Song:
    """Create a downloaded song whose file lives in the configured library root."""
    old_path = tmp_path / "Old Artist" / "Old Album" / "old-file.m4a"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"audio data")
    return Song.objects.create(
        name=name,
        gid=f"song{artist.pk}{album.pk}",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(old_path)),
    )


@pytest.mark.integration
@pytest.mark.django_db
def test_metadata_update_migrates_file_without_redownload(tmp_path):
    """Applying an artist rename rewrites and moves an existing file in place."""
    artist = Artist.objects.create(name="New Artist", gid="artist-migration")
    album = Album.objects.create(
        name="New Album",
        spotify_gid="album-migration",
        artist=artist,
        total_tracks=1,
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    update = PendingMetadataUpdate.objects.create(
        content_type=ContentType.objects.get_for_model(Artist),
        object_id=artist.pk,
        old_value="Old Artist",
        new_value="New Artist",
    )

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ) as update_tags,
        patch(
            "library_manager.tasks.download_missing_albums_for_artist.delay"
        ) as redownload,
    ):
        apply_metadata_update.run(update.pk)

    song.refresh_from_db()
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    assert destination.is_file()
    assert not (tmp_path / "Old Artist" / "Old Album" / "old-file.m4a").exists()
    assert song.downloaded is True
    assert song.file_path == str(destination)
    update_tags.assert_called_once()
    redownload.assert_not_called()


@pytest.mark.integration
@pytest.mark.django_db
def test_metadata_update_does_not_move_colliding_file(tmp_path):
    """A collision leaves the source untouched and uses the existing retry path."""
    artist = Artist.objects.create(name="Artist", gid="artist-collision")
    album = Album.objects.create(
        name="Album",
        spotify_gid="album-collision",
        artist=artist,
        total_tracks=1,
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    destination = tmp_path / "Artist" / "Album" / "Artist - Old Song.m4a"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"different audio")

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata"
        ) as update_tags,
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert Path(song.file_path).is_file()
    assert destination.read_bytes() == b"different audio"
    update_tags.assert_not_called()


@pytest.mark.integration
@pytest.mark.django_db
def test_metadata_update_does_not_rewrite_shared_file(tmp_path):
    """A shared physical file is left for the redownload fallback."""
    artist = Artist.objects.create(name="Shared Artist", gid="artist-shared")
    album = Album.objects.create(
        name="Shared Album",
        spotify_gid="album-shared",
        artist=artist,
        total_tracks=2,
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    Song.objects.create(
        name="Other Song",
        gid="song-shared-other",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=song.file_path_ref,
    )

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata"
        ) as update_tags,
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert Path(song.file_path).is_file()
    update_tags.assert_not_called()
