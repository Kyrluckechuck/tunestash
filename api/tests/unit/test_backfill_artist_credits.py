"""backfill_artist_credits: dry-run default, audited apply, no duplicate artists.

All names and ids in this module are synthetic.
"""

import json
import os
import stat
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.management.commands import backfill_artist_credits as cmd
from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    Song,
    TrackingTier,
)
from src.providers.metadata_base import ArtistCredit, TrackResult

LEAD = ArtistCredit(name="Lead Person", deezer_id=101, role="main")
GUEST = ArtistCredit(name="Guest Person", deezer_id=102, role="main")
REMIXER = ArtistCredit(name="Remixer Person", deezer_id=103, role="featured")


def _track(deezer_id: int, credits: list[ArtistCredit], isrc: str = "ZZTEST000001"):
    return TrackResult(
        name="Synthetic Song",
        artist_name=credits[0].name,
        deezer_id=deezer_id,
        isrc=isrc,
        artist_deezer_id=credits[0].deezer_id,
        credits=credits,
    )


@pytest.fixture
def tracked() -> Artist:
    return Artist.objects.create(
        name="Tracked Person", deezer_id=102, tracking_tier=TrackingTier.TRACKED
    )


@pytest.fixture
def song(tracked: Artist) -> Song:
    album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=42)
    return Song.objects.create(
        name="Synthetic Song",
        deezer_id=9001,
        isrc="ZZTEST000001",
        primary_artist=tracked,
        album=album,
        downloaded=True,
    )


class _Lookups:
    """Stand-in for the Deezer client keyed by track id."""

    def __init__(self, tracks: dict[int, TrackResult | None]) -> None:
        self.tracks = tracks
        self.calls: list[int] = []

    def __call__(self, deezer_id: int) -> TrackResult | None:
        self.calls.append(deezer_id)
        track = self.tracks.get(deezer_id)
        if track is not None and track.album_deezer_id is None:
            # By default the Deezer track belongs to the song's own release.
            song = (
                Song.objects.filter(deezer_id=deezer_id).select_related("album").first()
            )
            if song is not None and song.album is not None:
                track.album_deezer_id = song.album.deezer_id
                track.album_name = song.album.name
        return track


def _run(lookups: _Lookups, *args: str) -> str:
    out = StringIO()
    with (
        patch.object(cmd.Command, "_fetch_track", lookups),
        patch.object(cmd.time, "sleep") as sleep,
        # Mounted test tmp dirs can stall fsync; production code always syncs
        # and test_audit_is_fsynced_before_writes proves the call happens.
        patch.object(cmd.os, "fsync") as fsync,
    ):
        call_command("backfill_artist_credits", *args, "--sleep", "0.5", stdout=out)
    _run.sleep = sleep  # type: ignore[attr-defined]
    _run.fsync = fsync  # type: ignore[attr-defined]
    return out.getvalue()


