"""Task lifecycle correctness: orphan cleanup, terminal-state protection,
atomic enqueue claims, cancel-all purge scope, and counter atomicity."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

import pytest

from library_manager.models import Album, Artist, Song, TaskHistory


def _task(task_id: str, status: str = "RUNNING", **extra) -> TaskHistory:
    return TaskHistory.objects.create(
        task_id=task_id,
        type="DOWNLOAD",
        entity_id="1",
        entity_type="ALBUM",
        status=status,
        **extra,
    )


@pytest.mark.django_db
class TestOrphanCleanup(TestCase):
    def test_only_rows_older_than_boot_time_are_failed(self):
        import celery_app

        boot = timezone.now()
        old = _task("orphan-old")
        TaskHistory.objects.filter(pk=old.pk).update(
            last_heartbeat=boot - timedelta(minutes=1)
        )
        live = _task("live-sibling")  # heartbeat >= boot

        celery_app._cleanup_orphaned_tasks(boot_time=boot)

        old.refresh_from_db()
        live.refresh_from_db()
        assert old.status == "FAILED"
        assert live.status == "RUNNING"

    def test_tasks_started_at_boot_time_are_not_failed(self):
        import celery_app

        boot = timezone.now()
        live = _task("live-at-boot")
        TaskHistory.objects.filter(pk=live.pk).update(last_heartbeat=boot)

        celery_app._cleanup_orphaned_tasks(boot_time=boot)

        live.refresh_from_db()
        assert live.status == "RUNNING"

    def test_cleanup_not_run_from_worker_process_init(self):
        import celery_app

        with (
            patch.object(celery_app, "_cleanup_orphaned_tasks") as cleanup,
            patch.object(celery_app, "_log_spotify_rate_limit_status"),
        ):
            celery_app.worker_process_init_handler()
        cleanup.assert_not_called()

    def test_cleanup_runs_from_worker_ready(self):
        import celery_app

        with patch.object(celery_app, "_cleanup_orphaned_tasks") as cleanup:
            celery_app.worker_ready_handler()
        cleanup.assert_called_once()


@pytest.mark.django_db
class TestTerminalStatesPreserved(TestCase):
    def test_progress_does_not_revive_cancelled(self):
        from library_manager.tasks.core import update_task_progress

        row = _task("cancel-progress")
        stale = TaskHistory.objects.get(pk=row.pk)  # worker's in-memory copy
        TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")

        update_task_progress(stale, 50.0, "still going")

        row.refresh_from_db()
        assert row.status == "CANCELLED"
        assert stale.status == "CANCELLED"

    def test_progress_promotes_pending_to_running(self):
        from library_manager.tasks.core import update_task_progress

        row = _task("pending-progress", status="PENDING")
        update_task_progress(row, 10.0, "hi")
        row.refresh_from_db()
        assert row.status == "RUNNING"
        assert row.progress_percentage == 10.0
        assert row.log_messages[-1]["message"] == "hi"

    def test_mark_completed_and_failed_do_not_overwrite_cancelled(self):
        for name, call in (
            ("c1", lambda t: t.mark_completed()),
            ("c2", lambda t: t.mark_failed("boom")),
        ):
            row = _task(name)
            stale = TaskHistory.objects.get(pk=row.pk)
            TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")
            call(stale)
            row.refresh_from_db()
            assert row.status == "CANCELLED", name

    def test_mark_completed_works_normally(self):
        row = _task("normal")
        row.mark_completed()
        row.refresh_from_db()
        assert row.status == "COMPLETED"
        assert row.progress_percentage == 100.0
        assert row.completed_at is not None

    def test_mark_stuck_does_not_overwrite_completed(self):
        row = _task("stuck-race")
        stale = TaskHistory.objects.get(pk=row.pk)
        TaskHistory.objects.filter(pk=row.pk).update(status="COMPLETED")
        stale.mark_stuck("Task timeout")
        row.refresh_from_db()
        assert row.status == "COMPLETED"

    def test_mark_stuck_is_guarded_by_stale_heartbeat(self):
        row = _task("stuck-stale-hb")
        stale = TaskHistory.objects.get(pk=row.pk)
        # Heartbeat refreshes after the stale copy was read.
        TaskHistory.objects.filter(pk=row.pk).update(
            last_heartbeat=timezone.now() + timedelta(minutes=5)
        )
        assert stale.mark_stuck("Task timeout") is False
        row.refresh_from_db()
        assert row.status == "RUNNING"

    def test_stale_instance_cannot_complete_over_cancelled(self):
        row = _task("stale-complete")
        stale = TaskHistory.objects.get(pk=row.pk)
        TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")
        assert stale.mark_completed() is False
        row.refresh_from_db()
        assert row.status == "CANCELLED"

    def test_stale_instance_can_fail_running_row(self):
        row = _task("stale-fail")
        stale = TaskHistory.objects.get(pk=row.pk)
        assert stale.mark_failed("boom") is True
        row.refresh_from_db()
        assert row.status == "FAILED"
        assert row.completed_at is not None


@pytest.mark.django_db
class TestCleanupStuckTasks(TestCase):
    def test_fails_stuck_rows_and_counts_them(self):
        row = _task("cleanup-ok", status="RUNNING")
        TaskHistory.objects.filter(pk=row.pk).update(
            started_at=timezone.now() - timedelta(hours=2),
            last_heartbeat=timezone.now() - timedelta(hours=2),
        )
        assert TaskHistory.cleanup_stuck_tasks() == 1
        row.refresh_from_db()
        assert row.status == "FAILED"

    def test_does_not_count_when_transition_lost_to_refresh(self):
        _task("cleanup-lost")
        with (
            patch.object(TaskHistory, "is_stuck", return_value=True),
            patch.object(TaskHistory, "mark_stuck", return_value=False),
        ):
            assert TaskHistory.cleanup_stuck_tasks() == 0

    def test_does_not_touch_non_running_rows(self):
        _task("cleanup-done", status="COMPLETED")
        assert TaskHistory.cleanup_stuck_tasks() == 0

    def test_cancelled_is_a_valid_choice_and_aged_out(self):
        assert "CANCELLED" in dict(TaskHistory.STATUS_CHOICES)
        old = _task("old-cancel", status="CANCELLED")
        TaskHistory.objects.filter(pk=old.pk).update(
            started_at=timezone.now() - timedelta(days=60)
        )
        TaskHistory.cleanup_old_tasks(days_to_keep=30)
        assert not TaskHistory.objects.filter(pk=old.pk).exists()
        before = TaskHistory.get_storage_stats()["cancelled_tasks"]
        _task("c-stat", status="CANCELLED")
        assert TaskHistory.get_storage_stats()["cancelled_tasks"] == before + 1


@pytest.mark.django_db
class TestEnqueueDeduped(TestCase):
    def test_claims_row_then_publishes_once(self):
        from library_manager.helpers import enqueue_deduped

        task = MagicMock()
        assert enqueue_deduped(task, task_id="tid-1", args=[1]) is True
        assert enqueue_deduped(task, task_id="tid-1", args=[1]) is False
        assert task.apply_async.call_count == 1
        assert TaskHistory.objects.get(task_id="tid-1").status == "PENDING"

    def test_publish_failure_releases_claim(self):
        from library_manager.helpers import enqueue_deduped

        task = MagicMock()
        task.apply_async.side_effect = RuntimeError("broker down")
        with pytest.raises(RuntimeError):
            enqueue_deduped(task, task_id="tid-2", args=[1])
        assert not TaskHistory.objects.filter(task_id="tid-2").exists()

    def test_stale_pending_claim_is_reclaimed(self):
        from library_manager.helpers import enqueue_deduped

        row = _task("tid-3", status="PENDING")
        TaskHistory.objects.filter(pk=row.pk).update(
            started_at=timezone.now() - timedelta(hours=7)
        )
        task = MagicMock()
        assert enqueue_deduped(task, task_id="tid-3", args=[1]) is True
        assert TaskHistory.objects.get(task_id="tid-3").status == "PENDING"

    def test_running_row_blocks(self):
        from library_manager.helpers import enqueue_deduped

        _task("tid-4", status="RUNNING")
        task = MagicMock()
        assert enqueue_deduped(task, task_id="tid-4", args=[1]) is False
        task.apply_async.assert_not_called()

    def test_terminal_row_allows_requeue(self):
        from library_manager.helpers import enqueue_deduped

        _task("tid-5", status="COMPLETED")
        task = MagicMock()
        assert enqueue_deduped(task, task_id="tid-5", args=[1]) is True

    def test_task_start_adopts_claim_and_runs_it(self):
        from library_manager.helpers import enqueue_deduped
        from library_manager.tasks.core import create_task_history

        enqueue_deduped(MagicMock(), task_id="tid-6", args=[1])
        adopted = create_task_history(
            task_id="tid-6",
            task_type="FETCH",
            entity_id="9",
            entity_type="ARTIST",
        )
        assert TaskHistory.objects.filter(task_id="tid-6").count() == 1
        adopted.refresh_from_db()
        assert adopted.status == "RUNNING"
        assert adopted.type == "FETCH"
        assert adopted.entity_id == "9"

    def test_adoption_resets_stale_lifecycle_fields(self):
        from library_manager.tasks.core import create_task_history

        row = _task("tid-reset", status="PENDING")
        TaskHistory.objects.filter(pk=row.pk).update(
            completed_at=timezone.now() - timedelta(days=1),
            error_message="stale error",
            duration_seconds=999,
            progress_percentage=88.0,
            log_messages=[{"message": "stale log"}],
            last_heartbeat=timezone.now() - timedelta(days=1),
        )
        adopted = create_task_history(
            task_id="tid-reset", task_type="FETCH", entity_id="9", entity_type="ARTIST"
        )
        adopted.refresh_from_db()
        assert adopted.status == "RUNNING"
        assert adopted.completed_at is None
        assert adopted.error_message is None
        assert adopted.duration_seconds is None
        assert adopted.progress_percentage == 0.0
        assert adopted.log_messages == []
        assert adopted.last_heartbeat >= adopted.started_at

    def test_adoption_does_not_revive_cancelled(self):
        from library_manager.tasks.core import create_task_history

        row = _task("tid-7", status="CANCELLED")
        TaskHistory.objects.filter(pk=row.pk).update(
            completed_at=timezone.now(), error_message="cancelled"
        )
        adopted = create_task_history(task_id="tid-7", task_type="FETCH")
        adopted.refresh_from_db()
        assert adopted.status == "CANCELLED"
        assert adopted.completed_at is not None
        assert adopted.error_message == "cancelled"

    def test_adoption_does_not_revive_cancelled_won_in_race(self):
        from library_manager.tasks.core import create_task_history

        row = _task("tid-race", status="PENDING")
        original_filter = TaskHistory.objects.filter
        calls = 0

        def flip_to_cancelled(**kwargs):
            nonlocal calls
            calls += 1
            # A cancel arrives after the first read (the lookup by task_id),
            # before the conditional adoption UPDATE (the second filter call).
            if calls == 2:
                original_filter(pk=row.pk).update(status="CANCELLED")
            return original_filter(**kwargs)

        with patch.object(TaskHistory.objects, "filter", side_effect=flip_to_cancelled):
            adopted = create_task_history(task_id="tid-race", task_type="FETCH")
        adopted.refresh_from_db()
        assert adopted.status == "CANCELLED"
        assert adopted.completed_at is None
        assert adopted.log_messages == []

    def test_publish_failure_with_nonce_preserves_newer_claim(self):
        from library_manager.helpers import enqueue_deduped

        task = MagicMock()

        def fail_publish(**kwargs):
            # Simulate a newer generation reusing the same claim row.
            TaskHistory.objects.filter(task_id="tid-nonce").update(
                log_messages=[{"export_sync_nonce": "newer"}]
            )
            raise RuntimeError("broker down")

        task.apply_async.side_effect = fail_publish
        with pytest.raises(RuntimeError):
            enqueue_deduped(
                task,
                task_id="tid-nonce",
                args=[1],
                claim_nonce="old",
                nonce_key="export_sync_nonce",
            )
        claim = TaskHistory.objects.get(task_id="tid-nonce")
        assert claim.log_messages == [{"export_sync_nonce": "newer"}]

    def test_publish_failure_with_nonce_releases_matching_claim(self):
        from library_manager.helpers import enqueue_deduped

        task = MagicMock()

        def fail_publish(**kwargs):
            TaskHistory.objects.filter(task_id="tid-nonce-2").update(
                log_messages=[{"nonce": "mine"}]
            )
            raise RuntimeError("broker down")

        task.apply_async.side_effect = fail_publish
        with pytest.raises(RuntimeError):
            enqueue_deduped(task, task_id="tid-nonce-2", args=[1], claim_nonce="mine")
        assert not TaskHistory.objects.filter(task_id="tid-nonce-2").exists()

    def test_download_missing_albums_ids_converge(self):
        from library_manager.helpers import download_missing_tracked_artists

        artist = Artist.objects.create(name="A", gid="g1", tracking_tier=1)
        mock_task = MagicMock()
        with patch(
            "library_manager.tasks.download_missing_albums_for_artist", mock_task
        ):
            download_missing_tracked_artists([], [artist])
            from library_manager.helpers import enqueue_batch_artist_operations

            enqueue_batch_artist_operations(
                Artist.objects.filter(pk=artist.pk),
                operations=["download"],
                extra_args={"delay": 0},
            )
        assert mock_task.apply_async.call_count == 1


@pytest.mark.django_db
class TestCancelAllPurge(TestCase):
    def test_purges_only_tunestash_queues_once_each(self):
        import asyncio

        from src.services import task_management

        channel = MagicMock()
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.default_channel = channel
        with (
            patch.object(
                task_management.celery_app, "connection_for_write", return_value=conn
            ),
            patch.object(task_management.celery_app.control, "purge") as purge,
        ):
            asyncio.run(
                task_management.TaskManagementService().cancel_all_pending_tasks()
            )

        purge.assert_not_called()
        purged = [c.args[0] for c in channel.queue_purge.call_args_list]
        assert sorted(purged) == ["celery", "downloads", "metadata"]


@pytest.mark.django_db
class TestActiveTasksStat(TestCase):
    def test_counts_running_and_pending(self):
        from src.services.cached_stat import _STAT_COMPUTERS

        _task("s1", status="RUNNING")
        _task("s2", status="PENDING")
        _task("s3", status="COMPLETED")
        assert _STAT_COMPUTERS["active_tasks"]() == 2


@pytest.mark.django_db
class TestCounterAtomicity(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(name="Art", gid="ga")
        self.album = Album.objects.create(
            name="Alb",
            spotify_gid="alb1",
            spotify_uri="spotify:album:1",
            artist=self.artist,
            total_tracks=1,
        )
        self.song = Song.objects.create(
            name="S", gid="sg1", primary_artist=self.artist, album=self.album
        )

    def test_increment_failed_count_is_not_lost_with_stale_instances(self):
        a = Song.objects.get(pk=self.song.pk)
        b = Song.objects.get(pk=self.song.pk)
        a.increment_failed_count()
        b.increment_failed_count()
        assert Song.objects.get(pk=self.song.pk).failed_count == 2
        assert b.failed_count == 2

    def test_increment_does_not_clobber_other_columns(self):
        stale = Song.objects.get(pk=self.song.pk)
        Song.objects.filter(pk=self.song.pk).update(isrc="USABC1234567")
        stale.increment_failed_count()
        assert Song.objects.get(pk=self.song.pk).isrc == "USABC1234567"

    def test_mark_downloaded_does_not_clobber_other_columns(self):
        stale = Song.objects.get(pk=self.song.pk)
        Song.objects.filter(pk=self.song.pk).update(isrc="USABC1234567")
        stale.mark_downloaded(bitrate=320, file_path="/m/a.mp3")
        fresh = Song.objects.get(pk=self.song.pk)
        assert fresh.isrc == "USABC1234567"
        assert fresh.downloaded is True
        assert fresh.bitrate == 320

    def test_add_log_message_preserves_concurrent_entries(self):
        row = _task("logs")
        stale = TaskHistory.objects.get(pk=row.pk)
        row.add_log_message("one")
        stale.add_log_message("two")
        msgs = [m["message"] for m in TaskHistory.objects.get(pk=row.pk).log_messages]
        assert msgs == ["one", "two"]
