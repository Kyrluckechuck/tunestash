"""Tests for timestamp field sorting with proper null handling."""

from datetime import timedelta

from django.utils import timezone

import pytest
from asgiref.sync import sync_to_async

from library_manager.models import Album as DjangoAlbum
from library_manager.models import Artist as DjangoArtist
from src.services.album import AlbumService
from src.services.artist import ArtistService


@pytest.fixture
def artist_service() -> ArtistService:
    return ArtistService()


@pytest.fixture
def album_service() -> AlbumService:
    return AlbumService()


def _create_artist(
    name: str,
    gid: str,
    last_synced_at: object = None,
    last_downloaded_at: object = None,
) -> DjangoArtist:
    """Create a real Artist in the database."""
    artist = DjangoArtist(
        name=name,
        gid=gid,
        tracking_tier=1,
        last_synced_at=last_synced_at,
        last_downloaded_at=last_downloaded_at,
    )
    artist.save()
    return artist


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_artist_sorting_last_synced_ascending_nulls_first(
    artist_service: ArtistService,
) -> None:
    """Ascending sort by lastSynced should put nulls first."""
    now = timezone.now()
    old = now - timedelta(days=7)

    await sync_to_async(_create_artist)(
        "Never Synced", "asc_null_1", last_synced_at=None
    )
    await sync_to_async(_create_artist)(
        "Synced Recently", "asc_null_2", last_synced_at=now
    )
    await sync_to_async(_create_artist)(
        "Synced Week Ago", "asc_null_3", last_synced_at=old
    )

    result = await artist_service.get_page(
        page=1,
        page_size=10,
        tracking_tier=1,
        sort_by="lastSynced",
        sort_direction="asc",
    )

    names = [item.name for item in result.items]
    null_idx = names.index("Never Synced")
    old_idx = names.index("Synced Week Ago")
    recent_idx = names.index("Synced Recently")

    assert null_idx < old_idx < recent_idx


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_artist_sorting_last_synced_descending_nulls_last(
    artist_service: ArtistService,
) -> None:
    """Descending sort by lastSynced should put nulls last."""
    now = timezone.now()
    old = now - timedelta(days=7)

    await sync_to_async(_create_artist)(
        "Never Synced", "desc_null_1", last_synced_at=None
    )
    await sync_to_async(_create_artist)(
        "Synced Recently", "desc_null_2", last_synced_at=now
    )
    await sync_to_async(_create_artist)(
        "Synced Week Ago", "desc_null_3", last_synced_at=old
    )

    result = await artist_service.get_page(
        page=1,
        page_size=10,
        tracking_tier=1,
        sort_by="lastSynced",
        sort_direction="desc",
    )

    names = [item.name for item in result.items]
    null_idx = names.index("Never Synced")
    recent_idx = names.index("Synced Recently")
    old_idx = names.index("Synced Week Ago")

    assert recent_idx < old_idx < null_idx


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_artist_sorting_last_downloaded_nulls_handling(
    artist_service: ArtistService,
) -> None:
    """Ascending sort by lastDownloaded should put nulls first."""
    now = timezone.now()

    await sync_to_async(_create_artist)(
        "Never Downloaded", "dl_null_1", last_downloaded_at=None
    )
    await sync_to_async(_create_artist)(
        "Downloaded Recently", "dl_null_2", last_downloaded_at=now
    )

    result = await artist_service.get_page(
        page=1,
        page_size=10,
        tracking_tier=1,
        sort_by="lastDownloaded",
        sort_direction="asc",
    )

    names = [item.name for item in result.items]
    null_idx = names.index("Never Downloaded")
    recent_idx = names.index("Downloaded Recently")

    assert null_idx < recent_idx


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_album_sorting_by_name(
    album_service: AlbumService,
) -> None:
    """Album sorting by name returns correctly ordered results."""
    artist = await sync_to_async(_create_artist)("Album Sort Artist", "alb_sort_1")

    for name in ["Zebra Album", "Alpha Album", "Middle Album"]:
        await sync_to_async(DjangoAlbum.objects.create)(
            name=name,
            spotify_gid=f"alb_sort_{name[:3].lower()}",
            artist=artist,
            total_tracks=10,
            wanted=True,
            downloaded=False,
        )

    result = await album_service.get_page(
        page=1, page_size=10, sort_by="name", sort_direction="asc"
    )

    names = [item.name for item in result.items]
    alpha_idx = names.index("Alpha Album")
    middle_idx = names.index("Middle Album")
    zebra_idx = names.index("Zebra Album")

    assert alpha_idx < middle_idx < zebra_idx
