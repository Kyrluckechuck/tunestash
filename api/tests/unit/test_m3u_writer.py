"""Tests for M3U playlist file generation."""

import pytest
from downloader.m3u_writer import _sanitize_playlist_name


class TestSanitizePlaylistName:
    """Test filesystem-safe playlist name generation."""

    def test_removes_slashes(self):
        assert _sanitize_playlist_name("My/Playlist") == "MyPlaylist"

    def test_removes_backslashes(self):
        assert _sanitize_playlist_name("My\\Playlist") == "MyPlaylist"

    def test_removes_special_chars(self):
        assert _sanitize_playlist_name("Song: Best <Mix>") == "Song Best Mix"

    def test_strips_dots_and_spaces(self):
        assert _sanitize_playlist_name("  ..playlist.. ") == "playlist"

    def test_empty_string_returns_default(self):
        assert _sanitize_playlist_name("") == "Untitled Playlist"

    def test_truncates_long_names(self):
        long_name = "A" * 300
        result = _sanitize_playlist_name(long_name)
        assert len(result) <= 200


@pytest.mark.django_db
class TestWritePlaylistM3u:
    """Test M3U file generation with real DB records."""

    def test_generates_valid_m3u(self, tmp_path):
        from downloader.m3u_writer import write_playlist_m3u

        from library_manager.models import (
            Artist,
            FilePath,
            PlaylistSong,
            Song,
            TrackedPlaylist,
        )

        artist = Artist.objects.create(name="Test Artist", gid="test123")
        fp = FilePath.objects.create(
            path=str(tmp_path / "Test Artist" / "Album" / "Test Artist - Song.m4a")
        )
        song = Song.objects.create(
            name="Song",
            gid="song123",
            primary_artist=artist,
            downloaded=True,
            file_path_ref=fp,
        )
        playlist = TrackedPlaylist.objects.create(
            name="Test Playlist",
            url="https://open.spotify.com/playlist/test",
        )
        PlaylistSong.objects.create(playlist=playlist, song=song, track_order=0)

        # Create the fake audio file so the path exists for relative resolution
        audio_dir = tmp_path / "Test Artist" / "Album"
        audio_dir.mkdir(parents=True)
        (audio_dir / "Test Artist - Song.m4a").touch()

        result = write_playlist_m3u(playlist.pk, tmp_path, "Playlists")

        assert result is not None
        assert result.exists()
        assert result.name == "TS - Test Playlist.m3u"

        content = result.read_text()
        assert "#EXTM3U" in content
        assert "#PLAYLIST:TS | Test Playlist" in content
        assert "Test Artist - Song" in content
        # Paths should use ../ to navigate from Playlists/ to music root
        assert "../Test Artist/Album/" in content

    def test_returns_none_for_empty_playlist(self, tmp_path):
        from downloader.m3u_writer import write_playlist_m3u

        from library_manager.models import TrackedPlaylist

        playlist = TrackedPlaylist.objects.create(
            name="Empty",
            url="https://open.spotify.com/playlist/empty",
        )

        result = write_playlist_m3u(playlist.pk, tmp_path, "Playlists")
        assert result is None

    def test_returns_none_for_nonexistent_playlist(self, tmp_path):
        from downloader.m3u_writer import write_playlist_m3u

        result = write_playlist_m3u(99999, tmp_path, "Playlists")
        assert result is None
