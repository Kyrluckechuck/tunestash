"""
Celery app configuration for TuneStash.
"""

import logging
import os
import signal
import sys
from types import FrameType
from typing import Any, Optional

import django

import psutil
from celery import Celery
from celery.signals import (
    task_postrun,
    worker_process_init,
    worker_process_shutdown,
    worker_shutdown,
)

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

# Initialize Django before creating Celery app

django.setup()

# Configure logger for signal handlers (before Celery app creation)
logger = logging.getLogger("celery_diagnostics")

app = Celery("tunestash")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Task routing by service type to enable per-service concurrency control
app.conf.task_routes = {
    # Download tasks - route to 'downloads' queue (YouTube/spotdl - very rate-limited)
    "library_manager.tasks.download_missing_albums_for_artist": {"queue": "downloads"},
    "library_manager.tasks.download_single_album": {"queue": "downloads"},
    "library_manager.tasks.download_playlist": {"queue": "downloads"},
    "library_manager.tasks.download_extra_album_types_for_artist": {
        "queue": "downloads"
    },
    "library_manager.tasks.download_missing_tracked_artists": {"queue": "downloads"},
    # Spotify API tasks - route to 'spotify' queue (moderate rate limits)
    "library_manager.tasks.fetch_all_albums_for_artist": {"queue": "spotify"},
    "library_manager.tasks.sync_tracked_playlist": {"queue": "spotify"},
    "library_manager.tasks.sync_tracked_playlist_artists": {"queue": "spotify"},
    "library_manager.tasks.update_tracked_artists": {"queue": "spotify"},
    "library_manager.tasks.sync_tracked_playlists": {"queue": "spotify"},
    # Maintenance/cleanup tasks - route to default 'celery' queue
    "library_manager.tasks.cleanup_stuck_tasks_periodic": {"queue": "celery"},
    "library_manager.tasks.cleanup_celery_history": {"queue": "celery"},
    # Fallback for any other tasks
    "library_manager.tasks.*": {"queue": "celery"},
}

# Task priority configuration
app.conf.task_default_priority = 5
app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True
app.conf.worker_disable_rate_limits = (
    False  # Enable rate limits for concurrency control
)

# Per-task rate limits to control concurrency (rate_limit format: "tasks/time_period")
# Download tasks: Limit to 2 concurrent (YouTube is very rate-sensitive)
app.conf.task_annotations = {
    "library_manager.tasks.download_missing_albums_for_artist": {"rate_limit": "2/s"},
    "library_manager.tasks.download_single_album": {"rate_limit": "2/s"},
    "library_manager.tasks.download_playlist": {"rate_limit": "2/s"},
    "library_manager.tasks.download_extra_album_types_for_artist": {
        "rate_limit": "2/s"
    },
    "library_manager.tasks.download_missing_tracked_artists": {"rate_limit": "2/s"},
    # Spotify tasks: Conservative rate to avoid 429s at startup when many tasks queue
    # (Spotify API is 180 req/min = 3/sec, but bursts cause issues)
    "library_manager.tasks.fetch_all_albums_for_artist": {"rate_limit": "2/s"},
    "library_manager.tasks.sync_tracked_playlist": {"rate_limit": "2/s"},
    "library_manager.tasks.sync_tracked_playlist_artists": {"rate_limit": "2/s"},
    "library_manager.tasks.update_tracked_artists": {"rate_limit": "2/s"},
    "library_manager.tasks.sync_tracked_playlists": {"rate_limit": "2/s"},
}

# Ensure all task results include task names
app.conf.result_extended = True
app.conf.task_track_started = True


@app.task(bind=True, name="celery_app.debug_task")  # type: ignore[misc]
def debug_task(self: "Celery.Task") -> None:
    """Debug task for testing Celery configuration."""
    print(f"Request: {self.request!r}")


# ============================================================================
# Worker Diagnostics and Signal Handlers
# ============================================================================


def get_memory_info() -> dict:
    """Get current process memory usage information."""
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        return {
            "rss_mb": memory_info.rss / 1024 / 1024,  # Resident Set Size in MB
            "vms_mb": memory_info.vms / 1024 / 1024,  # Virtual Memory Size in MB
            "percent": process.memory_percent(),
        }
    except Exception as e:
        return {"error": str(e)}


def log_process_state(reason: str) -> None:
    """Log comprehensive process state for diagnostics."""
    try:
        process = psutil.Process(os.getpid())
        memory = get_memory_info()

        logger.critical(
            f"[WORKER DIAGNOSTIC] {reason} - "
            f"PID: {os.getpid()}, "
            f"Memory RSS: {memory.get('rss_mb', 'N/A'):.2f} MB, "
            f"Memory %: {memory.get('percent', 'N/A'):.2f}%, "
            f"Threads: {process.num_threads()}, "
            f"Status: {process.status()}"
        )
    except Exception as e:
        logger.error(f"[WORKER DIAGNOSTIC] Failed to log process state: {e}")


