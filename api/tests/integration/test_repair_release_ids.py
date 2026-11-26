"""repair_release_ids: a song's deezer_id must be the track on its own release."""

import json
import os
import stat
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.management.commands import repair_release_ids as cmd
from library_manager.management.commands.repair_release_ids import Command
from library_manager.models import Album, Artist, Song
from src.providers.metadata_base import TrackResult

ISRC = "TESTISRC0001"
# Valid EAN-13 UPC; 5901234123457 has check digit 7.
VALID_UPC = "5901234123457"
# Deezer indexes some Spotify UPCs zero-padded to 14 digits.
PADDED_UPC = "05901234123457"


def _track(deezer_id, isrc, pos=1, disc=1, name="Test Track"):
    return TrackResult(
        name=name,
        artist_name="",
        deezer_id=deezer_id,
        isrc=isrc,
        track_number=pos,
        disc_number=disc,
    )


@pytest.fixture
def artist():
    return Artist.objects.create(name="Synthetic Artist", deezer_id=7700001)


def _album(artist, deezer_id=7710001, **extra):
    extra.setdefault("name", "Test Album")
    gid = f"album-fixture-{Album.objects.count() + 1}"
    extra.setdefault("spotify_gid", gid)
    return Album.objects.create(artist=artist, deezer_id=deezer_id, **extra)


def _song(artist, album, deezer_id, isrc=ISRC, gid=None, **extra):
    return Song.objects.create(
        name=extra.pop("name", "Test Track"),
        gid=gid,
        primary_artist=artist,
        album=album,
        deezer_id=deezer_id,
        isrc=isrc,
        **extra,
    )


def _run(*args, tracks=None, upcs=None, sp_upcs=None, position=None, **options):
    """Run the command with provider calls replaced by in-memory fixtures."""
    tracks = tracks or {}
    upcs = dict(upcs or {})
    sp_upcs = dict(sp_upcs or {})
    out = StringIO()
    for album in Album.objects.exclude(spotify_gid=""):
        gid = str(album.spotify_gid).rsplit(":", 1)[-1]
        sp_upcs.setdefault(gid, VALID_UPC)
        if ("upc", VALID_UPC) not in upcs and album.deezer_id is not None:
            upcs[("upc", VALID_UPC)] = album.deezer_id

    def fetch_album(self, album_id):
        value = tracks[album_id]
        if value is cmd.AlbumMissing:
            raise cmd.AlbumMissing(str(album_id))
        if value is cmd.LookupFailed:
            raise cmd.LookupFailed("boom")
        return value, (upcs.get(("album", album_id)))

    with (
        patch.object(Command, "_fetch_album", fetch_album),
        patch.object(
            Command, "_fetch_album_id_by_upc", lambda self, upc: upcs.get(("upc", upc))
        ),
        patch.object(Command, "_fetch_spotify_upc", lambda self, gid: sp_upcs.get(gid)),
        patch.object(Command, "_fetch_spotify_position", lambda self, gid: position),
    ):
        call_command(
            "repair_release_ids", *args, stdout=out, sleep=0.0, show=10, **options
        )
    return out.getvalue()


def _count(text, key):
    for line in text.splitlines():
        if line.strip().startswith(f"{key}:"):
            return int(line.split(":")[1].split()[0])
    return 0


@pytest.mark.django_db
def test_dry_run_classifies_and_writes_nothing(artist):
    album = _album(artist)
    song = _song(artist, album, deezer_id=999)  # id of the same song on an EP
    text = _run(tracks={7710001: [_track(111, ISRC)]})
    assert "DRY RUN" in text
    assert _count(text, "repairable") == 1
    assert "999" in text and "111" in text
    song.refresh_from_db()
    assert song.deezer_id == 999


@pytest.mark.django_db
def test_apply_requires_audit_file(artist):
    with pytest.raises(CommandError, match="requires --audit-file"):
        call_command("repair_release_ids", apply=True, stdout=StringIO())
    with pytest.raises(CommandError, match="only applies with --apply"):
        call_command("repair_release_ids", audit_file="/tmp/x", stdout=StringIO())


