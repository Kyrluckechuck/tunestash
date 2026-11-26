"""Re-download command must be dry-run by default, audited and deduped."""

import json
import stat
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

import pytest

from library_manager.models import Artist, ContributingArtist, DownloadProvider, Song
from library_manager.tasks import TaskPriority


@pytest.fixture
def artist():
    return Artist.objects.create(name="Lead Artist", gid="gid-redownload")


def _song(artist, **overrides):
    values = {
        "name": "Wrong Recording",
        "gid": "gid-wrong-recording",
        "primary_artist": artist,
        "isrc": "TESTREDOWNLOAD1",
        "deezer_id": 12345,
        "downloaded": True,
        "bitrate": 320,
        "matched_provider": "youtube",
        "matched_provider_track_id": "bad-track",
        "matched_title": "Wrong Recording",
        "matched_artist": "Lead Artist feat. Guest",
        "matched_duration_ms": 96_000,
        "match_confidence": 0.5,
    }
    values.update(overrides)
    return Song.objects.create(**values)


@pytest.mark.django_db
def test_dry_run_writes_nothing(artist, tmp_path):
    song = _song(artist)
    music_root = tmp_path / "music"
    music_root.mkdir()
    target = music_root / "Lead Artist - Wrong Recording.m4a"
    target.write_bytes(b"audio")
    song.set_file_path(str(target))
    song.save(update_fields=["file_path_ref"])

    output = StringIO()
    with (
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ) as queue,
        override_settings(OUTPUT_PATH=str(music_root)),
    ):
        call_command("redownload_songs", song=[str(song.id)], stdout=output)

    text = output.getvalue()
    assert "DRY RUN" in text
    assert "Lead Artist" in text
    assert "Wrong Recording" in text
    assert "bad-track" in text
    assert str(target) in text
    queue.assert_not_called()
    assert target.exists()
    song.refresh_from_db()
    assert song.downloaded is True
    assert song.rejected_matches == []
    assert song.file_path == str(target)


@pytest.mark.django_db
def test_apply_audits_before_writing_and_keeps_file_permissions(artist, tmp_path):
    song = _song(artist)
    music_root = tmp_path / "music"
    music_root.mkdir()
    target = music_root / "Wrong Recording.m4a"
    target.write_bytes(b"audio")
    song.set_file_path(str(target))
    song.save(update_fields=["file_path_ref"])
    audit = tmp_path / "new-audit.json"

    def fail_on_update(*args, **kwargs):
        raise AssertionError("update attempted before audit file was written")

    with (
        patch.object(Song, "save", side_effect=fail_on_update),
        pytest.raises(AssertionError, match="before audit file was written"),
    ):
        call_command(
            "redownload_songs",
            song=[str(song.id)],
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )
    assert audit.exists()
    assert stat.S_IMODE(audit.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    records = json.loads(audit.read_text(encoding="utf-8"))
    assert records[0]["id"] == song.id
    assert records[0]["rejected_entry"]["provider_track_id"] == "bad-track"
    assert target.exists()
    song.refresh_from_db()
    assert song.downloaded is True


@pytest.mark.django_db
def test_shared_file_is_kept(artist, tmp_path):
    song = _song(artist)
    other = _song(artist, gid="gid-other-track", deezer_id=54321)
    music_root = tmp_path / "music"
    music_root.mkdir()
    target = music_root / "Shared.m4a"
    target.write_bytes(b"audio")
    for row in (song, other):
        row.set_file_path(str(target))
        row.save(update_fields=["file_path_ref"])
    audit = tmp_path / "shared-audit.json"

    with (
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ),
        override_settings(OUTPUT_PATH=str(music_root)),
    ):
        call_command(
            "redownload_songs",
            song=[str(song.id)],
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )

    assert target.exists()
    song.refresh_from_db()
    assert song.file_path == str(target)
    other.refresh_from_db()
    assert other.file_path == str(target)


@pytest.mark.django_db
def test_current_match_goes_to_rejected_matches(artist, tmp_path):
    song = _song(artist)
    guest = Artist.objects.create(name="Guest", gid="gid-guest")
    ContributingArtist.objects.create(song=song, artist=guest)
    audit = tmp_path / "rejected-audit.json"

    with (
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ) as queue,
    ):
        call_command(
            "redownload_songs",
            song=[str(song.id)],
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )

    song.refresh_from_db()
    assert song.rejected_matches[-1]["provider"] == "youtube"
    assert song.rejected_matches[-1]["provider_track_id"] == "bad-track"
    assert song.downloaded is False
    assert song.bitrate == 0
    assert song.matched_provider is None
    assert song.matched_provider_track_id is None
    assert song.matched_title is None
    queue.assert_called_once_with(song.id, priority=TaskPriority.TRACK_DOWNLOAD)


@pytest.mark.django_db
def test_legacy_youtube_id_is_recorded_as_rejection(artist, tmp_path):
    song = _song(
        artist,
        matched_provider=None,
        matched_provider_track_id=None,
        matched_title=None,
        matched_artist=None,
        matched_duration_ms=None,
        matched_isrc=None,
        matched_at=None,
        match_confidence=None,
        youtube_id="legacy-video-id",
        download_provider=DownloadProvider.SPOTDL,
    )
    audit = tmp_path / "legacy-audit.json"
    with patch(
        "library_manager.helpers.enqueue_download_deezer_track", return_value=True
    ):
        call_command(
            "redownload_songs",
            song=[str(song.id)],
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )
    song.refresh_from_db()
    assert song.rejected_matches[-1]["provider"] == "youtube"
    assert song.rejected_matches[-1]["provider_track_id"] == "legacy-video-id"


@pytest.mark.django_db
def test_deduped_queue_and_csv_input(artist, tmp_path):
    song = _song(artist, deezer_id=None)
    csv_path = tmp_path / "ids.csv"
    csv_path.write_text(
        "song_id,reason\n" + f"{song.id},duration mismatch\n", encoding="utf-8"
    )
    audit = tmp_path / "dedup-audit.json"

    with (
        patch(
            "library_manager.helpers.enqueue_download_track_by_spotify_gid",
            return_value=False,
        ) as queue_gid,
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ) as queue_dz,
    ):
        output = StringIO()
        call_command(
            "redownload_songs",
            from_csv=str(csv_path),
            column="song_id",
            apply=True,
            audit_file=str(audit),
            stdout=output,
        )

    queue_gid.assert_called_once_with(song.gid, priority=TaskPriority.TRACK_DOWNLOAD)
    queue_dz.assert_not_called()
    assert "already active" in output.getvalue()


@pytest.mark.django_db
def test_high_confidence_match_is_skipped_unless_forced(artist, tmp_path):
    song = _song(
        artist,
        name="Right Recording",
        matched_title="Right Recording",
        matched_artist="Lead Artist",
        matched_isrc="TESTREDOWNLOAD1",
        match_confidence=0.99,
    )
    output = StringIO()
    with patch(
        "library_manager.helpers.enqueue_download_deezer_track", return_value=True
    ) as queue:
        call_command("redownload_songs", song=[str(song.id)], stdout=output)
    assert "high confidence" in output.getvalue()
    queue.assert_not_called()

    audit = tmp_path / "force-audit.json"
    with (
        patch(
            "library_manager.helpers.enqueue_download_deezer_track", return_value=True
        ) as forced_queue,
    ):
        call_command(
            "redownload_songs",
            song=[str(song.id)],
            force=True,
            apply=True,
            audit_file=str(audit),
            stdout=StringIO(),
        )
    forced_queue.assert_called_once()
