"""Merge mode: same release, wrong album row, full audit and relation re-pointing."""

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import pytest

from library_manager.management.commands.repair_song_identity import TrackTruth
from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    ExternalList,
    ExternalListTrack,
    PendingMetadataUpdate,
    PlaylistSong,
    Song,
    SongLyricsStatus,
    SongUpgradeAttempt,
    TrackedPlaylist,
)
from library_manager.tasks import TaskPriority


@pytest.fixture
def artist():
    return Artist.objects.create(name="Merge artist", deezer_id=9902001)


@pytest.fixture(autouse=True)
def same_release(monkeypatch):
    monkeypatch.setattr(
        "library_manager.management.commands.repair_song_identity.fetch_album_identity",
        lambda album: SimpleNamespace(upc="197190945775"),
    )


def _truth(**overrides):
    values = {
        "title": "Test Track One",
        "isrc": "TEST00000001",
        "deezer_track_id": 900101,
        "deezer_album_id": 900103,
        "artist_name": "Test Artist A",
        "artist_deezer_id": 1650547,
        "all_artist_names": ("Test Artist A", "Test Artist C", "Test Artist D"),
        "duration_ms": 147000,
        "local_album_ok": False,
        "reason": None,
        "sp_album_id": "synthetic-album-gid-b",
        "sp_album_upc": "197190945775",
    }
    values.update(overrides)
    return TrackTruth(**values)


def _albums(artist):
    wrong_album = Album.objects.create(
        name="Shut Up and Dance",
        artist=artist,
        deezer_id=900104,
        spotify_gid="spotify:album:synthetic-album-gid-a",
    )
    correct_album = Album.objects.create(
        name="Test Track One",
        artist=artist,
        deezer_id=900103,
        spotify_gid="spotify:album:synthetic-album-gid-b",
    )
    return wrong_album, correct_album


def _songs(artist, wrong_album, correct_album):
    keep = Song.objects.create(
        id=900003,
        name="Test Track One",
        gid="synthetic-track-gid",
        primary_artist=artist,
        isrc="TEST00000001",
        deezer_id=900102,
        album=wrong_album,
        downloaded=True,
        bitrate=256,
        matched_title="stale",
    )
    drop = Song.objects.create(
        id=900002,
        name="Test Track One",
        primary_artist=artist,
        isrc="TEST00000001",
        deezer_id=900101,
        album=correct_album,
        downloaded=True,
        bitrate=256,
    )
    return keep, drop


@pytest.mark.django_db
def test_merge_moves_all_relations_without_duplicates(artist, tmp_path):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    playlist = TrackedPlaylist.objects.create(
        name="Sports", url="https://open.spotify.com/playlist/sports"
    )
    PlaylistSong.objects.create(playlist=playlist, song=keep, track_order=0)
    PlaylistSong.objects.create(playlist=playlist, song=drop, track_order=1)
    contributor = Artist.objects.create(name="Test Artist C", deezer_id=900107)
    ContributingArtist.objects.create(song=drop, artist=contributor)
    external = ExternalList.objects.create(
        name="list", source="lastfm", list_type="loved", username="u"
    )
    ExternalListTrack.objects.create(
        external_list=external, artist_name="A", track_name="T", song=drop
    )
    SongLyricsStatus.objects.create(song=drop, has_lyrics=True)
    SongUpgradeAttempt.objects.create(song=drop, provider=2, result=1)
    ct = ContentType.objects.get_for_model(Song)
    PendingMetadataUpdate.objects.create(
        content_type=ct,
        object_id=drop.id,
        field_name="name",
        old_value="T",
        new_value="Test Track One",
    )

    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ) as queue,
    ):
        call_command(
            "repair_song_identity",
            merge_into="900003:900002",
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )

    keep.refresh_from_db()
    assert keep.deezer_id == 900101
    assert keep.album_id == correct_album.id
    assert not Song.objects.filter(id=900002).exists()
    assert PlaylistSong.objects.filter(playlist=playlist, song=keep).count() == 1
    assert ContributingArtist.objects.filter(song=keep, artist=contributor).exists()
    assert ExternalListTrack.objects.filter(song=keep).count() == 1
    assert SongLyricsStatus.objects.filter(song_id=keep.id).exists()
    assert SongUpgradeAttempt.objects.filter(song=keep).exists()
    assert PendingMetadataUpdate.objects.filter(
        content_type=ct, object_id=keep.id
    ).exists()
    assert keep.downloaded is False and keep.bitrate == 0 and keep.matched_title is None
    queue.assert_called_once_with(keep.id, priority=TaskPriority.TRACK_DOWNLOAD)

    audit = json.loads((tmp_path / "audit.json").read_text())
    record = audit[0]
    assert record["merge"]["keep_id"] == 900003 and record["merge"]["drop_id"] == 900002
    assert "relations" in record["merge"]
    assert record["rollback"]["drop"]["id"] == 900002
    assert record["rollback"]["keep"]["deezer_id"] == 900102
    assert record["rollback"]["keep"]["album_id"] == wrong_album.id