@pytest.mark.django_db
def test_apply_writes_audit_first_and_changes_only_deezer_id(artist, tmp_path):
    album = _album(artist)
    song = _song(
        artist, album, 999, downloaded=True, bitrate=256, gid="g" * 22, failed_count=3
    )
    song.set_file_path("/music/synthetic/track.m4a")
    song.save(update_fields=["file_path_ref"])
    path_id = song.file_path_ref_id
    audit = tmp_path / "audit.jsonl"

    _run(
        apply=True,
        audit_file=str(audit),
        tracks={7710001: [_track(111, ISRC)]},
    )

    song.refresh_from_db()
    assert song.deezer_id == 111
    assert song.downloaded is True and song.bitrate == 256
    assert song.file_path_ref_id == path_id and song.failed_count == 3
    assert stat.S_IMODE(os.stat(audit).st_mode) == 0o600
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert records[0]["record"] == "header"
    plan = next(r for r in records if r["record"] == "plan")
    assert plan["old_deezer_id"] == 999 and plan["new_deezer_id"] == 111
    assert records.index(plan) < next(
        i for i, r in enumerate(records) if r["record"] == "complete"
    )
    with pytest.raises(CommandError, match="already exists"):
        _run(apply=True, audit_file=str(audit), tracks={})


@pytest.mark.django_db
def test_same_recording_on_two_albums_each_gets_its_own_release_id(artist, tmp_path):
    single = _album(artist, 7710001, name="Single")
    compilation = _album(artist, 7710002, name="Compilation")
    on_single = _song(artist, single, 500)  # both rows hold the compilation's id
    on_comp = _song(artist, compilation, 500)
    single_gid = str(single.spotify_gid).rsplit(":", 1)[-1]
    comp_gid = str(compilation.spotify_gid).rsplit(":", 1)[-1]
    _run(
        tracks={
            7710001: [_track(111, ISRC)],
            7710002: [_track(222, ISRC)],
        },
        sp_upcs={single_gid: VALID_UPC, comp_gid: PADDED_UPC},
        upcs={("upc", VALID_UPC): 7710001, ("upc", PADDED_UPC): 7710002},
        apply=True,
        audit_file=str(tmp_path / "two-albums.jsonl"),
    )
    on_single.refresh_from_db()
    on_comp.refresh_from_db()
    assert (on_single.deezer_id, on_comp.deezer_id) == (111, 222)


@pytest.mark.django_db
def test_already_correct_is_not_repairable(artist):
    album = _album(artist)
    _song(artist, album, 111)
    text = _run(tracks={7710001: [_track(111, ISRC)]})
    assert _count(text, "already_correct") == 1
    assert _count(text, "repairable") == 0


@pytest.mark.django_db
def test_no_album_and_no_isrc_are_reported(artist):
    album = _album(artist)
    _song(artist, None, 999, name="Orphan")
    Song.objects.create(
        name="No Isrc",
        gid="n" * 22,
        primary_artist=artist,
        album=album,
        deezer_id=998,
    )
    text = _run(tracks={7710001: [_track(111, ISRC)]})
    assert _count(text, "skip_no_album") == 1
    assert _count(text, "skip_no_isrc") == 1


@pytest.mark.django_db
def test_alternate_isrc_matches(artist):
    album = _album(artist)
    song = _song(artist, album, 999, alternate_isrcs=["TESTALT00001"])
    song.isrc = "TESTOTHER001"
    song.save(update_fields=["isrc"])
    text = _run(tracks={7710001: [_track(111, "testalt00001")]})
    assert _count(text, "repairable") == 1


@pytest.mark.django_db
def test_no_matching_track_is_reported_and_not_borrowed(artist):
    album = _album(artist)
    song = _song(artist, album, 999)
    text = _run(tracks={7710001: [_track(111, "OTHERISRC001")]})
    assert _count(text, "skip_no_matching_track") == 1
    song.refresh_from_db()
    assert song.deezer_id == 999


@pytest.mark.django_db
def test_current_id_on_album_with_other_isrc_is_recording_mismatch(artist):
    album = _album(artist)
    _song(artist, album, 111)
    text = _run(tracks={7710001: [_track(111, "OTHERISRC001")]})
    assert _count(text, "skip_recording_mismatch") == 1
    assert "repair_song_identity" in text


