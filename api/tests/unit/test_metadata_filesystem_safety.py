"""Filesystem safety regression tests for metadata migrations and downloads.

These tests cover the C2 audit finding: path traversal and symlink escapes must
not let a metadata rename or a download filename write outside the configured
music root, and a failed DB write must not leave a migrated file stranded at a
path the database no longer references.
"""

from pathlib import Path
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test import override_settings

import pytest
from downloader.filesystem_safety import (
    UnsafePathError,
    assert_within,
    is_within,
    safe_join,
    sanitize_component,
)
from downloader.providers.fallback import DownloadProviderChain

from library_manager.metadata_detection import dismiss_superseded_updates  # noqa: F401
from library_manager.models import (
    Album,
    Artist,
    FilePath,
    PendingMetadataUpdate,
    Song,
)
from library_manager.tasks.metadata import (
    _metadata_destination,
    _migrate_downloaded_song,
    apply_metadata_update,
    cleanup_old_files,
)

# ---------------------------------------------------------------------------
# Shared sanitizer / containment helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sanitize_component_rejects_dot_and_dotdot():
    assert sanitize_component("..") == ""
    assert sanitize_component(".") == ""
    assert sanitize_component("...") == ""
    assert sanitize_component("  ..  ") == ""


@pytest.mark.unit
def test_sanitize_component_preserves_normal_artist_names():
    assert sanitize_component("Pink Floyd") == "Pink Floyd"
    assert sanitize_component("AC/DC") == "AC-DC"
    assert sanitize_component("A:B * C?") == "A-B  C"


@pytest.mark.unit
def test_safe_join_contains_resolved_destination(tmp_path):
    root = (tmp_path / "music").resolve()
    root.mkdir()

    resolved = safe_join(root, "Artist", "Album", "Artist - Song.m4a")
    assert is_within(resolved, root)

    with pytest.raises(UnsafePathError):
        safe_join(root, "..", "outside.m4a")


@pytest.mark.unit
def test_safe_join_rejects_symlink_escape(tmp_path):
    root = (tmp_path / "music").resolve()
    root.mkdir()
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (root / "Linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        safe_join(root, "Linked", "escape.m4a")


# ---------------------------------------------------------------------------
# Metadata migration
# ---------------------------------------------------------------------------


def _make_downloaded_song(tmp_path, *, artist, album, name="Old Song"):
    old_path = tmp_path / "Old Artist" / "Old Album" / "old-file.m4a"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"audio data")
    return Song.objects.create(
        name=name,
        gid=f"song{artist.pk}{album.pk}",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(old_path)),
    )


@pytest.mark.unit
@pytest.mark.django_db
def test_migration_rejects_dotdot_artist_name(tmp_path):
    """A '..' artist name must not move a file outside the music root."""
    artist = Artist.objects.create(name="..", gid="artist-dotdot")
    album = Album.objects.create(
        name="Album", spotify_gid="album-dotdot", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ) as update_tags,
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert Path(song.file_path).is_file()
    assert not (tmp_path.parent / "Album").exists()
    update_tags.assert_not_called()


