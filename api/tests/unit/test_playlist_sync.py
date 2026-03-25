"""Tests for playlist sync logic — PlaylistSong management and M3U generation."""

import pytest

from library_manager.models import Artist, PlaylistSong, Song, TrackedPlaylist
from library_manager.tasks.playlist import _update_playlist_songs


@pytest.mark.django_db
class TestUpdatePlaylistSongs:
    """Test the diff logic for syncing PlaylistSong records."""

    @pytest.fixture
    def setup(self):
        artist = Artist.objects.create(name="Artist", gid="art1")
        playlist = TrackedPlaylist.objects.create(
            name="Test", url="https://open.spotify.com/playlist/test1"
        )
        songs = []
        for i in range(5):
            songs.append(
                Song.objects.create(
                    name=f"Song {i}", gid=f"gid{i}", primary_artist=artist
                )
            )
        return playlist, songs

    def test_creates_entries_for_new_playlist(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, songs[:3])

        entries = PlaylistSong.objects.filter(playlist=playlist).order_by("track_order")
        assert entries.count() == 3
        assert list(entries.values_list("track_order", flat=True)) == [0, 1, 2]

    def test_removes_songs_no_longer_in_playlist(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, songs[:3])
        assert PlaylistSong.objects.filter(playlist=playlist).count() == 3

        # Re-sync with only the first song
        _update_playlist_songs(playlist, songs[:1])
        assert PlaylistSong.objects.filter(playlist=playlist).count() == 1

    def test_updates_track_order_on_reorder(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, [songs[0], songs[1], songs[2]])

        # Reverse order
        _update_playlist_songs(playlist, [songs[2], songs[1], songs[0]])

        entries = PlaylistSong.objects.filter(playlist=playlist).order_by("track_order")
        song_ids = list(entries.values_list("song_id", flat=True))
        assert song_ids == [songs[2].id, songs[1].id, songs[0].id]

    def test_handles_adding_and_removing_simultaneously(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, [songs[0], songs[1]])

        # Remove song 0, keep song 1, add songs 3 and 4
        _update_playlist_songs(playlist, [songs[1], songs[3], songs[4]])

        entries = PlaylistSong.objects.filter(playlist=playlist).order_by("track_order")
        assert entries.count() == 3
        song_ids = list(entries.values_list("song_id", flat=True))
        assert song_ids == [songs[1].id, songs[3].id, songs[4].id]

    def test_empty_list_clears_all(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, songs)
        assert PlaylistSong.objects.filter(playlist=playlist).count() == 5

        _update_playlist_songs(playlist, [])
        assert PlaylistSong.objects.filter(playlist=playlist).count() == 0

    def test_idempotent_on_same_input(self, setup):
        playlist, songs = setup
        _update_playlist_songs(playlist, songs[:3])
        _update_playlist_songs(playlist, songs[:3])

        assert PlaylistSong.objects.filter(playlist=playlist).count() == 3