def signal_handler(signum: int, frame: Optional[FrameType]) -> None:
    """
    Handle termination signals to log diagnostic information before shutdown.

    This helps identify WHY the worker was killed (OOM, Docker, manual kill, etc.)
    """
    signal_names: dict[int, str] = {
        signal.SIGTERM: "SIGTERM (graceful shutdown requested)",
        signal.SIGINT: "SIGINT (interrupt from keyboard)",
        signal.SIGQUIT: "SIGQUIT (quit from keyboard)",
    }
    signal_name = signal_names.get(signum, f"Signal {signum}")

    log_process_state(f"Received {signal_name}")

    # Get active task info if available
    try:
        from celery import current_task

        if current_task and current_task.request:
            logger.critical(
                f"[WORKER DIAGNOSTIC] Active task: {current_task.name}, "
                f"Task ID: {current_task.request.id}"
            )
    except Exception as e:
        logger.warning(f"[WORKER DIAGNOSTIC] Could not get active task info: {e}")

    # Re-raise the signal to allow normal shutdown
    sys.exit(128 + signum)


# Register signal handlers only when running in the main thread
# This prevents errors when celery_app is imported from async contexts (e.g., FastAPI)
def _register_signal_handlers() -> None:
    """
    Register signal handlers for worker processes.

    Only registers if we're in the main thread, since signal.signal()
    can only be called from the main thread of the main interpreter.
    """
    import threading

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)


_register_signal_handlers()


# ============================================================================
# Worker Lifecycle Hooks
# ============================================================================


@worker_process_init.connect  # type: ignore[misc]
def worker_process_init_handler(sender: Any = None, **kwargs: Any) -> None:
    """Log when worker process starts."""
    from django.conf import settings

    diagnostics_enabled = getattr(settings, "worker_diagnostics_enabled", False)
    if diagnostics_enabled:
        logger.info(
            f"[WORKER LIFECYCLE] Worker process started - PID: {os.getpid()}, "
            f"Parent PID: {os.getppid()}"
        )
        log_process_state("Worker process initialization")

    # Always check and log Spotify rate limit status on startup
    _log_spotify_rate_limit_status()


def _log_spotify_rate_limit_status() -> None:
    """Check and log Spotify API rate limit status on worker startup.

    This helps identify if Spotify has banned our credentials before
    we start making API calls that will immediately fail.
    """
    try:
        from library_manager.models import SpotifyRateLimitState

        rate_status = SpotifyRateLimitState.get_status()
        if rate_status["is_rate_limited"]:
            seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
            hours = seconds_remaining / 3600
            logger.warning(
                "\n"
                "╔════════════════════════════════════════════════════════════════════╗\n"
                "║  🚨  SPOTIFY API IS RATE LIMITED!                                  ║\n"
                "╠════════════════════════════════════════════════════════════════════╣\n"
                f"║  Time remaining: {hours:.1f} hours ({seconds_remaining} seconds)".ljust(
                    72
                )
                + "║\n"
                "║                                                                    ║\n"
                "║  All Spotify API calls will be blocked until the rate limit       ║\n"
                "║  expires. Download and sync tasks will be rescheduled.            ║\n"
                "║                                                                    ║\n"
                "║  If this happens frequently, ensure you're using your own         ║\n"
                "║  Spotify Developer credentials (SPOTIPY_CLIENT_ID/SECRET).        ║\n"
                "╚════════════════════════════════════════════════════════════════════╝"
            )
        else:
            # Log current rate limit bucket status
            burst = rate_status.get("burst_calls", 0)
            burst_max = rate_status.get("burst_max", 10)
            sustained = rate_status.get("sustained_calls", 0)
            sustained_max = rate_status.get("sustained_max", 100)
            logger.info(
                f"[SPOTIFY API] Rate limit status OK - "
                f"burst: {burst}/{burst_max}, sustained: {sustained}/{sustained_max}"
            )
    except Exception as e:
        logger.warning(f"[SPOTIFY API] Could not check rate limit status: {e}")


@worker_process_shutdown.connect  # type: ignore[misc]
def worker_process_shutdown_handler(sender: Any = None, **kwargs: Any) -> None:
    """Log when worker process shuts down (only if diagnostics enabled)."""
    from django.conf import settings

    diagnostics_enabled = getattr(settings, "worker_diagnostics_enabled", False)
    if diagnostics_enabled:
        logger.warning(
            f"[WORKER LIFECYCLE] Worker process shutting down - PID: {os.getpid()}"
        )
        log_process_state("Worker process shutdown")


@worker_shutdown.connect  # type: ignore[misc]
def worker_shutdown_handler(sender: Any = None, **kwargs: Any) -> None:
    """Log when main worker shuts down (only if diagnostics enabled)."""
    from django.conf import settings

    diagnostics_enabled = getattr(settings, "worker_diagnostics_enabled", False)
    if diagnostics_enabled:
        logger.warning(
            f"[WORKER LIFECYCLE] Main worker shutting down - PID: {os.getpid()}"
        )
        log_process_state("Main worker shutdown")


# ============================================================================
# Post-Task Memory Management
# ============================================================================

