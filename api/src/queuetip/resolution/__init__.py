"""Queuetip Phase 0 — the resolution interface.

Public functions: catalog_search, resolve_link, resolve_collection, ingest_track.

Async/sync note: catalog_search is async; resolve_link, resolve_collection, and
ingest_track are synchronous (blocking network + Django ORM) and must be wrapped
with asgiref.sync.sync_to_async when called from an async context.
"""

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.catalog import catalog_search
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.links import resolve_link
from src.queuetip.resolution.playlists import resolve_collection, resolve_playlist

__all__ = [
    "TrackCandidate",
    "catalog_search",
    "ingest_track",
    "resolve_link",
    "resolve_collection",
    "resolve_playlist",
]
