"""Base classes for external music list providers."""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExternalTrack:
    """A track from an external source (Last.fm, ListenBrainz)."""

    artist_name: str
    track_name: str
    musicbrainz_id: Optional[str] = None


@dataclass
class ExternalListResult:
    """Result of fetching tracks from an external list."""

    tracks: list[ExternalTrack] = field(default_factory=list)
    # The upstream's own total for the list; 0 means the source did not say.
    total_count: int = 0
    content_hash: str = ""
    # Positive proof that ``tracks`` is the whole list: set True only by code
    # that fetched every page without error and checked it against the upstream
    # total. Anything else (default, per-page results, unknown) is incomplete,
    # and absence from an incomplete list never authorizes a removal.
    complete: bool = False

    @staticmethod
    def compute_content_hash(tracks: list[ExternalTrack]) -> str:
        """Compute a stable SHA-256 hash of the track list for change detection."""
        sorted_tuples = sorted(
            (t.artist_name.lower().strip(), t.track_name.lower().strip())
            for t in tracks
        )
        content = "|".join(f"{a}::{t}" for a, t in sorted_tuples)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ExternalListProvider(ABC):
    """Abstract base for external music list providers."""

    @abstractmethod
    def validate_user(self, username: str) -> tuple[bool, Optional[str]]:
        """Validate that a user exists on this service.

        Returns:
            (is_valid, error_message) — error_message is None if valid.
        """

    @abstractmethod
    def fetch_tracks(
        self,
        username: str,
        list_type: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        page: int = 1,
        limit: int = 200,
    ) -> ExternalListResult:
        """Fetch tracks from the external service.

        Args:
            username: The user on the external service.
            list_type: One of "loved", "top", "playlist", "chart".
            period: Time period for top tracks (service-specific).
            list_identifier: Source-specific ID (playlist MBID, chart tag, etc.).
            page: Page number (1-indexed).
            limit: Max tracks per page.

        Returns:
            ExternalListResult with tracks and content hash.
        """

    def fetch_all_tracks(
        self,
        username: str,
        list_type: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        max_tracks: int = 5000,
    ) -> ExternalListResult:
        """Fetch all pages of tracks from an external list.

        Default implementation paginates using fetch_tracks().
        """
        all_tracks: list[ExternalTrack] = []
        page = 1
        limit = 200

        upstream_total = 0
        ended = False  # a page said "no more" (rather than hitting max_tracks)

        while len(all_tracks) < max_tracks:
            result = self.fetch_tracks(
                username=username,
                list_type=list_type,
                period=period,
                list_identifier=list_identifier,
                page=page,
                limit=limit,
            )
            upstream_total = max(upstream_total, result.total_count or 0)
            if not result.tracks:
                ended = True
                break
            all_tracks.extend(result.tracks)
            if len(result.tracks) < limit:
                ended = True
                break
            page += 1

        content_hash = ExternalListResult.compute_content_hash(all_tracks)
        # Complete only when the source reported a total and the pages we
        # collected add up to exactly that; an early empty/short page or a
        # source that gives no total is unproven, hence incomplete.
        complete = (
            ended
            and len(all_tracks) < max_tracks
            and upstream_total > 0
            and len(all_tracks) == upstream_total
        )
        return ExternalListResult(
            tracks=all_tracks,
            total_count=upstream_total,
            content_hash=content_hash,
            complete=complete,
        )
