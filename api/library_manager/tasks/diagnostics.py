"""Diagnostic tasks for memory profiling and debugging.

These tasks are designed to be run on-demand in production to diagnose
memory issues without impacting normal operation.

Includes:
- On-demand memory profiling tasks (tracemalloc, object counts, etc.)
- Periodic memory health check task for early warning of memory issues
- Container-level memory monitoring to detect main process leaks
"""

import gc
import linecache
import logging
import os
import signal
import sys
import tracemalloc
from typing import Any, Dict, List, Tuple

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


def _get_parent_process_memory() -> Dict[str, Any]:
    """
    Get memory statistics for the parent (main Celery) process.

    This allows workers to monitor the parent process's memory, which
    is where the memory leak actually occurs in Celery's prefork pool.
    """
    try:
        parent_pid = os.getppid()
        parent = psutil.Process(parent_pid)
        mem_info = parent.memory_info()

        # Get memory maps summary (shows where memory is allocated)
        memory_maps_summary: Dict[str, float] = {}
        try:
            for mmap in parent.memory_maps(grouped=True):
                # Group by path type
                path = mmap.path
                if path.startswith("["):
                    key = path  # [heap], [stack], [anon], etc.
                elif path.startswith("/"):
                    # Simplify library paths
                    if "python" in path.lower():
                        key = "[python-libs]"
                    elif ".so" in path:
                        key = "[shared-libs]"
                    else:
                        key = "[mapped-files]"
                else:
                    key = "[other]"
                memory_maps_summary[key] = memory_maps_summary.get(key, 0) + mmap.rss
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # Convert to MB
        maps_mb = {k: round(v / 1024 / 1024, 2) for k, v in memory_maps_summary.items()}

        return {
            "rss_mb": round(mem_info.rss / 1024 / 1024, 2),
            "vms_mb": round(mem_info.vms / 1024 / 1024, 2),
            "percent": round(parent.memory_percent(), 2),
            "pid": parent_pid,
            "num_threads": parent.num_threads(),
            "num_fds": parent.num_fds(),
            "memory_maps": maps_mb,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return {"error": str(e), "pid": os.getppid()}


def _get_all_celery_processes() -> List[Dict[str, Any]]:
    """
    Get memory info for all Celery-related processes in the container.

    This helps understand where memory is distributed across main + workers.
    """
    processes = []
    current_pid = os.getpid()
    parent_pid = os.getppid()

    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "memory_info"]):
        try:
            info = proc.info
            cmdline = " ".join(info.get("cmdline") or [])

            # Only include celery-related processes
            if "celery" not in cmdline.lower():
                continue

            mem = info.get("memory_info")
            if not mem:
                continue

            role = "unknown"
            if info["pid"] == parent_pid:
                role = "main"
            elif info["pid"] == current_pid:
                role = "this-worker"
            elif info.get("ppid") == parent_pid:
                role = "sibling-worker"

            processes.append(
                {
                    "pid": info["pid"],
                    "role": role,
                    "rss_mb": round(mem.rss / 1024 / 1024, 2),
                    "vms_mb": round(mem.vms / 1024 / 1024, 2),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(processes, key=lambda x: x["rss_mb"], reverse=True)


def _get_container_memory() -> Tuple[float, float]:
    """
    Get total memory usage for all processes in the container.

    The main Celery process (parent) leaks memory over time, but worker tasks
    only see their own process memory. This function reads cgroup stats to get
    the total container memory, which includes the leaking parent process.

    Returns:
        Tuple of (current_mb, limit_mb). limit_mb is 0 if no limit detected.
    """
    # Try cgroup v2 first (modern Docker/containerd)
    try:
        with open("/sys/fs/cgroup/memory.current", encoding="utf-8") as f:
            container_bytes = int(f.read().strip())
        container_mb = container_bytes / 1024 / 1024

        limit_mb = 0.0
        try:
            with open("/sys/fs/cgroup/memory.max", encoding="utf-8") as f:
                limit_str = f.read().strip()
                if limit_str != "max":
                    limit_mb = int(limit_str) / 1024 / 1024
        except Exception:
            pass

        return container_mb, limit_mb
    except FileNotFoundError:
        pass

    # Try cgroup v1 (older Docker)
    try:
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", encoding="utf-8") as f:
            container_bytes = int(f.read().strip())
        container_mb = container_bytes / 1024 / 1024

        limit_mb = 0.0
        try:
            with open(
                "/sys/fs/cgroup/memory/memory.limit_in_bytes", encoding="utf-8"
            ) as f:
                limit_bytes = int(f.read().strip())
                # Check if it's a real limit or effectively unlimited
                if limit_bytes < 9223372036854771712:  # Not near max int64
                    limit_mb = limit_bytes / 1024 / 1024
        except Exception:
            pass

        return container_mb, limit_mb
    except FileNotFoundError:
        pass

    # Fallback: sum all process memory (less accurate, doesn't catch shared pages)
    try:
        total_rss = 0
        for proc in psutil.process_iter(["memory_info"]):
            try:
                total_rss += proc.info["memory_info"].rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        return total_rss / 1024 / 1024, 0.0
    except Exception:
        return 0.0, 0.0


def _request_main_process_shutdown() -> bool:
    """
    Request graceful shutdown of the main Celery process.

    This sends SIGTERM to PID 1 (the main Celery process in Docker), which
    triggers a graceful shutdown. Docker's restart policy will then restart
    the container with fresh memory.

    Returns:
        True if signal was sent, False otherwise
    """
    try:
        parent_pid = os.getppid()
        logger.warning(
            f"[MEMORY] Requesting main process shutdown (parent PID: {parent_pid})"
        )
        os.kill(parent_pid, signal.SIGTERM)
        return True
    except Exception as e:
        logger.error(f"[MEMORY] Failed to signal parent process: {e}")
        return False


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
    Profile memory after worker initialization.

    Useful for understanding the baseline memory cost of
    the download infrastructure before any tasks run.
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
        "description": "Memory after worker initialization",
    }

    results["process_memory"] = _get_process_memory()

    loaded_modules = [
        name
        for name in sys.modules
        if any(x in name for x in ["yt_dlp", "spotipy", "deezer"])
    ]
    results["relevant_modules"] = sorted(loaded_modules)

    return results


@celery_app.task(bind=True, name="library_manager.tasks.memory_compare_before_after")
def memory_compare_before_after(self: Any) -> Dict[str, Any]:
    """
    Measure current worker memory state.

    Returns:
        Memory measurement results
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "task_id": self.request.id,
    }

    gc.collect()
    results["before"] = _get_process_memory()

    gc.collect()
    results["after"] = _get_process_memory()

    results["delta_mb"] = round(
        results["after"]["rss_mb"] - results["before"]["rss_mb"], 2
    )

    return results


# ============================================================================
# Periodic Memory Health Check
# ============================================================================

# Thresholds for periodic health check (in MB)
# Worker process thresholds
MEMORY_HEALTHY_THRESHOLD_MB = 600
MEMORY_WARNING_THRESHOLD_MB = 800
MEMORY_CRITICAL_THRESHOLD_MB = 1200

# Container-level thresholds (detects main Celery process memory leaks)
# Celery's main process leaks ~150-200MB per worker cycle - this is a known issue
# See: https://github.com/celery/celery/issues/4843
CONTAINER_WARNING_PERCENT = 70  # Warn at 70% of container limit
CONTAINER_RESTART_PERCENT = 85  # Request restart at 85% of limit


@celery_app.task(bind=True, name="library_manager.tasks.periodic_memory_health_check")
def periodic_memory_health_check(self: Any) -> Dict[str, Any]:
    """
    Periodic task to check memory health of workers and container.

    This task monitors both:
    1. Worker process memory (via psutil)
    2. Container memory (via cgroup) - catches main Celery process leaks

    The main Celery process leaks memory over time (known Celery issue #4843).
    This task detects when container memory is approaching the limit and
    requests a graceful restart before OOM kills occur.

    Returns:
        Dictionary with memory health status and recommendations
    """
    results: Dict[str, Any] = {
        "worker_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "task_id": self.request.id,
    }

    gc.collect()

    # Worker process memory (this worker only)
    worker_memory = _get_process_memory()
    results["worker_memory"] = worker_memory

    # Container-level memory (all processes including leaking main process)
    container_mb, limit_mb = _get_container_memory()
    results["container_memory"] = {
        "current_mb": round(container_mb, 1),
        "limit_mb": round(limit_mb, 1) if limit_mb > 0 else None,
        "percent": round(container_mb / limit_mb * 100, 1) if limit_mb > 0 else None,
    }

    rss_mb = worker_memory["rss_mb"]

    # Check container memory first (catches main process leaks)
    if limit_mb > 0:
        container_percent = (container_mb / limit_mb) * 100

        if container_percent >= CONTAINER_RESTART_PERCENT:
            results["status"] = "CONTAINER_CRITICAL"
            results["message"] = (
                f"Container memory at {container_percent:.0f}% "
                f"({container_mb:.0f}/{limit_mb:.0f} MB). "
                f"Main Celery process may be leaking. Requesting graceful restart."
            )
            logger.critical(
                f"[MEMORY HEALTH] CONTAINER CRITICAL - "
                f"{container_mb:.0f}/{limit_mb:.0f} MB ({container_percent:.0f}%). "
                f"Requesting main process restart."
            )
            # Request main process shutdown - Docker will restart the container
            results["restart_requested"] = _request_main_process_shutdown()
            return results

        if container_percent >= CONTAINER_WARNING_PERCENT:
            results["status"] = "CONTAINER_WARNING"
            results["message"] = (
                f"Container memory at {container_percent:.0f}% "
                f"({container_mb:.0f}/{limit_mb:.0f} MB). "
                f"Main process may be accumulating memory."
            )
            logger.warning(
                f"[MEMORY HEALTH] CONTAINER WARNING - "
                f"{container_mb:.0f}/{limit_mb:.0f} MB ({container_percent:.0f}%). "
                f"Worker={rss_mb:.0f}MB, PID={os.getpid()}"
            )
            return results

    # Worker process memory checks (fallback if container checks pass)
    if rss_mb >= MEMORY_CRITICAL_THRESHOLD_MB:
        results["status"] = "WORKER_CRITICAL"
        results["message"] = (
            f"Worker memory critical ({rss_mb:.1f} MB). "
            f"Worker may be killed by OOM soon."
        )
        logger.critical(
            f"[MEMORY HEALTH] WORKER CRITICAL - {rss_mb:.1f} MB on PID {os.getpid()}. "
            f"Container: {container_mb:.0f} MB"
        )
    elif rss_mb >= MEMORY_WARNING_THRESHOLD_MB:
        results["status"] = "WORKER_WARNING"
        results["message"] = (
            f"Worker memory elevated ({rss_mb:.1f} MB). "
            f"Container restart may be needed if memory continues growing."
        )
        logger.warning(
            f"[MEMORY HEALTH] WORKER WARNING - {rss_mb:.1f} MB on PID {os.getpid()}. "
            f"Container: {container_mb:.0f} MB"
        )
    elif rss_mb >= MEMORY_HEALTHY_THRESHOLD_MB:
        results["status"] = "OK"
        results["message"] = (
            f"Memory usage normal (worker={rss_mb:.1f} MB, container={container_mb:.0f} MB)."
        )
        logger.info(
            f"[MEMORY HEALTH] OK - worker={rss_mb:.1f}MB, container={container_mb:.0f}MB, "
            f"PID={os.getpid()}"
        )
    else:
        results["status"] = "HEALTHY"
        results["message"] = (
            f"Memory usage healthy (worker={rss_mb:.1f} MB, container={container_mb:.0f} MB)."
        )
        logger.info(
            f"[MEMORY HEALTH] HEALTHY - worker={rss_mb:.1f}MB, container={container_mb:.0f}MB, "
            f"PID={os.getpid()}"
        )

    # Include worker context
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


@celery_app.task(bind=True, name="library_manager.tasks.profile_parent_process")
def profile_parent_process(self: Any) -> Dict[str, Any]:
    """
    Profile the PARENT (main Celery) process memory from a worker.

    This task runs in a worker but inspects the parent process to understand
    where memory is being used. Useful for debugging the main Celery process
    memory leak issue.

    Returns:
        Dictionary with parent process memory breakdown and all Celery processes
    """
    results: Dict[str, Any] = {
        "task_id": self.request.id,
        "worker_pid": os.getpid(),
        "parent_pid": os.getppid(),
    }

    # Get parent process detailed memory info
    results["parent_memory"] = _get_parent_process_memory()

    # Get this worker's memory for comparison
    results["worker_memory"] = _get_process_memory()

    # Get container-level memory
    container_mb, limit_mb = _get_container_memory()
    results["container_memory"] = {
        "current_mb": round(container_mb, 1),
        "limit_mb": round(limit_mb, 1) if limit_mb > 0 else None,
        "percent": round(container_mb / limit_mb * 100, 1) if limit_mb > 0 else None,
    }

    # Get all Celery processes for a complete picture
    results["all_celery_processes"] = _get_all_celery_processes()

    # Calculate where the memory is
    parent_rss = results["parent_memory"].get("rss_mb", 0)
    worker_rss = results["worker_memory"].get("rss_mb", 0)
    total_processes = parent_rss + worker_rss

    results["analysis"] = {
        "parent_rss_mb": parent_rss,
        "worker_rss_mb": worker_rss,
        "total_celery_processes_mb": total_processes,
        "container_mb": round(container_mb, 1),
        "unaccounted_mb": round(container_mb - total_processes, 1),
        "parent_percent_of_container": (
            round(parent_rss / container_mb * 100, 1) if container_mb > 0 else None
        ),
    }

    # Log summary
    logger.info(
        f"[PARENT PROFILE] Parent={parent_rss:.0f}MB, Worker={worker_rss:.0f}MB, "
        f"Container={container_mb:.0f}MB, "
        f"Parent is {results['analysis']['parent_percent_of_container']:.0f}% of container"
    )

    return results
