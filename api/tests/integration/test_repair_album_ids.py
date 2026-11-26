"""repair_album_ids: UPC-verified, CAS-guarded Album.deezer_id repair."""

import json
import os
import stat
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.management.commands import repair_album_ids as cmd
from library_manager.management.commands.repair_album_ids import Command
from library_manager.models import Album, Artist, Song

VALID_UPC = "5901234123457"
PADDED_UPC = "05901234123457"


def _artist():
    return Artist.objects.create(name="Synthetic Album Artist", deezer_id=8800001)


def _album(artist, deezer_id=8810001, idx=1, **extra):
    extra.setdefault("name", f"Album {idx}")
    extra.setdefault("spotify_gid", f"album-fixture-{idx}")
    extra.setdefault("spotify_uri", f"spotify:album:album-fixture-{idx}")
    return Album.objects.create(artist=artist, deezer_id=deezer_id, **extra)


def _sp(title="Album 1", artist="Synthetic Album Artist", tracks=10, upc=VALID_UPC):
    return {
        "name": title,
        "artists": [{"name": artist}],
        "total_tracks": tracks,
        "external_ids": {"upc": upc},
    }


def _dz(title="Album 1", artist="Synthetic Album Artist", tracks=10, upc=VALID_UPC):
    return {"title": title, "artist": artist, "tracks": tracks, "upc": upc}


def _run(*args, sp=None, upcs=None, dz=None, stdout=None, **options):
    """Run the command with provider calls replaced by synthetic fixtures."""
    sp = dict(sp or {})
    upcs = dict(upcs or {})
    dz = dict(dz or {})
    out = stdout or StringIO()
    albums = {}
    for i, album in enumerate(Album.objects.all(), start=1):
        gid = str(album.spotify_gid).rsplit(":", 1)[-1]
        albums.setdefault(gid, album)
        sp.setdefault(gid, _sp(title=album.name))
        upcs.setdefault(("upc", VALID_UPC), 8810001 + i)
        dz.setdefault(8810001 + i, _dz(title=album.name))

    def fetch_upc(self, upc):
        value = upcs.get(("upc", cmd.norm_upc(upc)))
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_sp(self, gid):
        value = sp[gid]
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_dz(self, album_id):
        value = dz.get(album_id, _dz())
        if isinstance(value, Exception):
            raise value
        return value

    with (
        patch.object(Command, "_fetch_album_id_by_upc", fetch_upc),
        patch.object(Command, "_fetch_spotify_album", fetch_sp),
        patch.object(Command, "_fetch_deezer_album", fetch_dz),
    ):
        call_command(
            "repair_album_ids", *args, stdout=out, sleep=0.0, show=10, **options
        )
    return out.getvalue()


def _count(text, key):
    for line in text.splitlines():
        if line.strip().startswith(f"{key}:"):
            return int(line.split(":")[1].split()[0])
    return 0


# -- normalization and agreement helpers --------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (VALID_UPC, "5901234123457"),
        (PADDED_UPC, "5901234123457"),
        (f"  {VALID_UPC}  ", "5901234123457"),
        ("", ""),
        ("590123412345A", ""),
    ],
)
def test_norm_upc(raw, expected):
    assert cmd.norm_upc(raw) == expected


@pytest.mark.parametrize(
    "raw,valid",
    [(VALID_UPC, True), (PADDED_UPC, True), ("1234", False), ("ABC", False)],
)
def test_valid_upc(raw, valid):
    assert cmd.valid_upc(raw) is valid


def test_names_agree_ignores_order_and_featured_credits():
    assert cmd.names_agree("Stellar, Baasik", "Stellar")
    assert cmd.names_agree("Stellar", "Stellar feat. Baasik")
    assert not cmd.names_agree("Stellar", "KALUMA")
    assert not cmd.names_agree("", "Stellar")


def test_metadata_agrees_requires_track_counts():
    plan = cmd.AlbumPlan(
        album_id=1,
        name="x",
        status=cmd.REPAIRABLE,
        spotify_title="Album",
        deezer_title="Album",
        spotify_artist="Artist",
        deezer_artist="Artist",
        spotify_tracks=10,
        deezer_tracks=9,
    )
    assert not cmd.metadata_agrees(plan)
    plan.deezer_tracks = 10
    assert cmd.metadata_agrees(plan)
    plan.deezer_tracks = None
    assert not cmd.metadata_agrees(plan)


# -- planning -----------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_wrong_id_reports_repairable_and_writes_nothing():
    artist = _artist()
    album = _album(artist, deezer_id=999)  # points at another release
    song = Song.objects.create(
        name="Synthetic Song",
        primary_artist=artist,
        album=album,
        deezer_id=12345,
    )
    text = _run(
        sp={"album-fixture-1": _sp()},
        upcs={("upc", VALID_UPC): 8810002},
        dz={8810002: _dz()},
    )
    assert "DRY RUN" in text
    assert _count(text, cmd.REPAIRABLE) == 1
    assert "999" in text and "8810002" in text
    album.refresh_from_db()
    assert album.deezer_id == 999
    song.refresh_from_db()
    assert song.deezer_id == 12345


