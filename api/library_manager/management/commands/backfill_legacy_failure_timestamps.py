"""Backfill legacy Song failure timestamps without retrying downloads.

Legacy failed Song rows can have failed_count>0 but last_failed_at=NULL because
the timestamp field was added after those rows were written. The retry backoff
logic treats a NULL timestamp as ready, so these rows can be retried
immediately. Stamping a conservative timestamp lets their normal backoff apply
instead of fabricating a historical failure date.

Scope is Song only (album legacy rows were documented as 0 in production).
"""

import json
import os
from datetime import UTC, datetime
from typing import Any, Iterator, Optional, TextIO

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from library_manager.models import Song

CHUNK_SIZE = 1000
AUDIT_MODE = 0o600
FINALIZED = "committed"
PREPARED = "prepared_rolled_back"


class Command(BaseCommand):
    help = (
        "Dry-run legacy song failure timestamp backfill; --apply requires a new "
        "audit file and --last-failed-at (recommend current UTC)."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._audit_handle: Optional[TextIO] = None
        self._audit_first = True

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--audit-file",
            help="New JSON file for original values; never overwritten.",
        )
        parser.add_argument(
            "--last-failed-at",
            dest="last_failed_at",
            help=(
                "Stamp for last_failed_at when applying. Recommend current UTC "
                "so legacy failures wait their normal backoff instead of being "
                "immediately requeued. Must not be in the future."
            ),
        )

    def _parse_stamp(self, value: str) -> datetime:
        try:
            stamp = parse_datetime(value)
        except ValueError as error:
            raise CommandError(f"Invalid --last-failed-at: {error}") from error
        if stamp is None or "T" not in value.upper():
            raise CommandError(
                "--last-failed-at must be an ISO-8601 datetime (not a date), "
                f"for example {timezone.now().isoformat()}"
            )
        if timezone.is_naive(stamp):
            stamp = timezone.make_aware(stamp, UTC)
        if stamp > timezone.now():
            raise CommandError(
                "--last-failed-at must not be in the future; use current UTC"
            )
        return stamp

    def _candidate_chunks(self) -> Iterator[list[dict[str, Any]]]:
        last_id = 0
        while True:
            rows = list(
                Song.objects.filter(
                    id__gt=last_id,
                    failed_count__gt=0,
                    last_failed_at__isnull=True,
                    downloaded=False,
                )
                .order_by("id")[:CHUNK_SIZE]
                .values(
                    "id",
                    "failed_count",
                    "failure_reason",
                    "last_failed_at",
                    "downloaded",
                    "unavailable",
                    "bitrate",
                )
            )
            if not rows:
                return
            last_id = rows[-1]["id"]
            yield rows

    def _write_audit_snapshot(self, path: str, rows: list[dict[str, Any]]) -> None:
        """Append a chunk to the private, exclusive audit file.

        The file is created with mode 0600 and O_EXCL via os.open, then wrapped
        in a file object. Streaming the JSON array in chunks keeps memory bound.
        """
        if self._audit_handle is None:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(path, flags, AUDIT_MODE)
            except OSError as error:
                raise CommandError(f"Cannot create audit file: {error}") from error
            self._audit_handle = os.fdopen(fd, "w", encoding="utf-8")
            self._audit_handle.write("[")
            self._audit_first = True
        for row in rows:
            if not self._audit_first:
                self._audit_handle.write(",")
            self._audit_handle.write("\n  ")
            json.dump(row, self._audit_handle, cls=DjangoJSONEncoder)
            self._audit_first = False

    def _finish_audit(self, status: str, updated: int) -> None:
        handle = getattr(self, "_audit_handle", None)
        if handle is None:
            return
        # Envelope stays parseable JSON: the array plus a final outcome object.
        if not getattr(self, "_audit_first", True):
            handle.write("\n")
        handle.write(",\n  ")
        json.dump(
            {"outcome": status, "updated_count": updated},
            handle,
            cls=DjangoJSONEncoder,
        )
        handle.write("\n]\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        self._audit_handle = None

    def handle(self, *args: Any, **options: Any) -> None:
        candidate_count = sum(len(chunk) for chunk in self._candidate_chunks())
        if not options["apply"]:
            self.stdout.write(
                f"Dry run: would backfill {candidate_count} legacy song failure "
                "timestamp(s)"
            )
            return

        if not options["audit_file"]:
            raise CommandError("--apply requires --audit-file")
        if not options["last_failed_at"]:
            raise CommandError(
                "--apply requires --last-failed-at (recommend current UTC)"
            )

        stamp = self._parse_stamp(options["last_failed_at"])
        audit_path = options["audit_file"]
        updated = 0
        try:
            with transaction.atomic():
                for rows in self._candidate_chunks():
                    ids = [row["id"] for row in rows]
                    self._write_audit_snapshot(audit_path, rows)
                    # Locks are taken in ID order; recheck the candidate
                    # predicate so concurrent changes are not clobbered.
                    locked = list(
                        Song.objects.filter(
                            id__in=ids,
                            failed_count__gt=0,
                            last_failed_at__isnull=True,
                            downloaded=False,
                        )
                        .select_for_update()
                        .order_by("id")
                        .values_list("id", flat=True)
                    )
                    if locked:
                        updated += Song.objects.filter(id__in=locked).update(
                            last_failed_at=stamp
                        )
        except Exception:
            # The preimage snapshot was already fsynced before mutation. Mark
            # the outcome as rolled back so the audit stays parseable and never
            # claims a commit that did not happen; keep the evidence on disk.
            self._finish_audit(PREPARED, updated)
            raise

        # Audit was written and fsynced before mutation. Finalize with the real
        # outcome: never claim "committed" if the transaction rolled back.
        self._finish_audit(FINALIZED, updated)
        self.stdout.write(
            f"Applied: backfilled {updated} legacy song failure timestamp(s); "
            "no downloads queued"
        )