@pytest.mark.unit
class TestDryRun:
    def test_dry_run_reports_and_changes_nothing(self, song: Song) -> None:
        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST, REMIXER])})

        output = _run(lookups)

        assert "DRY RUN" in output
        assert "featured_as_primary: 1" in output
        song.refresh_from_db()
        assert song.primary_artist.deezer_id == 102
        assert ContributingArtist.objects.count() == 0
        assert Artist.objects.count() == 1

    def test_apply_requires_audit_file(self) -> None:
        with pytest.raises(CommandError, match="--audit-file"):
            call_command("backfill_artist_credits", "--apply")

    def test_audit_file_requires_apply(self, tmp_path: Path) -> None:
        with pytest.raises(CommandError, match="only applies with --apply"):
            call_command("backfill_artist_credits", "--audit-file", str(tmp_path / "a"))

    def test_existing_audit_file_is_refused(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit.jsonl"
        audit.write_text("x")
        with pytest.raises(CommandError, match="already exists"):
            call_command(
                "backfill_artist_credits", "--apply", "--audit-file", str(audit)
            )


@pytest.mark.unit
class TestApply:
    def test_lead_becomes_primary_and_tracked_artist_stays_linked(
        self, song: Song, tracked: Artist, tmp_path: Path
    ) -> None:
        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST, REMIXER])})

        _run(lookups, "--apply", "--audit-file", str(tmp_path / "audit.jsonl"))

        song.refresh_from_db()
        assert song.primary_artist.deezer_id == 101
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__deezer_id", flat=True
            )
        ) == {101, 102, 103}
        assert Artist.objects.filter(deezer_id=102).count() == 1

    def test_audit_is_private_and_written_before_the_change(
        self, song: Song, tmp_path: Path
    ) -> None:
        audit = tmp_path / "audit.jsonl"
        seen: dict[str, Any] = {}
        original = cmd.Command._apply_plan

        def spy(self: Any, plan: Any) -> str:
            seen["mode"] = stat.S_IMODE(os.stat(audit).st_mode)
            seen["lines"] = audit.read_text().splitlines()
            seen["primary_at_audit"] = Song.objects.get(pk=song.pk).primary_artist_id
            return original(self, plan)

        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})
        with patch.object(cmd.Command, "_apply_plan", spy):
            _run(lookups, "--apply", "--audit-file", str(audit))

        assert seen["mode"] == 0o600
        records = [json.loads(line) for line in seen["lines"]]
        assert records[0]["record"] == "header"
        assert records[1]["song_id"] == song.pk
        assert records[1]["old_primary_id"] == seen["primary_at_audit"]

    def test_same_name_different_id_keeps_primary_and_creates_no_row(
        self, tmp_path: Path
    ) -> None:
        namesake = Artist.objects.create(
            name="Kim", deezer_id=300, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=namesake, deezer_id=45)
        song = Song.objects.create(
            name="Synthetic Song",
            deezer_id=9002,
            primary_artist=namesake,
            album=album,
            downloaded=True,
        )
        other_kim = ArtistCredit(name="Kim", deezer_id=301, role="main")
        before = Artist.objects.count()

        output = _run(
            _Lookups({9002: _track(9002, [other_kim])}),
            "--apply",
            "--audit-file",
            str(tmp_path / "audit.jsonl"),
        )

        song.refresh_from_db()
        assert "skip_same_name_different_id: 1" in output
        assert "same_name_different_id, unchanged" in output
        assert song.primary_artist == namesake
        assert Artist.objects.count() == before
        assert not ContributingArtist.objects.filter(song=song).exists()

    def test_recheck_is_idempotent(self, song: Song, tmp_path: Path) -> None:
        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})
        output = _run(lookups, "--apply", "--audit-file", str(tmp_path / "a.jsonl"))

        assert "featured_as_primary: 1" in output
        assert ContributingArtist.objects.filter(song=song).count() == 2
        # A second planning pass resolves to the same contributors without
        # duplicating rows.
        command = cmd.Command()
        command._sleep = 0
        command._cache = {}
        with patch.object(cmd.Command, "_fetch_track", lookups):
            plan = command._plan_song(Song.objects.get(pk=song.pk))
        assert plan.credits
        assert set(plan.existing_contributor_ids) == set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist_id", flat=True
            )
        )

    def test_primary_changed_since_planning_is_skipped(
        self, song: Song, tmp_path: Path
    ) -> None:
        elsewhere = Artist.objects.create(name="Someone Else", deezer_id=555)
        original = cmd.Command._plan_song

        def plan_then_edit(self: Any, s: Song) -> Any:
            plan = original(self, s)
            Song.objects.filter(pk=s.pk).update(primary_artist=elsewhere)
            return plan

        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})
        with patch.object(cmd.Command, "_plan_song", plan_then_edit):
            output = _run(lookups, "--apply", "--audit-file", str(tmp_path / "a.jsonl"))

        song.refresh_from_db()
        assert "skip_changed_concurrently: 1" in output
        # The CAS guard leaves the concurrently written primary in place.
        assert song.primary_artist_id == elsewhere.pk
        assert not ContributingArtist.objects.filter(song=song).exists()


