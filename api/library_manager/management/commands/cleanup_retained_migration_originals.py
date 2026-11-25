"""Audit and delete audio originals retained by earlier metadata migrations.

The command never guesses. It only deletes a file when the migration link log
(written by the metadata migration on successful cleanup) records an explicit
original→destination pair, the new path exists and is referenced by a Song, and
the old path is unreferenced at the moment of deletion. Without such a record it
reports that no reliable link exists and lists candidates only.
"""

import json
import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from downloader.filesystem_safety import is_safe_regular_file, iter_audio_files

from library_manager.models import FilePath, Song
from library_manager.tasks.metadata import migration_link_log_path


class Command(BaseCommand):
    help = "Clean up audio files retained by earlier metadata migrations"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete confirmed originals (default: dry-run)",
        )
        parser.add_argument(
            "--audit-file",
            type=str,
            default=None,
            help="Required with --apply; exclusive-create JSONL audit of deletions",
        )

    def handle(self, *args, **options) -> None:
        apply_changes = options["apply"]
        audit_file = options["audit_file"]
        if apply_changes and not audit_file:
            raise CommandError("--apply requires --audit-file")

        output_root = Path(
            getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")
        ).resolve()
        link_log = migration_link_log_path()

        referenced = set(
            FilePath.objects.filter(songs__isnull=False).values_list("path", flat=True)
        )
        referenced_resolved = {_resolve(p) for p in referenced}

        links = _read_links(link_log)
        pairs = _confirmed_pairs(links, output_root, referenced, referenced_resolved)

        candidates = []
        for path in iter_audio_files(output_root):
            if not is_safe_regular_file(path, output_root):
                continue
            if str(path) in referenced or str(_resolve(path)) in referenced_resolved:
                continue
            candidates.append(path)

        if not apply_changes:
            self._report(pairs, candidates, links, output_root)
            return

        self._apply(pairs, Path(audit_file), candidates, links, output_root)

    def _report(
        self,
        pairs,
        candidates,
        links,
        output_root,
    ) -> None:
        self.stdout.write("DRY RUN - no files will be deleted")
        if not links:
            self.stdout.write(
                "No reliable migration link log found; listing candidates only."
            )
        elif not pairs:
            self.stdout.write(
                "No confirmed migration originals found; listing candidates only."
            )
        for old_path, new_path in pairs:
            self.stdout.write(f"  confirmed: {old_path} -> {new_path}")
        for path in candidates:
            self.stdout.write(f"  candidate: {path}")
        self.stdout.write(
            f"Total: {len(pairs)} confirmed, {len(candidates)} unreferenced candidates"
        )

    def _apply(
        self,
        pairs,
        audit_path: Path,
        candidates,
        links,
        output_root,
    ) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(audit_path, flags, 0o600)
        except OSError as exc:
            raise CommandError(f"Cannot create audit file {audit_path}: {exc}") from exc

        if not links:
            os.close(fd)
            self.stdout.write(
                "No reliable migration link log found; refusing to delete any file."
            )
            for path in candidates:
                self.stdout.write(f"  candidate: {path}")
            return

        deleted = 0
        with os.fdopen(fd, "w", encoding="utf-8") as audit:
            for old_path, new_path in pairs:
                if not _still_confirmed(old_path, new_path, output_root):
                    self.stdout.write(f"  skipped (no longer confirmed): {old_path}")
                    continue
                try:
                    size = old_path.stat().st_size
                    audit.write(
                        json.dumps(
                            {
                                "path": str(old_path),
                                "size": size,
                                "new_path": str(new_path),
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    audit.flush()
                    os.fsync(audit.fileno())
                    old_path.unlink()
                    deleted += 1
                    self.stdout.write(f"  deleted: {old_path}")
                except OSError as exc:
                    self.stdout.write(f"  skipped ({exc}): {old_path}")

        self.stdout.write(f"Deleted {deleted} retained migration original(s)")


def _resolve(path: str) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _read_links(log_path: Path) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("event") == "retained"
                    and record.get("old_path")
                    and record.get("new_path")
                ):
                    links.append(record)
    except OSError:
        return []
    return links


def _confirmed_pairs(
    links: list[dict[str, Any]],
    output_root: Path,
    referenced: set[str],
    referenced_resolved: set[Path],
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    seen: set[tuple[str, str]] = set()
    for record in links:
        old_path = Path(record["old_path"])
        new_path = Path(record["new_path"])
        key = (str(old_path), str(new_path))
        if key in seen:
            continue
        seen.add(key)
        if str(new_path) not in referenced and str(_resolve(str(new_path))) not in (
            referenced_resolved
        ):
            continue
        if not is_safe_regular_file(new_path, output_root):
            continue
        if not is_safe_regular_file(old_path, output_root):
            continue
        if str(old_path) in referenced or str(_resolve(str(old_path))) in (
            referenced_resolved
        ):
            continue
        pairs.append((old_path, new_path))
    return pairs


def _still_confirmed(old_path: Path, new_path: Path, output_root: Path) -> bool:
    if not is_safe_regular_file(old_path, output_root):
        return False
    if not is_safe_regular_file(new_path, output_root):
        return False
    if Song.objects.filter(file_path_ref__path=str(old_path)).exists():
        return False
    if not Song.objects.filter(file_path_ref__path=str(new_path)).exists():
        return False
    return True
