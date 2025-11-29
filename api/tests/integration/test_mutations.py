"""Integration tests for GraphQL mutations."""

from django.test import TransactionTestCase

from asgiref.sync import sync_to_async

from library_manager.models import Album, Artist, PlaylistStatus, TrackedPlaylist
from src.schema import schema


class TestArtistMutations(TransactionTestCase):
    """Test artist-related mutations."""

    async def test_track_artist_mutation_success(self):
        """Test successful artist tracking."""
        untracked_artist = await sync_to_async(Artist.objects.create)(
            name="Untracked Artist", gid="untracked123", tracked=False
        )

        mutation = """
        mutation TrackArtist($artistId: Int!) {
            trackArtist(artistId: $artistId) {
                success
                message
                artist {
                    id
                    name
                    isTracked
                }
            }
        }
        """

        variables = {"artistId": untracked_artist.id}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["trackArtist"]["success"] is True
        assert result.data["trackArtist"]["artist"]["isTracked"] is True

    async def test_track_nonexistent_artist(self):
        """Test tracking a non-existent artist."""
        mutation = """
        mutation TrackArtist($artistId: Int!) {
            trackArtist(artistId: $artistId) {
                success
                message
                artist {
                    id
                    name
                    isTracked
                }
            }
        }
        """

        variables = {"artistId": 99999}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["trackArtist"]["success"] is False
        assert "not found" in result.data["trackArtist"]["message"].lower()

    async def test_untrack_artist_mutation_success(self):
        """Test successful artist untracking."""
        tracked_artist = await sync_to_async(Artist.objects.create)(
            name="Tracked Artist", gid="tracked123", tracked=True
        )

        mutation = """
        mutation UntrackArtist($artistId: Int!) {
            untrackArtist(artistId: $artistId) {
                success
                message
                artist {
                    id
                    name
                    isTracked
                }
            }
        }
        """

        variables = {"artistId": tracked_artist.id}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["untrackArtist"]["success"] is True
        assert result.data["untrackArtist"]["artist"]["isTracked"] is False


class TestAlbumMutations(TransactionTestCase):
    """Test album-related mutations."""

    async def test_mark_album_wanted(self):
        """Test marking an album as wanted."""
        artist = await sync_to_async(Artist.objects.create)(
            name="Test Artist", gid="test123", tracked=True
        )
        album = await sync_to_async(Album.objects.create)(
            name="Test Album",
            spotify_gid="album123",
            artist=artist,
            total_tracks=10,
            wanted=False,
            downloaded=False,
        )

        mutation = """
        mutation SetAlbumWanted($albumId: Int!, $wanted: Boolean!) {
            setAlbumWanted(albumId: $albumId, wanted: $wanted) {
                success
                message
                album {
                    id
                    name
                    wanted
                }
            }
        }
        """

        variables = {"albumId": album.id, "wanted": True}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["setAlbumWanted"]["success"] is True
        assert result.data["setAlbumWanted"]["album"]["wanted"] is True

    async def test_mark_album_unwanted(self):
        """Test marking an album as unwanted."""
        artist = await sync_to_async(Artist.objects.create)(
            name="Test Artist", gid="test123", tracked=True
        )
        album = await sync_to_async(Album.objects.create)(
            name="Test Album",
            spotify_gid="album123",
            artist=artist,
            total_tracks=10,
            wanted=True,
            downloaded=False,
        )

        mutation = """
        mutation SetAlbumWanted($albumId: Int!, $wanted: Boolean!) {
            setAlbumWanted(albumId: $albumId, wanted: $wanted) {
                success
                message
                album {
                    id
                    name
                    wanted
                }
            }
        }
        """

        variables = {"albumId": album.id, "wanted": False}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["setAlbumWanted"]["success"] is True
        assert result.data["setAlbumWanted"]["album"]["wanted"] is False


class TestPlaylistMutations(TransactionTestCase):
    """Test playlist-related mutations."""

    async def test_enable_playlist(self):
        """Test enabling a playlist."""
        playlist = await sync_to_async(TrackedPlaylist.objects.create)(
            name="Test Playlist",
            url="https://open.spotify.com/playlist/test123",
            status=PlaylistStatus.DISABLED_BY_USER,
            auto_track_artists=True,
        )

        mutation = """
        mutation TogglePlaylist($playlistId: Int!) {
            togglePlaylist(playlistId: $playlistId) {
                success
                message
                playlist {
                    id
                    name
                    enabled
                }
            }
        }
        """

        variables = {"playlistId": playlist.id}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["togglePlaylist"]["success"] is True
        assert result.data["togglePlaylist"]["playlist"]["enabled"] is True

    async def test_disable_playlist(self):
        """Test disabling a playlist."""
        # Create test data
        playlist = await sync_to_async(TrackedPlaylist.objects.create)(
            name="Test Playlist",
            url="https://open.spotify.com/playlist/test123",
            status=PlaylistStatus.ACTIVE,
            auto_track_artists=True,
        )

        mutation = """
        mutation TogglePlaylist($playlistId: Int!) {
            togglePlaylist(playlistId: $playlistId) {
                success
                message
                playlist {
                    id
                    name
                    enabled
                }
            }
        }
        """

        variables = {"playlistId": playlist.id}
        result = await schema.execute(mutation, variable_values=variables)

        assert result.errors is None
        assert result.data["togglePlaylist"]["success"] is True
        assert result.data["togglePlaylist"]["playlist"]["enabled"] is False

    async def test_recheck_not_found_playlist(self):
        """Test rechecking a playlist that was marked as not found."""
        from unittest.mock import MagicMock, patch

        playlist = await sync_to_async(TrackedPlaylist.objects.create)(
            name="Missing Playlist",
            url="https://open.spotify.com/playlist/notfound123",
            status=PlaylistStatus.NOT_FOUND,
            status_message="Playlist not found - may have been deleted or made private",
            auto_track_artists=False,
        )

        mutation = """
        mutation SyncPlaylist($playlistId: Int!, $recheck: Boolean) {
            syncPlaylist(playlistId: $playlistId, recheck: $recheck) {
                success
                message
                playlist {
                    id
                    name
                    status
                }
            }
        }
        """

        # Mock the Celery task to avoid broker connection issues
        with patch("library_manager.tasks.download_playlist") as mock_task:
            mock_task.delay = MagicMock()

            variables = {"playlistId": playlist.id, "recheck": True}
            result = await schema.execute(mutation, variable_values=variables)

            assert result.errors is None, f"GraphQL errors: {result.errors}"
            assert (
                result.data["syncPlaylist"]["success"] is True
            ), f"Expected success but got: {result.data['syncPlaylist']}"
            assert "recheck" in result.data["syncPlaylist"]["message"].lower()
            # Status should be reset to ACTIVE (sync task will update it if still not found)
            assert result.data["syncPlaylist"]["playlist"]["status"] == "active"

            # Verify the task was queued with correct parameters
            mock_task.delay.assert_called_once()
            call_kwargs = mock_task.delay.call_args[1]
            assert call_kwargs["force_playlist_resync"] is True


class TestTaskMutations(TransactionTestCase):
    """Test task-related mutations."""

    async def test_cancel_all_tasks(self):
        """Test canceling all tasks."""
        mutation = """
        mutation CancelAllTasks {
            cancelAllTasks {
                success
                message
            }
        }
        """

        result = await schema.execute(mutation)

        assert result.errors is None
        assert result.data["cancelAllTasks"]["success"] is True
