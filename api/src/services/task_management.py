"""
Task management service for handling Celery task operations.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.utils import timezone

from asgiref.sync import sync_to_async
from celery_app import app as celery_app
from django_celery_results.models import TaskResult


@dataclass
class PendingTaskInfo:  # pylint: disable=too-many-instance-attributes
    """Information about a pending task with resolved entity details."""

    task_id: str
    task_name: str
    display_name: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    entity_name: Optional[str]
    status: str
    created_at: Optional[str]


def _parse_json_field(value: Any) -> Any:
    """Parse a JSON field that might be a string or already parsed.

    Handles both JSON strings and Python repr strings (single quotes, True/False).
    Also handles double-encoded values (JSON string containing Python repr).
    """
    import ast

    if isinstance(value, str):
        # First try JSON parsing
        try:
            parsed = json.loads(value)
            # If result is still a string, it might be double-encoded
            # (JSON string containing Python repr)
            if isinstance(parsed, str):
                try:
                    return ast.literal_eval(parsed)
                except (ValueError, SyntaxError):
                    return parsed
            return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Fall back to ast.literal_eval for Python repr strings
        # (single quotes, True/False/None instead of true/false/null)
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass

        return value
    return value


def _format_task_name(full_name: str) -> str:
    """Convert task name to human-readable format."""
    name = full_name.replace("library_manager.tasks.", "").replace("downloader.", "")
    return " ".join(word.capitalize() for word in name.split("_"))


def _get_entity_type(task_name: str) -> Optional[str]:
    """Determine entity type from task name."""
    task_lower = task_name.lower()
    if "artist" in task_lower:
        return "artist"
    if "album" in task_lower:
        return "album"
    if "playlist" in task_lower:
        return "playlist"
    if "track" in task_lower:
        return "track"
    return None


def _extract_entity_id(
    task_name: str, args: List[Any], kwargs: Dict[str, Any]
) -> Optional[Any]:
    """Extract entity ID from task arguments based on task type."""
    # Check kwargs first (more explicit) - order matters for priority
    # kwargs might be a string if JSON parsing failed, so check type first
    if isinstance(kwargs, dict):
        kwarg_keys = [
            "playlist_url",
            "playlist_id",
            "artist_id",
            "album_id",
            "track_id",
            "spotify_album_id",
        ]
        for key in kwarg_keys:
            if key in kwargs:
                return kwargs[key]

    # Fall back to positional args
    # args might be a string if JSON parsing failed, so check type first
    # Note: Celery stores args as tuple repr "(123,)", so check for both list and tuple
    if isinstance(args, (list, tuple)) and args:
        return args[0]

    return None


class MutationResult:
    """Simple result object for mutations."""

    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


class TaskManagementService:
    """Service for managing Celery tasks."""

    async def cancel_all_pending_tasks(self) -> MutationResult:
        """
        Cancel all pending tasks by purging Celery broker queues and updating DB.

        This method:
        1. Purges all Celery broker queues (downloads, spotify, celery)
        2. Updates TaskResult records to REVOKED status
        3. Updates TaskHistory records to CANCELLED status

        Note: purge() clears the broker queue directly, which is necessary because
        with PostgreSQL broker, tasks live in kombu_message table, not TaskResult.
        """
        try:
            from library_manager.models import TaskHistory

            # 1. Purge all broker queues (this actually stops tasks from running)
            queues_to_purge = ["downloads", "metadata", "celery"]
            purged_count = 0

            def purge_queues() -> int:
                total = 0
                for queue in queues_to_purge:
                    try:
                        count = celery_app.control.purge()
                        if count:
                            total += count
                    except Exception:
                        pass
                return total

            purged_count = await sync_to_async(purge_queues)()

            # 2. Update TaskResult records to REVOKED status
            task_result_count = await TaskResult.objects.filter(
                status__in=["PENDING", "STARTED", "RETRY"]
            ).aupdate(status="REVOKED")

            # 3. Update TaskHistory records to CANCELLED status
            task_history_count = await TaskHistory.objects.filter(
                status__in=["PENDING", "RUNNING"]
            ).aupdate(
                status="CANCELLED",
                completed_at=timezone.now(),
                error_message="Cancelled by user (all tasks purged)",
            )

            return MutationResult(
                success=True,
                message=(
                    f"Successfully cancelled tasks: {purged_count} purged from queue, "
                    f"{task_result_count} TaskResult updated, "
                    f"{task_history_count} TaskHistory updated"
                ),
            )

        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to cancel tasks: {str(e)}"
            )

    async def cancel_tasks_by_name(self, task_name: str) -> MutationResult:
        """Cancel all pending tasks with a specific name by updating database records."""
        try:
            # Update pending tasks with matching name to REVOKED status
            cancelled_count = await TaskResult.objects.filter(
                status__in=["PENDING", "STARTED", "RETRY"],
                task_name=task_name,
            ).aupdate(status="REVOKED")

            return MutationResult(
                success=True,
                message=f"Successfully cancelled {cancelled_count} tasks with name '{task_name}'",
            )

        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to cancel tasks: {str(e)}"
            )

    async def cancel_running_tasks_by_name(self, task_name: str) -> MutationResult:
        """Cancel running tasks by marking them as cancelled in the database."""
        try:
            from library_manager.models import TaskHistory

            # Find running tasks with the specified name using sync_to_async
            queryset = TaskHistory.objects.filter(
                type__iexact=task_name.replace("_", ""), status="RUNNING"
            )
            running_tasks: list = await sync_to_async(lambda: list(queryset))()

            cancelled_count = 0
            for task_history in running_tasks:
                try:
                    # Mark the task as cancelled
                    task_history.status = "CANCELLED"
                    task_history.completed_at = timezone.now()
                    task_history.error_message = "Task cancelled by user"
                    await task_history.asave()
                    cancelled_count += 1
                except Exception as e:
                    print(f"Failed to cancel running task {task_history.task_id}: {e}")

            return MutationResult(
                success=True,
                message=f"Successfully cancelled {cancelled_count} running tasks with name '{task_name}'",
            )

        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to cancel running tasks: {str(e)}"
            )

    async def cancel_all_tasks(self) -> MutationResult:
        """
        Cancel both pending and running tasks by updating database records.

        Note: With SQLAlchemy/PostgreSQL broker, we mark tasks as cancelled
        in the database instead of using control.revoke().
        """
        try:
            # Cancel pending tasks in Celery queue (from database)
            pending_result = await self.cancel_all_pending_tasks()

            # Cancel/clean up tasks marked as RUNNING in database
            from library_manager.models import TaskHistory

            queryset = TaskHistory.objects.filter(status="RUNNING")
            running_tasks: list = await sync_to_async(lambda: list(queryset))()
            cancelled_running_count = 0

            for task_history in running_tasks:
                try:
                    # Mark as cancelled in TaskHistory
                    task_history.status = "CANCELLED"
                    task_history.completed_at = timezone.now()
                    task_history.error_message = "Task cancelled by user"
                    await task_history.asave()

                    # Also mark as REVOKED in TaskResult if it exists
                    await TaskResult.objects.filter(
                        task_id=task_history.task_id
                    ).aupdate(status="REVOKED")
                    cancelled_running_count += 1
                except Exception as e:
                    print(f"Failed to cancel running task {task_history.task_id}: {e}")

            # Safely parse pending count from message; default to 0 if parsing fails
            try:
                pending_count = int(pending_result.message.split()[2])
            except Exception:
                pending_count = 0

            total_cancelled = pending_count + cancelled_running_count

            return MutationResult(
                success=True,
                message=f"Successfully cancelled {total_cancelled} total tasks ({pending_count} pending, {cancelled_running_count} running)",
            )

        except Exception as e:
            return MutationResult(
                success=True, message=f"No tasks to cancel ({str(e)})"
            )

    def get_pending_tasks(self) -> list:
        """
        Get list of pending tasks from database.

        Note: Uses database queries since inspect.active() doesn't work
        with SQLAlchemy broker.
        """
        try:
            tasks = TaskResult.objects.filter(
                status__in=["PENDING", "STARTED", "RETRY"]
            ).values("task_id", "task_name", "task_args", "task_kwargs")

            result = []
            for task in tasks:
                task_info = {
                    "id": task.get("task_id"),
                    "name": task.get("task_name", "unknown"),
                    "args": task.get("task_args", []),
                    "kwargs": task.get("task_kwargs", {}),
                }
                result.append(task_info)

            return result
        except Exception as e:
            # Re-raise the exception as expected by the test
            raise e

    async def get_pending_tasks_with_details(self) -> List[PendingTaskInfo]:
        """
        Get pending tasks with resolved entity names.

        Parses task arguments to extract entity IDs, then looks up
        the entity names from the database.
        """
        from library_manager.models import Album, Artist, Song, TrackedPlaylist

        def fetch_tasks_and_resolve() -> List[PendingTaskInfo]:
            tasks = TaskResult.objects.filter(
                status__in=["PENDING", "STARTED", "RETRY"]
            ).values(
                "task_id",
                "task_name",
                "task_args",
                "task_kwargs",
                "status",
                "date_created",
            )

            # Pre-fetch entities for efficiency
            artist_ids: set = set()
            album_ids: set = set()
            playlist_ids: set = set()
            playlist_urls: set = set()
            track_gids: set = set()  # Spotify track GIDs

            task_list = list(tasks)

            # First pass: collect entity IDs
            for task in task_list:
                task_name = task.get("task_name", "")
                args = _parse_json_field(task.get("task_args", "[]"))
                kwargs = _parse_json_field(task.get("task_kwargs", "{}"))

                entity_id = _extract_entity_id(task_name, args, kwargs)
                if entity_id:
                    entity_id_str = str(entity_id)
                    if "artist" in task_name.lower():
                        try:
                            artist_ids.add(int(entity_id))
                        except (ValueError, TypeError):
                            pass
                    elif "album" in task_name.lower():
                        try:
                            album_ids.add(int(entity_id))
                        except (ValueError, TypeError):
                            pass
                    elif "track" in task_name.lower():
                        # Track IDs are Spotify GIDs (strings), not database IDs
                        track_gids.add(entity_id_str)
                    elif "playlist" in task_name.lower():
                        if entity_id_str.startswith(
                            "spotify:"
                        ) or entity_id_str.startswith("http"):
                            playlist_urls.add(entity_id_str)
                        else:
                            try:
                                playlist_ids.add(int(entity_id))
                            except (ValueError, TypeError):
                                pass

            # Batch fetch entities
            artists = {a.id: a.name for a in Artist.objects.filter(id__in=artist_ids)}
            # For albums, include artist name for better context
            albums = {
                a.id: f"{a.artist.name} - {a.name}" if a.artist else a.name
                for a in Album.objects.select_related("artist").filter(id__in=album_ids)
            }
            # For tracks/songs, include artist name for better context
            # Songs are looked up by Spotify GID (not database ID)
            tracks = {
                s.gid: (
                    f"{s.primary_artist.name} - {s.name}"
                    if s.primary_artist
                    else s.name
                )
                for s in Song.objects.select_related("primary_artist").filter(
                    gid__in=track_gids
                )
            }
            playlists_by_id = {
                p.id: p.name
                for p in TrackedPlaylist.objects.filter(id__in=playlist_ids)
            }
            playlists_by_url = {
                p.url: p.name
                for p in TrackedPlaylist.objects.filter(url__in=playlist_urls)
            }

            # Second pass: build result with resolved names
            result: List[PendingTaskInfo] = []
            for task in task_list:
                task_name = task.get("task_name", "unknown")
                args = _parse_json_field(task.get("task_args", "[]"))
                kwargs = _parse_json_field(task.get("task_kwargs", "{}"))

                entity_type = _get_entity_type(task_name)
                entity_id = _extract_entity_id(task_name, args, kwargs)
                entity_name = None

                if entity_id and entity_type:
                    entity_id_str = str(entity_id)
                    if entity_type == "artist":
                        try:
                            entity_name = artists.get(int(entity_id))
                        except (ValueError, TypeError):
                            pass
                    elif entity_type == "album":
                        try:
                            entity_name = albums.get(int(entity_id))
                        except (ValueError, TypeError):
                            pass
                    elif entity_type == "track":
                        # Track IDs are Spotify GIDs (strings)
                        entity_name = tracks.get(entity_id_str)
                    elif entity_type == "playlist":
                        if entity_id_str.startswith(
                            "spotify:"
                        ) or entity_id_str.startswith("http"):
                            entity_name = playlists_by_url.get(entity_id_str)
                        else:
                            try:
                                entity_name = playlists_by_id.get(int(entity_id))
                            except (ValueError, TypeError):
                                pass

                created_at = task.get("date_created")
                created_at_str = created_at.isoformat() if created_at else None

                result.append(
                    PendingTaskInfo(
                        task_id=task.get("task_id", ""),
                        task_name=task_name,
                        display_name=_format_task_name(task_name),
                        entity_type=entity_type,
                        entity_id=str(entity_id) if entity_id else None,
                        entity_name=entity_name,
                        status=task.get("status", "PENDING"),
                        created_at=created_at_str,
                    )
                )

            return result

        return await sync_to_async(fetch_tasks_and_resolve)()

    async def cancel_task_by_id(self, task_id: str) -> MutationResult:
        """Cancel a single task by its ID."""
        try:
            from library_manager.models import TaskHistory

            # Update TaskResult to REVOKED
            updated = await TaskResult.objects.filter(
                task_id=task_id, status__in=["PENDING", "STARTED", "RETRY"]
            ).aupdate(status="REVOKED")

            # Also update TaskHistory if it exists
            await TaskHistory.objects.filter(
                task_id=task_id, status__in=["PENDING", "RUNNING"]
            ).aupdate(
                status="CANCELLED",
                completed_at=timezone.now(),
                error_message="Cancelled by user",
            )

            if updated > 0:
                return MutationResult(
                    success=True, message="Task cancelled successfully"
                )
            return MutationResult(
                success=False, message="Task not found or already completed"
            )

        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to cancel task: {str(e)}"
            )

    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Get overall queue status information from database.

        Note: Uses database queries only since inspect.active() doesn't work
        with SQLAlchemy broker (PostgreSQL).
        """

        # Count pending/started tasks from database
        total_tasks = await TaskResult.objects.filter(
            status__in=["PENDING", "STARTED", "RETRY"]
        ).acount()

        # Get task counts by name from database
        task_counts = await self.get_task_count_by_name()

        return {
            "total_pending_tasks": total_tasks,
            "task_counts": task_counts,
            "queue_size": total_tasks,
        }

    async def get_task_count_by_name(self) -> Dict[str, int]:
        """Get count of tasks by name from the database."""
        try:
            # Use sync_to_async for Django ORM operations
            queryset = TaskResult.objects.filter(
                status__in=["PENDING", "STARTED", "RETRY"]
            ).values("task_name")
            task_results: list = await sync_to_async(lambda: list(queryset))()

            task_counts = {}
            for task in task_results:
                task_name = task["task_name"]
                # Skip tasks with null or empty task names
                if not task_name:
                    continue
                if task_name not in task_counts:
                    task_counts[task_name] = 0
                task_counts[task_name] += 1

            return task_counts

        except Exception as e:
            print(f"Error getting task counts: {e}")
            return {}

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get status of a specific task from database.

        Checks TaskHistory first, then falls back to TaskResult.
        """
        try:
            from library_manager.models import TaskHistory

            # Try TaskHistory first
            try:
                task = await TaskHistory.objects.aget(task_id=task_id)
                return {
                    "task_id": task.task_id,
                    "status": task.status,
                    "type": task.type,
                    "started_at": task.started_at,
                    "completed_at": task.completed_at,
                    "error_message": task.error_message,
                }
            except TaskHistory.DoesNotExist:
                # Try TaskResult as fallback
                try:
                    task_result = await TaskResult.objects.aget(task_id=task_id)
                except TaskResult.DoesNotExist:
                    task_result = None

                if task_result:
                    return {
                        "task_id": task_id,
                        "status": task_result.status,
                        "type": task_result.task_name or "UNKNOWN",
                        "started_at": task_result.date_created,
                        "completed_at": task_result.date_done,
                        "error_message": None,
                    }

                return {"error": "Task not found"}

        except Exception as e:
            return {"error": f"Error getting task status: {str(e)}"}

    async def clear_completed_tasks(self, days_old: int = 7) -> MutationResult:
        """Clear completed tasks older than specified days."""
        try:
            from datetime import timedelta

            cutoff_date = timezone.now() - timedelta(days=days_old)

            # Use sync_to_async for Django ORM operations
            deleted_count = await sync_to_async(
                lambda: TaskResult.objects.filter(
                    status__in=["SUCCESS", "FAILURE", "REVOKED"],
                    date_done__lt=cutoff_date,
                ).delete()
            )()

            return MutationResult(
                success=True,
                message=f"Successfully cleared {deleted_count[0]} completed tasks older than {days_old} days",
            )

        except Exception as e:
            return MutationResult(
                success=False, message=f"Failed to clear completed tasks: {str(e)}"
            )