@pytest.mark.unit
class TestBatchingAndResume:
    def _songs(self, tracked: Artist, count: int) -> list[Song]:
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=77)
        return [
            Song.objects.create(
                name=f"Synthetic {i}",
                deezer_id=8000 + i,
                primary_artist=tracked,
                album=album,
                downloaded=True,
            )
            for i in range(count)
        ]

    def test_batches_and_after_id_resume(self, tracked: Artist, tmp_path: Path) -> None:
        songs = self._songs(tracked, 5)
        lookups = _Lookups(
            {s.deezer_id: _track(s.deezer_id, [LEAD, GUEST]) for s in songs}
        )

        first = _run(
            lookups,
            "--apply",
            "--audit-file",
            str(tmp_path / "a1.jsonl"),
            "--batch-size",
            "2",
            "--limit",
            "3",
        )
        assert "songs examined: 3" in first
        assert first.count("batch done") == 2

        resume_from = songs[2].pk
        second = _run(
            lookups,
            "--apply",
            "--audit-file",
            str(tmp_path / "a2.jsonl"),
            "--batch-size",
            "2",
            "--after-id",
            str(resume_from),
        )
        assert "songs examined: 2" in second
        assert Song.objects.filter(primary_artist__deezer_id=101).count() == 5

    def test_lookups_are_throttled_and_cached(
        self, tracked: Artist, tmp_path: Path
    ) -> None:
        songs = self._songs(tracked, 3)
        lookups = _Lookups(
            {s.deezer_id: _track(s.deezer_id, [LEAD, GUEST]) for s in songs}
        )
        cache = tmp_path / "cache.json"

        _run(lookups, "--cache-file", str(cache))

        assert len(lookups.calls) == 3
        assert _run.sleep.call_count == 2  # type: ignore[attr-defined]
        assert stat.S_IMODE(os.stat(cache).st_mode) == 0o600

        _run(lookups, "--cache-file", str(cache))
        assert len(lookups.calls) == 3  # served from the cache file


@pytest.mark.unit
class TestFilePaths:
    def test_paths_are_reported_not_changed(
        self, song: Song, settings: Any, tmp_path: Path
    ) -> None:
        settings.OUTPUT_PATH = str(tmp_path)
        old = (
            tmp_path
            / "Tracked Person"
            / "Their Album"
            / "Tracked Person - Synthetic Song.m4a"
        )
        song.set_file_path(str(old))
        song.save()
        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})

        output = _run(lookups)
        assert "path_would_change: 1" in output

        _run(
            lookups,
            "--apply",
            "--audit-file",
            str(tmp_path / "audit.jsonl"),
        )
        song.refresh_from_db()
        assert song.file_path == str(old)

    def test_path_already_under_the_lead_is_not_flagged(
        self, song: Song, settings: Any, tmp_path: Path
    ) -> None:
        settings.OUTPUT_PATH = str(tmp_path)
        same = (
            tmp_path
            / "Lead Person"
            / "Their Album"
            / "Lead Person - Synthetic Song.m4a"
        )
        song.set_file_path(str(same))
        song.save()
        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})

        output = _run(lookups)

        assert "path_would_change: " not in output


