"""Tests for safe deletion of migration-retained originals and the cleanup command.

The metadata migration copies a file to a canonical destination, tags only the
copy, and CAS-updates the DB. Once the transaction commits, the retained original
may be unlinked, but only after a strict set of re-checks that protect against
concurrent writers and shared references. The cleanup command handles originals
left behind by earlier migrations using an explicit migration link log.
"""

import json
import stat
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import override_settings

import pytest

from library_manager.models import Album, Artist, FilePath, Song
from library_manager.tasks.metadata import _migrate_downloaded_song


def _make_song(tmp_path, *, artist, album, name="Old Song", gid="song-cleanup"):
    old_path = tmp_path / "Old Artist" / "Old Album" / "old-file.m4a"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"audio data")
    return Song.objects.create(
        name=name,
        gid=gid,
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(old_path)),
    )


def _setup(tmp_path, gid="song-cleanup", name="Old Song"):
    artist = Artist.objects.create(name="New Artist", gid=f"artist-{gid}")
    album = Album.objects.create(
        name="New Album",
        spotify_gid=f"album-{gid}",
        artist=artist,
        total_tracks=2,
    )
    song = _make_song(tmp_path, artist=artist, album=album, name=name, gid=gid)
    return song


def _migrate(tmp_path, song):
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    with (
        override_settings(
            OUTPUT_PATH=str(tmp_path),
            MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
        ),
        patch(
            "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
            return_value=True,
        ),
    ):
        result = _migrate_downloaded_song(song)
    return destination, result


# ---------------------------------------------------------------------------
# on_commit cleanup checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
def test_shared_reference_keeps_original(tmp_path, django_capture_on_commit_callbacks):
    """Another Song referencing the original FilePath blocks deletion."""
    song = _setup(tmp_path, gid="shared")
    source = Path(song.file_path)
    Song.objects.create(
        name="Other",
        gid="song-shared-other",
        primary_artist=song.primary_artist,
        album=song.album,
        downloaded=False,
        file_path_ref=song.file_path_ref,
    )
    with override_settings(MIGRATION_LINK_LOG=str(_link_log_for(tmp_path))):
        with django_capture_on_commit_callbacks(execute=True):
            _migrate(tmp_path, song)
    assert source.is_file()


@pytest.mark.unit
@pytest.mark.django_db
def test_downloaded_false_reference_keeps_original(
    tmp_path, django_capture_on_commit_callbacks
):
    """A downloaded=False Song holding the old path still blocks deletion."""
    song = _setup(tmp_path, gid="notdownloaded")
    source = Path(song.file_path)
    Song.objects.create(
        name="Inactive",
        gid="song-not-dl",
        primary_artist=song.primary_artist,
        album=song.album,
        downloaded=False,
        file_path_ref=song.file_path_ref,
    )
    with override_settings(MIGRATION_LINK_LOG=str(_link_log_for(tmp_path))):
        with django_capture_on_commit_callbacks(execute=True):
            _migrate(tmp_path, song)
    assert source.is_file()


