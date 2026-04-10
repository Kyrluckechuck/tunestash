"""Tests for service layer using real DB objects."""

from datetime import datetime, timezone

import pytest
from tests.factories import (
    AlbumFactory,
    ArtistFactory,
    SongFactory,
    TrackedPlaylistFactory,
)

from library_manager.models import DownloadHistory
from src.services.album import AlbumService
from src.services.artist import ArtistService
from src.services.history import DownloadHistoryService
from src.services.playlist import PlaylistService
from src.services.song import SongService


@pytest.mark.django_db(transaction=True)
class TestArtistService:
    """Test ArtistService with real DB objects."""

    @pytest.fixture
    def service(self):
        return ArtistService()

    @pytest.fixture
    def artists(self):
        return {
            "alpha": ArtistFactory(name="Alpha", tracking_tier=1, gid="aaa"),
            "mango": ArtistFactory(name="Mango", tracking_tier=1, gid="mmm"),
            "zebra": ArtistFactory(name="Zebra", tracking_tier=1, gid="zzz"),
            "untracked": ArtistFactory(name="Untracked", tracking_tier=0, gid="uuu"),
        }

    @pytest.mark.asyncio
    async def test_get_by_id_returns_artist(self, service, artists):
        result = await service.get_by_id(str(artists["alpha"].id))
        assert result is not None
        assert result.name == "Alpha"
        assert result.id == artists["alpha"].id
        assert result.tracking_tier == 1

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, service):
        result = await service.get_by_id("999999")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_page_filters_by_tracking_tier(self, service, artists):
        result = await service.get_page(page=1, page_size=50, tracking_tier=1)
        names = [a.name for a in result.items]
        assert "Alpha" in names
        assert "Untracked" not in names

    @pytest.mark.asyncio
    async def test_get_page_search(self, service, artists):
        result = await service.get_page(page=1, page_size=50, search="Mango")
        assert len(result.items) == 1
        assert result.items[0].name == "Mango"

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name_asc(self, service, artists):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="asc"
        )
        names = [a.name for a in result.items]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name_desc(self, service, artists):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="desc"
        )
        names = [a.name for a in result.items]
        assert names == sorted(names, reverse=True)

    @pytest.mark.asyncio
    async def test_get_page_pagination(self, service, artists):
        page1 = await service.get_page(page=1, page_size=2)
        page2 = await service.get_page(page=2, page_size=2)

        assert len(page1.items) == 2
        assert len(page2.items) == 2
        assert page1.total_count == 4
        page1_ids = {a.id for a in page1.items}
        page2_ids = {a.id for a in page2.items}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.fixture
    def timestamped_artist(self):
        now = datetime.now(tz=timezone.utc)
        return ArtistFactory(
            name="With Timestamps",
            last_synced_at=now,
            last_downloaded_at=now,
            added_at=now,
        )

    @pytest.mark.asyncio
    async def test_graphql_type_includes_timestamps(self, service, timestamped_artist):
        result = await service.get_by_id(str(timestamped_artist.id))
        assert result is not None
        assert result.last_synced is not None
        assert result.added_at is not None

    @pytest.fixture
    def null_timestamp_artist(self):
        return ArtistFactory(
            name="No Sync",
            last_synced_at=None,
            last_downloaded_at=None,
        )

    @pytest.mark.asyncio
    async def test_graphql_type_handles_null_timestamps(
        self, service, null_timestamp_artist
    ):
        result = await service.get_by_id(str(null_timestamp_artist.id))
        assert result is not None
        assert result.last_synced is None
        assert result.last_downloaded is None


@pytest.mark.django_db(transaction=True)
class TestSongService:
    """Test SongService with real DB objects."""

    @pytest.fixture
    def service(self):
        return SongService()

    @pytest.fixture
    def songs(self):
        artist_a = ArtistFactory(name="Alpha Band")
        artist_z = ArtistFactory(name="Zeta Band")
        return {
            "zebra": SongFactory(
                name="Zebra Song", primary_artist=artist_z, downloaded=False
            ),
            "alpha": SongFactory(
                name="Alpha Song", primary_artist=artist_a, downloaded=True
            ),
            "beta": SongFactory(
                name="Beta Song", primary_artist=artist_a, downloaded=False
            ),
        }

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name_asc(self, service, songs):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="asc"
        )
        names = [s.name for s in result.items]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name_desc(self, service, songs):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="desc"
        )
        names = [s.name for s in result.items]
        assert names == sorted(names, reverse=True)

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_primary_artist(self, service, songs):
        result = await service.get_page(
            page=1, page_size=50, sort_by="primaryArtist", sort_direction="asc"
        )
        artists = [s.primary_artist for s in result.items]
        assert artists == sorted(artists)

    @pytest.mark.asyncio
    async def test_get_page_filters_by_downloaded(self, service, songs):
        result = await service.get_page(page=1, page_size=50, downloaded=True)
        assert all(s.downloaded for s in result.items)
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_get_page_pagination(self, service, songs):
        page1 = await service.get_page(page=1, page_size=2)
        assert len(page1.items) == 2
        assert page1.total_count == 3


