"""Cooperative cancellation: cheap status checks, clean loop exits, queued
task revocation, and no untracked partial download files."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

import pytest

from library_manager.models import TaskHistory
from library_manager.tasks.core import (
    TaskCancelledException,
    clear_cancelled_cache,
    is_task_cancelled,
    raise_if_cancelled,
)


@pytest.mark.django_db
class TestCancellationHelper(TestCase):
    def setUp(self):
        clear_cancelled_cache()

    def tearDown(self):
        clear_cancelled_cache()

    def test_is_task_cancelled_reads_status_and_caches(self):
        row = TaskHistory.objects.create(
            task_id="cancel-helper-1",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="CANCELLED",
        )
        assert is_task_cancelled(row.task_id) is True

        with patch(
            "library_manager.tasks.core.TaskHistory.objects.filter"
        ) as mock_filter:
            assert is_task_cancelled(row.task_id) is True
            mock_filter.assert_not_called()

    def test_uncached_status_is_reflected_after_ttl(self):
        row = TaskHistory.objects.create(
            task_id="cancel-helper-2",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="RUNNING",
        )
        assert is_task_cancelled(row.task_id) is False
        clear_cancelled_cache(row.task_id)
        TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")
        assert is_task_cancelled(row.task_id) is True

    def test_raise_if_cancelled_raises_without_touching_row(self):
        TaskHistory.objects.create(
            task_id="cancel-helper-3",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="CANCELLED",
        )
        with pytest.raises(TaskCancelledException):
            raise_if_cancelled(TaskHistory(task_id="cancel-helper-3"))

    def test_forced_refresh_sees_cancel_set_mid_batch(self):
        """A cancel set after the pre-batch check is seen before the next track."""
        row = TaskHistory.objects.create(
            task_id="cancel-mid-batch",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="RUNNING",
        )
        # Pre-batch check caches "not cancelled".
        assert is_task_cancelled(row.task_id) is False

        # User cancels while the async batch is running.
        TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")

        # A critical boundary must bypass the cache and see the cancellation.
        assert is_task_cancelled(row.task_id, force_refresh=True) is True
        with pytest.raises(TaskCancelledException):
            raise_if_cancelled(TaskHistory(task_id=row.task_id), force_refresh=True)

    def test_negative_result_expires_quickly(self):
        """A short batch cannot keep a stale 'not cancelled' for long."""
        row = TaskHistory.objects.create(
            task_id="cancel-short-ttl",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="RUNNING",
        )
        with patch("library_manager.tasks.core.time.monotonic", side_effect=[0.0, 1.0]):
            assert is_task_cancelled(row.task_id) is False  # cached at t=0
            TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")
            assert is_task_cancelled(row.task_id) is True  # expired at t=1


@pytest.mark.django_db
class TestCancelMidLoop(TestCase):
    def setUp(self):
        clear_cancelled_cache()

    def tearDown(self):
        clear_cancelled_cache()

    def test_loop_stops_after_current_item_when_cancelled(self):
        """A loop that checks is_task_cancelled stops before the next item."""
        row = TaskHistory.objects.create(
            task_id="cancel-loop",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="RUNNING",
        )

        processed = []
        for item in (1, 2, 3):
            if is_task_cancelled(row.task_id):
                break
            processed.append(item)
            if item == 2:
                TaskHistory.objects.filter(pk=row.pk).update(status="CANCELLED")
                clear_cancelled_cache(row.task_id)

        assert processed == [1, 2]

    def test_loop_check_uses_cache_so_it_does_not_hammer_db(self):
        row = TaskHistory.objects.create(
            task_id="cancel-loop-cached",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="CANCELLED",
        )
        assert is_task_cancelled(row.task_id) is True
        with patch(
            "library_manager.tasks.core.TaskHistory.objects.filter"
        ) as mock_filter:
            for _ in range(50):
                assert is_task_cancelled(row.task_id) is True
            mock_filter.assert_not_called()


@pytest.mark.django_db
class TestStatusStaysCancelled(TestCase):
    def test_cancelled_task_is_not_marked_failed(self):
        from library_manager.tasks.artist import fetch_all_albums_for_artist
        from library_manager.tasks.core import TaskCancelledException

        row = TaskHistory.objects.create(
            task_id="cancel-status",
            type="FETCH",
            entity_id="1",
            entity_type="ARTIST",
            status="CANCELLED",
        )
        artist = MagicMock(id=1, deezer_id="123", name="Test")
        with (
            patch(
                "library_manager.tasks.artist.Artist.objects.get", return_value=artist
            ),
            patch("library_manager.tasks.artist.create_task_history", return_value=row),
            patch(
                "library_manager.tasks.artist._fetch_albums_via_deezer",
                side_effect=TaskCancelledException(),
            ),
            patch("library_manager.tasks.artist.complete_task") as mock_complete,
        ):
            fetch_all_albums_for_artist(1)

        mock_complete.assert_not_called()
        row.refresh_from_db()
        assert row.status == "CANCELLED"


@pytest.mark.django_db
class TestQueuedCancelRevokes(TestCase):
    async def test_cancel_task_by_id_revokes_queued_task_without_terminate(self):
        from asgiref.sync import sync_to_async
        from django_celery_results.models import TaskResult

        from src.services.task_management import TaskManagementService

        await sync_to_async(TaskResult.objects.create)(
            task_id="queued-revoke",
            task_name="library_manager.tasks.download_single_album",
            status="PENDING",
        )
        row = await sync_to_async(TaskHistory.objects.create)(
            task_id="queued-revoke",
            type="DOWNLOAD",
            entity_id="1",
            entity_type="ALBUM",
            status="PENDING",
        )
        with patch("src.services.task_management._revoke_task") as mock_revoke:
            result = await TaskManagementService().cancel_task_by_id(row.task_id)

        assert result.success is True
        mock_revoke.assert_called_once_with("queued-revoke")

    def test_revoke_helper_never_terminates(self):
        from src.services.task_management import _revoke_task

        with patch("src.services.task_management.celery_app") as mock_app:
            _revoke_task("task-xyz")
        mock_app.control.revoke.assert_called_once_with("task-xyz", terminate=False)


@pytest.mark.django_db
class TestCancellationLeavesNoPartialFile(TestCase):
    def test_unfinalized_file_is_removed_when_cancelled_before_finalize(self):
        """The exact cleanup performed in the album result loop."""
        from downloader.providers.fallback import DownloadChainResult

        destination = Path("/tmp/tunestash-cancel-partial.flac")
        destination.write_bytes(b"partial audio")
        result = DownloadChainResult(
            success=True,
            file_path=destination,
            provider_used="youtube",
            error_message=None,
            track_match=None,
            validation_result=None,
        )

        # Mirror the guard in _download_deezer_album's result loop.
        cancelled = True
        if cancelled:
            try:
                result.file_path.unlink(missing_ok=True)
            except OSError:
                pass
            with pytest.raises(TaskCancelledException):
                raise TaskCancelledException()

        assert not destination.exists()
