"""Song identity repair must be explicit, audited, and reversible."""

import json
import os
import stat
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import pytest

from library_manager.management.commands.repair_song_identity import TrackTruth
from library_manager.models import Album, Artist, ContributingArtist, Song
from library_manager.tasks import TaskPriority


@pytest.fixture
def wrong_artist():
    return Artist.objects.create(name="Wrong Credit", deezer_id=8802001)


@pytest.fixture
def right_artist():
    return Artist.objects.create(name="Right Credit", deezer_id=8802002)


def _truth(**overrides):
    values = {
        "title": "Test Track Three",
        "isrc": "TEST00000003",
        "deezer_track_id": 900105,
        "deezer_album_id": 900106,
        "local_album_ok": True,
        "reason": None,
        "sp_album_id": "album-gid",
        "sp_album_upc": "upc-1",
        "artist_name": "Right Credit",
        "artist_deezer_id": 8802002,
        "all_artist_names": ("Right Credit", "Wrong Credit"),
        "duration_ms": 144000,
    }
    values.update(overrides)
    return TrackTruth(**values)


def _song(
    artist,
    *,
    name="Test Track Three",
    gid="gid-repair",
    isrc,
    deezer_id,
    file_path=None,
):
    album = Album.objects.create(
        name=name, artist=artist, deezer_id=8802999, spotify_gid="album-repair"
    )
    song = Song.objects.create(
        name=name,
        gid=gid,
        primary_artist=artist,
        isrc=isrc,
        deezer_id=deezer_id,
        album=album,
        downloaded=True,
        bitrate=256,
        matched_title="stale",
    )
    if file_path:
        song.set_file_path(file_path)
        song.save(update_fields=["file_path_ref"])
    return song


@pytest.mark.django_db
def test_dry_run_reports_changes_without_writing(wrong_artist):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch("library_manager.helpers.enqueue_download_deezer_track") as queue,
    ):
        call_command("repair_song_identity", song=[str(song.id)], stdout=output)

    text = output.getvalue()
    assert "DRY RUN" in text
    assert "deezer_id" in text and "999999" in text and "900105" in text
    song.refresh_from_db()
    assert song.deezer_id == 999999
    assert song.primary_artist == wrong_artist
    queue.assert_not_called()


@pytest.mark.django_db
def test_apply_requires_new_audit_file_and_writes_it_before_updates(wrong_artist):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    with pytest.raises(CommandError, match="requires --audit-file"):
        call_command(
            "repair_song_identity", song=[str(song.id)], apply=True, stdout=StringIO()
        )

    audit_path = "/tmp/repair-song-identity-audit.json"
    if os.path.exists(audit_path):
        os.unlink(audit_path)

    def fail_on_update(*args, **kwargs):
        raise AssertionError("update attempted before audit file was written")

    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch.object(Song, "save", side_effect=fail_on_update),
    ):
        with pytest.raises(AssertionError, match="update attempted"):
            call_command(
                "repair_song_identity",
                song=[str(song.id)],
                apply=True,
                audit_file=audit_path,
                stdout=StringIO(),
            )

    payload = json.loads(open(audit_path, encoding="utf-8").read())
    assert payload[0]["id"] == song.id
    assert payload[0]["rollback"]["deezer_id"] == 999999
    assert stat.S_IMODE(os.stat(audit_path).st_mode) == 0o600
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        pytest.raises(CommandError, match="already exists"),
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=audit_path,
            stdout=StringIO(),
        )
    os.unlink(audit_path)


@pytest.mark.django_db
def test_apply_corrects_identity_adds_artists_and_queues_once(
    wrong_artist, right_artist, tmp_path
):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    audit = tmp_path / "audit.json"
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track",
            return_value=True,
        ) as queue,
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )

    song.refresh_from_db()
    assert song.deezer_id == 900105
    assert song.album.deezer_id == 900106
    assert song.primary_artist.name == "Right Credit"
    assert song.downloaded is False
    assert song.bitrate == 0
    assert song.matched_title is None
    assert set(
        ContributingArtist.objects.filter(song=song).values_list(
            "artist__name", flat=True
        )
    ) == {"Wrong Credit"}
    queue.assert_called_once_with(song.id, priority=TaskPriority.TRACK_DOWNLOAD)


@pytest.mark.django_db
def test_shared_file_is_kept(tmp_path, wrong_artist):
    music_root = tmp_path / "music"
    target = music_root / "Wrong Credit" / "Test Track Three.m4a"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"audio")
    song = _song(
        wrong_artist,
        isrc="TEST00000003",
        deezer_id=999999,
        file_path=str(target),
    )
    other = Song.objects.create(
        name="Other", gid="gid-other", primary_artist=wrong_artist, deezer_id=888888
    )
    other.set_file_path(str(target))
    other.save(update_fields=["file_path_ref"])

    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ),
        override_settings(OUTPUT_PATH=str(music_root)),
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )

    assert target.exists()
    song.refresh_from_db()
    assert song.file_path_ref is not None


@pytest.mark.django_db
def test_deduped_requeue_reports_when_task_already_active(wrong_artist, tmp_path):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track",
            return_value=False,
        ) as queue,
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=output,
        )
    queue.assert_called_once()
    assert "already active" in output.getvalue()


@pytest.mark.django_db
def test_scan_reports_candidates_without_changes(wrong_artist):
    _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)

    output = StringIO()
    truth = _truth(deezer_track_id=900105)
    with patch(
        "library_manager.management.commands.repair_song_identity.fetch_truth",
        return_value=truth,
    ):
        call_command("repair_song_identity", scan=True, stdout=output)
    assert "999999" in output.getvalue()
    assert "900105" in output.getvalue()