@pytest.mark.unit
@pytest.mark.django_db
def test_destination_replaced_keeps_original(
    tmp_path, django_capture_on_commit_callbacks
):
    """A destination replaced after commit registration fails the inode check."""
    song = _setup(tmp_path, gid="replaced")
    source = Path(song.file_path)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"

    with override_settings(
        OUTPUT_PATH=str(tmp_path),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            with patch(
                "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                return_value=True,
            ):
                assert _migrate_downloaded_song(song) is True
            # A concurrent writer replaces the destination between the
            # successful CAS and the on_commit cleanup.
            destination.write_bytes(b"replaced by another writer")
            for callback in callbacks:
                callback()

    assert source.is_file()
    assert destination.read_bytes() == b"replaced by another writer"


@pytest.mark.unit
@pytest.mark.django_db
def test_original_replaced_keeps_original(tmp_path, django_capture_on_commit_callbacks):
    """If the original's inode changed, deletion is skipped."""
    song = _setup(tmp_path, gid="orig-replaced")
    source = Path(song.file_path)

    def replace_original(*args, **kwargs):
        source.write_bytes(b"new inode at old path")
        return True

    with override_settings(
        OUTPUT_PATH=str(tmp_path),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            with patch(
                "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                side_effect=replace_original,
            ):
                assert _migrate_downloaded_song(song) is True
    assert source.read_bytes() == b"new inode at old path"


@pytest.mark.unit
@pytest.mark.django_db
def test_normal_migration_deletes_original_after_commit(
    tmp_path, django_capture_on_commit_callbacks
):
    """With no blockers, the original is deleted once the transaction commits."""
    song = _setup(tmp_path, gid="normal")
    source = Path(song.file_path)
    with override_settings(MIGRATION_LINK_LOG=str(_link_log_for(tmp_path))):
        with django_capture_on_commit_callbacks(execute=True):
            destination, result = _migrate(tmp_path, song)
    assert result is True
    assert destination.is_file()
    assert not source.exists()
    song.refresh_from_db()
    assert song.file_path == str(destination)
    assert song.downloaded is True


@pytest.mark.unit
@pytest.mark.django_db
def test_outer_rollback_deletes_nothing(tmp_path):
    """An outer rollback after the CAS means on_commit never runs."""
    song = _setup(tmp_path, gid="rollback")
    source = Path(song.file_path)

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            with (
                override_settings(
                    OUTPUT_PATH=str(tmp_path),
                    MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
                ),
                patch(
                    "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                    return_value=True,
                ),
            ):
                assert _migrate_downloaded_song(song) is True
            raise RuntimeError("outer rollback")

    assert source.is_file()
    assert source.read_bytes() == b"audio data"
    song.refresh_from_db()
    assert song.file_path == str(source)


@pytest.mark.unit
@pytest.mark.django_db
def test_callback_never_raises_on_missing_files(
    tmp_path, django_capture_on_commit_callbacks
):
    """A callback whose destination vanished logs and keeps the original."""
    song = _setup(tmp_path, gid="missing")
    source = Path(song.file_path)
    destination = tmp_path / "New Artist" / "New Album" / "New Artist - Old Song.m4a"

    def remove_destination(*args, **kwargs):
        published = destination
        if published.is_file():
            published.unlink()
        return True

    with override_settings(
        OUTPUT_PATH=str(tmp_path),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            with patch(
                "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                side_effect=remove_destination,
            ):
                # Tagging removing the destination before identity capture
                # must not raise out of the migration.
                _migrate_downloaded_song(song)
    assert source.is_file()


# ---------------------------------------------------------------------------
# Cleanup management command
# ---------------------------------------------------------------------------


def _link_log_for(tmp_path):
    return tmp_path / "migration-links.jsonl"


def _retained(old_path, new_path, song_id=1, reason="test retention"):
    return {
        "event": "retained",
        "song_id": song_id,
        "old_path": str(old_path),
        "new_path": str(new_path),
        "old_size": 10,
        "reason": reason,
    }


def _write_link_log(tmp_path, links):
    log = _link_log_for(tmp_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        for link in links:
            handle.write(json.dumps(link) + "\n")
    return log


@pytest.mark.unit
@pytest.mark.django_db
def test_command_dry_run_deletes_nothing(tmp_path):
    """Dry-run (the default) must list candidates but never delete."""
    artist = Artist.objects.create(name="New Artist", gid="artist-cmd")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-cmd", artist=artist, total_tracks=1
    )
    original = tmp_path / "Old Artist" / "Old Album" / "old.m4a"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"audio data")
    new_path = tmp_path / "New Artist" / "New Album" / "New Artist - Song.m4a"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(b"audio data")
    Song.objects.create(
        name="Song",
        gid="song-cmd-dry",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(new_path)),
    )
    _write_link_log(tmp_path, [_retained(original, new_path)])

    with override_settings(
        OUTPUT_PATH=str(tmp_path),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        call_command("cleanup_retained_migration_originals")

    assert original.is_file()


@pytest.mark.unit
@pytest.mark.django_db
def test_command_apply_writes_audit_then_deletes(tmp_path):
    """--apply with an audit file audits and unlinks only confirmed pairs."""
    artist = Artist.objects.create(name="New Artist", gid="artist-cmd-apply")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-cmd-apply", artist=artist, total_tracks=1
    )
    original = tmp_path / "Old Artist" / "Old Album" / "old.m4a"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"audio data")
    new_path = tmp_path / "New Artist" / "New Album" / "New Artist - Song.m4a"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(b"audio data")
    Song.objects.create(
        name="Song",
        gid="song-cmd-apply",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(new_path)),
    )
    _write_link_log(tmp_path, [_retained(original, new_path)])
    audit = tmp_path / "audit.jsonl"

    with override_settings(
        OUTPUT_PATH=str(tmp_path),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        call_command(
            "cleanup_retained_migration_originals",
            "--apply",
            "--audit-file",
            str(audit),
        )

    assert not original.exists()
    assert new_path.is_file()
    assert audit.is_file()
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    records = [json.loads(line) for line in audit.read_text().splitlines() if line]
    assert len(records) == 1
    assert records[0]["path"] == str(original)
    assert records[0]["size"] == 10
    assert records[0]["new_path"] == str(new_path)


@pytest.mark.unit
@pytest.mark.django_db
def test_command_apply_requires_audit_file(tmp_path):
    """--apply without --audit-file is rejected without deleting anything."""
    original = tmp_path / "music" / "old.m4a"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"audio data")

    with override_settings(
        OUTPUT_PATH=str(tmp_path / "music"),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        with pytest.raises(CommandError):
            call_command("cleanup_retained_migration_originals", "--apply")

    assert original.is_file()


@pytest.mark.unit
@pytest.mark.django_db
def test_command_reports_no_reliable_link_and_lists_candidates(tmp_path, capsys):
    """Without a link log, candidates are listed but never deleted."""
    original = tmp_path / "music" / "Old Artist" / "old.m4a"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"audio data")
    _link_log_for(tmp_path).unlink(missing_ok=True)

    with override_settings(
        OUTPUT_PATH=str(tmp_path / "music"),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        call_command(
            "cleanup_retained_migration_originals",
            "--apply",
            "--audit-file",
            str(tmp_path / "audit.jsonl"),
        )

    output = capsys.readouterr().out
    assert "no reliable migration link" in output.lower()
    assert str(original) in output
    assert original.is_file()


@pytest.mark.unit
@pytest.mark.django_db
def test_command_skips_symlinks_and_outside_root(tmp_path):
    """Symlinked files and files outside the music root are never deleted."""
    root = tmp_path / "music"
    root.mkdir()
    outside = tmp_path / "outside" / "outside.m4a"
    outside.parent.mkdir()
    outside.write_bytes(b"audio data")
    linked = root / "linked.m4a"
    linked.symlink_to(outside)

    new_path = root / "New Artist" / "new.m4a"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(b"audio data")
    artist = Artist.objects.create(name="New Artist", gid="artist-cmd-symlink")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-cmd-symlink", artist=artist, total_tracks=1
    )
    Song.objects.create(
        name="Song",
        gid="song-cmd-symlink",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(new_path)),
    )
    _write_link_log(
        root,
        [
            _retained(linked, new_path),
            _retained(outside, new_path),
        ],
    )
    audit = tmp_path / "audit.jsonl"

    with override_settings(
        OUTPUT_PATH=str(root),
        MIGRATION_LINK_LOG=str(_link_log_for(root)),
    ):
        call_command(
            "cleanup_retained_migration_originals",
            "--apply",
            "--audit-file",
            str(audit),
        )

    assert outside.is_file()
    assert linked.is_symlink()
    assert not audit.exists() or audit.read_text() == ""


