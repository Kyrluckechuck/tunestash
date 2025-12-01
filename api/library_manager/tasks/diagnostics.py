"""Diagnostic tasks for memory profiling and debugging.

These tasks are designed to be run on-demand in production to diagnose
memory issues without impacting normal operation.

Includes:
- On-demand memory profiling tasks (tracemalloc, object counts, etc.)
- Periodic memory health check task for early warning of memory issues
"""

import gc
import linecache
import logging
import os
import sys
import tracemalloc
from typing import Any, Dict, List, Optional

import psutil
from celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _get_process_memory() -> Dict[str, Any]:
    """Get current process memory statistics."""
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return {
        "rss_mb": round(mem_info.rss / 1024 / 1024, 2),
        "vms_mb": round(mem_info.vms / 1024 / 1024, 2),
        "percent": round(process.memory_percent(), 2),
        "pid": os.getpid(),
    }


def _get_top_malloc_stats(
    snapshot: tracemalloc.Snapshot, limit: int = 30
) -> List[Dict]:
    """Get top memory allocations from tracemalloc snapshot."""
    stats = snapshot.statistics("lineno")
    results = []

    for stat in stats[:limit]:
        frame = stat.traceback[0]
        results.append(
            {
                "file": frame.filename,
                "line": frame.lineno,
                "size_mb": round(stat.size / 1024 / 1024, 4),
                "count": stat.count,
                "code": linecache.getline(frame.filename, frame.lineno).strip(),
            }
        )

    return results


def _get_top_malloc_by_file(
    snapshot: tracemalloc.Snapshot, limit: int = 20
) -> List[Dict]:
    """Get memory allocations grouped by file."""
    stats = snapshot.statistics("filename")
    results = []

    for stat in stats[:limit]:
        results.append(
            {
                "file": stat.traceback[0].filename,
                "size_mb": round(stat.size / 1024 / 1024, 4),
                "count": stat.count,
            }
        )

    return results


def _get_object_counts(limit: int = 30) -> List[Dict]:
    """Get counts of most common object types in memory."""
    gc.collect()

    type_counts: Dict[str, int] = {}
    for obj in gc.get_objects():
        obj_type = type(obj).__name__
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

    sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)

    return [{"type": t, "count": c} for t, c in sorted_types[:limit]]


def _get_large_objects(min_size_kb: int = 100, limit: int = 20) -> List[Dict[str, Any]]:
    """Find large objects in memory."""
    gc.collect()
    large_objects: List[Dict[str, Any]] = []

    for obj in gc.get_objects():
        try:
            size = sys.getsizeof(obj)
            if size >= min_size_kb * 1024:
                large_objects.append(
                    {
                        "type": type(obj).__name__,
                        "size_kb": round(size / 1024, 2),
                        "repr": repr(obj)[:200],
                    }
                )
        except (TypeError, ReferenceError):
            continue

    large_objects.sort(key=lambda x: x["size_kb"], reverse=True)
    return large_objects[:limit]


