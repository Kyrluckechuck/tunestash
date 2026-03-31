"""Service for pre-computed statistics stored in CachedStat model."""

import logging
from typing import Any, Optional

from django.db.models import Count, F, Q

from library_manager.models import (
    Album,
    Artist,
    CachedStat,
    Song,
    TaskHistory,
    TrackedPlaylist,
)

logger = logging.getLogger(__name__)

FAST_STATS: dict[str, dict[str, str]] = {
    "tracked_artists": {
        "display_name": "Tracked Artists",
        "category": "counts",
    },
    "total_songs": {
        "display_name": "Total Songs",
        "category": "counts",
    },
    "downloaded_songs": {
        "display_name": "Downloaded Songs",
        "category": "counts",
    },
    "total_playlists": {
        "display_name": "Total Playlists",
        "category": "counts",
    },
    "failed_songs": {
        "display_name": "Failed Songs",
        "category": "counts",
    },
    "active_tasks": {
        "display_name": "Active Tasks",
        "category": "tasks",
    },
}

EXPENSIVE_STATS: dict[str, dict[str, str]] = {
    "total_albums": {
        "display_name": "Total Albums",
        "category": "albums",
    },
    "downloaded_albums": {
        "display_name": "Downloaded Albums",
        "category": "albums",
    },
    "partial_albums": {
        "display_name": "Partial Albums",
        "category": "albums",
    },
    "missing_albums": {
        "display_name": "Missing Albums",
        "category": "albums",
    },
    "song_completion_pct": {
        "display_name": "Song Completion %",
        "category": "completion",
    },
    "album_completion_pct": {
        "display_name": "Album Completion %",
        "category": "completion",
    },
}


def _album_download_annotations() -> Any:
    """Shared annotation for album download counts."""
    return Album.objects.annotate(
        dl=Count("songs", filter=Q(songs__downloaded=True)),
        total=Count("songs"),
    )


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _total_songs() -> int:
    return Song.objects.count()


def _total_playlists() -> int:
    return TrackedPlaylist.objects.count()


def _total_albums() -> int:
    return Album.objects.count()


_STAT_COMPUTERS: dict[str, Any] = {
    "tracked_artists": lambda: Artist.objects.filter(tracked=True).count(),
    "total_songs": _total_songs,
    "downloaded_songs": lambda: Song.objects.filter(downloaded=True).count(),
    "total_playlists": _total_playlists,
    "failed_songs": lambda: Song.objects.filter(
        downloaded=False, failed_count__gt=0
    ).count(),
    "active_tasks": lambda: TaskHistory.objects.filter(status="IN_PROGRESS").count(),
    "total_albums": _total_albums,
    "downloaded_albums": lambda: (
        _album_download_annotations().filter(dl=F("total"), total__gt=0).count()
    ),
    "partial_albums": lambda: (
        _album_download_annotations()
        .filter(dl__gt=0, total__gt=0)
        .exclude(dl=F("total"))
        .count()
    ),
    "missing_albums": lambda: (
        _album_download_annotations().filter(dl=0, total__gt=0).count()
    ),
    "song_completion_pct": lambda: _pct(
        Song.objects.filter(downloaded=True).count(), _total_songs()
    ),
    "album_completion_pct": lambda: _pct(
        _album_download_annotations().filter(dl=F("total"), total__gt=0).count(),
        _total_albums(),
    ),
}


def _compute_stat(key: str) -> Any:
    """Compute a single stat value by key."""
    computer = _STAT_COMPUTERS.get(key)
    if computer is None:
        raise ValueError(f"Unknown stat key: {key}")
    return computer()


def refresh_fast_stats() -> None:
    """Refresh all fast (simple count) stats."""
    for key, meta in FAST_STATS.items():
        try:
            value = _compute_stat(key)
            CachedStat.objects.update_or_create(
                key=key,
                defaults={
                    "display_name": meta["display_name"],
                    "value": value,
                    "category": meta["category"],
                },
            )
        except Exception:
            logger.exception("Failed to compute fast stat: %s", key)


def refresh_expensive_stats() -> None:
    """Refresh all expensive (join/aggregate) stats."""
    for key, meta in EXPENSIVE_STATS.items():
        try:
            value = _compute_stat(key)
            CachedStat.objects.update_or_create(
                key=key,
                defaults={
                    "display_name": meta["display_name"],
                    "value": value,
                    "category": meta["category"],
                },
            )
        except Exception:
            logger.exception("Failed to compute expensive stat: %s", key)


def get_cached_stats(
    category: Optional[str] = None,
) -> list[CachedStat]:
    """Read cached stats, optionally filtered by category."""
    qs = CachedStat.objects.all()
    if category:
        qs = qs.filter(category=category)
    return list(qs.order_by("key"))
