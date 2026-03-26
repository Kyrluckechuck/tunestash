"""Service for managing one-off maintenance tasks."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asgiref.sync import sync_to_async

from ..graphql_types.models import MutationResult, OneOffTask


@dataclass
class OneOffTaskDefinition:
    """Definition of a one-off task."""

    id: str
    name: str
    description: str
    category: str
    task_func: Any  # Celery task - typed as Any because .delay() is dynamically added


class OneOffTaskService:
    """Service for managing and executing one-off maintenance tasks."""

    def __init__(self) -> None:
        self._tasks: Dict[str, OneOffTaskDefinition] = {}
        self._register_tasks()

    def _register_tasks(self) -> None:
        """Register all available one-off tasks."""
        # Import tasks here to avoid circular imports
        from library_manager.tasks import (
            backfill_album_tracks,
            backfill_lyrics_status,
            backfill_song_album,
            backfill_song_isrc,
            cleanup_appears_on_albums,
            cleanup_orphaned_albums,
            merge_duplicate_songs,
            repair_misassigned_songs,
            resolve_all_artists_to_deezer,
            retry_failed_external_mappings,
            send_test_notification,
            upgrade_low_quality_songs,
        )

        self._tasks["backfill_song_isrc"] = OneOffTaskDefinition(
            id="backfill_song_isrc",
            name="Backfill Song ISRC",
            description=(
                "Fetch ISRC codes from Deezer for songs that don't have them. "
                "Processes 250 songs per task and chains until complete. "
                "Songs without a deezer_id are skipped."
            ),
            category="data-migration",
            task_func=backfill_song_isrc,
        )

        self._tasks["backfill_song_album"] = OneOffTaskDefinition(
            id="backfill_song_album",
            name="Backfill Song Album Links",
            description=(
                "Link existing songs to their albums using Deezer track metadata. "
                "Processes 250 songs per task and chains until complete. "
                "Songs without a deezer_id or whose albums aren't in the database "
                "are skipped."
            ),
            category="data-migration",
            task_func=backfill_song_album,
        )

        self._tasks["upgrade_low_quality_songs"] = OneOffTaskDefinition(
            id="upgrade_low_quality_songs",
            name="Upgrade Low Quality Songs",
            description=(
                "Attempt to upgrade songs below 220kbps (typically 128kbps from YouTube) "
                "to higher quality versions from Tidal or Qobuz. Processes up to 50 songs "
                "per run and tracks attempts to avoid re-trying songs that aren't available."
            ),
            category="maintenance",
            task_func=upgrade_low_quality_songs,
        )

        self._tasks["retry_failed_external_mappings"] = OneOffTaskDefinition(
            id="retry_failed_external_mappings",
            name="Retry Failed External Mappings",
            description=(
                "Reset all failed track mappings in external lists back to pending "
                "and re-queue the mapping pipeline. Useful after Spotify catalog "
                "updates or mapping logic improvements."
            ),
            category="external-lists",
            task_func=retry_failed_external_mappings,
        )

        self._tasks["resolve_artists_to_deezer"] = OneOffTaskDefinition(
            id="resolve_artists_to_deezer",
            name="Resolve Artists to Deezer",
            description=(
                "Search Deezer for all artists that don't have a Deezer ID yet. "
                "Processes tracked artists first, then untracked. "
                "Self-chains in batches of 200. After resolution, run "
                "'Migrate Catalog to Deezer' to fetch their albums and songs."
            ),
            category="data-migration",
            task_func=resolve_all_artists_to_deezer,
        )

        self._tasks["merge_duplicate_songs"] = OneOffTaskDefinition(
            id="merge_duplicate_songs",
            name="Merge Duplicate Songs",
            description=(
                "Merge albumless duplicate songs into their with-album counterparts. "
                "Finds songs with matching ISRC where one copy has an album and the "
                "other doesn't. Carries over download data, Spotify GID, and other "
                "fields from the albumless copy, then deletes it. "
                "Self-chains in batches of 500."
            ),
            category="maintenance",
            task_func=merge_duplicate_songs,
        )

        self._tasks["repair_misassigned_songs"] = OneOffTaskDefinition(
            id="repair_misassigned_songs",
            name="Repair Misassigned Songs",
            description=(
                "Find and fix songs assigned to albums belonging to a different "
                "artist (cross-artist contamination). Reassigns to the correct "
                "album by name match or Deezer API lookup, or nulls the album "
                "if no correct album is found. Run BEFORE 'Backfill Album Tracks' "
                "for best results. Self-chains in batches of 500."
            ),
            category="maintenance",
            task_func=repair_misassigned_songs,
        )

        self._tasks["cleanup_appears_on_albums"] = OneOffTaskDefinition(
            id="cleanup_appears_on_albums",
            name="Cleanup Appears-On Albums",
            description=(
                "Remove empty 'appears_on' compilation albums (Spotify legacy data) "
                "that have zero songs and will never be downloaded. Albums with songs "
                "are kept but marked as unwanted. Typically clears ~70% of album bloat."
            ),
            category="maintenance",
            task_func=cleanup_appears_on_albums,
        )

        self._tasks["backfill_album_tracks"] = OneOffTaskDefinition(
            id="backfill_album_tracks",
            name="Backfill Album Tracks",
            description=(
                "Re-fetch tracks from Deezer for albums that have a deezer_id but "
                "0 songs (usually caused by silent API failures during migration). "
                "Processes 200 albums per batch and self-chains until complete. "
                "Updates total_tracks from actual track count."
            ),
            category="data-migration",
            task_func=backfill_album_tracks,
        )

        self._tasks["cleanup_orphaned_albums"] = OneOffTaskDefinition(
            id="cleanup_orphaned_albums",
            name="Cleanup Orphaned Albums",
            description=(
                "Remove garbage album data: empty albums with bad names "
                "('missing', 'Unknown', etc.), Spotify-only empty albums "
                "(no deezer_id, 0 songs), empty albums marked downloaded, "
                "and unwant misattributed compilation albums. "
                "May delete 1M+ empty Spotify stubs — runs in batches."
            ),
            category="maintenance",
            task_func=cleanup_orphaned_albums,
        )

        self._tasks["backfill_lyrics_status"] = OneOffTaskDefinition(
            id="backfill_lyrics_status",
            name="Backfill Lyrics Status",
            description=(
                "Scan all downloaded songs and create lyrics tracking records. "
                "For songs with existing .lrc files on disk (exact or fuzzy match), "
                "marks has_lyrics=True. Songs without .lrc files are queued for "
                "automatic retry via the daily lyrics task. Safe to re-run."
            ),
            category="maintenance",
            task_func=backfill_lyrics_status,
        )

        self._tasks["send_test_notification"] = OneOffTaskDefinition(
            id="send_test_notification",
            name="Send Test Notification",
            description=(
                "Send a test notification to all configured Apprise URLs. "
                "Verifies that NOTIFICATIONS_ENABLED is true and NOTIFICATIONS_URLS "
                "are reachable. Check worker logs for [NOTIFY] output."
            ),
            category="notifications",
            task_func=send_test_notification,
        )

    def get_all(self) -> List[OneOffTask]:
        """Get all available one-off tasks."""
        return [
            OneOffTask(
                id=task.id,
                name=task.name,
                description=task.description,
                category=task.category,
            )
            for task in self._tasks.values()
        ]

    def get_by_id(self, task_id: str) -> Optional[OneOffTaskDefinition]:
        """Get a task definition by ID."""
        return self._tasks.get(task_id)

    async def run_task(self, task_id: str) -> MutationResult:
        """Queue a one-off task for execution."""
        task_def = self.get_by_id(task_id)
        if not task_def:
            return MutationResult(
                success=False,
                message=f"Unknown task: {task_id}",
            )

        try:
            # Queue the task using .delay()
            def queue_task() -> None:
                task_def.task_func.delay()

            await sync_to_async(queue_task)()

            return MutationResult(
                success=True,
                message=f"Task '{task_def.name}' queued for execution",
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Failed to queue task: {str(e)}",
            )