@pytest.mark.django_db
def test_repeated_isrc_without_position_is_ambiguous(artist):
    album = _album(artist)
    song = _song(artist, album, 999)
    tracks = {7710001: [_track(111, ISRC, pos=1), _track(112, ISRC, pos=5)]}
    text = _run(tracks=tracks)
    assert _count(text, "skip_ambiguous_candidates") == 1
    assert "[111, 112]" in text
    song.refresh_from_db()
    assert song.deezer_id == 999


@pytest.mark.django_db
def test_repeated_isrc_resolved_by_spotify_position(artist, tmp_path):
    album = _album(artist)
    song = _song(artist, album, 999, gid="p" * 22)
    tracks = {7710001: [_track(111, ISRC, pos=1), _track(112, ISRC, pos=5)]}
    _run(
        tracks=tracks,
        position=(1, 5),
        apply=True,
        audit_file=str(tmp_path / "position.jsonl"),
    )
    song.refresh_from_db()
    assert song.deezer_id == 112


@pytest.mark.django_db
def test_target_held_by_another_song_on_same_album_is_duplicate(artist):
    album = _album(artist)
    song = _song(artist, album, 999, gid="a" * 22)
    holder = _song(artist, album, 111, isrc="OTHERISRC002", gid="b" * 22)
    text = _run(tracks={7710001: [_track(111, ISRC)]})
    assert _count(text, "skip_duplicate_on_album") == 1
    assert str(holder.pk) in text
    song.refresh_from_db()
    assert song.deezer_id == 999


@pytest.mark.django_db
def test_target_held_on_another_albums_row_is_still_repairable(artist):
    album = _album(artist)
    other = _album(artist, 7710009, name="Other")
    song = _song(artist, album, 999, gid="a" * 22)
    _song(artist, other, 111, gid="b" * 22)  # that row has the wrong-release id
    text = _run(
        tracks={7710001: [_track(111, ISRC)], 7710009: []},
        sp_upcs={
            str(album.spotify_gid): VALID_UPC,
            str(other.spotify_gid): PADDED_UPC,
        },
        upcs={("upc", PADDED_UPC): 7710009},
        song=[song.pk],
    )
    assert _count(text, "repairable") == 1
    assert _count(text, "new_id_also_on_other_album_rows") == 1


@pytest.mark.django_db
def test_album_missing_on_deezer_is_reported(artist):
    album = _album(artist)
    _song(artist, album, 999)
    text = _run(tracks={7710001: cmd.AlbumMissing})
    assert _count(text, "skip_album_not_on_deezer") == 1


@pytest.mark.django_db
def test_lookup_failure_is_retryable_and_holds_the_cursor(artist, tmp_path):
    album = _album(artist)
    song = _song(artist, album, 999)
    audit = tmp_path / "a.jsonl"
    text = _run(tracks={7710001: cmd.LookupFailed}, apply=True, audit_file=str(audit))
    assert _count(text, "skip_lookup_failed") == 1
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    failed = [r for r in records if r["record"] == "failed"]
    assert failed and failed[0]["song_id"] == song.pk
    assert failed[0]["cursor"] == 0
    song.refresh_from_db()
    assert song.deezer_id == 999  # a non-repairable plan never writes

    retry = _run(
        tracks={7710001: [_track(111, ISRC)]},
        apply=True,
        audit_file=str(audit),
        retry_failed=True,
    )
    assert "repairable" in retry
    song.refresh_from_db()
    assert song.deezer_id == 111


@pytest.mark.django_db
def test_concurrent_change_is_skipped_by_conditional_update(artist):
    album = _album(artist)
    song = _song(artist, album, 999)
    command = Command()
    plan = cmd.SongPlan(
        song_id=song.pk,
        name=song.name,
        status=cmd.REPAIRABLE,
        isrc=ISRC,
        album_id=album.pk,
        old_deezer_id=999,
        new_deezer_id=111,
        old_album_deezer_id=7710001,
        expected_album_deezer_id=7710001,
        album_spotify_gid=str(album.spotify_gid),
    )
    Song.objects.filter(pk=song.pk).update(deezer_id=777)  # someone else repaired it
    assert command._apply_plan(plan) == cmd.SKIP_CHANGED
    song.refresh_from_db()
    assert song.deezer_id == 777