@pytest.mark.django_db
def test_padded_upc_variant_is_used():
    artist = _artist()
    _album(artist, deezer_id=999)
    text = _run(
        sp={"album-fixture-1": _sp(upc=PADDED_UPC)},
        upcs={("upc", cmd.norm_upc(PADDED_UPC)): 8810002},
        dz={8810002: _dz()},
    )
    assert _count(text, cmd.REPAIRABLE) == 1
    assert "05901234123457" in text


@pytest.mark.django_db
def test_already_correct_is_not_rewritten():
    artist = _artist()
    _album(artist, deezer_id=8810002)
    text = _run(upcs={("upc", VALID_UPC): 8810002}, dz={8810002: _dz()})
    assert _count(text, cmd.ALREADY_CORRECT) == 1
    assert _count(text, cmd.REPAIRABLE) == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "deezer,expected",
    [
        (_dz(title="Other Release"), cmd.SKIP_METADATA_MISMATCH),
        (_dz(artist="KALUMA"), cmd.SKIP_METADATA_MISMATCH),
        (_dz(tracks=9), cmd.SKIP_METADATA_MISMATCH),
        (_dz(tracks=None), cmd.SKIP_METADATA_MISMATCH),
        ({"missing": True}, cmd.SKIP_UNRESOLVABLE),
    ],
)
def test_mismatched_or_missing_deezer_album_is_skipped(deezer, expected):
    artist = _artist()
    album = _album(artist, deezer_id=999)
    text = _run(upcs={("upc", VALID_UPC): 8810002}, dz={8810002: deezer})
    assert _count(text, expected) == 1
    assert _count(text, cmd.REPAIRABLE) == 0
    album.refresh_from_db()
    assert album.deezer_id == 999


@pytest.mark.django_db
def test_no_upc_or_no_gid_is_skipped():
    artist = _artist()
    _album(artist, deezer_id=999, spotify_gid="", spotify_uri="")
    text = _run()
    assert _count(text, cmd.SKIP_NO_GID) == 1
    other = _album(artist, deezer_id=998, idx=2)
    text = _run(sp={"album-fixture-2": _sp(upc="invalid")}, upcs={}, dz={})
    assert _count(text, cmd.SKIP_NO_UPC) == 1
    assert Album.objects.get(pk=other.pk).deezer_id == 998


@pytest.mark.django_db
def test_duplicate_album_is_reported_not_merged():
    artist = _artist()
    wrong = _album(artist, deezer_id=999, idx=1)
    holder = _album(artist, deezer_id=8810002, idx=2)
    song = Song.objects.create(
        name="S", primary_artist=artist, album=holder, deezer_id=1
    )
    text = _run(upcs={("upc", VALID_UPC): 8810002}, dz={8810002: _dz()})
    assert _count(text, cmd.SKIP_DUPLICATE) == 1
    assert f"duplicate_albums=[{holder.pk}]" in text or str(holder.pk) in text
    wrong.refresh_from_db()
    assert wrong.deezer_id == 999
    assert Album.objects.filter(pk=holder.pk).exists()
    assert Song.objects.filter(pk=song.pk).exists()


# -- apply, CAS, audit --------------------------------------------------


@pytest.mark.django_db
def test_apply_uses_conditional_update_and_writes_0600_audit(tmp_path):
    artist = _artist()
    album = _album(artist, deezer_id=999)
    song = Song.objects.create(
        name="S", primary_artist=artist, album=album, deezer_id=77
    )
    audit = tmp_path / "audit.jsonl"
    text = _run(
        apply=True,
        audit_file=str(audit),
        upcs={("upc", VALID_UPC): 8810002},
        dz={8810002: _dz()},
    )
    assert "APPLY" in text
    assert _count(text, cmd.REPAIRABLE) == 1
    album.refresh_from_db()
    assert album.deezer_id == 8810002
    song.refresh_from_db()
    assert song.deezer_id == 77  # songs never touched
    assert stat.S_IMODE(os.stat(audit).st_mode) == 0o600
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert records[0]["record"] == "header"
    assert records[0]["songs_mutated"] is False
    assert any(r["record"] == "plan" and r["old_deezer_id"] == 999 for r in records)
    assert any(r["record"] == "complete" and r["album_id"] == album.pk for r in records)
    with pytest.raises(CommandError, match="already exists"):
        _run(apply=True, audit_file=str(audit))


