"""Repair historical retry-count availability flags without retrying downloads."""

import json
from datetime import datetime, timezone
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from library_manager.models import FailureReason, Song

# c1763a2 replaced the unconditional failed_count > 3 availability verdict.
FIXED_AT = datetime(2026, 6, 19, 20, 2, 34, tzinfo=timezone.utc)


class Command(BaseCommand):
    help = (
        "Dry-run legacy temporary-failure flag repair; --apply requires an audit file."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--audit-file", help="New JSON file for original values; never overwritten"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        candidates = Song.objects.filter(
            unavailable=True,
            downloaded=False,
            failure_reason=FailureReason.TEMPORARY_ERROR,
            last_failed_at__lt=FIXED_AT,
        )
        if not options["apply"]:
            self.stdout.write(f"Dry run: would repair {candidates.count()} song flags")
            return
        if not options["audit_file"]:
            raise CommandError("--apply requires --audit-file")

        with transaction.atomic():
            rows = list(
                candidates.select_for_update()
                .order_by("id")
                .values(
                    "id",
                    "unavailable",
                    "failure_reason",
                    "failed_count",
                    "last_failed_at",
                )
            )
            try:
                with open(options["audit_file"], "x", encoding="utf-8") as report:
                    json.dump(rows, report, cls=DjangoJSONEncoder)
            except OSError as error:
                raise CommandError(f"Cannot create audit file: {error}") from error
            # Row locks preserve the audited predicate until the narrow update.
            changed = candidates.filter(id__in=[row["id"] for row in rows]).update(
                unavailable=False
            )
        self.stdout.write(
            f"Applied: repaired {changed} song flags; no downloads queued"
        )