@pytest.mark.django_db
def test_merge_dry_run_changes_nothing(artist):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    playlist = TrackedPlaylist.objects.create(name="P", url="https://x/1")
    PlaylistSong.objects.create(playlist=playlist, song=drop, track_order=0)
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch("library_manager.helpers.enqueue_download_deezer_track") as queue,
    ):
        call_command("repair_song_identity", merge_into="900003:900002", stdout=output)
    text = output.getvalue()
    assert "DRY RUN" in text
    assert "constraint simulation" in text.lower()
    keep.refresh_from_db()
    drop.refresh_from_db()
    assert keep.deezer_id == 900102 and keep.album_id == wrong_album.id
    assert Song.objects.filter(id=900002).exists()
    assert PlaylistSong.objects.filter(song=drop).exists()
    queue.assert_not_called()


@pytest.mark.django_db
def test_merge_rejects_drop_that_is_a_different_recording(artist):
    wrong_album, correct_album = _albums(artist)
    keep, _ = _songs(artist, wrong_album, correct_album)
    other = Song.objects.create(
        id=900099,
        name="Other Recording",
        gid="g-other",
        primary_artist=artist,
        isrc="TEST00000099",
        deezer_id=1,
        album=correct_album,
    )
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        pytest.raises(CommandError, match="different recording"),
    ):
        call_command(
            "repair_song_identity",
            merge_into=f"{keep.id}:{other.id}",
            stdout=StringIO(),
        )
    assert Song.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_merge_refuses_different_releases(artist):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_album_identity",
            return_value=SimpleNamespace(upc="999999999999"),
        ),
        pytest.raises(CommandError, match="not the release"),
    ):
        call_command(
            "repair_song_identity", merge_into=f"{keep.id}:{drop.id}", stdout=StringIO()
        )
    assert Song.objects.filter(id=drop.id).exists()


@pytest.mark.django_db
def test_merge_leaves_wrong_album_when_empty_and_audits_it(artist, tmp_path):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=_truth(),
        ),
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ),
    ):
        call_command(
            "repair_song_identity",
            merge_into=f"{keep.id}:{drop.id}",
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )
    assert Album.objects.filter(id=wrong_album.id).exists()
    assert Album.objects.get(id=wrong_album.id).deezer_id == 900104
    record = json.loads((tmp_path / "audit.json").read_text())[0]
    assert record["merge"]["leftover_album"]["id"] == wrong_album.id


@pytest.mark.django_db
def test_merge_keeps_shared_file(artist, tmp_path):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    root = tmp_path / "music"
    target = root / "Test Artist A" / "track.m4a"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"audio")
    drop.set_file_path(str(target))
    drop.save(update_fields=["file_path_ref"])
    other = Song.objects.create(
        name="other", gid="g-other", primary_artist=artist, deezer_id=777
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
        override_settings(OUTPUT_PATH=str(root)),
    ):
        call_command(
            "repair_song_identity",
            merge_into="900003:900002",
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )
    assert target.exists()


@pytest.mark.django_db
def test_song_on_wrong_album_recommends_merge(artist):
    wrong_album, correct_album = _albums(artist)
    keep, drop = _songs(artist, wrong_album, correct_album)
    truth = _truth(local_album_ok=False, reason=None, different_release=True)
    output = StringIO()
    with (
        patch(
            "library_manager.management.commands.repair_song_identity.fetch_truth",
            return_value=truth,
        ),
        patch("library_manager.helpers.enqueue_download_track_by_spotify_gid") as gid,
    ):
        call_command("repair_song_identity", song=[str(keep.id)], stdout=output)
    text = output.getvalue()
    assert "--merge-into" in text and str(drop.id) in text
    gid.assert_not_called()
    assert keep.deezer_id == 900102