@pytest.mark.unit
@pytest.mark.django_db
def test_command_audit_file_exclusive_create(tmp_path):
    """An existing audit file is never overwritten."""
    audit = tmp_path / "audit.jsonl"
    audit.write_text("previous\n")

    with override_settings(
        OUTPUT_PATH=str(tmp_path / "music"),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        with pytest.raises(CommandError):
            call_command(
                "cleanup_retained_migration_originals",
                "--apply",
                "--audit-file",
                str(audit),
            )

    assert audit.read_text() == "previous\n"


# ---------------------------------------------------------------------------
# Retained/deletion link log records (outside the music root)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
def test_retained_record_written_outside_music_root_on_commit(
    tmp_path, django_capture_on_commit_callbacks
):
    """A kept original produces one retained record under the config dir."""
    root = tmp_path / "music"
    root.mkdir()
    config_dir = tmp_path / "config"
    log = config_dir / "migration-links.jsonl"
    artist = Artist.objects.create(name="New Artist", gid="artist-log-retained")
    album = Album.objects.create(
        name="New Album",
        spotify_gid="album-log-retained",
        artist=artist,
        total_tracks=2,
    )
    song = _make_song(root, artist=artist, album=album, gid="log-retained")
    source = Path(song.file_path)
    Song.objects.create(
        name="Other",
        gid="song-log-retained-other",
        primary_artist=artist,
        album=album,
        downloaded=False,
        file_path_ref=song.file_path_ref,
    )
    destination = root / "New Artist" / "New Album" / "New Artist - Old Song.m4a"

    with override_settings(OUTPUT_PATH=str(root), MIGRATION_LINK_LOG=str(log)):
        with django_capture_on_commit_callbacks(execute=True):
            with patch(
                "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                return_value=True,
            ):
                assert _migrate_downloaded_song(song) is True

    assert source.is_file()
    assert log.is_file()
    assert log.is_relative_to(config_dir)
    assert not log.is_relative_to(root)
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    records = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "retained"
    assert record["song_id"] == song.pk
    assert record["old_path"] == str(source)
    assert record["new_path"] == str(destination)
    assert record["old_size"] == 10
    assert record["old_identity"]
    assert record["timestamp"]
    assert "references" in record["reason"]


@pytest.mark.unit
@pytest.mark.django_db
def test_deletion_record_written_and_log_appends(
    tmp_path, django_capture_on_commit_callbacks
):
    """A successful deletion is recorded too, and records append as JSON lines."""
    root = tmp_path / "music"
    root.mkdir()
    log = tmp_path / "config" / "migration-links.jsonl"
    artist = Artist.objects.create(name="New Artist", gid="artist-log-deleted")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-log-deleted", artist=artist, total_tracks=1
    )
    song = _make_song(root, artist=artist, album=album, gid="log-deleted")
    source = Path(song.file_path)

    with override_settings(OUTPUT_PATH=str(root), MIGRATION_LINK_LOG=str(log)):
        with django_capture_on_commit_callbacks(execute=True):
            with patch(
                "library_manager.tasks.metadata.MetadataEmbedder.update_basic_metadata",
                return_value=True,
            ):
                assert _migrate_downloaded_song(song) is True

    assert not source.exists()
    records = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(records) == 1
    assert records[0]["event"] == "deleted"
    assert records[0]["song_id"] == song.pk
    assert records[0]["old_path"] == str(source)
    assert records[0]["reason"] is None

    before = log.read_text()
    from library_manager.tasks.metadata import _append_link_record

    with override_settings(MIGRATION_LINK_LOG=str(log)):
        _append_link_record({"event": "marker", "note": "second line"})
    after = log.read_text()
    assert after.startswith(before)
    assert len(after.splitlines()) == 2


