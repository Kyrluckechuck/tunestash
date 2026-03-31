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


def _compute_stat(key: str) -> Any:
    """Compute a single stat value by key."""
    if key == "tracked_artists":
        return Artist.objects.filter(tracked=True).count()
    if key == "total_songs":
        return Song.objects.count()
    if key == "downloaded_songs":
        return Song.objects.filter(downloaded=True).count()
    if key == "total_playlists":
        return TrackedPlaylist.objects.count()
    if key == "failed_songs":
        return Song.objects.filter(downloaded=False, failed_count__gt=0).count()
    if key == "active_tasks":
        return TaskHistory.objects.filter(status="IN_PROGRESS").count()
    if key == "total_albums":
        return Album.objects.count()
    if key == "downloaded_albums":
        return (
            Album.objects.annotate(
                dl=Count("songs", filter=Q(songs__downloaded=True)),
                total=Count("songs"),
            )
            .filter(dl=F("total"), total__gt=0)
            .count()
        )
    if key == "partial_albums":
        return (
            Album.objects.annotate(
                dl=Count("songs", filter=Q(songs__downloaded=True)),
                total=Count("songs"),
            )
            .filter(dl__gt=0, total__gt=0)
            .exclude(dl=F("total"))
            .count()
        )
    if key == "missing_albums":
        return (
            Album.objects.annotate(
                dl=Count("songs", filter=Q(songs__downloaded=True)),
                total=Count("songs"),
            )
            .filter(dl=0, total__gt=0)
            .count()
        )
    if key == "song_completion_pct":
        total = Song.objects.count()
        if total == 0:
            return 0.0
        downloaded = Song.objects.filter(downloaded=True).count()
        return round(downloaded / total * 100, 1)
    if key == "album_completion_pct":
        total_albums = Album.objects.count()
        if total_albums == 0:
            return 0.0
        complete = (
            Album.objects.annotate(
                dl=Count("songs", filter=Q(songs__downloaded=True)),
                total=Count("songs"),
            )
            .filter(dl=F("total"), total__gt=0)
            .count()
        )
        return round(complete / total_albums * 100, 1)

    raise ValueError(f"Unknown stat key: {key}")


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