@pytest.mark.unit
@pytest.mark.django_db
def test_migration_rejects_symlink_destination(tmp_path):
    """A symlinked album directory must not redirect the move outside root."""
    root = (tmp_path / "music").resolve()
    root.mkdir()
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (root / "New Artist").mkdir()
    (root / "New Artist" / "Linked").symlink_to(outside, target_is_directory=True)

    artist = Artist.objects.create(name="New Artist", gid="artist-symlink")
    album = Album.objects.create(
        name="Linked", spotify_gid="album-symlink", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(root, artist=artist, album=album)

    with (
        override_settings(OUTPUT_PATH=str(root)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ) as update_tags,
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert not (outside / "New Artist - Old Song.m4a").exists()
    assert Path(song.file_path).is_file()
    update_tags.assert_not_called()


@pytest.mark.unit
@pytest.mark.django_db
def test_migration_does_not_overwrite_existing_destination(tmp_path):
    artist = Artist.objects.create(name="New Artist", gid="artist-collision-safety")
    album = Album.objects.create(
        name="New Album",
        spotify_gid="album-collision-safety",
        artist=artist,
        total_tracks=1,
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"other audio")

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert destination.read_bytes() == b"other audio"
    assert Path(song.file_path).read_bytes() == b"audio data"


@pytest.mark.unit
@pytest.mark.django_db
def test_db_failure_keeps_original_valid(tmp_path):
    """A DB failure must leave the old DB path referencing valid audio.

    The destination copy may remain inert, but the original is never removed
    or tagged before commit, so the database's old reference stays valid.
    """
    artist = Artist.objects.create(name="New Artist", gid="artist-dbfail")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-dbfail", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    source = Path(song.file_path)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ) as update_tags,
        patch(
            "library_manager.tasks.metadata.FilePath.objects.get_or_create",
            side_effect=RuntimeError("simulated DB failure"),
        ),
    ):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                _migrate_downloaded_song(song)

    song.refresh_from_db()
    assert Path(song.file_path) == source
    assert source.is_file()
    assert source.read_bytes() == b"audio data"
    # Tags were applied to the independent destination copy, never the source.
    assert update_tags.call_args.args[0] == destination


@pytest.mark.unit
@pytest.mark.django_db
def test_resume_rejects_ambiguous_destination_without_db_mutation(tmp_path):
    """A missing source with a matching filename is never adopted."""
    artist = Artist.objects.create(name="New Artist", gid="artist-resume")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-resume", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    original_ref_id = song.file_path_ref_id
    source = Path(song.file_path)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    destination.write_bytes(b"unrelated audio")

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ) as update_tags,
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert destination.read_bytes() == b"unrelated audio"
    update_tags.assert_not_called()
    song.refresh_from_db()
    # Ambiguity must not mutate the database: no destructive clearing.
    assert song.file_path_ref_id == original_ref_id
    assert song.downloaded is True


@pytest.mark.unit
@pytest.mark.django_db
def test_unreadable_source_leaves_db_unchanged(tmp_path):
    """An unreadable source is rejected without touching the song row."""
    artist = Artist.objects.create(name="New Artist", gid="artist-unreadable")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-unreadable", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    original_ref_id = song.file_path_ref_id
    # Simulate a transient/stat error: Path.is_file() returns False even though
    # the file still exists. The migration must reject without DB mutation.
    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch("pathlib.Path.is_file", return_value=False),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert Path(song.file_path).is_file()
    song.refresh_from_db()
    assert song.file_path_ref_id == original_ref_id
    assert song.downloaded is True


@pytest.mark.unit
@pytest.mark.django_db
def test_db_failure_keeps_original_even_with_inert_destination(tmp_path):
    """A failed migration never removes the original before commit."""
    artist = Artist.objects.create(name="New Artist", gid="artist-race")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-race", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    source = Path(song.file_path)

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
        patch(
            "library_manager.tasks.metadata.FilePath.objects.get_or_create",
            side_effect=RuntimeError("simulated DB failure"),
        ),
    ):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                _migrate_downloaded_song(song)

    song.refresh_from_db()
    assert Path(song.file_path) == source
    assert source.is_file()
    assert source.read_bytes() == b"audio data"


@pytest.mark.unit
@pytest.mark.django_db
def test_outer_transaction_rollback_keeps_original_valid(tmp_path):
    """Outer rollback must leave the DB path pointing at valid audio.

    The destination copy is inert (no DB reference); the original is retained
    and never adopted by filename on a later run.
    """
    artist = Artist.objects.create(name="New Artist", gid="artist-outer")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-outer", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    original_ref_id = song.file_path_ref_id
    source = Path(song.file_path)

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        try:
            with transaction.atomic():
                _migrate_downloaded_song(song)
                raise RuntimeError("outer rollback")
        except RuntimeError:
            pass

    song.refresh_from_db()
    assert song.file_path_ref_id == original_ref_id
    assert Path(song.file_path) == source
    assert source.is_file()
    assert source.read_bytes() == b"audio data"

    # A later run still rejects rather than adopting the destination copy.
    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        # The source still exists, so this run can migrate again; it must not
        # silently overwrite the inert destination from the rolled-back run.
        assert _migrate_downloaded_song(song) is False
    song.refresh_from_db()
    assert song.file_path_ref_id == original_ref_id