@pytest.mark.django_db
def test_apply_skips_changed_row_cas(tmp_path):
    artist = _artist()
    album = _album(artist, deezer_id=999)
    text = _run(
        apply=True,
        audit_file=str(tmp_path / "audit1.jsonl"),
        upcs={("upc", VALID_UPC): 8810002},
        dz={8810002: _dz()},
    )
    assert _count(text, cmd.REPAIRABLE) == 1
    assert Album.objects.get(pk=album.pk).deezer_id == 8810002

    # Second run with a stale plan for a row that has since changed.
    plan = cmd.AlbumPlan(
        album_id=album.pk,
        name=album.name,
        status=cmd.REPAIRABLE,
        old_deezer_id=999,
        new_deezer_id=8810003,
        spotify_gid=cmd.Command._gid(album),
    )
    outcome = Command()._apply_plan(plan)
    assert outcome == cmd.SKIP_CHANGED
    assert Album.objects.get(pk=album.pk).deezer_id == 8810002


@pytest.mark.django_db
def test_integrity_error_is_reported_as_duplicate(tmp_path):
    artist = _artist()
    album = _album(artist, deezer_id=999)
    plan = cmd.AlbumPlan(
        album_id=album.pk,
        name=album.name,
        status=cmd.REPAIRABLE,
        old_deezer_id=999,
        new_deezer_id=8810002,
        spotify_gid=cmd.Command._gid(album),
    )
    from contextlib import contextmanager

    from django.db import IntegrityError

    @contextmanager
    def exploding_atomic():
        raise IntegrityError("unique violation")
        yield  # pragma: no cover

    with patch.object(cmd.transaction, "atomic", exploding_atomic):
        outcome = Command()._apply_plan(plan)
    assert outcome == cmd.SKIP_DUPLICATE


# -- batching / resume / cache ------------------------------------------


@pytest.mark.django_db
def test_batch_size_limit_and_resume():
    artist = _artist()
    albums = [_album(artist, deezer_id=99000 + i, idx=i) for i in range(1, 6)]
    sp = {f"album-fixture-{i}": _sp(title=f"Album {i}") for i in range(1, 6)}
    dz = {8810010 + i: _dz(title=f"Album {i}") for i in range(1, 6)}
    text = _run(
        batch_size=2,
        limit=3,
        sp=sp,
        upcs={("upc", VALID_UPC): 8810010},
        dz=dz,
    )
    assert "albums examined: 3" in text
    assert "batch done" in text
    assert "resume with --after-id" in text
    # Resuming past the first two rows examines only the remainder.
    text = _run(
        batch_size=2,
        after_id=albums[1].pk,
        limit=2,
        sp=sp,
        upcs={("upc", VALID_UPC): 8810010},
        dz=dz,
    )
    assert "albums examined: 2" in text


@pytest.mark.django_db
def test_cache_and_seed_cache_are_used_readonly(tmp_path):
    artist = _artist()
    _album(artist, deezer_id=999)
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "sp_album": {
                    "album-fixture-1": {
                        "name": "Album 1",
                        "artist": "Synthetic Album Artist",
                        "tracks": 10,
                        "upc": VALID_UPC,
                    }
                },
                "upc_album": {VALID_UPC: 8810002},
                "dz_album": {"8810002": _dz()},
            }
        ),
        encoding="utf-8",
    )
    seed = tmp_path / "seed.json"
    seed.write_text(cache.read_text(encoding="utf-8"), encoding="utf-8")
    with (
        patch.object(
            Command,
            "_fetch_spotify_album",
            side_effect=AssertionError("uncached Spotify call"),
        ),
        patch.object(
            Command,
            "_fetch_album_id_by_upc",
            side_effect=AssertionError("uncached UPC call"),
        ),
        patch.object(
            Command,
            "_fetch_deezer_album",
            side_effect=AssertionError("uncached Deezer call"),
        ),
    ):
        out = StringIO()
        call_command(
            "repair_album_ids",
            cache_file=str(cache),
            seed_cache=str(seed),
            stdout=out,
            sleep=0.0,
        )
    assert _count(out.getvalue(), cmd.REPAIRABLE) == 1
    assert "provider calls:" in out.getvalue()
    assert stat.S_IMODE(os.stat(cache).st_mode) in (0o600, 0o644)


@pytest.mark.django_db
def test_retry_failed_uses_failed_ids_from_audit(tmp_path):
    artist = _artist()
    album = _album(artist, deezer_id=999)
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        json.dumps(
            {"record": "failed", "album_id": album.pk, "outcome": "skip_lookup_failed"}
        )
        + "\n",
        encoding="utf-8",
    )
    text = _run(
        apply=True,
        retry_failed=True,
        audit_file=str(audit),
        sp={"album-fixture-1": _sp()},
        upcs={("upc", VALID_UPC): 8810002},
        dz={8810002: _dz()},
    )
    assert "albums examined: 1" in text
    assert _count(text, cmd.REPAIRABLE) == 1


@pytest.mark.django_db
def test_lookup_failure_is_retryable():
    artist = _artist()
    _album(artist, deezer_id=999)
    boom = cmd.LookupFailed("throttled")
    text = _run(
        sp={"album-fixture-1": boom},
    )
    assert _count(text, cmd.SKIP_LOOKUP_FAILED) == 1