@pytest.mark.unit
class TestMatcherSourceCredit:
    def test_source_credit_is_lead_then_contributors(self, song: Song) -> None:
        from library_manager.artist_credits import source_credit_for

        lead = Artist.objects.create(name="Alpha Lead", deezer_id=901)
        guest = Artist.objects.create(name="Beta Guest", deezer_id=902)
        remixer = Artist.objects.create(name="Gamma Remixer", deezer_id=903)
        for artist in (lead, guest, remixer):
            ContributingArtist.objects.get_or_create(song=song, artist=artist)
        song.primary_artist = lead
        song.save()

        assert source_credit_for(song) == "Alpha Lead, Beta Guest, Gamma Remixer"

    def test_album_artist_not_in_credits_is_excluded(self, song: Song) -> None:
        from library_manager.artist_credits import source_credit_for

        lead = Artist.objects.create(name="Alpha Lead", deezer_id=901)
        song.primary_artist = lead
        song.save()
        ContributingArtist.objects.create(song=song, artist=lead)

        assert source_credit_for(song) == "Alpha Lead"
        assert song.album.artist.name not in source_credit_for(song)

    def test_provider_match_artist_is_never_the_source(
        self, song: Song, settings: Any
    ) -> None:
        from library_manager.artist_credits import source_credit_for
        from library_manager.tasks import maintenance

        settings.OUTPUT_PATH = "/tmp/synthetic-output"
        lead = Artist.objects.create(name="Alpha Lead", deezer_id=901)
        song.primary_artist = lead
        song.save()
        ContributingArtist.objects.create(song=song, artist=lead)
        metadata = maintenance._build_track_metadata(song)

        assert metadata.artist == "Alpha Lead"
        assert source_credit_for(song) == "Alpha Lead"


@pytest.mark.unit
class TestIdentityPreImage:
    def test_contributor_only_change_is_not_overwritten(
        self, song: Song, tmp_path: Path
    ) -> None:
        bystander = Artist.objects.create(name="Bystander Person", deezer_id=900)
        original = cmd.Command._plan_song

        def plan_then_edit(self: Any, s: Song) -> Any:
            plan = original(self, s)
            # A newer correction links a contributor; the primary is unchanged.
            ContributingArtist.objects.create(song=s, artist=bystander)
            return plan

        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})
        with patch.object(cmd.Command, "_plan_song", plan_then_edit):
            output = _run(lookups, "--apply", "--audit-file", str(tmp_path / "a.jsonl"))

        song.refresh_from_db()
        assert "skip_changed_concurrently: 1" in output
        assert song.primary_artist.deezer_id == 102  # untouched
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist_id", flat=True
            )
        ) == {bystander.pk}


@pytest.mark.unit
class TestLeadRule:
    def test_backfill_uses_listing_lead_not_contributor_position(
        self, song: Song, tmp_path: Path
    ) -> None:
        # Deezer lists the guest first, but names LEAD as the track artist.
        track = _track(9001, [GUEST, LEAD])
        track.artist_name, track.artist_deezer_id = LEAD.name, LEAD.deezer_id

        _run(_Lookups({9001: track}), "--apply", "--audit-file", str(tmp_path / "a"))

        song.refresh_from_db()
        assert song.primary_artist.deezer_id == 101

    def test_first_main_credit_leads_when_listing_names_nobody(self) -> None:
        from library_manager.artist_credits import lead_first

        ordered = lead_first([REMIXER, GUEST, LEAD])

        assert [c.deezer_id for c in ordered] == [102, 103, 101]


@pytest.mark.unit
class TestAuditDurability:
    def test_audit_is_fsynced_before_the_first_write(
        self, song: Song, tmp_path: Path
    ) -> None:
        events: list[str] = []
        original = cmd.Command._apply_plan

        def spy(self: Any, plan: Any) -> str:
            events.append("apply")
            return original(self, plan)

        def fake_fsync(_fd: int) -> None:
            events.append("fsync")

        lookups = _Lookups({9001: _track(9001, [LEAD, GUEST])})
        with (
            patch.object(cmd.Command, "_apply_plan", spy),
            patch.object(cmd.Command, "_fetch_track", lookups),
            patch.object(cmd.time, "sleep"),
            patch.object(cmd.os, "fsync", fake_fsync),
        ):
            call_command(
                "backfill_artist_credits",
                "--apply",
                "--audit-file",
                str(tmp_path / "a.jsonl"),
                stdout=StringIO(),
            )

        # header and batch plan are both synced before the first DB write
        assert events.index("apply") >= 2
        assert events[: events.index("apply")].count("fsync") >= 2


