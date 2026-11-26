"""Print or write a read-only review of backfill-reported artist identity pairs.

Reads the backfill's JSONL audit (and optionally its WARNING log), groups the
``skip_ambiguous_artist`` / ``skip_same_name_different_id`` reports, and adds
ISRC evidence from the database only. Nothing on disk or in the DB is written.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, TextIO

from django.core.management.base import BaseCommand, CommandError

from library_manager.artist_review import (
    ACTION_DIFFERENT,
    ACTION_LINK,
    ACTION_MERGE,
    ACTION_NEEDS_REVIEW,
    KIND_AMBIGUOUS,
    KIND_SAME_NAME,
    build_review,
    write_review_csv,
)


class Command(BaseCommand):
    help = "Report artist identity pairs left unchanged by the credits backfill"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "audit_file", help="JSONL audit from backfill_artist_credits"
        )
        parser.add_argument("--log-file", help="Optional app log with WARNING lines")
        parser.add_argument(
            "--output", help="Write the review CSV here (default stdout)"
        )
        parser.add_argument(
            "--show",
            type=int,
            default=15,
            help="Biggest groups to print to stdout (default 15)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        audit_path = Path(options["audit_file"])
        if not audit_path.exists():
            raise CommandError(f"audit file not found: {audit_path}")
        log_path = Path(options["log_file"]) if options["log_file"] else None
        cases = build_review(audit_path, log_path)

        with ExitStack() as stack:
            target: TextIO
            if options["output"]:
                output = Path(options["output"])
                if output.exists():
                    raise CommandError(f"output file already exists: {output}")
                target = stack.enter_context(
                    output.open("x", encoding="utf-8", newline="")
                )
            else:
                target = sys.stdout
            write_review_csv(cases, target)

        counts: dict[str, int] = {}
        actions: dict[str, int] = {}
        for case in cases:
            counts[case.kind] = counts.get(case.kind, 0) + 1
            actions[case.suggested_action] = actions.get(case.suggested_action, 0) + 1
        self.stdout.write(f"groups: {len(cases)}")
        self.stdout.write(f"  {KIND_AMBIGUOUS}: {counts.get(KIND_AMBIGUOUS, 0)}")
        self.stdout.write(f"  {KIND_SAME_NAME}: {counts.get(KIND_SAME_NAME, 0)}")
        for action in (
            ACTION_LINK,
            ACTION_MERGE,
            ACTION_DIFFERENT,
            ACTION_NEEDS_REVIEW,
        ):
            self.stdout.write(f"  suggested {action}: {actions.get(action, 0)}")
        if options["output"]:
            self.stdout.write(f"CSV written to {options['output']}")
        show = max(0, int(options["show"]))
        if show:
            self.stdout.write(f"largest groups (top {show}):")
            for case in cases[:show]:
                self.stdout.write(
                    f"  {case.case_key}: {case.affected_songs} song(s), "
                    f"tier={case.existing_tier}, ISRC overlap="
                    f"{case.isrc_overlap_songs}, {case.suggested_action}"
                )