@celery_app.task(bind=True, name="library_manager.tasks.memory_profile_worker")
def memory_profile_worker(
    self: Any,
    include_tracemalloc: bool = True,
    include_object_counts: bool = True,
    include_large_objects: bool = False,
    tracemalloc_limit: int = 30,
) -> Dict[str, Any]:
    """
    Profile memory usage of the current worker process.

    This task runs on whichever worker picks it up and returns detailed
    memory information about that worker's process.

    Args:
        include_tracemalloc: Include detailed allocation tracking (slight overhead)
        include_object_counts: Include object type counts
        include_large_objects: Include scan for large objects (slower)
        tracemalloc_limit: Number of top allocations to include

    Returns:
        Dictionary with memory profiling results
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
    }

    # Basic process memory
    results["process_memory"] = _get_process_memory()

    # Tracemalloc detailed allocations
    if include_tracemalloc:
        # Start tracemalloc if not already running
        was_tracing = tracemalloc.is_tracing()
        if not was_tracing:
            tracemalloc.start()

        # Force garbage collection to get accurate picture
        gc.collect()

        # Take snapshot
        snapshot = tracemalloc.take_snapshot()

        results["allocations_by_line"] = _get_top_malloc_stats(
            snapshot, tracemalloc_limit
        )
        results["allocations_by_file"] = _get_top_malloc_by_file(snapshot)

        # Get tracemalloc's own stats
        traced_mem, peak_mem = tracemalloc.get_traced_memory()
        results["tracemalloc_stats"] = {
            "traced_mb": round(traced_mem / 1024 / 1024, 2),
            "peak_mb": round(peak_mem / 1024 / 1024, 2),
        }

        # Stop if we started it
        if not was_tracing:
            tracemalloc.stop()

    # Object counts
    if include_object_counts:
        results["object_counts"] = _get_object_counts()

    # Large objects (slower, optional)
    if include_large_objects:
        results["large_objects"] = _get_large_objects()

    return results


@celery_app.task(bind=True, name="library_manager.tasks.memory_profile_after_init")
def memory_profile_after_init(self: Any) -> Dict[str, Any]:
    """
    Profile memory after SpotdlWrapper initialization.

    This is useful for understanding the baseline memory cost of
    the download infrastructure before any tasks run.
    """
    from library_manager.tasks.core import spotdl_wrapper  # noqa: F401 - ensures init

    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
        "description": "Memory after SpotdlWrapper initialization",
    }

    results["process_memory"] = _get_process_memory()

    # Check what's loaded
    loaded_modules = [
        name
        for name in sys.modules
        if any(x in name for x in ["spotdl", "yt_dlp", "ytmusic", "spotipy"])
    ]
    results["relevant_modules"] = sorted(loaded_modules)

    return results


@celery_app.task(bind=True, name="library_manager.tasks.memory_compare_before_after")
def memory_compare_before_after(
    self: Any,
    spotify_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare memory before and after a simulated download operation.

    If spotify_uri is provided, does a metadata fetch (no actual download).
    Otherwise just measures the current state.

    Args:
        spotify_uri: Optional Spotify URI to fetch metadata for

    Returns:
        Memory comparison results
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
    }

    gc.collect()
    results["before"] = _get_process_memory()

    if spotify_uri:
        # Import and use spotdl_wrapper to simulate real usage
        from library_manager.tasks.core import spotdl_wrapper

        try:
            # Just fetch metadata, don't actually download
            song_info = spotdl_wrapper.downloader.get_download_queue(
                url=spotify_uri,
                include_metadata=True,
            )
            results["metadata_fetched"] = True
            results["tracks_found"] = (
                len(song_info[0]) if isinstance(song_info, tuple) else len(song_info)
            )
        except Exception as e:
            results["metadata_error"] = str(e)

    gc.collect()
    results["after"] = _get_process_memory()

    # Calculate delta
    results["delta_mb"] = round(
        results["after"]["rss_mb"] - results["before"]["rss_mb"], 2
    )

    return results


# ============================================================================
# Periodic Memory Health Check
# ============================================================================

# Thresholds for periodic health check (in MB)
MEMORY_HEALTHY_THRESHOLD_MB = 600
MEMORY_WARNING_THRESHOLD_MB = 800
MEMORY_CRITICAL_THRESHOLD_MB = 1200


@celery_app.task(bind=True, name="library_manager.tasks.periodic_memory_health_check")
def periodic_memory_health_check(self: Any) -> Dict[str, Any]:
    """
    Periodic task to check memory health of workers.

    This task is designed to run every 10-15 minutes to provide early
    warning of memory issues before they cause OOM kills.

    Returns:
        Dictionary with memory health status and recommendations
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
    }

    gc.collect()
    memory = _get_process_memory()
    results["memory"] = memory

    rss_mb = memory["rss_mb"]

    # Determine health status
    if rss_mb >= MEMORY_CRITICAL_THRESHOLD_MB:
        results["status"] = "CRITICAL"
        results["message"] = (
            f"Memory usage critical ({rss_mb:.1f} MB). "
            f"Worker may be killed by OOM soon. Consider restarting workers."
        )
        logger.critical(
            f"[MEMORY HEALTH] CRITICAL - {rss_mb:.1f} MB on PID {os.getpid()}. "
            f"OOM risk is high!"
        )
    elif rss_mb >= MEMORY_WARNING_THRESHOLD_MB:
        results["status"] = "WARNING"
        results["message"] = (
            f"Memory usage elevated ({rss_mb:.1f} MB). "
            f"Worker recycling should occur soon via --max-tasks-per-child."
        )
        logger.warning(
            f"[MEMORY HEALTH] WARNING - {rss_mb:.1f} MB on PID {os.getpid()}. "
            f"Elevated but not critical."
        )
    elif rss_mb >= MEMORY_HEALTHY_THRESHOLD_MB:
        results["status"] = "OK"
        results["message"] = f"Memory usage normal ({rss_mb:.1f} MB)."
        logger.info(f"[MEMORY HEALTH] OK - {rss_mb:.1f} MB on PID {os.getpid()}")
    else:
        results["status"] = "HEALTHY"
        results["message"] = f"Memory usage healthy ({rss_mb:.1f} MB)."
        logger.info(f"[MEMORY HEALTH] HEALTHY - {rss_mb:.1f} MB on PID {os.getpid()}")

    # Include some context about the worker
    try:
        process = psutil.Process(os.getpid())
        results["worker_info"] = {
            "threads": process.num_threads(),
            "cpu_percent": process.cpu_percent(),
            "create_time": process.create_time(),
        }
    except Exception:
        pass

    return results