@pytest.mark.unit
class TestResumeCursor:
    def test_cursor_does_not_pass_a_retryable_failure(
        self, tracked: Artist, tmp_path: Path
    ) -> None:
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=88)
        Song.objects.create(
            name="One",
            deezer_id=8101,
            primary_artist=tracked,
            album=album,
            downloaded=True,
        )
        second = Song.objects.create(
            name="Two",
            deezer_id=8102,
            primary_artist=tracked,
            album=album,
            downloaded=True,
        )
        lookups = _Lookups({8102: _track(8102, [LEAD, GUEST])})  # 8101 fails

        output = _run(lookups, "--apply", "--audit-file", str(tmp_path / "a.jsonl"))

        assert "skip_lookup_failed: 1" in output
        # Only retryable failures hold the cursor at its starting point.
        assert "resume with --after-id 0" in output
        second.refresh_from_db()
        assert second.primary_artist.deezer_id == 101


@pytest.mark.unit
class TestAmbiguousAndAdopted:
    def _track_for(self, credits: list[ArtistCredit]) -> TrackResult:
        return _track(9001, credits)

    def test_unverified_same_name_row_leaves_the_song_unchanged(
        self, song: Song, tmp_path: Path
    ) -> None:
        Artist.objects.create(name="Remixer Person", gid="r" * 22)  # unlinked twin
        before = Artist.objects.count()

        output = _run(
            _Lookups({9001: self._track_for([LEAD, REMIXER])}),
            "--apply",
            "--audit-file",
            str(tmp_path / "a.jsonl"),
        )

        song.refresh_from_db()
        assert "skip_ambiguous_artist: 1" in output
        assert "ambiguous, unchanged" in output
        assert song.primary_artist.deezer_id == 102
        assert not ContributingArtist.objects.filter(song=song).exists()
        assert Artist.objects.count() == before  # no duplicate, no new row

    def test_dry_run_reports_ambiguity_and_writes_nothing(self, song: Song) -> None:
        Artist.objects.create(name="Remixer Person", gid="r" * 22)
        before = Artist.objects.count()

        output = _run(_Lookups({9001: self._track_for([LEAD, REMIXER])}))

        assert "skip_ambiguous_artist: 1" in output
        assert Artist.objects.count() == before

    def test_isrc_verified_spotify_only_row_is_adopted_not_duplicated(
        self, tracked: Artist, tmp_path: Path
    ) -> None:
        spotify_row = Artist.objects.create(
            name="Lead Person", gid="l" * 22, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=95)
        led_song = Song.objects.create(
            name="Synthetic Song",
            deezer_id=9001,
            isrc="ZZTEST000001",
            primary_artist=spotify_row,
            album=album,
            downloaded=True,
        )
        # An independent song (different track id) already carries the ISRC
        # on the Spotify-only row; the song being corrected cannot vouch itself.
        Song.objects.create(
            name="Other Copy",
            gid="k" * 22,
            isrc="ZZTEST000001",
            primary_artist=spotify_row,
        )
        before = Artist.objects.count()

        output = _run(
            _Lookups({9001: self._track_for([LEAD, REMIXER])}),
            "--apply",
            "--audit-file",
            str(tmp_path / "a.jsonl"),
        )

        led_song.refresh_from_db()
        spotify_row.refresh_from_db()
        assert led_song.primary_artist == spotify_row  # same artist, same row
        assert spotify_row.deezer_id == 101
        assert spotify_row.tracking_tier == TrackingTier.TRACKED
        assert Artist.objects.filter(name="Lead Person").count() == 1
        assert Artist.objects.count() == before + 1  # only the new remixer
        assert "primary_is_lead: 1" in output
        assert "artists_to_adopt: 1" in output

    def test_stale_plan_leaves_no_orphan_artist_rows(
        self, song: Song, tmp_path: Path
    ) -> None:
        elsewhere = Artist.objects.create(name="Someone Else", deezer_id=555)
        original = cmd.Command._plan_song

        def plan_then_edit(self: Any, s: Song) -> Any:
            plan = original(self, s)
            Song.objects.filter(pk=s.pk).update(primary_artist=elsewhere)
            return plan

        before = set(Artist.objects.values_list("pk", flat=True))
        with patch.object(cmd.Command, "_plan_song", plan_then_edit):
            output = _run(
                _Lookups({9001: self._track_for([LEAD, REMIXER])}),
                "--apply",
                "--audit-file",
                str(tmp_path / "a.jsonl"),
            )

        assert "skip_changed_concurrently: 1" in output
        assert set(Artist.objects.values_list("pk", flat=True)) == before
        assert not Artist.objects.filter(deezer_id__in=[101, 103]).exists()


