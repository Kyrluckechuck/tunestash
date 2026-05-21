"""Track search for the contribution box — wraps TuneStash's Deezer-backed search."""

from __future__ import annotations

from src.services.catalog_search import CatalogSearchService, CatalogSearchTrack


async def catalog_search(query: str, limit: int = 10) -> list[CatalogSearchTrack]:
    """Search for tracks. Returns CatalogSearchTrack rows, which carry `in_library`
    and `local_id` for UI display. Convert a chosen result to a TrackCandidate via
    TrackCandidate.from_deezer_catalog_track() before ingest.
    """
    service = CatalogSearchService()
    results = await service.search(query, types=["track"], limit=limit)
    return results.tracks
