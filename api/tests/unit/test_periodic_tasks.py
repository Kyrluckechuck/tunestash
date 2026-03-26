"""
Tests for periodic Celery tasks in library_manager.tasks
"""

from unittest.mock import patch

from django.test import TestCase

from library_manager.models import (
    Album,
    Artist,
    PlaylistStatus,
    TrackedPlaylist,
    get_album_groups_to_ignore,
    get_album_types_to_download,
)


class TestSyncTrackedPlaylists(TestCase):
    """Test sync_tracked_playlists periodic task."""

    def setUp(self):
        """Set up test playlists with different statuses."""
        # Create active playlists (should be synced)
        self.active_playlist1 = TrackedPlaylist.objects.create(
            name="Active Playlist 1",
            url="spotify:playlist:active001",
            status=PlaylistStatus.ACTIVE,
        )
        self.active_playlist2 = TrackedPlaylist.objects.create(
            name="Active Playlist 2",
            url="spotify:playlist:active002",
            status=PlaylistStatus.ACTIVE,
        )

        # Create restricted playlist (should NOT be synced)
        self.restricted_playlist = TrackedPlaylist.objects.create(
            name="Daily Mix - API Restricted",
            url="spotify:playlist:restricted01",
            status=PlaylistStatus.SPOTIFY_API_RESTRICTED,
            status_message="Spotify-generated playlist cannot be accessed via API",
        )

        # Create not found playlist (should NOT be synced)
        self.not_found_playlist = TrackedPlaylist.objects.create(
            name="Deleted Playlist",
            url="spotify:playlist:notfound001",
            status=PlaylistStatus.NOT_FOUND,
            status_message="Playlist not found - deleted or private",
        )

        # Create disabled by user playlist (should NOT be synced)
        self.disabled_playlist = TrackedPlaylist.objects.create(
            name="Disabled Playlist",
            url="spotify:playlist:disabled001",
            status=PlaylistStatus.DISABLED_BY_USER,
        )

    @patch("library_manager.tasks.periodic.helpers")
    def test_sync_tracked_playlists_only_syncs_active_playlists(self, mock_helpers):
        """Test that sync_tracked_playlists only queues active playlists."""
        from library_manager.tasks import sync_tracked_playlists

        # Run the periodic task
        sync_tracked_playlists()

        # Verify enqueue_playlists was called
        assert mock_helpers.enqueue_playlists.call_count == 1

        # Get the playlists that were passed to enqueue_playlists
        call_args = mock_helpers.enqueue_playlists.call_args
        synced_playlists = call_args[0][0]

        # Should only include active playlists
        synced_urls = [p.url for p in synced_playlists]
        assert self.active_playlist1.url in synced_urls
        assert self.active_playlist2.url in synced_urls

        # Should NOT include restricted, not found, or disabled playlists
        assert self.restricted_playlist.url not in synced_urls
        assert self.not_found_playlist.url not in synced_urls
        assert self.disabled_playlist.url not in synced_urls

    @patch("library_manager.tasks.periodic.helpers")
    def test_sync_tracked_playlists_handles_no_active_playlists(self, mock_helpers):
        """Test that task handles case when no active playlists exist."""
        from library_manager.tasks import sync_tracked_playlists

        # Set all playlists to non-active status
        TrackedPlaylist.objects.filter(status=PlaylistStatus.ACTIVE).update(
            status=PlaylistStatus.DISABLED_BY_USER
        )

        # Run the periodic task
        sync_tracked_playlists()

        # Should NOT call enqueue_playlists when no playlists need syncing
        assert mock_helpers.enqueue_playlists.call_count == 0


