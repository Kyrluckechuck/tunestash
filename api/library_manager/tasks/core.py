"""Core task utilities and helper functions.

This module contains shared utilities used across all task modules:
- Task history management (create, update, complete)
- Progress tracking and cancellation checks
- Memory usage logging
- Download capability validation
- Task priority constants
- Name normalization for cross-provider matching
"""

import os
import re
import time
import unicodedata
import uuid
from functools import wraps
from typing import Any, Callable, Optional, cast

from django.conf import settings

import psutil
from celery.utils.log import get_task_logger
from celery_app import app as celery_app  # noqa: F401 - re-exported

from ..models import TaskHistory
from ..task_priorities import TaskPriority  # noqa: F401 - re-exported

# Circuit breaker: when True, download tasks are rejected immediately
# without re-checking auth (saves API calls during extended outages).
# Re-checked every _PAUSE_RECHECK_SECONDS to detect credential renewal.
_downloads_paused = False  # pylint: disable=invalid-name
_downloads_paused_at: float = 0.0  # pylint: disable=invalid-name
_PAUSE_RECHECK_SECONDS = 900  # 15 minutes


class TaskCancelledException(Exception):
    """Raised when a task has been cancelled and should stop execution."""


# Initialize Celery logger
logger = get_task_logger(__name__)


_TRADEMARK_RE = re.compile(r"[®™©]|\((?:R|TM|C)\)", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^\w\s]|_")
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalize a name for fuzzy cross-provider comparison.

    Handles accent stripping, punctuation, trademark symbols, and
    ampersand/and equivalence. Whitespace is preserved (collapsed to
    single spaces) so that compound-word differences like
    "New Man" vs "Newman" remain distinct and fall through to
    track-level matching.
    """
    s = name.replace("&", " and ")
    s = _TRADEMARK_RE.sub("", s)
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s.lower()


_DEEZER_PLAYLIST_RE = re.compile(r"deezer\.com/(?:\w+/)?playlist/(\d+)")


def extract_deezer_playlist_id(url: str) -> Optional[str]:
    """Extract the numeric playlist ID from a Deezer playlist URL."""
    match = _DEEZER_PLAYLIST_RE.search(url)
    return match.group(1) if match else None


def log_memory_usage(context: str, task_id: Optional[str] = None) -> None:
    """Log current memory usage for diagnostics (only if enabled in settings)."""
    diagnostics_enabled = getattr(settings, "worker_diagnostics_enabled", False)
    if not diagnostics_enabled:
        return

    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        rss_mb = memory_info.rss / 1024 / 1024
        memory_percent = process.memory_percent()

        log_msg = (
            f"[MEMORY] {context} - "
            f"RSS: {rss_mb:.2f} MB, "
            f"Memory %: {memory_percent:.2f}%"
        )
        if task_id:
            log_msg += f", Task: {task_id}"

        logger.info(log_msg)
    except Exception as e:
        logger.warning(f"[MEMORY] Failed to log memory usage: {e}")


def create_task_history(
    task_id: Optional[str] = None,
    task_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    task_name: Optional[str] = None,
) -> TaskHistory:
    """Create a task history record for tracking task execution"""
    if task_id is None:
        # Create task ID if not provided
        entity_type_str = entity_type or "unknown"
        if entity_id:
            generated_task_id = f"{task_type}-{entity_type_str.lower()}-{entity_id}"
        else:
            generated_task_id = f"{task_name or 'unknown'}-{uuid.uuid4().hex[:8]}"
    else:
        generated_task_id = task_id

    # Check if task history already exists for this task
    existing_task = TaskHistory.objects.filter(task_id=generated_task_id).first()
    if existing_task:
        return existing_task

    # Log memory usage at task start
    log_memory_usage(f"Task created: {task_type}/{entity_type}", generated_task_id)

    # Create new task history record
    task_history = TaskHistory(
        task_id=generated_task_id,
        type=task_type or "UNKNOWN",
        entity_id=str(entity_id) if entity_id else "unknown",
        entity_type=entity_type or "UNKNOWN",
        status="PENDING",
    )
    task_history.save()
    return task_history


def update_task_progress(
    task_history: TaskHistory, progress: float, message: Optional[str] = None
) -> None:
    """Update task progress, heartbeat, and add log message"""
    task_history.status = "RUNNING"
    task_history.progress_percentage = progress
    task_history.update_heartbeat()  # Update heartbeat on progress
    if message:
        task_history.add_log_message(message)
    task_history.save()


def update_task_heartbeat(task_history: TaskHistory) -> None:
    """Update task heartbeat (no log message)"""
    task_history.update_heartbeat()


def complete_task(
    task_history: TaskHistory, success: bool = True, error_message: Optional[str] = None
) -> None:
    """Mark task as completed or failed"""
    # Log memory usage at task completion
    status_str = "completed" if success else f"failed: {error_message}"
    log_memory_usage(f"Task {status_str}", task_history.task_id)

    if success:
        task_history.mark_completed()
    else:
        task_history.mark_failed(error_message)


def check_task_cancellation(task_history: TaskHistory) -> bool:
    """Check if the task has been cancelled by checking the database status."""
    # Refresh from database to get latest status
    task_history.refresh_from_db()
    status_str: str = cast(str, task_history.status)
    return status_str == "CANCELLED"


def check_if_cancelled(task_id: str) -> None:
    """
    Check if task has been cancelled. Raise TaskCancelledException if it has.

    This function checks both TaskResult (for queued tasks marked as REVOKED)
    and TaskHistory (for running tasks marked as CANCELLED).

    Call this at safe checkpoints in long-running tasks (e.g., after each song/album).

    Args:
        task_id: The Celery task ID to check

    Raises:
        TaskCancelledException: If the task has been cancelled
    """
    from django_celery_results.models import TaskResult

    # Check TaskResult first (for pending/queued tasks marked as REVOKED)
    try:
        task_result = TaskResult.objects.filter(task_id=task_id).first()
        if task_result and task_result.status == "REVOKED":
            logger.info(f"Task {task_id} cancelled via TaskResult (REVOKED)")
            raise TaskCancelledException(f"Task {task_id} was cancelled")
    except TaskResult.DoesNotExist:
        pass

    # Check TaskHistory (for running tasks marked as CANCELLED)
    try:
        task_history = TaskHistory.objects.filter(task_id=task_id).first()
        if task_history and task_history.status == "CANCELLED":
            logger.info(f"Task {task_id} cancelled via TaskHistory (CANCELLED)")
            raise TaskCancelledException(f"Task {task_id} was cancelled")
    except TaskHistory.DoesNotExist:
        pass


def skip_if_cancelled(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that checks if task is cancelled before starting execution.

    If the task has been cancelled (REVOKED or CANCELLED status), it will be skipped
    and return a cancellation result instead of executing.

    Usage:
        @shared_task(bind=True)
        @skip_if_cancelled
        def my_task(self, arg1, arg2):
            # Task code here
    """

    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        task_id = self.request.id
        try:
            check_if_cancelled(task_id)
        except TaskCancelledException:
            logger.info(f"Task {task_id} skipped - already cancelled before start")
            return {
                "status": "cancelled",
                "skipped": True,
                "message": "Task was cancelled before execution started",
            }

        # Execute task
        return func(self, *args, **kwargs)

    return wrapper


