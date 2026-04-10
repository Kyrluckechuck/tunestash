"""Tests for AlbumService error paths and type conversion."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from tests.factories import AlbumFactory, ArtistFactory

from library_manager.models import Album as DjangoAlbum
from src.graphql_types.models import Album, MutationResult
from src.services.album import AlbumService


class TestAlbumServiceErrorPaths:
    """Test AlbumService error handling (mock-based, appropriate for error paths)."""

    @pytest.fixture
    def service(self) -> AlbumService:
        return AlbumService()

    @pytest.mark.asyncio
    async def test_update_album_not_found_raises(self, service):
        with patch(
            "library_manager.models.Album.objects.aget", new_callable=AsyncMock
        ) as mock_aget:
            mock_aget.side_effect = DjangoAlbum.DoesNotExist
            with pytest.raises(ValueError, match="Album with ID .* not found"):
                await service.update_album("invalid", is_wanted=True)

    @pytest.mark.asyncio
    async def test_set_album_wanted_not_found(self, service):
        with patch("src.services.album.sync_to_async") as mock_sync_to_async:
            mock_get = AsyncMock(side_effect=DjangoAlbum.DoesNotExist)
            mock_sync_to_async.return_value = mock_get

            result = await service.set_album_wanted(999999, True)

            assert isinstance(result, MutationResult)
            assert result.success is False
            assert "Album not found" in result.message

    @pytest.mark.asyncio
    async def test_set_album_wanted_save_error(self, service):
        mock_album = Mock(spec=DjangoAlbum)
        mock_album.id = 1
        mock_album.asave = AsyncMock(side_effect=Exception("Save failed"))

        with patch("src.services.album.sync_to_async") as mock_sync_to_async:
            mock_get = AsyncMock(return_value=mock_album)
            mock_sync_to_async.return_value = mock_get

            result = await service.set_album_wanted(1, True)

            assert isinstance(result, MutationResult)
            assert result.success is False
            assert "Error updating album" in result.message


@pytest.mark.django_db
class TestAlbumServiceTypeConversion:
    """Test _to_graphql_type with real DB objects."""

    @pytest.fixture
    def service(self) -> AlbumService:
        return AlbumService()

    def test_converts_real_album(self, service):
        artist = ArtistFactory(name="Radiohead", gid="artist_gid")
        album = AlbumFactory(
            name="OK Computer",
            artist=artist,
            spotify_gid="album_gid",
            total_tracks=12,
            wanted=True,
            downloaded=True,
            album_type="album",
            album_group="album",
            deezer_id="12345",
        )

        result = service._to_graphql_type(album)

        assert isinstance(result, Album)
        assert result.id == album.id
        assert result.name == "OK Computer"
        assert result.artist == "Radiohead"
        assert result.total_tracks == 12
        assert result.wanted is True
        assert result.downloaded is True

    def test_handles_none_id(self, service):
        artist = ArtistFactory(name="Test")
        album = AlbumFactory(name="Test Album", artist=artist)
        album.id = None

        result = service._to_graphql_type(album)
        assert result.id == 0