@pytest.mark.django_db
def test_apply_rechecks_duplicate_before_writing(artist):
    album = _album(artist)
    song = _song(artist, album, 999, gid="a" * 22)
    _song(artist, album, 111, isrc="OTHERISRC003", gid="b" * 22)  # appears later
    command = Command()
    plan = cmd.SongPlan(
        song_id=song.pk,
        name=song.name,
        status=cmd.REPAIRABLE,
        isrc=ISRC,
        album_id=album.pk,
        old_deezer_id=999,
        new_deezer_id=111,
        old_album_deezer_id=7710001,
        expected_album_deezer_id=7710001,
        album_spotify_gid=str(album.spotify_gid),
    )
    assert command._apply_plan(plan) == cmd.SKIP_DUPLICATE
    song.refresh_from_db()
    assert song.deezer_id == 999


@pytest.mark.django_db
def test_album_without_deezer_id_is_reported_not_mutated(artist, tmp_path):
    """Finding 2/4: no album mutation; unverifiable album is reported only."""
    album = Album.objects.create(
        name="Test Album", artist=artist, spotify_gid="album-gid-1"
    )
    song = _song(artist, album, 999)
    kwargs = {
        "tracks": {7710050: [_track(111, ISRC)]},
        "upcs": {("upc", VALID_UPC): 7710050},
        "sp_upcs": {"album-gid-1": VALID_UPC},
    }
    text = _run(**kwargs)
    assert _count(text, "album_correction_reported_only") == 1
    assert "left unchanged" in text and "7710050" in text

    audit = tmp_path / "a.jsonl"
    _run(apply=True, audit_file=str(audit), **kwargs)
    song.refresh_from_db()
    album.refresh_from_db()
    assert song.deezer_id == 999 and album.deezer_id is None

    parser = Command().create_parser("manage.py", "repair_release_ids")
    with pytest.raises((SystemExit, CommandError)):
        parser.parse_args(["--apply", "--fix-albums"])


@pytest.mark.django_db
def test_upc_comparison_is_symmetric_and_invalid_upc_is_unverifiable(artist):
    """Finding 5: both sides canonicalized; bad UPCs never authorize a write."""
    album = _album(artist, 7710001)
    song = _song(artist, album, 999)
    # Spotify padded, Deezer unpadded: same canonical UPC → still repairable.
    text = _run(
        tracks={7710001: [_track(111, ISRC)]},
        sp_upcs={str(album.spotify_gid): PADDED_UPC},
        upcs={("upc", PADDED_UPC): 7710001},
    )
    assert _count(text, "repairable") == 1

    song.refresh_from_db()
    bad = _run(
        tracks={7710001: [_track(111, ISRC)]},
        sp_upcs={str(album.spotify_gid): "12345"},  # too short, not a UPC
    )
    assert _count(bad, "skip_unverified_release") == 1
    assert "no valid UPC" in bad


@pytest.mark.django_db
def test_upc_normalization_helpers_are_symmetric():
    from library_manager.management.commands.repair_release_ids import (
        _norm_upc,
        _valid_upc,
    )

    assert _norm_upc("05901234123457") == _norm_upc("5901234123457")
    assert _norm_upc(VALID_UPC) == _norm_upc(PADDED_UPC)
    assert _norm_upc(None) == "" and _norm_upc("ABC") == ""
    assert _valid_upc(VALID_UPC) and not _valid_upc("12345")
    assert _valid_upc("4062851533126")  # real Spotify UPC; checksum not enforced
    assert not _valid_upc("ABCDEFGHIJKLM")  # not digits
    variants = Command._upc_variants(PADDED_UPC)
    assert PADDED_UPC in variants and "5901234123457" in variants


@pytest.mark.django_db
def test_album_without_gid_is_unverifiable_even_with_deezer_id(artist):
    """Finding 4: no independent UPC authority → skip, never trust the id."""
    album = Album.objects.create(
        name="Test Album", artist=artist, deezer_id=7710001, youtube_id="yt-1"
    )
    _song(artist, album, 999)
    text = _run(tracks={7710001: [_track(111, ISRC)]})
    assert _count(text, "skip_unverified_release") == 1
    assert "no Spotify gid" in text


@pytest.mark.django_db
def test_album_without_deezer_id_and_gid_is_reported(artist):
    album = Album.objects.create(name="Test Album", artist=artist, youtube_id="yt-2")
    _song(artist, album, 999)
    text = _run()
    assert _count(text, "skip_unverified_release") == 1


