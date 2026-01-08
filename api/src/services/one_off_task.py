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
            upgrade_low_quality_songs,
        )

        self._tasks["backfill_song_isrc"] = OneOffTaskDefinition(
            id="backfill_song_isrc",
            name="Backfill Song ISRC",
            description=(
                "Fetch ISRC codes from Spotify for songs that don't have them. "
                "Processes 500 songs per task (10 batches of 50) and chains "
                "until complete."
            ),
            category="data-migration",
            task_func=backfill_song_isrc,
        )

        self._tasks["backfill_song_album"] = OneOffTaskDefinition(
            id="backfill_song_album",
            name="Backfill Song Album Links",
            description=(
                "Link existing songs to their albums using Spotify track metadata. "
                "Processes 500 songs per task (10 batches of 50) and chains "
                "until complete. Songs whose albums aren't in the database are skipped."
            ),
            category="data-migration",
            task_func=backfill_song_album,
        )

        self._tasks["upgrade_low_quality_songs"] = OneOffTaskDefinition(
            id="upgrade_low_quality_songs",
            name="Upgrade Low Quality Songs",
            description=(
                "Attempt to upgrade songs below 220kbps (typically 128kbps from spotdl) "
                "to higher quality versions from Tidal or Qobuz. Processes up to 50 songs "
                "per run and tracks attempts to avoid re-trying songs that aren't available."
            ),
            category="maintenance",
            task_func=upgrade_low_quality_songs,
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
