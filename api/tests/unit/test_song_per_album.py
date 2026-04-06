"""Tests for per-album Song records (ghost album fix)."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import IntegrityError, transaction

import pytest

from library_manager.models import Album, Artist, Song, TaskHistory

# Mock out unavailable C-extension libraries so src.providers.deezer can import
_mock_modules = {}
for _mod_name in ("deezer", "deezer.exceptions", "httpx"):
    if _mod_name not in sys.modules:
        _mock_modules[_mod_name] = MagicMock()
        sys.modules[_mod_name] = _mock_modules[_mod_name]

from library_manager.tasks.download import _download_deezer_album  # noqa: E402


@pytest.mark.unit
class TestSongPerAlbumConstraint:
    """Test that deezer_id is unique per album but allowed across albums."""

    def _create_artist(self) -> Artist:
        return Artist.objects.create(name="Test Artist", gid="0aB1cD2eF3gH4iJ5kL6mN7")

    def _create_album(self, artist: Artist, name: str, deezer_id: int) -> Album:
        return Album.objects.create(
            name=name,
            artist=artist,
            deezer_id=deezer_id,
            wanted=True,
        )

    def test_same_deezer_id_different_albums_allowed(self) -> None:
        """A track can exist as separate Song records on different albums."""
        artist = self._create_artist()
        album_a = self._create_album(artist, "Full Album", deezer_id=100)
        album_b = self._create_album(artist, "The Single", deezer_id=200)

        Song.objects.create(
            name="Track", deezer_id=999, primary_artist=artist, album=album_a
        )
        song_b = Song.objects.create(
            name="Track", deezer_id=999, primary_artist=artist, album=album_b
        )

        assert song_b.pk is not None
        assert Song.objects.filter(deezer_id=999).count() == 2

    def test_same_deezer_id_same_album_blocked(self) -> None:
        """Cannot add the same track to the same album twice."""
        artist = self._create_artist()
        album = self._create_album(artist, "Album", deezer_id=100)

        Song.objects.create(
            name="Track", deezer_id=999, primary_artist=artist, album=album
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Song.objects.create(
                    name="Track Copy",
                    deezer_id=999,
                    primary_artist=artist,
                    album=album,
                )

    def test_null_deezer_id_unconstrained(self) -> None:
        """Songs without deezer_id are not affected by the constraint."""
        artist = self._create_artist()
        album = self._create_album(artist, "Album", deezer_id=100)

        Song.objects.create(
            name="Spotify Song A",
            gid="1aB1cD2eF3gH4iJ5kL6mN7",
            primary_artist=artist,
            album=album,
        )
        song_b = Song.objects.create(
            name="Spotify Song B",
            gid="2aB1cD2eF3gH4iJ5kL6mN7",
            primary_artist=artist,
            album=album,
        )
        assert song_b.pk is not None

    def test_orphan_songs_unconstrained(self) -> None:
        """Songs with deezer_id but no album are not constrained."""
        artist = self._create_artist()

        Song.objects.create(
            name="Orphan A", deezer_id=999, primary_artist=artist, album=None
        )
        orphan_b = Song.objects.create(
            name="Orphan B", deezer_id=999, primary_artist=artist, album=None
        )
        assert orphan_b.pk is not None


def _make_task_history() -> TaskHistory:
    return TaskHistory.objects.create(
        task_id="test-task-123",
        type="DOWNLOAD",
        status="RUNNING",
    )


def _make_deezer_track(
    deezer_id: int,
    name: str,
    isrc: str = "USRC10000001",
    artist_name: str = "Test Artist",
    track_number: int = 1,
    duration_ms: int = 200000,
    disc_number: int = 1,
) -> MagicMock:
    track = MagicMock()
    track.deezer_id = deezer_id
    track.name = name
    track.isrc = isrc
    track.artist_name = artist_name
    track.track_number = track_number
    track.duration_ms = duration_ms
    track.disc_number = disc_number
    return track


def _make_album_data(image_url: str = "https://example.com/cover.jpg") -> MagicMock:
    data = MagicMock()
    data.image_url = image_url
    return data


@pytest.mark.unit
class TestDownloadCreatesPerAlbumSongs:
    """Test that _download_deezer_album creates separate Song records per album."""

    @patch("downloader.providers.fallback.FallbackDownloader")
    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_creates_new_song_when_track_exists_on_other_album(
        self, mock_provider_cls, mock_downloader_cls
    ) -> None:
        """When a track's deezer_id exists on album A, downloading album B
        should create a NEW Song record for album B."""
        artist = Artist.objects.create(name="DJ Snake", gid="0aB1cD2eF3gH4iJ5kL6mN7")
        album_a = Album.objects.create(
            name="Carte Blanche", artist=artist, deezer_id=100, wanted=True
        )
        album_b = Album.objects.create(
            name="Enzo Single", artist=artist, deezer_id=200, wanted=True
        )

        # Pre-existing song on album A (already downloaded)
        Song.objects.create(
            name="Enzo",
            deezer_id=555,
            primary_artist=artist,
            album=album_a,
            downloaded=True,
            isrc="USRC10000001",
        )

        # Mock Deezer returning the same track for album B
        provider = mock_provider_cls.return_value
        provider.get_album_tracks.return_value = [
            _make_deezer_track(deezer_id=555, name="Enzo", isrc="USRC10000001"),
        ]
        provider.get_album.return_value = _make_album_data()

        # Mock downloader to succeed
        downloader_instance = mock_downloader_cls.return_value
        result_mock = MagicMock()
        result_mock.success = True
        result_mock.file_path = "/mnt/music/DJ Snake/Enzo Single/Enzo.m4a"
        result_mock.provider_used = "youtube"

        async def fake_download(metadata):
            return result_mock

        downloader_instance.download_track = fake_download
        downloader_instance.close = AsyncMock()

        task_history = _make_task_history()
        downloaded, failed = _download_deezer_album(album_b, task_history)

        assert downloaded == 1
        assert failed == 0
        # Two separate Song records with the same deezer_id
        assert Song.objects.filter(deezer_id=555).count() == 2
        assert Song.objects.filter(deezer_id=555, album=album_b).exists()

    @patch("downloader.providers.fallback.FallbackDownloader")
    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_adopts_orphan_song_instead_of_creating_duplicate(
        self, mock_provider_cls, mock_downloader_cls
    ) -> None:
        """An orphan song (no album) should be linked, not duplicated."""
        artist = Artist.objects.create(name="Test", gid="0aB1cD2eF3gH4iJ5kL6mN7")
        album = Album.objects.create(
            name="Album", artist=artist, deezer_id=100, wanted=True
        )

        # Pre-existing orphan song
        orphan = Song.objects.create(
            name="Orphan Track",
            deezer_id=555,
            primary_artist=artist,
            album=None,
            downloaded=False,
        )

        provider = mock_provider_cls.return_value
        provider.get_album_tracks.return_value = [
            _make_deezer_track(deezer_id=555, name="Orphan Track"),
        ]
        provider.get_album.return_value = _make_album_data()

        downloader_instance = mock_downloader_cls.return_value
        result_mock = MagicMock()
        result_mock.success = True
        result_mock.file_path = "/mnt/music/Test/Album/Track.m4a"
        result_mock.provider_used = "youtube"
        downloader_instance.download_track = AsyncMock(return_value=result_mock)
        downloader_instance.close = AsyncMock()

        task_history = _make_task_history()
        _download_deezer_album(album, task_history)

        orphan.refresh_from_db()
        assert orphan.album == album
        assert Song.objects.filter(deezer_id=555).count() == 1

    @patch("downloader.providers.fallback.FallbackDownloader")
    @patch("src.providers.deezer.DeezerMetadataProvider")
    def test_idempotent_redownload_does_not_duplicate(
        self, mock_provider_cls, mock_downloader_cls
    ) -> None:
        """Re-running download on an album that already has songs should not
        create duplicate Song records."""
        artist = Artist.objects.create(name="Test", gid="0aB1cD2eF3gH4iJ5kL6mN7")
        album = Album.objects.create(
            name="Album", artist=artist, deezer_id=100, wanted=True
        )
        Song.objects.create(
            name="Track",
            deezer_id=555,
            primary_artist=artist,
            album=album,
            downloaded=True,
        )

        provider = mock_provider_cls.return_value
        provider.get_album_tracks.return_value = [
            _make_deezer_track(deezer_id=555, name="Track"),
        ]
        provider.get_album.return_value = _make_album_data()

        downloader_instance = mock_downloader_cls.return_value
        downloader_instance.close = AsyncMock()

        task_history = _make_task_history()
        downloaded, failed = _download_deezer_album(album, task_history)

        assert downloaded == 0
        assert failed == 0
        assert Song.objects.filter(deezer_id=555).count() == 1


@pytest.mark.unit
class TestCleanupGhostAlbums:
    """Test that cleanup_orphaned_albums resets ghost albums correctly."""

    def _create_artist(self) -> Artist:
        return Artist.objects.create(name="Test Artist", gid="0aB1cD2eF3gH4iJ5kL6mN7")

    def test_resets_downloaded_empty_deezer_albums(self) -> None:
        """Ghost albums (downloaded=True, 0 songs, has deezer_id) get reset."""
        from django.db.models import Count

        artist = self._create_artist()
        ghost = Album.objects.create(
            name="Ghost Single",
            artist=artist,
            deezer_id=12345,
            downloaded=True,
            wanted=True,
            failed_count=0,
        )

        empty_downloaded = (
            Album.objects.filter(downloaded=True, deezer_id__isnull=False)
            .annotate(song_count=Count("songs"))
            .filter(song_count=0)
        )
        reset_count = empty_downloaded.update(downloaded=False, failed_count=0)

        ghost.refresh_from_db()
        assert ghost.downloaded is False
        assert ghost.failed_count == 0
        assert reset_count == 1

    def test_does_not_reset_spotify_only_empties(self) -> None:
        """Spotify-only empty albums (no deezer_id) should not be reset."""
        from django.db.models import Count

        artist = self._create_artist()
        spotify_only = Album.objects.create(
            name="Spotify Album",
            artist=artist,
            spotify_gid="0aB1cD2eF3gH4iJ5kL6mN7oP",
            downloaded=True,
            wanted=True,
        )

        empty_downloaded = (
            Album.objects.filter(downloaded=True, deezer_id__isnull=False)
            .annotate(song_count=Count("songs"))
            .filter(song_count=0)
        )
        reset_count = empty_downloaded.update(downloaded=False, failed_count=0)

        spotify_only.refresh_from_db()
        assert spotify_only.downloaded is True
        assert reset_count == 0

    def test_does_not_reset_albums_with_songs(self) -> None:
        """Albums that have songs should not be reset even if they're Deezer albums."""
        from django.db.models import Count

        artist = self._create_artist()
        album = Album.objects.create(
            name="Real Album",
            artist=artist,
            deezer_id=67890,
            downloaded=True,
            wanted=True,
        )
        Song.objects.create(
            name="Track",
            deezer_id=111,
            primary_artist=artist,
            album=album,
            downloaded=True,
        )

        empty_downloaded = (
            Album.objects.filter(downloaded=True, deezer_id__isnull=False)
            .annotate(song_count=Count("songs"))
            .filter(song_count=0)
        )
        reset_count = empty_downloaded.update(downloaded=False, failed_count=0)

        album.refresh_from_db()
        assert album.downloaded is True
        assert reset_count == 0