@pytest.mark.django_db
def test_same_isrc_two_albums_get_each_albums_deezer_id(wrong_artist, tmp_path):
    album_a = Album.objects.create(
        name="Album A", artist=wrong_artist, deezer_id=8802999, spotify_gid="album-a"
    )
    album_b = Album.objects.create(
        name="Album B", artist=wrong_artist, deezer_id=8803999, spotify_gid="album-b"
    )
    song_a = Song.objects.create(
        name="Track",
        gid="gid-a",
        primary_artist=wrong_artist,
        isrc="SAME-ISRC",
        deezer_id=999991,
        album=album_a,
    )
    song_b = Song.objects.create(
        name="Track",
        gid="gid-b",
        primary_artist=wrong_artist,
        isrc="SAME-ISRC",
        deezer_id=999992,
        album=album_b,
    )
    truth_a = _truth(
        isrc="SAME-ISRC",
        deezer_track_id=8801111,
        deezer_album_id=8802999,
        local_album_ok=True,
    )
    truth_b = _truth(
        isrc="SAME-ISRC",
        deezer_track_id=8802222,
        deezer_album_id=8803999,
        local_album_ok=True,
    )

    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            side_effect=[truth_a, truth_b],
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ),
    ):
        call_command(
            "repair_song_identity",
            song=[str(song_a.id), str(song_b.id)],
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )

    song_a.refresh_from_db()
    song_b.refresh_from_db()
    assert song_a.deezer_id == 8801111
    assert song_b.deezer_id == 8802222
    assert song_a.album.deezer_id == 8802999
    assert song_b.album.deezer_id == 8803999


@pytest.mark.django_db
def test_ambiguous_album_clears_deezer_id_and_reports_reason(wrong_artist, tmp_path):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    truth = _truth(
        deezer_track_id=None,
        deezer_album_id=None,
        local_album_ok=False,
        reason="ambiguous: two Deezer albums match UPC and artist",
    )
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=truth,
        ),
        patch(
            "library_manager.helpers.enqueue_download_track_by_spotify_gid",
            return_value=True,
        ) as queue_gid,
        patch("library_manager.helpers.enqueue_download_deezer_track") as queue_dz,
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=output,
        )

    song.refresh_from_db()
    assert song.deezer_id is None
    assert "ambiguous" in output.getvalue()
    queue_gid.assert_called_once_with(song.gid, priority=TaskPriority.TRACK_DOWNLOAD)
    queue_dz.assert_not_called()


@pytest.mark.django_db
def test_ambiguous_album_dry_run_never_reports_collision(wrong_artist):
    song = _song(wrong_artist, isrc="TEST00000003", deezer_id=999999)
    Song.objects.create(
        name="Other", gid="gid-other", primary_artist=wrong_artist, deezer_id=900105
    )
    output = StringIO()
    truth = _truth(
        deezer_track_id=None,
        deezer_album_id=None,
        local_album_ok=False,
        reason="ambiguous: no unique Deezer album",
    )
    with patch(
        "library_manager.management.commands.repair_song_identity.fetch_truth",
        return_value=truth,
    ):
        call_command("repair_song_identity", song=[str(song.id)], stdout=output)
    assert "NULL" in output.getvalue()
    assert "collision" not in output.getvalue().lower()


@pytest.mark.django_db
def test_existing_song_on_target_album_blocks_id_borrowing(wrong_artist):
    wrong_album = Album.objects.create(
        name="Shut Up and Dance",
        artist=wrong_artist,
        deezer_id=900104,
        spotify_gid="album-kaluma",
    )
    correct_album = Album.objects.create(
        name="Test Track One",
        artist=wrong_artist,
        deezer_id=900103,
        spotify_gid="album-crystal",
    )
    song = Song.objects.create(
        name="Test Track One",
        gid="gid-dupe",
        primary_artist=wrong_artist,
        isrc="TEST00000001",
        deezer_id=900102,
        album=wrong_album,
    )
    Song.objects.create(
        name="Test Track One",
        gid="gid-other",
        primary_artist=wrong_artist,
        isrc="TEST00000001",
        deezer_id=900101,
        album=correct_album,
    )
    truth = _truth(
        isrc="TEST00000001",
        deezer_track_id=900101,
        deezer_album_id=900103,
        local_album_ok=False,
        reason=None,
        sp_album_id="album-crystal",
    )
    output = StringIO()
    with patch(
        "library_manager.management.commands.repair_song_identity.fetch_truth",
        return_value=truth,
    ):
        call_command("repair_song_identity", song=[str(song.id)], stdout=output)

    text = output.getvalue()
    assert "already has song" in text
    assert "deezer_id: 900102 -> None" in text
    assert "collision" not in text.lower()


@pytest.mark.django_db
def test_different_release_repair_clears_song_id_and_keeps_album(
    wrong_artist, tmp_path
):
    song = _song(wrong_artist, isrc="TEST00000001", deezer_id=900102)
    truth = _truth(
        deezer_track_id=900101,
        deezer_album_id=900103,
        local_album_ok=False,
        reason=None,
        different_release=True,
        sp_album_upc="197190945775",
    )
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=truth,
        ),
        patch(
            "library_manager.helpers.enqueue_download_track_by_spotify_gid",
            return_value=True,
        ) as queue_gid,
        patch("library_manager.helpers.enqueue_download_deezer_track") as queue_dz,
    ):
        call_command(
            "repair_song_identity",
            song=[str(song.id)],
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=output,
        )
    song.refresh_from_db()
    assert song.deezer_id is None
    assert song.album.deezer_id == 8802999
    assert "different release" in output.getvalue()
    queue_gid.assert_called_once()
    queue_dz.assert_not_called()