@pytest.mark.unit
class TestReleaseMismatch:
    def test_track_from_another_release_is_skipped_and_counted(
        self, song: Song, tmp_path: Path
    ) -> None:
        # Same recording, but Deezer's track belongs to a reissue (album 9999)
        # credited to other artists.
        reissue = _track(9001, [LEAD, GUEST])
        reissue.album_deezer_id = 9999
        reissue.album_name = "Reissue"
        before = Artist.objects.count()

        output = _run(
            _Lookups({9001: reissue}),
            "--apply",
            "--audit-file",
            str(tmp_path / "a.jsonl"),
        )

        song.refresh_from_db()
        assert "skip_release_mismatch: 1" in output
        assert "release_different_release: 1" in output
        assert "belongs to a different release: 1" in output
        assert song.primary_artist.deezer_id == 102  # unchanged
        assert not ContributingArtist.objects.filter(song=song).exists()
        assert Artist.objects.count() == before  # and it was no ISRC evidence

    def test_album_without_deezer_id_matches_by_title_and_artist(
        self, tracked: Artist, tmp_path: Path
    ) -> None:
        album = Album.objects.create(
            name="Their Album",
            artist=tracked,
            spotify_gid="synthalbum1",
            spotify_uri="spotify:album:synthalbum1",
        )
        song = Song.objects.create(
            name="Synthetic Song",
            deezer_id=9001,
            isrc="ZZTEST000001",
            primary_artist=tracked,
            album=album,
            downloaded=True,
        )
        same = _track(9001, [LEAD, GUEST])
        same.album_deezer_id, same.album_name = 8888, "Their Album"

        output = _run(
            _Lookups({9001: same}), "--apply", "--audit-file", str(tmp_path / "a.jsonl")
        )

        song.refresh_from_db()
        assert "skip_release_mismatch" not in output
        assert song.primary_artist.deezer_id == 101

    def test_album_without_deezer_id_and_other_title_is_a_different_release(
        self, tracked: Artist
    ) -> None:
        from library_manager.artist_credits import release_match

        album = Album.objects.create(
            name="Their Album",
            artist=tracked,
            spotify_gid="synthalbum1",
            spotify_uri="spotify:album:synthalbum1",
        )
        song = Song.objects.create(
            name="Synthetic Song", deezer_id=9001, primary_artist=tracked, album=album
        )
        other = _track(9001, [LEAD, GUEST])
        other.album_deezer_id, other.album_name = 8888, "Greatest Hits"

        assert release_match(song, other) == "different_release"

    def test_reconcile_path_ignores_credits_from_another_release(
        self, song: Song
    ) -> None:
        from library_manager.artist_credits import credits_for_song_release

        reissue = _track(9001, [LEAD, GUEST])
        reissue.album_deezer_id, reissue.album_name = 9999, "Reissue"

        assert credits_for_song_release(song, reissue) == []

        own = _track(9001, [LEAD, GUEST])
        own.album_deezer_id = song.album.deezer_id
        assert [c.deezer_id for c in credits_for_song_release(song, own)] == [101, 102]
