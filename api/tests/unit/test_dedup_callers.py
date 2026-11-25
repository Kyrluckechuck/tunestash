"""Every converted task-enqueue caller must skip a second enqueue for the
same entity while the first claim is still active."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

import pytest

from library_manager.helpers import (
    enqueue_apply_metadata_update,
    enqueue_download_album_by_deezer_id,
    enqueue_download_album_by_spotify_id,
    enqueue_download_deezer_track,
    enqueue_download_single_album,
    enqueue_download_track_by_spotify_gid,
    enqueue_fetch_all_albums_for_artist,
    enqueue_map_external_list_tracks,
    enqueue_sync_deezer_playlist,
)
from library_manager.models import TaskHistory


@pytest.mark.django_db
class TestConvertedCallersDedupe(TestCase):
    def _assert_second_enqueue_skipped(self, enqueue, entity, task_path):
        with patch(task_path) as task:
            task.apply_async = MagicMock()
            assert enqueue(entity) is True
            assert enqueue(entity) is False
            assert task.apply_async.call_count == 1

    def test_download_album_by_spotify_id(self):
        self._assert_second_enqueue_skipped(
            enqueue_download_album_by_spotify_id,
            "spotify-album-123",
            "library_manager.tasks.download_album_by_spotify_id",
        )
        assert TaskHistory.objects.filter(
            entity_type="ALBUM", entity_id="spotify-album-123", status="PENDING"
        ).exists()

    def test_download_single_album(self):
        self._assert_second_enqueue_skipped(
            enqueue_download_single_album,
            42,
            "library_manager.tasks.download_single_album",
        )
        assert TaskHistory.objects.filter(
            entity_type="ALBUM", entity_id="42", status="PENDING"
        ).exists()

    def test_download_album_by_deezer_id(self):
        self._assert_second_enqueue_skipped(
            enqueue_download_album_by_deezer_id,
            77,
            "library_manager.tasks.download_album_by_deezer_id",
        )
        assert TaskHistory.objects.filter(
            entity_type="ALBUM", entity_id="77", status="PENDING"
        ).exists()

    def test_download_deezer_track(self):
        self._assert_second_enqueue_skipped(
            enqueue_download_deezer_track,
            11,
            "library_manager.tasks.download_deezer_track",
        )
        assert TaskHistory.objects.filter(
            entity_type="TRACK", entity_id="11", status="PENDING"
        ).exists()

    def test_download_track_by_spotify_gid(self):
        self._assert_second_enqueue_skipped(
            enqueue_download_track_by_spotify_gid,
            "track-gid-456",
            "library_manager.tasks.download_track_by_spotify_gid",
        )
        assert TaskHistory.objects.filter(
            entity_type="TRACK", entity_id="track-gid-456", status="PENDING"
        ).exists()

    def test_apply_metadata_update(self):
        self._assert_second_enqueue_skipped(
            enqueue_apply_metadata_update,
            5,
            "library_manager.tasks.apply_metadata_update",
        )
        assert TaskHistory.objects.filter(
            entity_type="METADATA_UPDATE", entity_id="5", status="PENDING"
        ).exists()

    def test_map_external_list_tracks(self):
        self._assert_second_enqueue_skipped(
            enqueue_map_external_list_tracks,
            9,
            "library_manager.tasks.map_external_list_tracks",
        )
        assert TaskHistory.objects.filter(
            entity_type="PLAYLIST", entity_id="9", status="PENDING"
        ).exists()

    def test_sync_deezer_playlist(self):
        self._assert_second_enqueue_skipped(
            enqueue_sync_deezer_playlist,
            13,
            "library_manager.tasks.sync_deezer_playlist",
        )
        assert TaskHistory.objects.filter(
            entity_type="PLAYLIST", entity_id="13", status="PENDING"
        ).exists()

    def test_fetch_all_albums_for_artist(self):
        self._assert_second_enqueue_skipped(
            enqueue_fetch_all_albums_for_artist,
            21,
            "library_manager.tasks.fetch_all_albums_for_artist",
        )
        assert TaskHistory.objects.filter(
            entity_type="ARTIST", entity_id="21", status="PENDING"
        ).exists()

    def test_enqueue_deduped_forwards_queue_and_countdown(self):
        from library_manager.helpers import enqueue_deduped

        task = MagicMock()
        assert (
            enqueue_deduped(
                task,
                task_id="queue-countdown-task",
                args=[1],
                queue="queuetip-downloads",
                countdown=30,
            )
            is True
        )
        kwargs = task.apply_async.call_args.kwargs
        assert kwargs["queue"] == "queuetip-downloads"
        assert kwargs["countdown"] == 30