def check_and_update_progress(
    task_history: TaskHistory, progress: float, message: Optional[str] = None
) -> bool:
    """Update task progress and check for cancellation. Returns True if cancelled."""
    if check_task_cancellation(task_history):
        return True

    update_task_progress(task_history, progress, message)
    return False


def _pause_downloads_queue(reason: str) -> None:
    """Stop consuming from the downloads queue so tasks stay queued, not lost."""
    global _downloads_paused, _downloads_paused_at  # pylint: disable=global-statement
    if _downloads_paused:
        return
    _downloads_paused = True
    _downloads_paused_at = time.monotonic()
    try:
        celery_app.control.cancel_consumer("downloads")
        logger.critical(
            "[AUTH] Downloads queue paused: %s. "
            "Renew credentials and restart the stack to resume.",
            reason,
        )
    except Exception as exc:
        logger.error("[AUTH] Failed to cancel downloads consumer: %s", exc)


def resume_downloads_queue() -> None:
    """Re-enable the downloads queue consumer (called when auth is restored)."""
    global _downloads_paused, _downloads_paused_at  # pylint: disable=global-statement
    if not _downloads_paused:
        return
    _downloads_paused = False
    _downloads_paused_at = 0.0
    try:
        celery_app.control.add_consumer("downloads")
        logger.info("[AUTH] Downloads queue resumed — authentication restored.")
    except Exception as exc:
        logger.error("[AUTH] Failed to re-add downloads consumer: %s", exc)


def require_download_capability(task_history: Optional[TaskHistory] = None) -> None:
    """Check authentication status and block task execution if downloads are not possible.

    This function verifies that the system has valid authentication (cookies) before
    allowing download tasks to proceed. If authentication is invalid or expired, the
    task is failed immediately to prevent wasted API calls.

    When ``pause_downloads_on_auth_failure`` is enabled (default), the first failure
    also pauses the downloads queue so queued tasks are preserved rather than
    drained as failures.

    Args:
        task_history: Optional task history to update with failure status if auth fails

    Raises:
        RuntimeError: If downloads are not possible due to authentication issues
    """
    from src.services.system_health import SystemHealthService

    # Fast path: if paused and not yet time to re-check, reject immediately
    if _downloads_paused:
        elapsed = time.monotonic() - _downloads_paused_at
        if elapsed < _PAUSE_RECHECK_SECONDS:
            error_msg = "Downloads paused due to auth failure — waiting for renewal"
            if task_history:
                task_history.status = "FAILED"
                task_history.add_log_message(error_msg)
                task_history.save()
            raise RuntimeError(error_msg)
        logger.info("[AUTH] Re-checking download capability after pause window...")

    can_download, reason = SystemHealthService.is_download_capable()
    if not can_download:
        pause_enabled = getattr(settings, "PAUSE_DOWNLOADS_ON_AUTH_FAILURE", True)
        if pause_enabled and reason:
            _pause_downloads_queue(reason)

        error_msg = f"Cannot download: {reason}"
        logger.error(error_msg)
        if task_history:
            task_history.status = "FAILED"
            task_history.add_log_message(error_msg)
            task_history.save()
        raise RuntimeError(error_msg)

    # Auth is valid — if we were paused, resume
    if _downloads_paused:
        resume_downloads_queue()


def check_spotify_rate_limit() -> Optional[int]:
    """Check if Spotify API is rate limited and return retry delay if so.

    This should be called at the very START of download tasks, BEFORE creating
    task history records or doing any other work. This prevents the "hammering"
    pattern where many queued tasks all start up and immediately fail.

    Returns:
        None if not rate limited, otherwise the number of seconds to wait.
        Tasks should use this value with Celery's self.retry(countdown=...).
    """
    from ..models import SpotifyRateLimitState

    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        if seconds_remaining > 0:
            return int(seconds_remaining)
    return None
