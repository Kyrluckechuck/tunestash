"""The uniform track DTO emitted by every resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.services.catalog_search import CatalogSearchTrack


@dataclass
class TrackCandidate:
    """A track identity, source-agnostic, ready for ingest.

    artist_name is the PRIMARY artist only — never a joined multi-artist string.
    Joined strings degrade TrackMappingService fuzzy scoring; all_artists keeps the
    full list for display only.
    """

    track_name: str
    artist_name: str
    source: Literal["spotify", "apple", "deezer"]
    isrc: str | None = None
    source_id: str | None = None
    all_artists: list[str] = field(default_factory=list)

    @classmethod
    def from_deezer_catalog_track(cls, track: CatalogSearchTrack) -> "TrackCandidate":
        return cls(
            track_name=track.name,
            artist_name=track.artist_name,
            source="deezer",
            source_id=track.provider_id,
            all_artists=[track.artist_name],
        )
