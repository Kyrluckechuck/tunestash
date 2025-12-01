"""Management command to profile worker memory usage.

Usage:
    # Basic memory profile of a worker
    docker compose exec web python manage.py memory_profile

    # Include large object scan (slower)
    docker compose exec web python manage.py memory_profile --include-large-objects

    # Profile after fetching metadata for a specific album
    docker compose exec web python manage.py memory_profile --spotify-uri spotify:album:xyz

    # Compare memory before/after metadata fetch
    docker compose exec web python manage.py memory_profile --compare --spotify-uri spotify:album:xyz
"""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Profile memory usage of Celery workers"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--include-large-objects",
            action="store_true",
            help="Include scan for large objects (slower)",
        )
        parser.add_argument(
            "--no-tracemalloc",
            action="store_true",
            help="Skip detailed tracemalloc profiling",
        )
        parser.add_argument(
            "--no-object-counts",
            action="store_true",
            help="Skip object type counting",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=30,
            help="Number of top allocations to show (default: 30)",
        )
        parser.add_argument(
            "--compare",
            action="store_true",
            help="Compare memory before/after a metadata fetch",
        )
        parser.add_argument(
            "--spotify-uri",
            type=str,
            help="Spotify URI to fetch metadata for (used with --compare)",
        )
        parser.add_argument(
            "--init-only",
            action="store_true",
            help="Only profile after SpotdlWrapper initialization",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="Timeout in seconds waiting for task result (default: 60)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output raw JSON instead of formatted text",
        )

    def handle(self, *args, **options) -> None:
        from library_manager.tasks.diagnostics import (
            memory_compare_before_after,
            memory_profile_after_init,
            memory_profile_worker,
        )

        timeout = options["timeout"]
        output_json = options["json"]

        if options["compare"]:
            self._run_compare(
                memory_compare_before_after,
                options["spotify_uri"],
                timeout,
                output_json,
            )
        elif options["init_only"]:
            self._run_init_profile(memory_profile_after_init, timeout, output_json)
        else:
            self._run_full_profile(
                memory_profile_worker,
                include_tracemalloc=not options["no_tracemalloc"],
                include_object_counts=not options["no_object_counts"],
                include_large_objects=options["include_large_objects"],
                tracemalloc_limit=options["limit"],
                timeout=timeout,
                output_json=output_json,
            )

    def _run_full_profile(
        self,
        task,
        include_tracemalloc: bool,
        include_object_counts: bool,
        include_large_objects: bool,
        tracemalloc_limit: int,
        timeout: int,
        output_json: bool,
    ) -> None:
        self.stdout.write("Dispatching memory profile task to worker...")

        result = task.delay(
            include_tracemalloc=include_tracemalloc,
            include_object_counts=include_object_counts,
            include_large_objects=include_large_objects,
            tracemalloc_limit=tracemalloc_limit,
        )

        self.stdout.write(f"Task ID: {result.id}")
        self.stdout.write(f"Waiting up to {timeout}s for result...")

        try:
            data = result.get(timeout=timeout)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Task failed: {e}"))
            return

        if output_json:
            self.stdout.write(json.dumps(data, indent=2))
            return

        self._format_full_profile(data)

    def _run_init_profile(self, task, timeout: int, output_json: bool) -> None:
        self.stdout.write("Dispatching init profile task to worker...")

        result = task.delay()
        self.stdout.write(f"Task ID: {result.id}")

        try:
            data = result.get(timeout=timeout)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Task failed: {e}"))
            return

        if output_json:
            self.stdout.write(json.dumps(data, indent=2))
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Worker Init Memory Profile ==="))
        self.stdout.write(f"Worker PID: {data['worker_pid']}")
        self.stdout.write("")

        mem = data["process_memory"]
        self.stdout.write(self.style.WARNING("Process Memory:"))
        self.stdout.write(f"  RSS:     {mem['rss_mb']} MB")
        self.stdout.write(f"  VMS:     {mem['vms_mb']} MB")
        self.stdout.write(f"  Percent: {mem['percent']}%")
        self.stdout.write("")

        self.stdout.write(
            self.style.WARNING("Loaded Modules (spotdl/yt_dlp/ytmusic/spotipy):")
        )
        for mod in data.get("relevant_modules", []):
            self.stdout.write(f"  - {mod}")

    def _run_compare(
        self, task, spotify_uri: str, timeout: int, output_json: bool
    ) -> None:
        self.stdout.write("Dispatching memory comparison task to worker...")

        result = task.delay(spotify_uri=spotify_uri)
        self.stdout.write(f"Task ID: {result.id}")

        try:
            data = result.get(timeout=timeout)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Task failed: {e}"))
            return

        if output_json:
            self.stdout.write(json.dumps(data, indent=2))
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Memory Comparison ==="))
        self.stdout.write(f"Worker PID: {data['worker_pid']}")
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("Before:"))
        self.stdout.write(f"  RSS: {data['before']['rss_mb']} MB")

        self.stdout.write(self.style.WARNING("After:"))
        self.stdout.write(f"  RSS: {data['after']['rss_mb']} MB")

        delta = data["delta_mb"]
        style = self.style.ERROR if delta > 10 else self.style.SUCCESS
        self.stdout.write(style(f"Delta: {delta:+.2f} MB"))

        if data.get("metadata_fetched"):
            self.stdout.write(f"Tracks found: {data.get('tracks_found', 'N/A')}")
        elif data.get("metadata_error"):
            self.stdout.write(self.style.ERROR(f"Error: {data['metadata_error']}"))

    def _format_full_profile(self, data: dict) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("  WORKER MEMORY PROFILE"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"Worker PID: {data['worker_pid']}")
        self.stdout.write(f"Task ID:    {data['task_id']}")
        self.stdout.write("")

        # Process memory
        mem = data["process_memory"]
        self.stdout.write(self.style.WARNING("PROCESS MEMORY"))
        self.stdout.write("-" * 40)
        self.stdout.write(f"  RSS (Resident):  {mem['rss_mb']:>10.2f} MB")
        self.stdout.write(f"  VMS (Virtual):   {mem['vms_mb']:>10.2f} MB")
        self.stdout.write(f"  System Percent:  {mem['percent']:>10.2f}%")
        self.stdout.write("")

        # Tracemalloc stats
        if "tracemalloc_stats" in data:
            tm = data["tracemalloc_stats"]
            self.stdout.write(self.style.WARNING("TRACEMALLOC STATS"))
            self.stdout.write("-" * 40)
            self.stdout.write(f"  Currently traced: {tm['traced_mb']:>10.2f} MB")
            self.stdout.write(f"  Peak traced:      {tm['peak_mb']:>10.2f} MB")
            self.stdout.write("")

        # Allocations by file
        if "allocations_by_file" in data:
            self.stdout.write(self.style.WARNING("TOP ALLOCATIONS BY FILE"))
            self.stdout.write("-" * 40)
            for alloc in data["allocations_by_file"][:15]:
                # Shorten path for readability
                filepath = alloc["file"]
                if "site-packages" in filepath:
                    filepath = "..." + filepath.split("site-packages")[-1]
                elif len(filepath) > 50:
                    filepath = "..." + filepath[-47:]

                self.stdout.write(
                    f"  {alloc['size_mb']:>8.2f} MB  ({alloc['count']:>6} allocs)  {filepath}"
                )
            self.stdout.write("")

        # Allocations by line (more detail)
        if "allocations_by_line" in data:
            self.stdout.write(self.style.WARNING("TOP ALLOCATIONS BY LINE"))
            self.stdout.write("-" * 40)
            for alloc in data["allocations_by_line"][:20]:
                filepath = alloc["file"]
                if "site-packages" in filepath:
                    filepath = "..." + filepath.split("site-packages")[-1]
                elif len(filepath) > 40:
                    filepath = "..." + filepath[-37:]

                self.stdout.write(
                    f"  {alloc['size_mb']:>8.4f} MB  {filepath}:{alloc['line']}"
                )
                if alloc["code"]:
                    self.stdout.write(f"                    {alloc['code'][:60]}")
            self.stdout.write("")

        # Object counts
        if "object_counts" in data:
            self.stdout.write(self.style.WARNING("TOP OBJECT TYPES BY COUNT"))
            self.stdout.write("-" * 40)
            for obj in data["object_counts"][:15]:
                self.stdout.write(f"  {obj['count']:>10,}  {obj['type']}")
            self.stdout.write("")

        # Large objects
        if "large_objects" in data:
            self.stdout.write(self.style.WARNING("LARGE OBJECTS (>100KB)"))
            self.stdout.write("-" * 40)
            for obj in data["large_objects"][:10]:
                self.stdout.write(f"  {obj['size_kb']:>10.2f} KB  {obj['type']}")
                if obj["repr"]:
                    self.stdout.write(f"                    {obj['repr'][:60]}...")
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("=" * 60))