@pytest.mark.django_db
def test_album_upc_unknown_on_deezer_is_unresolvable(artist):
    album = Album.objects.create(name="Test Album", artist=artist, spotify_gid="ag-2")
    _song(artist, album, 999)
    text = _run(sp_upcs={"ag-2": VALID_UPC})
    assert _count(text, "skip_album_unresolvable") == 1


@pytest.mark.django_db
def test_mismatched_album_id_is_reported_only_never_mutated(artist, tmp_path):
    """Finding 2: a wrong album id is reported, not applied."""
    album = _album(artist, 7710001, spotify_gid="ag-4")
    song = _song(artist, album, 999)
    kwargs = {
        "tracks": {7710001: [_track(111, ISRC)], 7710077: [_track(333, ISRC)]},
        "upcs": {("upc", VALID_UPC): 7710077},
        "sp_upcs": {"ag-4": VALID_UPC},
    }
    text = _run(**kwargs)
    assert _count(text, "album_correction_reported_only") == 1
    assert "7710077" in text and "left unchanged" in text
    _run(apply=True, audit_file=str(tmp_path / "a.jsonl"), **kwargs)
    song.refresh_from_db()
    album.refresh_from_db()
    assert (song.deezer_id, album.deezer_id) == (999, 7710001)


@pytest.mark.django_db
def test_same_upc_lookups_agree_without_padding(artist):
    album = _album(artist, 7710001, spotify_gid="ag-5")
    _song(artist, album, 999)
    text = _run(
        tracks={7710001: [_track(111, ISRC)]},
        sp_upcs={"ag-5": VALID_UPC},
        upcs={("upc", VALID_UPC): 7710001},
    )
    assert _count(text, "repairable") == 1
    assert _count(text, "album_correction_reported_only") == 0


@pytest.mark.django_db
def test_no_authoritative_deezer_album_for_upc_is_unresolvable(artist):
    album = _album(artist, 7710001, spotify_gid="ag-6")
    _song(artist, album, 999)
    out = StringIO()
    with (
        patch.object(
            Command, "_fetch_album", lambda self, aid: ([_track(111, ISRC)], None)
        ),
        patch.object(Command, "_fetch_album_id_by_upc", lambda self, upc: None),
        patch.object(Command, "_fetch_spotify_upc", lambda self, gid: VALID_UPC),
    ):
        call_command("repair_release_ids", stdout=out, sleep=0.0)
    assert _count(out.getvalue(), "skip_album_unresolvable") == 1


@pytest.mark.django_db
def test_full_preimage_changed_isrc_or_album_id_skips(artist):
    """Finding 3: every field used for selection is in the CAS guard."""
    album = _album(artist)
    song = _song(artist, album, 999, gid="a" * 22)
    base = dict(
        song_id=song.pk,
        name=song.name,
        status=cmd.REPAIRABLE,
        isrc=ISRC,
        album_id=album.pk,
        old_deezer_id=999,
        new_deezer_id=111,
        old_album_deezer_id=7710001,
        expected_album_deezer_id=7710001,
        album_spotify_gid=str(album.spotify_gid),
    )
    command = Command()
    Song.objects.filter(pk=song.pk).update(isrc="CHANGED0001")
    assert command._apply_plan(cmd.SongPlan(**base)) == cmd.SKIP_CHANGED
    Song.objects.filter(pk=song.pk).update(isrc=ISRC)
    Album.objects.filter(pk=album.pk).update(deezer_id=7719999)
    assert command._apply_plan(cmd.SongPlan(**base)) == cmd.SKIP_CHANGED
    Album.objects.filter(pk=album.pk).update(deezer_id=7710001)
    Album.objects.filter(pk=album.pk).update(spotify_gid="other-gid")
    assert command._apply_plan(cmd.SongPlan(**base)) == cmd.SKIP_CHANGED


@pytest.mark.django_db
def test_cached_upc_lookups_are_reused(artist):
    album = _album(artist)
    for i in range(3):
        _song(artist, album, 900 + i, isrc=f"TESTISRC00{i}0", gid=f"{i}" * 22)
    calls = []

    def fetch_upc(self, upc):
        calls.append(upc)
        return 7710001

    out = StringIO()
    with (
        patch.object(
            Command,
            "_fetch_album",
            lambda self, aid: (
                [_track(100 + i, f"TESTISRC00{i}0") for i in range(3)],
                None,
            ),
        ),
        patch.object(Command, "_fetch_album_id_by_upc", fetch_upc),
        patch.object(Command, "_fetch_spotify_upc", lambda self, gid: VALID_UPC),
    ):
        call_command("repair_release_ids", stdout=out, sleep=0.0)
    assert _count(out.getvalue(), "repairable") == 3
    assert calls.count(VALID_UPC) == 1


