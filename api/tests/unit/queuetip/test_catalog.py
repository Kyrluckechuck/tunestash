from unittest.mock import AsyncMock, patch

import pytest

from src.queuetip.resolution.catalog import catalog_search
from src.services.catalog_search import CatalogSearchResults, CatalogSearchTrack


def _track(name: str) -> CatalogSearchTrack:
    return CatalogSearchTrack(
        provider_id="1",
        name=name,
        external_url=None,
        artist_name="Artist",
        artist_provider_id="a",
        album_name="Album",
        album_provider_id="b",
        duration_ms=1000,
    )


@pytest.mark.asyncio
async def test_catalog_search_returns_only_tracks():
    fake = CatalogSearchResults(artists=[], albums=[], tracks=[_track("Maps")])
    with patch(
        "src.queuetip.resolution.catalog.CatalogSearchService.search",
        new=AsyncMock(return_value=fake),
    ) as mock_search:
        result = await catalog_search("maps", limit=5)
    assert [t.name for t in result] == ["Maps"]
    mock_search.assert_awaited_once_with("maps", types=["track"], limit=5)