@pytest.mark.unit
@pytest.mark.django_db
def test_cleanup_refuses_paths_outside_library(tmp_path):
    """cleanup_old_files must not delete a file outside OUTPUT_PATH."""
    root = (tmp_path / "music").resolve()
    root.mkdir()
    outsider = tmp_path / "precious.txt"
    outsider.write_bytes(b"keep me")

    with override_settings(OUTPUT_PATH=str(root)):
        cleanup_old_files([str(outsider)])

    assert outsider.is_file(), "file outside the music root must be untouched"


# ---------------------------------------------------------------------------
# Download filename sanitizer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_download_sanitizer_rejects_dotdot():
    chain = DownloadProviderChain(output_dir=Path("/tmp/music"))
    assert chain._sanitize_filename("..") == ""
    assert chain._sanitize_filename(".") == ""
    assert chain._sanitize_filename("Pink Floyd") == "Pink Floyd"


@pytest.mark.unit
def test_apply_metadata_update_marks_applied_after_safe_migration(tmp_path):
    """End-to-end safety: a normal rename still applies and moves the file."""
    artist = Artist.objects.create(name="New Artist", gid="artist-e2e")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-e2e", artist=artist, total_tracks=1
    )
    _make_downloaded_song(tmp_path, artist=artist, album=album)
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
        ),
    ):
        apply_metadata_update.run(update.pk)

    update.refresh_from_db()
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    assert destination.is_file()
    assert update.status == "applied"


@pytest.mark.unit
def test_m3u_write_uses_atomic_replace(tmp_path):
    """M3U generation must not truncate a file another process is reading."""
    from unittest.mock import MagicMock, patch

    from downloader.m3u_writer import write_playlist_m3u

    playlist = MagicMock()
    playlist.name = "My Playlist"
    playlist_song = MagicMock()
    playlist_song.song = MagicMock()
    playlist_song.song.primary_artist_id = None
    playlist_song.song.name = "Song"
    playlist_song.song.file_path_ref = None
    playlist_song.song.isrc = None

    with (
        patch(
            "library_manager.models.TrackedPlaylist.objects.get",
            return_value=playlist,
        ),
        patch(
            "library_manager.models.PlaylistSong.objects.filter",
            return_value=MagicMock(
                select_related=lambda *args: MagicMock(
                    order_by=lambda *a: MagicMock(
                        exists=lambda: True,
                        __iter__=lambda self: iter([playlist_song]),
                    )
                ),
            ),
        ),
    ):
        result = write_playlist_m3u(1, tmp_path, "Playlists")

    assert result is not None
    assert result.read_text(encoding="utf-8").startswith("#EXTM3U")
    # No temporary files left behind in the playlist directory.
    assert sorted(p.name for p in result.parent.iterdir()) == [result.name]


@pytest.mark.unit
@pytest.mark.django_db
def test_long_composed_filename_keeps_extension(tmp_path):
    """Long artist/song names must not lose the extension on migration."""
    long_name = "A" * 95
    artist = Artist.objects.create(name=long_name, gid="artist-long")
    album = Album.objects.create(
        name="Album", spotify_gid="album-long", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album, name="B" * 95)
    with override_settings(OUTPUT_PATH=str(tmp_path)):
        destination = _metadata_destination(song, Path(song.file_path))
    assert destination.suffix == ".m4a"
    assert len(destination.name) > 100


@pytest.mark.unit
def test_assert_within_preserves_long_composed_m3u_name(tmp_path):
    root = tmp_path.resolve()
    name = "Playlist " + "X" * 200 + ".m3u"
    result = assert_within(root, name)
    assert result.name == name
    assert result.suffix == ".m3u"


@pytest.mark.unit
def test_secure_write_uses_private_temp_and_leaves_no_temp(tmp_path):
    from downloader.filesystem_safety import secure_write

    target = tmp_path / "playlist.m3u"
    secure_write(target, "#EXTM3U\n")
    assert target.read_text(encoding="utf-8") == "#EXTM3U\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


@pytest.mark.unit
@pytest.mark.django_db
def test_concurrent_destination_is_not_clobbered(tmp_path):
    """A destination created just before publish must not be overwritten."""
    import errno
    import os

    artist = Artist.objects.create(name="New Artist", gid="artist-concdest")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-concdest", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    real_link = os.link

    def racing_link(source, target):
        if Path(target) == destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"concurrent destination")
            raise OSError(errno.EEXIST, "destination appeared")
        return real_link(source, target)

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch("library_manager.tasks.metadata.os.link", racing_link),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        result = _migrate_downloaded_song(song)

    assert result is False
    assert destination.read_bytes() == b"concurrent destination"
    assert Path(song.file_path).read_bytes() == b"audio data"