@pytest.mark.django_db
def test_resume_cursor_and_limit(artist):
    album = _album(artist)
    first = _song(artist, album, 999, isrc="TESTISRC0001", gid="a" * 22)
    second = _song(artist, album, 998, isrc="TESTISRC0002", gid="b" * 22)
    tracks = {7710001: [_track(111, "TESTISRC0001"), _track(112, "TESTISRC0002")]}
    text = _run(tracks=tracks, limit=1)
    assert "songs examined: 1" in text
    assert f"resume with --after-id {first.pk}" in text
    text = _run(tracks=tracks, after_id=first.pk)
    assert "songs examined: 1" in text and str(second.pk) in text


@pytest.mark.django_db
def test_seed_cache_reports_which_album_the_old_id_belongs_to(artist, tmp_path):
    album = _album(artist)
    _song(artist, album, 999)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"999": {"album_deezer_id": 5555}}))
    text = _run(tracks={7710001: [_track(111, ISRC)]}, seed_cache=str(seed))
    assert "(on album 5555)" in text
    assert _count(text, "old_id_on_other_release_seeded") == 1


@pytest.mark.django_db
def test_album_track_lists_are_fetched_once_per_album(artist):
    album = _album(artist)
    for i in range(3):
        _song(artist, album, 900 + i, isrc=f"TESTISRC00{i}0", gid=f"{i}" * 22)
    calls = []

    def fetch_album(self, album_id):
        calls.append(album_id)
        return [_track(100 + i, f"TESTISRC00{i}0") for i in range(3)], None

    out = StringIO()
    with (
        patch.object(Command, "_fetch_album", fetch_album),
        patch.object(Command, "_fetch_album_id_by_upc", lambda self, upc: 7710001),
        patch.object(Command, "_fetch_spotify_upc", lambda self, gid: VALID_UPC),
    ):
        call_command("repair_release_ids", stdout=out, sleep=0.0)
    assert calls == [7710001]
    assert _count(out.getvalue(), "repairable") == 3


@pytest.mark.django_db(transaction=True)
def test_album_lock_held_during_apply_plan(artist):
    """The album row stays locked for the whole _apply_plan transaction."""
    import threading
    import time

    from django.db import connections

    album = _album(artist)
    song = _song(artist, album, 999, gid="a" * 22)
    plan = cmd.SongPlan(
        song_id=song.pk,
        name=song.name,
        status=cmd.REPAIRABLE,
        isrc=ISRC,
        album_id=album.pk,
        old_deezer_id=999,
        new_deezer_id=111,
        old_album_deezer_id=7710001,
        expected_album_deezer_id=7710001,
        album_spotify_gid=str(album.spotify_gid),
    )
    attempted = threading.Event()
    finished = threading.Event()
    outcome = {}

    def concurrent_album_write():
        try:
            conn = connections["default"]
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE albums SET deezer_id = 7719999 WHERE id = %s", [album.pk]
                )
            outcome["committed"] = True
        except Exception as exc:  # pragma: no cover - unexpected DB error
            outcome["error"] = str(exc)
        finally:
            attempted.set()
            finished.set()

    # Pause _apply_plan while both locks are held by starting the writer from
    # the preimage check, which runs under the album lock.
    command = Command()
    original = Command._preimage_matches

    thread_holder = []

    def checking(p, s, a):
        thread = threading.Thread(target=concurrent_album_write, daemon=True)
        thread.start()
        thread_holder.append(thread)
        time.sleep(0.4)
        assert not finished.is_set(), "album writer must block on the album lock"
        return original(p, s, a)

    with patch.object(command, "_preimage_matches", checking):
        assert command._apply_plan(plan) == cmd.REPAIRABLE
    # The writer can only commit once _apply_plan's transaction has released
    # the album row lock.
    thread_holder[0].join(timeout=10)
    assert finished.is_set() and outcome.get("committed") is True
    song.refresh_from_db()
    assert song.deezer_id == 111
