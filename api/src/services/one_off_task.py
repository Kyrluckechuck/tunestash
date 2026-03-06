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
            backfill_song_album,
            backfill_song_isrc,
            migrate_all_tracked_artists_to_deezer,
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

        self._tasks["migrate_catalog_to_deezer"] = OneOffTaskDefinition(
            id="migrate_catalog_to_deezer",
            name="Migrate Catalog to Deezer",
            description=(
                "Link existing albums and songs to Deezer IDs using ISRC and "
                "name matching. For each artist with a Deezer ID, fetches "
                "their full Deezer catalog, matches existing records, and creates "
                "new ones for missing content. Run 'Resolve Artists to Deezer' "
                "first to maximize coverage. Safe to re-run."
            ),
            category="data-migration",
            task_func=migrate_all_tracked_artists_to_deezer,
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
