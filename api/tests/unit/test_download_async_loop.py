"""Unit tests for download functionality focusing on async loop issues.

Tests verify Python 3.13+ compatibility where asyncio.gather() requires a running
event loop in the current thread. The download_song function always runs downloads
in a separate thread with a fresh event loop to work around this.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, Mock, patch

import pytest
from downloader.spotdl_override import (
    DownloadTimeoutError,
    _download_song_sync,
    download_multiple_songs,
    download_song,
)
from spotdl.download.downloader import Downloader
from spotdl.types.song import Song


class TestDownloadAsyncLoop:
    """Test download functionality with different event loop scenarios."""

    @pytest.fixture
    def mock_song(self):
        """Create a mock song for testing."""
        song = Mock(spec=Song)
        song.name = "Test Song"
        song.artists = ["Test Artist"]
        return song

    @pytest.fixture
    def mock_downloader(self):
        """Create a mock downloader with pool_download method."""
        downloader = Mock(spec=Downloader)
        downloader.loop = asyncio.new_event_loop()
        downloader.progress_handler = Mock()
        downloader.progress_handler.set_song_count = Mock()
        # pool_download is an async method
        downloader.pool_download = AsyncMock(return_value=(Mock(), "/fake/path"))
        return downloader

    def test_download_song_with_no_event_loop(self, mock_downloader, mock_song):
        """Test download_song function when no event loop exists in thread."""

        def worker_task():
            # Ensure no event loop exists
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    loop.close()
            except RuntimeError:
                pass  # Good, no loop exists

            # This should not raise an exception
            result = download_song(mock_downloader, mock_song)
            assert result is not None

        thread = threading.Thread(target=worker_task)
        thread.start()
        thread.join()

        # Verify the downloader methods were called
        mock_downloader.progress_handler.set_song_count.assert_called_once_with(1)
        mock_downloader.pool_download.assert_called_once_with(mock_song)

        # Clean up
        mock_downloader.loop.close()

    def test_download_song_with_different_event_loop(self, mock_downloader, mock_song):
        """Test download_song when a different event loop exists in thread.

        The new implementation always creates a fresh loop in the worker thread,
        so the existing loop in the calling thread doesn't matter.
        """

        def worker_task():
            # Create a different event loop
            different_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(different_loop)

            try:
                # This should work - download runs in its own thread with fresh loop
                result = download_song(mock_downloader, mock_song)
                assert result is not None
            finally:
                different_loop.close()

        thread = threading.Thread(target=worker_task)
        thread.start()
        thread.join()

        # Verify pool_download was called
        mock_downloader.pool_download.assert_called_once_with(mock_song)

        # Clean up
        mock_downloader.loop.close()

    def test_download_song_with_closed_event_loop(self, mock_downloader, mock_song):
        """Test download_song when a closed event loop exists in thread."""

        def worker_task():
            # Create and close an event loop
            closed_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(closed_loop)
            closed_loop.close()

            # This should not raise an exception - uses fresh loop in worker thread
            result = download_song(mock_downloader, mock_song)
            assert result is not None

        thread = threading.Thread(target=worker_task)
        thread.start()
        thread.join()

        # Verify pool_download was called
        mock_downloader.pool_download.assert_called_once_with(mock_song)

        # Clean up
        mock_downloader.loop.close()

    def test_download_song_with_running_event_loop(self, mock_downloader, mock_song):
        """Test download_song when called from within a running event loop."""

        async def async_caller():
            # This simulates calling download_song from an async context
            # (e.g., from a FastAPI endpoint or async Celery task)
            result = download_song(mock_downloader, mock_song)
            assert result is not None
            return result

        # Run in a new event loop
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(async_caller())
            assert result is not None
        finally:
            loop.close()

        # Verify pool_download was called
        mock_downloader.pool_download.assert_called_once_with(mock_song)
        mock_downloader.loop.close()

    def test_download_song_timeout(self, mock_downloader, mock_song):
        """Test that download_song raises DownloadTimeoutError on timeout."""

        # Use a fixed sleep that's longer than the patched timeout but still
        # short enough to not block the test for too long.
        # The ThreadPoolExecutor will timeout after 0.1s, but the thread
        # continues running. It will complete in ~0.5s.
        async def blocking_pool_download(song):
            await asyncio.sleep(0.5)
            return (Mock(), "/fake/path")

        mock_downloader.pool_download = blocking_pool_download

        # Patch DOWNLOAD_TIMEOUT_SECONDS to a very small value for testing
        with patch("downloader.spotdl_override.DOWNLOAD_TIMEOUT_SECONDS", 0.1):
            with pytest.raises(DownloadTimeoutError) as exc_info:
                download_song(mock_downloader, mock_song)

            assert "timed out" in str(exc_info.value).lower()
            assert mock_song.name in str(exc_info.value)

        mock_downloader.loop.close()

    def test_multiple_concurrent_downloads(self, mock_song):
        """Test multiple concurrent downloads in different threads."""
        results = []
        threads = []

        def download_task(task_id):
            """Download task for each thread."""
            try:
                # Each thread gets its own downloader
                downloader = Mock(spec=Downloader)
                downloader.loop = asyncio.new_event_loop()
                downloader.progress_handler = Mock()
                downloader.progress_handler.set_song_count = Mock()
                downloader.pool_download = AsyncMock(
                    return_value=(Mock(), f"/fake/path/{task_id}")
                )

                result = download_song(downloader, mock_song)

                results.append(
                    {
                        "task_id": task_id,
                        "success": True,
                        "result": result,
                    }
                )

                downloader.loop.close()

            except Exception as e:
                results.append(
                    {"task_id": task_id, "success": False, "exception": str(e)}
                )

        # Create multiple download threads
        for i in range(5):
            thread = threading.Thread(target=download_task, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all downloads succeeded
        assert len(results) == 5
        successful_results = [r for r in results if r["success"]]
        assert len(successful_results) == 5


class TestDownloadSongSyncHelper:
    """Test the _download_song_sync helper function directly."""

    @pytest.fixture
    def mock_song(self):
        """Create a mock song for testing."""
        song = Mock(spec=Song)
        song.name = "Test Song"
        song.artists = ["Test Artist"]
        return song

    def test_creates_fresh_event_loop(self, mock_song):
        """Test that _download_song_sync creates a fresh event loop."""
        downloader = Mock(spec=Downloader)
        original_loop = asyncio.new_event_loop()
        downloader.loop = original_loop
        downloader.progress_handler = Mock()
        downloader.progress_handler.set_song_count = Mock()
        downloader.pool_download = AsyncMock(return_value=(Mock(), "/fake/path"))

        # Run in a thread (simulating ThreadPoolExecutor behavior)
        def worker():
            result = _download_song_sync(downloader, mock_song)
            assert result is not None

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        # Verify downloader's loop was restored
        assert downloader.loop == original_loop
        original_loop.close()

    def test_restores_original_loop_on_exception(self, mock_song):
        """Test that original loop is restored even if download fails."""
        downloader = Mock(spec=Downloader)
        original_loop = asyncio.new_event_loop()
        downloader.loop = original_loop
        downloader.progress_handler = Mock()
        downloader.progress_handler.set_song_count = Mock()

        # Make pool_download raise an exception
        async def failing_download(song):
            raise RuntimeError("Download failed")

        downloader.pool_download = failing_download

        def worker():
            try:
                _download_song_sync(downloader, mock_song)
            except RuntimeError:
                pass  # Expected

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        # Verify downloader's loop was restored
        assert downloader.loop == original_loop
        original_loop.close()


class TestBatchDownload:
    """Test batch download functionality."""

    @pytest.fixture
    def mock_songs(self):
        """Create multiple mock songs for testing."""
        songs = []
        for i in range(3):
            song = Mock(spec=Song)
            song.name = f"Test Song {i}"
            song.artists = [f"Test Artist {i}"]
            songs.append(song)
        return songs

    @pytest.fixture
    def mock_downloader(self):
        """Create a mock downloader with pool_download method."""
        downloader = Mock(spec=Downloader)
        downloader.loop = asyncio.new_event_loop()
        downloader.progress_handler = Mock()
        downloader.progress_handler.set_song_count = Mock()
        # pool_download is an async method that returns (song, path) tuple
        downloader.pool_download = AsyncMock(
            side_effect=lambda song: (song, f"/fake/path/{song.name}")
        )
        return downloader

    def test_download_multiple_songs_basic(self, mock_downloader, mock_songs):
        """Test basic batch download functionality."""

        def worker_task():
            result = download_multiple_songs(mock_downloader, mock_songs)
            assert len(result) == 3
            # Each result should be a (song, path) tuple
            for song, path in result:
                assert song in mock_songs
                assert path is not None

        thread = threading.Thread(target=worker_task)
        thread.start()
        thread.join()

        # Verify pool_download was called for each song
        assert mock_downloader.pool_download.call_count == 3
        mock_downloader.progress_handler.set_song_count.assert_called_with(3)

        mock_downloader.loop.close()

    def test_download_multiple_songs_empty_list(self, mock_downloader):
        """Test batch download with empty list returns empty list."""
        result = download_multiple_songs(mock_downloader, [])
        assert result == []
        mock_downloader.loop.close()

    def test_download_multiple_songs_with_failures(self, mock_downloader, mock_songs):
        """Test batch download handles individual song failures gracefully."""

        async def partial_failure(song):
            if "Song 1" in song.name:
                raise Exception("Download failed for song 1")
            return (song, f"/fake/path/{song.name}")

        mock_downloader.pool_download = partial_failure

        def worker_task():
            result = download_multiple_songs(mock_downloader, mock_songs)
            assert len(result) == 3
            # Song 1 should have None path
            for song, path in result:
                if "Song 1" in song.name:
                    assert path is None
                else:
                    assert path is not None

        thread = threading.Thread(target=worker_task)
        thread.start()
        thread.join()

        mock_downloader.loop.close()

    def test_download_multiple_songs_timeout(self, mock_downloader, mock_songs):
        """Test that batch download raises DownloadTimeoutError on timeout."""

        # Sleep longer than the patched timeout (0.3s for 3 songs) but short
        # enough to not block the test. The thread will finish in ~0.5s.
        async def slow_download(song):
            await asyncio.sleep(0.5)
            return (song, f"/fake/path/{song.name}")

        mock_downloader.pool_download = slow_download

        # Patch timeout to small value for testing
        with (
            patch("downloader.spotdl_override.BATCH_TIMEOUT_PER_SONG_SECONDS", 0.1),
            patch("downloader.spotdl_override.DOWNLOAD_TIMEOUT_SECONDS", 0.1),
        ):
            with pytest.raises(DownloadTimeoutError) as exc_info:
                download_multiple_songs(mock_downloader, mock_songs)

            assert "timed out" in str(exc_info.value).lower()
            assert "3 songs" in str(exc_info.value)

        mock_downloader.loop.close()

    def test_download_multiple_songs_with_running_event_loop(
        self, mock_downloader, mock_songs
    ):
        """Test batch download works when called from async context."""

        async def async_caller():
            result = download_multiple_songs(mock_downloader, mock_songs)
            assert len(result) == 3
            return result

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(async_caller())
            assert result is not None
        finally:
            loop.close()

        mock_downloader.pool_download.assert_called()
        mock_downloader.loop.close()

    def test_download_multiple_songs_restores_loop_on_exception(
        self, mock_downloader, mock_songs
    ):
        """Test that original loop is restored even if batch fails."""
        original_loop = mock_downloader.loop

        async def all_fail(song):
            raise RuntimeError("All downloads fail")

        mock_downloader.pool_download = all_fail

        def worker():
            # Even with failures, should not raise (failures are converted to None paths)
            result = download_multiple_songs(mock_downloader, mock_songs)
            # All should have None paths
            for song, path in result:
                assert path is None

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        # Loop should be restored
        assert mock_downloader.loop == original_loop
        original_loop.close()