@pytest.mark.django_db(transaction=True)
class TestAlbumService:
    """Test AlbumService with real DB objects."""

    @pytest.fixture
    def service(self):
        return AlbumService()

    @pytest.fixture
    def albums(self):
        artist_a = ArtistFactory(name="Alpha Band")
        artist_z = ArtistFactory(name="Zebra Band")
        return {
            "ziggy": AlbumFactory(name="Ziggy", artist=artist_z, wanted=True),
            "abbey": AlbumFactory(name="Abbey", artist=artist_a, wanted=True),
        }

    @pytest.mark.asyncio
    async def test_get_by_id_success(self, service, albums):
        result = await service.get_by_id(albums["abbey"].spotify_gid)
        assert result is not None
        assert result.name == "Abbey"
        assert result.artist == "Alpha Band"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, service):
        result = await service.get_by_id("nonexistent_gid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_artist(self, service, albums):
        result = await service.get_page(
            page=1, page_size=50, sort_by="artist", sort_direction="asc"
        )
        artists = [a.artist for a in result.items]
        assert artists == sorted(artists)

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name(self, service, albums):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="asc"
        )
        names = [a.name for a in result.items]
        assert names == sorted(names)


@pytest.mark.django_db(transaction=True)
class TestPlaylistService:
    """Test PlaylistService with real DB objects."""

    @pytest.fixture
    def service(self):
        return PlaylistService()

    @pytest.fixture
    def playlists(self):
        return {
            "b": TrackedPlaylistFactory(name="Playlist B", status="active"),
            "a": TrackedPlaylistFactory(name="Playlist A", status="active"),
        }

    @pytest.fixture
    def my_playlist(self):
        return TrackedPlaylistFactory(
            name="My Playlist",
            url="spotify:playlist:test123",
            status="active",
            auto_track_tier=1,
        )

    @pytest.mark.asyncio
    async def test_get_by_id_success(self, service, my_playlist):
        result = await service.get_by_id(str(my_playlist.id))
        assert result is not None
        assert result.name == "My Playlist"
        assert result.auto_track_tier == 1

    @pytest.mark.asyncio
    async def test_get_page_sorts_by_name_desc(self, service, playlists):
        result = await service.get_page(
            page=1, page_size=50, sort_by="name", sort_direction="desc"
        )
        names = [p.name for p in result.items]
        assert names == sorted(names, reverse=True)

    def test_normalize_spotify_url_web_with_params(self, service):
        url = "https://open.spotify.com/playlist/12345?si=tracking_param&utm_source=web"
        assert service._normalize_spotify_url(url) == "spotify:playlist:12345"

    def test_normalize_spotify_url_web_without_params(self, service):
        url = "https://open.spotify.com/playlist/67890"
        assert service._normalize_spotify_url(url) == "spotify:playlist:67890"

    def test_normalize_spotify_url_already_normalized(self, service):
        url = "spotify:playlist:abcdef"
        assert service._normalize_spotify_url(url) == "spotify:playlist:abcdef"

    def test_normalize_spotify_url_other_types(self, service):
        url = "https://open.spotify.com/artist/artist123?si=param"
        assert service._normalize_spotify_url(url) == "spotify:artist:artist123"


@pytest.mark.django_db(transaction=True)
class TestDownloadHistoryService:
    """Test DownloadHistoryService with real DB objects."""

    @pytest.fixture
    def service(self):
        return DownloadHistoryService()

    @pytest.fixture
    def histories(self):
        items = []
        for i in range(5):
            completed = datetime.now(tz=timezone.utc) if i < 2 else None
            progress = 100 if i < 2 else 0
            items.append(
                DownloadHistory.objects.create(
                    url=f"spotify:track:song{i}",
                    progress=progress,
                    completed_at=completed,
                )
            )
        return items

    @pytest.mark.asyncio
    async def test_get_page_returns_items(self, service, histories):
        result = await service.get_page(page=1, page_size=10)
        assert len(result.items) == 5
        assert result.total_count == 5

    @pytest.mark.asyncio
    async def test_get_page_pagination(self, service, histories):
        page1 = await service.get_page(page=1, page_size=2)
        page2 = await service.get_page(page=2, page_size=2)

        assert len(page1.items) == 2
        assert len(page2.items) == 2
        assert page1.total_count == 5

    @pytest.mark.asyncio
    async def test_get_page_status_filter_completed(self, service, histories):
        result = await service.get_page(page=1, page_size=10, status="COMPLETED")
        assert len(result.items) == 2
        assert all(item.status.value == "COMPLETED" for item in result.items)