@pytest.mark.unit
@pytest.mark.django_db
def test_migration_sanitizes_separator_in_artist_once(tmp_path):
    """AC/DC becomes AC-DC in the path without escaping the root."""
    artist = Artist.objects.create(name="AC/DC", gid="artist-acdc")
    album = Album.objects.create(
        name="Back In Black", spotify_gid="album-acdc", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)

    with override_settings(OUTPUT_PATH=str(tmp_path)):
        destination = _metadata_destination(song, Path(song.file_path))

    assert destination.parent.parent.name == "AC-DC"
    assert destination.suffix == ".m4a"
    assert is_within(destination, tmp_path)


@pytest.mark.unit
def test_secure_write_preserves_readable_mode(tmp_path):
    """New playlists are 0644 (readable by media servers), not 0600."""
    from downloader.filesystem_safety import secure_write

    target = tmp_path / "playlist.m3u"
    secure_write(target, "#EXTM3U\n")
    assert target.stat().st_mode & 0o777 == 0o644

    # An existing target keeps its own mode across replacement.
    target.chmod(0o640)
    secure_write(target, "#EXTM3U\nupdated\n")
    assert target.stat().st_mode & 0o777 == 0o640


@pytest.mark.unit
@pytest.mark.django_db
def test_shared_reference_original_always_retained(tmp_path):
    """A second song sharing the original FilePath keeps that file valid."""
    artist = Artist.objects.create(name="New Artist", gid="artist-shared-ref")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-shared-ref", artist=artist, total_tracks=2
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    source = Path(song.file_path)
    # A non-downloaded song that still references the original path.
    Song.objects.create(
        name="Other Song",
        gid="song-shared-ref-other",
        primary_artist=artist,
        album=album,
        downloaded=False,
        file_path_ref=song.file_path_ref,
    )

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        result = _migrate_downloaded_song(song)

    assert result is True
    assert source.is_file()
    assert source.read_bytes() == b"audio data"


@pytest.mark.unit
@pytest.mark.django_db
def test_destination_replaced_before_commit_original_retained(tmp_path):
    """If the published destination is replaced, the original is never deleted."""
    artist = Artist.objects.create(name="New Artist", gid="artist-replaced")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-replaced", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    source = Path(song.file_path)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"

    def replace_destination(*args, **kwargs):
        # Simulate a concurrent writer replacing the destination after our
        # publish but before the DB update completes.
        destination.write_bytes(b"replaced by other process")
        return True

    with (
        override_settings(OUTPUT_PATH=str(tmp_path)),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            side_effect=replace_destination,
        ),
    ):
        result = _migrate_downloaded_song(song)

    assert result is True
    assert destination.read_bytes() == b"replaced by other process"
    assert source.is_file()
    assert source.read_bytes() == b"audio data"


@pytest.mark.unit
@pytest.mark.django_db
def test_in_place_migration_keeps_path_valid_on_rollback(tmp_path):
    """In-place tag rewrites keep the path valid; tag changes are documented."""
    artist = Artist.objects.create(name="Same Artist", gid="artist-inplace")
    album = Album.objects.create(
        name="Same Album", spotify_gid="album-inplace", artist=artist, total_tracks=1
    )
    song = _make_downloaded_song(tmp_path, artist=artist, album=album)
    source = Path(song.file_path)
    # Point at the canonical path so no move is needed.
    canonical = tmp_path / "Same Artist" / "Same Album" / "Same Artist - Old Song.m4a"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    source.replace(canonical)
    song.file_path_ref.path = str(canonical)
    song.file_path_ref.save(update_fields=["path"])

    try:
        with transaction.atomic():
            with override_settings(OUTPUT_PATH=str(tmp_path)):
                patcher = patch(
                    "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                    return_value=True,
                )
                patcher.start()
                try:
                    result = _migrate_downloaded_song(song)
                finally:
                    patcher.stop()
            assert result is True
            raise RuntimeError("outer rollback")
    except RuntimeError:
        pass

    song.refresh_from_db()
    assert Path(song.file_path) == canonical
    assert canonical.is_file()