# ---------------------------------------------------------------------------
# Historical migration data is not a reliable link (no --from-history)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
def test_history_data_alone_never_justifies_deletion(tmp_path, capsys):
    """Applied updates, orphan FilePaths and TaskHistory logs cannot map a pair.

    Earlier migrations left originals with no link record. The DB stores only
    entity renames (no file paths) and orphan FilePath rows with no old→new
    relation, so the command must list candidates and delete nothing even when
    convincing-looking history data exists.
    """
    from django.contrib.contenttypes.models import ContentType

    from library_manager.models import PendingMetadataUpdate, TaskHistory

    root = tmp_path / "music"
    root.mkdir()
    original = root / "Old Artist" / "Old Album" / "old.m4a"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"audio data")
    new_path = root / "New Artist" / "New Album" / "New Artist - Old Song.m4a"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(b"audio data")
    artist = Artist.objects.create(name="New Artist", gid="artist-history")
    album = Album.objects.create(
        name="New Album", spotify_gid="album-history", artist=artist, total_tracks=1
    )
    Song.objects.create(
        name="Song",
        gid="song-history",
        primary_artist=artist,
        album=album,
        downloaded=True,
        file_path_ref=FilePath.objects.create(path=str(new_path)),
    )
    FilePath.objects.create(path=str(original))
    PendingMetadataUpdate.objects.create(
        content_type=ContentType.objects.get_for_model(Artist),
        object_id=artist.pk,
        old_value="Old Artist",
        new_value="New Artist",
        status="applied",
    )
    TaskHistory.objects.create(
        task_id="history-1",
        type="SYNC",
        entity_id="1",
        entity_type="ARTIST",
        status="COMPLETED",
        log_messages=[{"message": "Updated artist name: 'Old Artist' → 'New Artist'"}],
    )
    audit = tmp_path / "audit.jsonl"

    with override_settings(
        OUTPUT_PATH=str(root),
        MIGRATION_LINK_LOG=str(_link_log_for(tmp_path)),
    ):
        call_command(
            "cleanup_retained_migration_originals",
            "--apply",
            "--audit-file",
            str(audit),
        )

    output = capsys.readouterr().out
    assert "no reliable migration link" in output.lower()
    assert str(original) in output
    assert original.is_file()
