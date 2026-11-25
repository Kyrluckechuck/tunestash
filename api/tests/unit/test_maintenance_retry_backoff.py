"""Tests for C1 retry correctness and legacy null-timestamp backfill."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from library_manager.models import Artist, FailureReason, Song


class TestRetryAllMissingKnownSongsBackoff(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(
            name="Artist", gid="artist_retry", tracking_tier=1
        )

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_honors_is_ready_for_retry(self, mock_fallback, _mock_cap):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        ready = Song.objects.create(
            name="Ready",
            gid="ready_song_00001",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=2,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=3),
        )
        in_backoff = Song.objects.create(
            name="Backoff",
            gid="backoff_song_001",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=2,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(hours=1),
        )

        from library_manager.tasks.maintenance import retry_all_missing_known_songs

        retry_all_missing_known_songs()

        downloaded = [s.id for s in mock_fallback.call_args[0][0]]
        assert ready.id in downloaded
        assert in_backoff.id not in downloaded

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_does_not_treat_unavailable_as_truly_gone(self, mock_fallback, _mock_cap):
        mock_fallback.return_value = (0, 0)
        Song.objects.create(
            name="Unavailable missing",
            gid="unavail_song_001",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            unavailable=True,
            failed_count=0,
        )

        from library_manager.tasks.maintenance import retry_all_missing_known_songs

        retry_all_missing_known_songs()

        assert mock_fallback.call_count == 1
        downloaded = mock_fallback.call_args[0][0]
        assert len(downloaded) == 1
        assert downloaded[0].unavailable is True


class TestValidateUndownloadedSongsBackoff(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(
            name="Artist", gid="artist_validate", tracking_tier=1
        )

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_low_confidence_honors_is_ready_for_retry(self, mock_fallback, _mock_cap):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        ready = Song.objects.create(
            name="Low ready",
            gid="low_ready_000001",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=1,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=2),
        )
        in_backoff = Song.objects.create(
            name="Low backoff",
            gid="low_backoff_0001",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=1,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(hours=1),
        )

        from library_manager.tasks.maintenance import validate_undownloaded_songs

        validate_undownloaded_songs()

        downloaded_ids = {s.id for s in mock_fallback.call_args[0][0]}
        assert ready.id in downloaded_ids
        assert in_backoff.id not in downloaded_ids

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_unavailable_batch_honors_is_ready_for_retry(
        self, mock_fallback, _mock_cap
    ):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        ready = Song.objects.create(
            name="Unavail ready",
            gid="unavail_ready_01",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=128,
            unavailable=True,
            failed_count=1,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=2),
        )
        in_backoff = Song.objects.create(
            name="Unavail backoff",
            gid="unavail_backoff1",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=128,
            unavailable=True,
            failed_count=1,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(hours=1),
        )

        from library_manager.tasks.maintenance import validate_undownloaded_songs

        validate_undownloaded_songs()

        downloaded_ids = {s.id for s in mock_fallback.call_args[0][0]}
        assert ready.id in downloaded_ids
        assert in_backoff.id not in downloaded_ids


class BackfillLegacyFailureTimestampsCommandTests(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(
            name="Artist", gid="artist_backfill1", tracking_tier=1
        )

    def _legacy_song(self, **kwargs):
        defaults = dict(
            name="Legacy",
            gid="legacy_song_0001",
            primary_artist=self.artist,
            downloaded=False,
            failed_count=3,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=None,
            unavailable=False,
        )
        defaults.update(kwargs)
        return Song.objects.create(**defaults)

    def test_dry_run_reports_and_does_not_write(self):
        song = self._legacy_song()
        out = StringIO()
        call_command("backfill_legacy_failure_timestamps", stdout=out)
        song.refresh_from_db()
        assert song.last_failed_at is None
        assert "Dry run" in out.getvalue()
        assert "1" in out.getvalue()

    def test_apply_requires_audit_file(self):
        self._legacy_song()
        with self.assertRaises(CommandError):
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--last-failed-at",
                timezone.now().isoformat(),
            )

    def test_apply_requires_last_failed_at(self):
        self._legacy_song()
        with self.assertRaises(CommandError):
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--audit-file",
                "/tmp/should-not-exist.json",
            )

    def test_apply_writes_audit_and_stamps_aware_timestamp(self):
        import json
        import os
        import tempfile

        song = self._legacy_song(
            gid="legacy_song_0002",
            failed_count=5,
            failure_reason=FailureReason.BOTH_UNAVAILABLE,
            unavailable=True,
        )
        stamp = timezone.now().replace(microsecond=0)
        fd, audit_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(audit_path)
        try:
            out = StringIO()
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--audit-file",
                audit_path,
                "--last-failed-at",
                stamp.isoformat(),
                stdout=out,
            )
            song.refresh_from_db()
            assert song.last_failed_at == stamp
            assert timezone.is_aware(song.last_failed_at)
            assert song.failed_count == 5
            assert song.failure_reason == FailureReason.BOTH_UNAVAILABLE
            assert song.unavailable is True
            assert song.downloaded is False
            with open(audit_path, encoding="utf-8") as f:
                audit = json.load(f)
            rows = [
                entry for entry in audit if isinstance(entry, dict) and "id" in entry
            ]
            assert len(rows) == 1
            assert rows[0]["id"] == song.id
            assert rows[0]["last_failed_at"] is None
            assert rows[0]["failed_count"] == 5
            assert audit[-1]["outcome"] == "committed"
            assert audit[-1]["updated_count"] == 1
            assert "Applied" in out.getvalue()
        finally:
            if os.path.exists(audit_path):
                os.remove(audit_path)

    def test_apply_does_not_overwrite_audit_file(self):
        import os
        import tempfile

        self._legacy_song(gid="legacy_song_0003")
        fd, audit_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with self.assertRaises(CommandError):
                call_command(
                    "backfill_legacy_failure_timestamps",
                    "--apply",
                    "--audit-file",
                    audit_path,
                    "--last-failed-at",
                    timezone.now().isoformat(),
                )
        finally:
            os.remove(audit_path)

    def test_narrows_scope(self):
        import os
        import tempfile

        now = timezone.now()
        should_fix = self._legacy_song(gid="scope_fix_000001")
        already_stamped = self._legacy_song(
            gid="scope_stamped_01",
            last_failed_at=now - timedelta(days=1),
        )
        downloaded = self._legacy_song(gid="scope_dl_0000001", downloaded=True)
        no_failures = self._legacy_song(
            gid="scope_nofail_001", failed_count=0, failure_reason=None
        )

        fd, audit_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(audit_path)
        try:
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--audit-file",
                audit_path,
                "--last-failed-at",
                now.isoformat(),
            )
        finally:
            if os.path.exists(audit_path):
                os.remove(audit_path)

        should_fix.refresh_from_db()
        already_stamped.refresh_from_db()
        downloaded.refresh_from_db()
        no_failures.refresh_from_db()
        assert should_fix.last_failed_at is not None
        assert already_stamped.last_failed_at == now - timedelta(days=1)
        assert downloaded.last_failed_at is None
        assert no_failures.last_failed_at is None

    def _fresh_audit_path(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)
        return path

    def test_rejects_date_only_impossible_malformed_and_future(self):
        song = self._legacy_song(gid="invalid_stamp_001")
        for value in (
            "2026-11-24",
            "2026-02-30T00:00:00Z",
            "not-a-date",
            (timezone.now() + timedelta(days=2)).isoformat(),
        ):
            path = self._fresh_audit_path()
            try:
                with self.assertRaises(CommandError):
                    call_command(
                        "backfill_legacy_failure_timestamps",
                        "--apply",
                        "--audit-file",
                        path,
                        "--last-failed-at",
                        value,
                    )
                song.refresh_from_db()
                assert song.last_failed_at is None
            finally:
                import os

                if os.path.exists(path):
                    os.remove(path)

    def test_accepts_aware_and_naive_datetimes(self):
        import json
        import os

        for value in ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00"):
            self._legacy_song(gid=f"stamp_fmt_{'aware' if '+' in value else 'naive'}")
            path = self._fresh_audit_path()
            try:
                call_command(
                    "backfill_legacy_failure_timestamps",
                    "--apply",
                    "--audit-file",
                    path,
                    "--last-failed-at",
                    value,
                )
                with open(path, encoding="utf-8") as f:
                    audit = json.load(f)
                assert audit[-1]["outcome"] == "committed"
            finally:
                if os.path.exists(path):
                    os.remove(path)

    def test_audit_file_is_private(self):
        import os
        import stat

        self._legacy_song(gid="perm_check_0001")
        path = self._fresh_audit_path()
        try:
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--audit-file",
                path,
                "--last-failed-at",
                timezone.now().isoformat(),
            )
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_failed_before_alias_removed(self):
        import os

        self._legacy_song(gid="alias_check_0001")
        path = self._fresh_audit_path()
        try:
            with self.assertRaises(CommandError):
                call_command(
                    "backfill_legacy_failure_timestamps",
                    "--apply",
                    "--audit-file",
                    path,
                    "--failed-before",
                    timezone.now().isoformat(),
                )
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_chunked_audit_bounded_and_all_rows(self):
        import json
        import os

        for i in range(5):
            self._legacy_song(gid=f"chunk_song_{i:08d}")
        path = self._fresh_audit_path()
        try:
            call_command(
                "backfill_legacy_failure_timestamps",
                "--apply",
                "--audit-file",
                path,
                "--last-failed-at",
                timezone.now().isoformat(),
            )
            with open(path, encoding="utf-8") as f:
                audit = json.load(f)
            rows = [
                entry for entry in audit if isinstance(entry, dict) and "id" in entry
            ]
            assert len(rows) == 5
            assert audit[-1]["updated_count"] == 5
            assert (
                Song.objects.filter(
                    last_failed_at__isnull=False, failed_count__gt=0
                ).count()
                == 5
            )
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_rollback_keeps_audit_preimage_without_commit_claim(self):
        import json
        import os
        from unittest.mock import patch

        from library_manager.models import Song as CommandSong

        original_filter = CommandSong.objects.filter

        def failing_update_filter(*args, **kwargs):
            queryset = original_filter(*args, **kwargs)
            if "id__in" in kwargs:

                def raise_on_update(*uargs, **ukwargs):
                    raise RuntimeError("db failure")

                queryset.update = raise_on_update
            return queryset

        self._legacy_song(gid="rollback_song_01")
        path = self._fresh_audit_path()
        try:
            with patch.object(
                CommandSong.objects, "filter", side_effect=failing_update_filter
            ):
                with self.assertRaises(RuntimeError):
                    call_command(
                        "backfill_legacy_failure_timestamps",
                        "--apply",
                        "--audit-file",
                        path,
                        "--last-failed-at",
                        timezone.now().isoformat(),
                    )
            assert os.path.exists(path)
            with open(path, encoding="utf-8") as f:
                audit = json.load(f)
            rows = [
                entry for entry in audit if isinstance(entry, dict) and "id" in entry
            ]
            assert rows
            assert audit[-1]["outcome"] == "prepared_rolled_back"
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestRetryStarvation(TestCase):
    """Old blocked rows must not starve newer ready rows past the batch cap."""

    def setUp(self):
        self.artist = Artist.objects.create(
            name="Artist", gid="artist_starve1", tracking_tier=1
        )

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_all_missing_scans_past_blocked_cap(self, mock_fallback, _mock_cap):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        for i in range(120):
            Song.objects.create(
                name=f"Blocked {i}",
                gid=f"blocked_song_{i:08d}",
                primary_artist=self.artist,
                downloaded=False,
                bitrate=0,
                failed_count=2,
                failure_reason=FailureReason.TEMPORARY_ERROR,
                last_failed_at=now - timedelta(hours=1),
            )
        ready = Song.objects.create(
            name="Ready after cap",
            gid="ready_after_cap_01",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=2,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=3),
        )

        from library_manager.tasks.maintenance import retry_all_missing_known_songs

        retry_all_missing_known_songs()

        ids = {s.id for s in mock_fallback.call_args[0][0]}
        assert ready.id in ids

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_validate_low_confidence_scans_past_blocked_cap(
        self, mock_fallback, _mock_cap
    ):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        for i in range(60):
            Song.objects.create(
                name=f"Low blocked {i}",
                gid=f"low_blocked_{i:08d}",
                primary_artist=self.artist,
                downloaded=False,
                bitrate=0,
                failed_count=2,
                failure_reason=FailureReason.TEMPORARY_ERROR,
                last_failed_at=now - timedelta(hours=1),
            )
        ready = Song.objects.create(
            name="Low ready after cap",
            gid="low_ready_cap_01",
            primary_artist=self.artist,
            downloaded=False,
            bitrate=0,
            failed_count=2,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=3),
        )

        from library_manager.tasks.maintenance import validate_undownloaded_songs

        validate_undownloaded_songs()

        ids = {s.id for s in mock_fallback.call_args[0][0]}
        assert ready.id in ids

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_scans_past_blocked_cap(self, mock_fallback, _mock_cap):
        mock_fallback.return_value = (0, 0)
        now = timezone.now()
        for i in range(210):
            Song.objects.create(
                name=f"Failed blocked {i}",
                gid=f"fail_blocked_{i:08d}",
                primary_artist=self.artist,
                downloaded=False,
                failed_count=2,
                failure_reason=FailureReason.TEMPORARY_ERROR,
                last_failed_at=now - timedelta(hours=1),
            )
        ready = Song.objects.create(
            name="Failed ready after cap",
            gid="fail_ready_cap_01",
            primary_artist=self.artist,
            downloaded=False,
            failed_count=2,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=now - timedelta(days=3),
        )

        from library_manager.tasks.maintenance import retry_failed_songs

        retry_failed_songs()

        ids = {s.id for s in mock_fallback.call_args[0][0]}
        assert ready.id in ids


class TestRetryDocstrings(TestCase):
    def test_retry_failed_songs_documents_both_unavailable_backoff(self):
        from library_manager.tasks.maintenance import retry_failed_songs

        doc = retry_failed_songs.__doc__ or ""
        assert "30 days flat" not in doc
        assert "90" in doc