class TestPeriodicTasks(TestCase):
    """Test periodic Celery Beat tasks."""

    def setUp(self):
        """Set up test data."""
        # Create tracked artist with missing albums
        self.tracked_artist1 = Artist.objects.create(
            name="Tracked Artist 1", gid="tracked_123", tracked=True
        )
        self.tracked_artist2 = Artist.objects.create(
            name="Tracked Artist 2", gid="tracked_456", tracked=True
        )

        # Create untracked artist (should be ignored)
        self.untracked_artist = Artist.objects.create(
            name="Untracked Artist", gid="untracked_789", tracked=False
        )

        # Create albums for tracked artists
        # Missing albums (wanted=True, downloaded=False)
        self.missing_album1 = Album.objects.create(
            name="Missing Album 1",
            spotify_gid="album_001",
            spotify_uri="spotify:album:001",
            artist=self.tracked_artist1,
            wanted=True,
            downloaded=False,
            album_type="album",
            album_group="album",
            total_tracks=10,
        )
        self.missing_album2 = Album.objects.create(
            name="Missing Album 2",
            spotify_gid="album_002",
            spotify_uri="spotify:album:002",
            artist=self.tracked_artist2,
            wanted=True,
            downloaded=False,
            album_type="single",
            album_group="single",
            total_tracks=2,
        )

        # Already downloaded album (should be skipped)
        self.downloaded_album = Album.objects.create(
            name="Downloaded Album",
            spotify_gid="album_003",
            spotify_uri="spotify:album:003",
            artist=self.tracked_artist1,
            wanted=True,
            downloaded=True,
            album_type="album",
            album_group="album",
            total_tracks=12,
        )

        # Unwanted album (should be skipped)
        self.unwanted_album = Album.objects.create(
            name="Unwanted Album",
            spotify_gid="album_004",
            spotify_uri="spotify:album:004",
            artist=self.tracked_artist1,
            wanted=False,
            downloaded=False,
            album_type="album",
            album_group="album",
            total_tracks=8,
        )

        # "Appears on" album (should be excluded by album_group filter)
        self.appears_on_album = Album.objects.create(
            name="Appears On Album",
            spotify_gid="album_005",
            spotify_uri="spotify:album:005",
            artist=self.tracked_artist1,
            wanted=True,
            downloaded=False,
            album_type="compilation",
            album_group="appears_on",
            total_tracks=20,
        )

        # Album from untracked artist (should be skipped)
        self.untracked_album = Album.objects.create(
            name="Untracked Artist Album",
            spotify_gid="album_006",
            spotify_uri="spotify:album:006",
            artist=self.untracked_artist,
            wanted=True,
            downloaded=False,
            album_type="album",
            album_group="album",
            total_tracks=10,
        )

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_for_tracked_artists(self, mock_download):
        """Test that periodic task queues correct albums from tracked artists."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Run the periodic task
        queue_missing_albums_for_tracked_artists()

        # Verify download_single_album.delay() was called for correct albums only
        # Should queue: missing_album1, missing_album2
        # Should skip: downloaded_album (already downloaded),
        #              unwanted_album (wanted=False),
        #              appears_on_album (album_group excluded),
        #              untracked_album (artist not tracked)
        assert mock_download.delay.call_count == 2

        # Extract the album IDs that were queued
        queued_album_ids = [call[0][0] for call in mock_download.delay.call_args_list]

        # Verify correct albums were queued
        assert self.missing_album1.id in queued_album_ids
        assert self.missing_album2.id in queued_album_ids

        # Verify incorrect albums were NOT queued
        assert self.downloaded_album.id not in queued_album_ids
        assert self.unwanted_album.id not in queued_album_ids
        assert self.appears_on_album.id not in queued_album_ids
        assert self.untracked_album.id not in queued_album_ids

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_respects_50_limit(self, mock_download):
        """Test that periodic task respects the 50 album limit per run."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Create 100 missing albums to test the limit
        for i in range(100):
            Album.objects.create(
                name=f"Test Album {i}",
                spotify_gid=f"album_{i:04d}",
                spotify_uri=f"spotify:album:{i:04d}",
                artist=self.tracked_artist1,
                wanted=True,
                downloaded=False,
                album_type="album",
                album_group="album",
                total_tracks=10,
            )

        # Run the periodic task
        queue_missing_albums_for_tracked_artists()

        # Should only queue 50 albums (not all 102 = 100 + 2 from setUp)
        assert mock_download.delay.call_count == 50

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_handles_no_albums(self, mock_download):
        """Test that periodic task handles case when no albums need downloading."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Mark all albums as downloaded or unwanted
        Album.objects.filter(
            artist__tracked=True, wanted=True, downloaded=False
        ).update(downloaded=True)

        # Run the periodic task
        queue_missing_albums_for_tracked_artists()

        # Should not queue any albums
        assert mock_download.delay.call_count == 0

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_applies_album_type_filter(self, mock_download):
        """Test that periodic task only queues albums matching get_album_types_to_download()."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Create album with excluded type (assuming 'ep' is not in get_album_types_to_download())
        excluded_type_album = Album.objects.create(
            name="EP Album",
            spotify_gid="album_ep",
            spotify_uri="spotify:album:ep",
            artist=self.tracked_artist1,
            wanted=True,
            downloaded=False,
            album_type="ep",  # Assuming 'ep' is not in get_album_types_to_download()
            album_group="album",
            total_tracks=6,
        )

        # Run the periodic task
        queue_missing_albums_for_tracked_artists()

        # Verify EP was not queued if 'ep' not in get_album_types_to_download()
        queued_album_ids = [call[0][0] for call in mock_download.delay.call_args_list]

        if "ep" not in get_album_types_to_download():
            assert excluded_type_album.id not in queued_album_ids

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_excludes_album_groups(self, mock_download):
        """Test that periodic task excludes albums from get_album_groups_to_ignore()."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Run the periodic task
        queue_missing_albums_for_tracked_artists()

        # Verify appears_on album was excluded
        queued_album_ids = [call[0][0] for call in mock_download.delay.call_args_list]
        assert self.appears_on_album.id not in queued_album_ids

        # Verify the constant is configured as expected
        assert "appears_on" in get_album_groups_to_ignore()

    @patch("library_manager.tasks.periodic.download_single_album")
    def test_queue_missing_albums_handles_task_queue_failure(self, mock_download):
        """Test that periodic task continues even if individual album queuing fails."""
        from library_manager.tasks import queue_missing_albums_for_tracked_artists

        # Make delay() raise an exception on first call, succeed on second
        mock_download.delay.side_effect = [Exception("Queue error"), None]

        # Run the periodic task - should not crash
        queue_missing_albums_for_tracked_artists()

        # Should have attempted to queue both albums despite first failure
        assert mock_download.delay.call_count == 2


class TestRetryFailedSongsTask(TestCase):
    """Test retry_failed_songs periodic task."""

    def setUp(self):
        """Set up test data with failed songs."""
        from library_manager.models import Song

        # Create test artist
        self.artist = Artist.objects.create(
            name="Test Artist", gid="artist_test", tracked=True
        )

        # Create songs with various failure states
        # Song with 1 failure (should be retried, high priority)
        self.song_failed_once = Song.objects.create(
            name="Failed Once",
            gid="song_001",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
        )

        # Song with 5 failures (should be retried, medium priority)
        self.song_failed_five = Song.objects.create(
            name="Failed Five Times",
            gid="song_005",
            primary_artist=self.artist,
            failed_count=5,
            downloaded=False,
        )

        # Song with 10 failures (should be retried, low priority - at threshold)
        self.song_failed_ten = Song.objects.create(
            name="Failed Ten Times",
            gid="song_010",
            primary_artist=self.artist,
            failed_count=10,
            downloaded=False,
        )

        # Song with 11 failures (should be SKIPPED - over threshold)
        self.song_failed_eleven = Song.objects.create(
            name="Failed Eleven Times",
            gid="song_011",
            primary_artist=self.artist,
            failed_count=11,
            downloaded=False,
        )

        # Song with 0 failures (should be SKIPPED - not failed yet)
        self.song_not_failed = Song.objects.create(
            name="Not Failed",
            gid="song_000",
            primary_artist=self.artist,
            failed_count=0,
            downloaded=False,
        )

        # Already downloaded song with failures (should be SKIPPED)
        self.song_downloaded = Song.objects.create(
            name="Downloaded Despite Failures",
            gid="song_dl",
            primary_artist=self.artist,
            failed_count=3,
            downloaded=True,
        )

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_basic(self, mock_fallback, mock_require_download):
        """Test that retry_failed_songs attempts to download failed songs."""
        from library_manager.tasks import retry_failed_songs

        mock_fallback.return_value = (0, 0)

        # Run the periodic task
        retry_failed_songs()

        # Verify fallback downloader was called
        assert mock_fallback.call_count == 1

        # Extract the Song objects that were passed to download
        downloaded_songs = mock_fallback.call_args[0][0]
        downloaded_ids = {s.gid for s in downloaded_songs}

        # Should include songs with 1, 5, and 10 failures
        assert self.song_failed_once.gid in downloaded_ids
        assert self.song_failed_five.gid in downloaded_ids
        assert self.song_failed_ten.gid in downloaded_ids

        # Should NOT include songs with 11+ failures, 0 failures, or already downloaded
        assert self.song_failed_eleven.gid not in downloaded_ids
        assert self.song_not_failed.gid not in downloaded_ids
        assert self.song_downloaded.gid not in downloaded_ids

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_priority_order(
        self, mock_fallback, mock_require_download
    ):
        """Test that songs with fewer failures are prioritized."""
        import time

        from library_manager.models import Song
        from library_manager.tasks import retry_failed_songs

        mock_fallback.return_value = (0, 0)

        for i in range(3):
            Song.objects.create(
                name=f"Priority Test {i}",
                gid=f"priority{i:06d}",  # Unique 22-char GID
                primary_artist=self.artist,
                failed_count=i + 1,  # 1, 2, 3 failures
                downloaded=False,
            )
            time.sleep(0.01)  # Ensure different created_at timestamps

        # Run the task
        retry_failed_songs()

        # Extract songs in the order they were passed
        downloaded_songs = mock_fallback.call_args[0][0]

        # Songs should be ordered by failed_count ASC
        # Find the position of song_failed_five (failed_count=5)
        gids = [s.gid for s in downloaded_songs]
        if self.song_failed_five.gid in gids:
            pos_five = gids.index(self.song_failed_five.gid)
            # All songs before this position should have fewer failures
            assert pos_five >= 0

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_respects_100_limit(
        self, mock_fallback, mock_require_download
    ):
        """Test that retry only processes 100 songs per run."""
        from library_manager.models import Song
        from library_manager.tasks import retry_failed_songs

        mock_fallback.return_value = (0, 0)

        # Create 150 failed songs
        for i in range(150):
            Song.objects.create(
                name=f"Failed Song {i}",
                gid=f"failsong{i:016d}",  # Unique 22-char GID
                primary_artist=self.artist,
                failed_count=1,
                downloaded=False,
            )

        # Run the task
        retry_failed_songs()

        # Should only process 100 songs
        downloaded_songs = mock_fallback.call_args[0][0]

        # Should be exactly 100 songs (plus the 3 from setUp = 103+ total eligible)
        # But limit is 100
        assert len(downloaded_songs) == 100

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_handles_no_songs(
        self, mock_fallback, mock_require_download
    ):
        """Test that task handles case when no songs need retry."""
        from library_manager.models import Song
        from library_manager.tasks import retry_failed_songs

        # Mark all failed songs as downloaded or over threshold
        Song.objects.filter(failed_count__gt=0).update(downloaded=True)

        # Run the task
        retry_failed_songs()

        # Should not call fallback downloader
        assert mock_fallback.call_count == 0

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_failed_songs_skips_high_failure_count(
        self, mock_fallback, mock_require_download
    ):
        """Test that songs with >10 failures are not retried."""
        from library_manager.models import Song
        from library_manager.tasks import retry_failed_songs

        mock_fallback.return_value = (0, 0)

        # Create songs with 11-20 failures
        for i in range(11, 21):
            Song.objects.create(
                name=f"High Failure {i}",
                gid=f"highfail{i:015d}",  # Unique 22-char GID
                primary_artist=self.artist,
                failed_count=i,
                downloaded=False,
            )

        # Run the task
        retry_failed_songs()

        # Extract downloaded song GIDs
        downloaded_songs = mock_fallback.call_args[0][0]
        downloaded_gids = {s.gid for s in downloaded_songs}

        # Verify none of the high-failure songs were included
        for i in range(11, 21):
            gid = f"highfail{i:015d}"
            assert gid not in downloaded_gids


class TestBackfillAlbumMetadata(TestCase):
    """Test backfill_album_metadata function for albums with type=None (Deezer-based)."""

    def setUp(self):
        """Set up test data with albums missing metadata."""
        # Create tracked artist
        self.tracked_artist = Artist.objects.create(
            name="Tracked Artist", gid="tracked_bf_123", tracked=True
        )

        # Create untracked artist
        self.untracked_artist = Artist.objects.create(
            name="Untracked Artist", gid="untracked_bf_456", tracked=False
        )

        # Album missing metadata with deezer_id (should be backfilled)
        self.album_no_type = Album.objects.create(
            name="Album Missing Type",
            spotify_gid="bf_album_001",
            spotify_uri="spotify:album:bf001",
            artist=self.tracked_artist,
            wanted=True,
            downloaded=False,
            album_type=None,
            album_group=None,
            total_tracks=10,
            deezer_id=11111,
        )

        # Album with metadata (should be skipped)
        self.album_with_type = Album.objects.create(
            name="Album With Type",
            spotify_gid="bf_album_002",
            spotify_uri="spotify:album:bf002",
            artist=self.tracked_artist,
            wanted=True,
            downloaded=False,
            album_type="album",
            album_group="album",
            total_tracks=12,
            deezer_id=22222,
        )

        # Album from untracked artist (should be skipped)
        self.untracked_album = Album.objects.create(
            name="Untracked Artist Album",
            spotify_gid="bf_album_003",
            spotify_uri="spotify:album:bf003",
            artist=self.untracked_artist,
            wanted=True,
            downloaded=False,
            album_type=None,
            album_group=None,
            total_tracks=8,
            deezer_id=33333,
        )

        # Already downloaded album missing metadata (should be skipped)
        self.downloaded_album = Album.objects.create(
            name="Downloaded Album",
            spotify_gid="bf_album_004",
            spotify_uri="spotify:album:bf004",
            artist=self.tracked_artist,
            wanted=True,
            downloaded=True,
            album_type=None,
            album_group=None,
            total_tracks=6,
            deezer_id=44444,
        )

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_updates_album_metadata(self, mock_get_album):
        """Test that backfill fetches and updates album metadata via Deezer."""
        from library_manager.tasks.periodic import backfill_album_metadata
        from src.providers.metadata_base import AlbumResult

        mock_get_album.return_value = AlbumResult(
            name="Album Missing Type",
            artist_name="Tracked Artist",
            album_type="compilation",
            album_group="appears_on",
        )

        updated = backfill_album_metadata(limit=10)

        assert updated == 1

        self.album_no_type.refresh_from_db()
        assert self.album_no_type.album_type == "compilation"
        assert self.album_no_type.album_group == "appears_on"

        self.album_with_type.refresh_from_db()
        assert self.album_with_type.album_type == "album"

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_skips_untracked_artists(self, mock_get_album):
        """Test that backfill only processes albums from tracked artists."""
        from library_manager.tasks.periodic import backfill_album_metadata
        from src.providers.metadata_base import AlbumResult

        mock_get_album.return_value = AlbumResult(
            name="Album",
            artist_name="Artist",
            album_type="album",
            album_group="album",
        )

        backfill_album_metadata(limit=10)

        self.untracked_album.refresh_from_db()
        assert self.untracked_album.album_type is None

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_respects_limit(self, mock_get_album):
        """Test that backfill respects the limit parameter."""
        from library_manager.tasks.periodic import backfill_album_metadata
        from src.providers.metadata_base import AlbumResult

        for i in range(5):
            Album.objects.create(
                name=f"Bulk Album {i}",
                spotify_gid=f"bf_bulk_{i:04d}",
                spotify_uri=f"spotify:album:bf_bulk_{i:04d}",
                artist=self.tracked_artist,
                wanted=True,
                downloaded=False,
                album_type=None,
                album_group=None,
                total_tracks=10,
                deezer_id=50000 + i,
            )

        mock_get_album.return_value = AlbumResult(
            name="Album",
            artist_name="Artist",
            album_type="album",
            album_group="album",
        )

        updated = backfill_album_metadata(limit=3)

        assert updated == 3

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_handles_api_failure(self, mock_get_album):
        """Test that backfill continues after API failures."""
        from library_manager.tasks.periodic import backfill_album_metadata
        from src.providers.metadata_base import AlbumResult

        album2 = Album.objects.create(
            name="Second Album",
            spotify_gid="bf_second_001",
            spotify_uri="spotify:album:bf_second_001",
            artist=self.tracked_artist,
            wanted=True,
            downloaded=False,
            album_type=None,
            album_group=None,
            total_tracks=10,
            deezer_id=55555,
        )

        mock_get_album.side_effect = [
            Exception("API Error"),
            AlbumResult(
                name="Second Album",
                artist_name="Artist",
                album_type="single",
                album_group="single",
            ),
        ]

        updated = backfill_album_metadata(limit=10)

        assert updated == 1

        album2.refresh_from_db()
        assert album2.album_type == "single"

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_returns_zero_when_no_albums(self, mock_get_album):
        """Test that backfill returns 0 when no albums need metadata."""
        from library_manager.tasks.periodic import backfill_album_metadata

        self.album_no_type.delete()

        updated = backfill_album_metadata(limit=10)

        assert updated == 0
        mock_get_album.assert_not_called()

    @patch("src.providers.deezer.DeezerMetadataProvider.get_album")
    def test_backfill_skips_albums_without_deezer_id(self, mock_get_album):
        """Test that backfill only processes albums that have a deezer_id."""
        from library_manager.tasks.periodic import backfill_album_metadata
        from src.providers.metadata_base import AlbumResult

        # Remove deezer_id from the album that needs backfill
        self.album_no_type.deezer_id = None
        self.album_no_type.save(update_fields=["deezer_id"])

        mock_get_album.return_value = AlbumResult(
            name="Album",
            artist_name="Artist",
            album_type="album",
            album_group="album",
        )

        updated = backfill_album_metadata(limit=10)

        assert updated == 0
        mock_get_album.assert_not_called()


class TestSongFailureBackoff(TestCase):
    """Test exponential backoff for failed song retries."""

    def setUp(self):
        """Set up test data."""
        from library_manager.models import FailureReason, Song

        self.artist = Artist.objects.create(
            name="Test Artist", gid="artist_backoff", tracked=True
        )

        # Song with temporary error - should have short backoff
        self.temp_error_song = Song.objects.create(
            name="Temporary Error Song",
            gid="song_temp_err",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
            failure_reason=FailureReason.TEMPORARY_ERROR,
        )

        # Song not found on Spotify - should have medium backoff
        self.spotify_404_song = Song.objects.create(
            name="Spotify 404 Song",
            gid="song_sp_404",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
            failure_reason=FailureReason.SPOTIFY_NOT_FOUND,
        )

        # Song unavailable on both platforms - should have long backoff
        self.both_unavailable_song = Song.objects.create(
            name="Both Unavailable Song",
            gid="song_both",
            primary_artist=self.artist,
            failed_count=3,
            downloaded=False,
            failure_reason=FailureReason.BOTH_UNAVAILABLE,
        )

    def test_backoff_days_temporary_error(self):
        """Test exponential backoff for temporary errors."""
        from library_manager.models import FailureReason, Song

        song = Song.objects.create(
            name="Temp Test",
            gid="temp_backoff_test",
            primary_artist=self.artist,
            failed_count=0,
            downloaded=False,
            failure_reason=None,
        )

        # First failure: 1 day backoff
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        assert song.get_retry_backoff_days() == 1

        # Second failure: 2 days backoff
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        assert song.get_retry_backoff_days() == 2

        # Third failure: 4 days backoff
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        assert song.get_retry_backoff_days() == 4

        # Fourth failure: 7 days backoff (capped)
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        assert song.get_retry_backoff_days() == 7

        # Fifth failure: still 7 days (capped)
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        assert song.get_retry_backoff_days() == 7

    def test_backoff_days_spotify_not_found(self):
        """Test longer backoff for Spotify 404 errors."""
        from library_manager.models import FailureReason, Song

        song = Song.objects.create(
            name="Spotify 404 Test",
            gid="sp404_backoff_test",
            primary_artist=self.artist,
            failed_count=0,
            downloaded=False,
            failure_reason=None,
        )

        # First failure: 2 days backoff
        song.increment_failed_count(FailureReason.SPOTIFY_NOT_FOUND)
        assert song.get_retry_backoff_days() == 2

        # Second failure: 4 days backoff
        song.increment_failed_count(FailureReason.SPOTIFY_NOT_FOUND)
        assert song.get_retry_backoff_days() == 4

        # Third failure: upgrades to BOTH_UNAVAILABLE with 30 day backoff
        song.increment_failed_count(FailureReason.SPOTIFY_NOT_FOUND)
        assert song.failure_reason == FailureReason.BOTH_UNAVAILABLE
        assert song.get_retry_backoff_days() == 30

    def test_backoff_days_both_unavailable(self):
        """Test flat 30-day backoff for both unavailable."""
        assert self.both_unavailable_song.get_retry_backoff_days() == 30

    def test_is_ready_for_retry_no_failures(self):
        """Test that songs with no failures are always ready."""
        from library_manager.models import Song

        song = Song.objects.create(
            name="No Failures",
            gid="no_fail_test",
            primary_artist=self.artist,
            failed_count=0,
            downloaded=False,
        )
        assert song.is_ready_for_retry() is True

    def test_is_ready_for_retry_with_backoff(self):
        """Test that songs in backoff period are not ready."""
        from datetime import timedelta

        from django.utils import timezone

        from library_manager.models import FailureReason, Song

        song = Song.objects.create(
            name="Backoff Test",
            gid="backoff_ready_test",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=timezone.now(),  # Just failed
        )

        # Just failed - should NOT be ready (backoff is 1 day)
        assert song.is_ready_for_retry() is False

        # Simulate time passing - 2 days later
        song.last_failed_at = timezone.now() - timedelta(days=2)
        song.save()

        # Should now be ready
        assert song.is_ready_for_retry() is True

    def test_is_ready_for_retry_both_unavailable(self):
        """Test 30-day backoff for songs unavailable on both platforms."""
        from datetime import timedelta

        from django.utils import timezone

        from library_manager.models import FailureReason, Song

        song = Song.objects.create(
            name="Both Unavailable Test",
            gid="both_unavail_test",
            primary_artist=self.artist,
            failed_count=5,
            downloaded=False,
            failure_reason=FailureReason.BOTH_UNAVAILABLE,
            last_failed_at=timezone.now() - timedelta(days=15),  # 15 days ago
        )

        # 15 days into 30-day backoff - should NOT be ready
        assert song.is_ready_for_retry() is False

        # 31 days later - should be ready
        song.last_failed_at = timezone.now() - timedelta(days=31)
        song.save()
        assert song.is_ready_for_retry() is True

    @patch("library_manager.tasks.maintenance.require_download_capability")
    @patch("library_manager.tasks.maintenance._download_deezer_songs_via_fallback")
    def test_retry_task_respects_backoff(self, mock_fallback, mock_require_download):
        """Test that retry task skips songs in backoff period."""
        from datetime import timedelta

        from django.utils import timezone

        from library_manager.models import FailureReason, Song
        from library_manager.tasks import retry_failed_songs

        mock_fallback.return_value = (0, 0)

        # Create a song that just failed (in backoff)
        recent_fail = Song.objects.create(
            name="Recent Failure",
            gid="recent_fail_test",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=timezone.now(),  # Just failed
        )

        # Create a song that failed long ago (past backoff)
        old_fail = Song.objects.create(
            name="Old Failure",
            gid="old_fail_test000",
            primary_artist=self.artist,
            failed_count=1,
            downloaded=False,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at=timezone.now() - timedelta(days=7),  # 7 days ago
        )

        # Run the retry task
        retry_failed_songs()

        # Should only include the old failure (past backoff)
        downloaded_songs = mock_fallback.call_args[0][0]
        downloaded_gids = {s.gid for s in downloaded_songs}

        assert old_fail.gid in downloaded_gids
        assert recent_fail.gid not in downloaded_gids

    def test_increment_failed_count_sets_timestamp(self):
        """Test that increment_failed_count sets last_failed_at."""
        from django.utils import timezone

        from library_manager.models import FailureReason, Song

        song = Song.objects.create(
            name="Timestamp Test",
            gid="timestamp_test00",
            primary_artist=self.artist,
            failed_count=0,
            downloaded=False,
        )

        assert song.last_failed_at is None

        before = timezone.now()
        song.increment_failed_count(FailureReason.TEMPORARY_ERROR)
        after = timezone.now()

        assert song.last_failed_at is not None
        assert before <= song.last_failed_at <= after
        assert song.failure_reason == FailureReason.TEMPORARY_ERROR

    def test_mark_downloaded_clears_failure_tracking(self):
        """Test that mark_downloaded resets all failure tracking fields."""
        from datetime import timedelta

        from django.utils import timezone

        from library_manager.models import FailureReason, Song

        # Create a song with failure history
        song = Song.objects.create(
            name="Previously Failed Song",
            gid="prev_failed_test",
            primary_artist=self.artist,
            failed_count=5,
            downloaded=False,
            failure_reason=FailureReason.SPOTIFY_NOT_FOUND,
            last_failed_at=timezone.now() - timedelta(days=1),
            unavailable=True,
        )

        # Mark it as downloaded
        song.mark_downloaded(bitrate=320, file_path="/music/test.mp3")

        # Refresh from DB to ensure it was saved
        song.refresh_from_db()

        # Verify all failure tracking was cleared
        assert song.downloaded is True
        assert song.bitrate == 320
        assert song.file_path == "/music/test.mp3"
        assert song.failed_count == 0
        assert song.failure_reason is None
        assert song.last_failed_at is None
        assert song.unavailable is False


class TestCleanupStuckTasksPeriodic(TestCase):
    """Test cleanup_stuck_tasks_periodic maintenance task."""

    @patch("django_celery_results.models.TaskResult")
    @patch("library_manager.models.TaskHistory")
    def test_cleans_up_stuck_task_history(self, mock_task_history, mock_task_result):
        """Test that stuck TaskHistory records are cleaned up."""
        from library_manager.tasks import cleanup_stuck_tasks_periodic

        # Mock TaskHistory.cleanup_stuck_tasks to return count
        mock_task_history.cleanup_stuck_tasks.return_value = 5

        # Mock TaskResult cleanup
        mock_task_result.objects.filter.return_value.update.return_value = 0

        # Run the task
        cleanup_stuck_tasks_periodic()

        # Should call cleanup on TaskHistory
        mock_task_history.cleanup_stuck_tasks.assert_called_once()

    @patch("django_celery_results.models.TaskResult")
    @patch("library_manager.models.TaskHistory")
    def test_cleans_up_stale_task_results(self, mock_task_history, mock_task_result):
        """Test that stale TaskResult records in STARTED status are cleaned up."""
        from library_manager.tasks import cleanup_stuck_tasks_periodic

        # Mock TaskHistory cleanup
        mock_task_history.cleanup_stuck_tasks.return_value = 0

        # Mock TaskResult.objects.filter().update() chain
        mock_filter = mock_task_result.objects.filter.return_value
        mock_filter.update.return_value = 3  # 3 stale records cleaned

        # Run the task
        cleanup_stuck_tasks_periodic()

        # Should filter for STARTED status older than threshold
        mock_task_result.objects.filter.assert_called()
        call_kwargs = mock_task_result.objects.filter.call_args[1]
        assert call_kwargs["status"] == "STARTED"
        assert "date_created__lt" in call_kwargs

        # Should update to FAILURE status
        mock_filter.update.assert_called_once_with(status="FAILURE")

    @patch("django_celery_results.models.TaskResult")
    @patch("library_manager.models.TaskHistory")
    def test_handles_no_stale_records(self, mock_task_history, mock_task_result):
        """Test that task handles case when no stale records exist."""
        from library_manager.tasks import cleanup_stuck_tasks_periodic

        # Mock no cleanup needed
        mock_task_history.cleanup_stuck_tasks.return_value = 0
        mock_task_result.objects.filter.return_value.update.return_value = 0

        # Run the task - should not raise any errors
        cleanup_stuck_tasks_periodic()

        # Verify both cleanups were attempted
        mock_task_history.cleanup_stuck_tasks.assert_called_once()
        mock_task_result.objects.filter.assert_called()