# Memory thresholds in MB (per-worker, not container total)
# With 2 workers + main process, aim for ~800MB each to stay under 2GB container limit
MEMORY_WARNING_THRESHOLD_MB = 600
MEMORY_CRITICAL_THRESHOLD_MB = 700
MEMORY_RECYCLE_THRESHOLD_MB = 800

# Track peak memory per worker for reporting
_worker_peak_memory_mb: float = 0.0


def try_release_memory() -> tuple[bool, float, float]:
    """
    Attempt to release memory back to the OS.

    Python's allocator (pymalloc) doesn't normally return memory to the OS.
    On Linux with glibc, we can use malloc_trim() to force this.

    Returns tuple of (success, gc_released_mb, malloc_trim_released_mb).
    """
    import gc

    import psutil

    process = psutil.Process(os.getpid())
    initial_rss = process.memory_info().rss / 1024 / 1024

    # First, run garbage collection to free Python objects
    gc.collect()

    after_gc = process.memory_info().rss / 1024 / 1024
    gc_released = initial_rss - after_gc

    # On Linux, try to use malloc_trim to release memory back to OS
    malloc_trim_released = 0.0
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        # malloc_trim(0) tells glibc to release as much memory as possible
        libc.malloc_trim(0)

        after_malloc_trim = process.memory_info().rss / 1024 / 1024
        malloc_trim_released = after_gc - after_malloc_trim
        return True, gc_released, malloc_trim_released
    except (OSError, AttributeError):
        # Not on Linux or glibc not available
        return False, gc_released, 0.0


def request_worker_shutdown() -> None:
    """
    Request graceful shutdown of this worker process.

    This sends SIGUSR1 to the parent (main worker) which tells Celery
    to restart this specific worker process after the current task completes.
    """
    try:
        # Send SIGTERM to ourselves - Celery will handle this gracefully
        # and restart the worker process
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception as e:
        logger.error(f"[MEMORY] Failed to request worker shutdown: {e}")


@task_postrun.connect  # type: ignore[misc]
def task_postrun_memory_check(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    retval: Any = None,
    state: Optional[str] = None,
    **kw: Any,
) -> None:
    """
    Log memory usage after each task completes and manage memory proactively.

    This hook:
    1. Logs memory usage at appropriate levels (INFO/WARNING/CRITICAL)
    2. Attempts to release memory back to OS using malloc_trim
    3. Requests graceful worker restart if memory exceeds recycle threshold
    """
    global _worker_peak_memory_mb

    try:
        memory = get_memory_info()
        if "error" in memory:
            return

        rss_mb = memory["rss_mb"]
        task_name = task.name if task else "unknown"

        # Update peak tracking
        if rss_mb > _worker_peak_memory_mb:
            _worker_peak_memory_mb = rss_mb

        # Try to release memory if above warning threshold
        if rss_mb >= MEMORY_WARNING_THRESHOLD_MB:
            _, gc_released, malloc_trim_released = try_release_memory()
            # Re-check memory after release attempt
            new_memory = get_memory_info()
            if "error" not in new_memory:
                total_released = rss_mb - new_memory["rss_mb"]
                if total_released > 1:  # Only log if meaningful release
                    logger.info(
                        f"[MEMORY POST-TASK] gc: {gc_released:.1f}MB, "
                        f"malloc_trim: {malloc_trim_released:.1f}MB, "
                        f"total: {total_released:.1f}MB "
                        f"({rss_mb:.1f} -> {new_memory['rss_mb']:.1f} MB)"
                    )
                rss_mb = new_memory["rss_mb"]

        # Determine log level and action based on memory usage
        if rss_mb >= MEMORY_RECYCLE_THRESHOLD_MB:
            logger.critical(
                f"[MEMORY RECYCLE] {rss_mb:.1f} MB after {task_name} exceeds "
                f"recycle threshold ({MEMORY_RECYCLE_THRESHOLD_MB} MB) - "
                f"requesting graceful worker restart. PID: {os.getpid()}"
            )
            request_worker_shutdown()
        elif rss_mb >= MEMORY_CRITICAL_THRESHOLD_MB:
            logger.critical(
                f"[MEMORY CRITICAL] {rss_mb:.1f} MB after {task_name} "
                f"(peak: {_worker_peak_memory_mb:.1f} MB) - "
                f"PID: {os.getpid()}, Task: {task_id}"
            )
        elif rss_mb >= MEMORY_WARNING_THRESHOLD_MB:
            logger.warning(
                f"[MEMORY WARNING] {rss_mb:.1f} MB after {task_name} "
                f"(peak: {_worker_peak_memory_mb:.1f} MB) - "
                f"PID: {os.getpid()}, Task: {task_id}"
            )
        else:
            # Standard info logging - useful for tracking memory growth over time
            logger.info(
                f"[MEMORY] {rss_mb:.1f} MB after {task_name} - PID: {os.getpid()}"
            )

    except Exception as e:
        logger.debug(f"[MEMORY] Failed to check post-task memory: {e}")
