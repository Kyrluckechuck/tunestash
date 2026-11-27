"""Restore primary artists wrongly changed by ``backfill_artist_credits``.

The backfill used to replace a song's primary with the first-listed main credit
even when the *current* primary was itself credited as a main artist (a
co-lead) or the song was a remix on the primary's own release. This command
reads the backfill's audit file, finds applied primary changes of that kind and
puts the old primary back.

Safety:

* Dry-run by default; ``--apply`` requires a new ``--audit-out`` (mode 0600),
  written and fsynced with every planned revert before any song is touched.
* A song is restored only while its current primary still is the artist the
  backfill set (compare-and-swap under a row lock); anything newer is skipped.
* The contributor set the backfill reconciled is left as it is; file paths are
  never touched.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterator, Optional

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from library_manager.models import Artist, Song

CHANGED_CATEGORIES = frozenset(
    {
        "featured_as_primary",
        "primary_not_credited",
        "primary_name_matches_other_credit",
    }
)
_MIXISH = re.compile(
    r"\b(mix|mixed|dj|session|asot|compiled|continuous|presents|vol(ume)?\.?\s*\d)",
    re.IGNORECASE,
)

REASON_MAIN = "old_primary_credited_main"
REASON_OWN_ALBUM = "old_primary_credited_on_own_album"
NOT_NEEDED = "genuine_fix_old_not_main_credited"
NO_DEEZER_ID = "undeterminable_old_primary_has_no_deezer_id"


def applied_changes(audit_path: Path) -> Iterator[dict[str, Any]]:
    """Yield each applied primary-changing plan from the audit, streaming.

    Only the plans of categories that change a primary are held in memory, and
    only until their ``complete`` record arrives.
    """
    pending: dict[int, dict[str, Any]] = {}
    with audit_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = record.get("record")
            if kind is None and record.get("status") == "fix":
                if record.get("category") in CHANGED_CATEGORIES:
                    pending[int(record["song_id"])] = record
                else:
                    pending.pop(int(record["song_id"]), None)
            elif kind == "complete":
                plan = pending.pop(int(record["song_id"]), None)
                if plan is not None and record.get("outcome") == plan["category"]:
                    yield plan


def credited_main_in_plan(plan: dict[str, Any]) -> Optional[str]:
    """REASON_MAIN / NO_DEEZER_ID / None, judged from the plan's own credits."""
    old = plan.get("old_primary_deezer_id")
    if old is None:
        return NO_DEEZER_ID
    for credit in plan.get("credits", []):
        if credit.get("deezer_id") == old and credit.get("role") == "main":
            return REASON_MAIN
    return None


def credited_any_in_plan(plan: dict[str, Any]) -> bool:
    old = plan.get("old_primary_deezer_id")
    return old is not None and any(
        c.get("deezer_id") == old for c in plan.get("credits", [])
    )


class Command(BaseCommand):
    help = (
        "Restore the old primary where backfill_artist_credits replaced a "
        "credited co-lead. Dry-run by default; --apply requires --audit-out."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--audit-in", required=True, help="backfill audit file")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-out", help="new 0600 audit file (with --apply)")
        parser.add_argument("--examples", type=int, default=10)
        parser.add_argument("--batch-size", type=int, default=200)

    # -- planning ---------------------------------------------------------

    def _classify(self, plan: dict[str, Any]) -> tuple[str, Optional[Song]]:
        """(reason, song) -- reason is a revert reason or a non-revert verdict."""
        reason = credited_main_in_plan(plan)
        song = (
            Song.objects.filter(pk=plan["song_id"])
            .select_related("album", "primary_artist")
            .first()
        )
        if reason == REASON_MAIN:
            return reason, song
        if (
            song is not None
            and song.album is not None
            and song.album.artist_id == plan["old_primary_id"]
            and credited_any_in_plan(plan)
        ):
            return REASON_OWN_ALBUM, song
        return reason or NOT_NEEDED, song

    def _revert_state(
        self, plan: dict[str, Any], song: Optional[Song]
    ) -> tuple[bool, str]:
        """Would the CAS pass right now? (ok, why-not)"""
        if song is None:
            return False, "skip_song_missing"
        if song.primary_artist_id == plan["old_primary_id"]:
            return False, "skip_already_restored"
        if song.primary_artist.deezer_id != plan["lead_deezer_id"]:
            return False, "skip_primary_changed_since_backfill"
        return True, "revertable"

    def _breakdown_primary_not_credited(self, plan: dict[str, Any], song: Any) -> str:
        """DJ-mix compilation vs other, for a primary_not_credited change."""
        if song is None or song.album is None:
            return "other_no_album"
        album = song.album
        mixish = album.album_type == "compilation" or bool(_MIXISH.search(album.name))
        owner_is_old = album.artist_id == plan["old_primary_id"]
        if mixish and owner_is_old:
            return "dj_mix_compilation"
        if mixish:
            return "compilation_other_owner"
        if owner_is_old:
            return "other_album_by_old_primary"
        return "other"

    # -- entry ------------------------------------------------------------

    def handle(self, *args: Any, **options: Any) -> None:
        audit_in = Path(options["audit_in"])
        if not audit_in.is_file():
            raise CommandError(f"audit file not found: {audit_in}")
        apply = options["apply"]
        if apply and not options["audit_out"]:
            raise CommandError("--apply requires --audit-out")
        if not apply and options["audit_out"]:
            raise CommandError("--audit-out only applies with --apply")

        counts: dict[str, int] = {}
        breakdown: dict[str, int] = {}
        to_revert: list[dict[str, Any]] = []
        examples: list[str] = []

        def bump(table: dict[str, int], key: str) -> None:
            table[key] = table.get(key, 0) + 1

        for plan in applied_changes(audit_in):
            bump(counts, f"applied_{plan['category']}")
            reason, song = self._classify(plan)
            if plan["category"] == "primary_not_credited":
                bump(breakdown, self._breakdown_primary_not_credited(plan, song))
            if reason not in (REASON_MAIN, REASON_OWN_ALBUM):
                bump(counts, f"keep_change_{reason}")
                continue
            ok, why = self._revert_state(plan, song)
            bump(counts, f"{plan['category']}:{reason}:{why}")
            if not ok:
                continue
            to_revert.append(
                {
                    "song_id": plan["song_id"],
                    "category": plan["category"],
                    "reason": reason,
                    "restore_primary_id": plan["old_primary_id"],
                    "expected_current_deezer_id": plan["lead_deezer_id"],
                }
            )
            if len(examples) < options["examples"]:
                examples.append(
                    f"  song {plan['song_id']} [{plan['category']}/{reason}] "
                    f"{plan['lead_name']!r} -> back to {plan['old_primary_name']!r}"
                )

        self.stdout.write(
            "APPLY" if apply else "DRY RUN — nothing written (audit read only)"
        )
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")
        self.stdout.write(f"revertable now: {len(to_revert)}")
        if breakdown:
            self.stdout.write("primary_not_credited breakdown:")
            for key in sorted(breakdown):
                self.stdout.write(f"  {key}: {breakdown[key]}")
        self.stdout.write("examples:")
        for line in examples:
            self.stdout.write(line)

        if apply:
            self._apply(to_revert, Path(options["audit_out"]), options["batch_size"])

    # -- apply ------------------------------------------------------------

    def _apply(self, items: list[dict[str, Any]], out: Path, batch: int) -> None:
        if out.exists():
            raise CommandError(f"audit file already exists: {out}")
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)

            def write(record: dict[str, Any]) -> None:
                handle.write(json.dumps(record, cls=DjangoJSONEncoder) + "\n")

            # The full plan is durable before the first song is touched.
            write({"record": "header", "command": "revert_artist_credit_changes"})
            for item in items:
                write({"record": "plan", **item})
            handle.flush()
            os.fsync(handle.fileno())

            done = skipped = 0
            for index, item in enumerate(items, 1):
                result = self._revert_one(item)
                done += result == "reverted"
                skipped += result != "reverted"
                write(
                    {"record": "result", "song_id": item["song_id"], "outcome": result}
                )
                if index % batch == 0:
                    handle.flush()
                    os.fsync(handle.fileno())
            handle.flush()
            os.fsync(handle.fileno())
        self.stdout.write(f"reverted: {done}; skipped (changed meanwhile): {skipped}")

    @staticmethod
    def _revert_one(item: dict[str, Any]) -> str:
        with transaction.atomic():
            song = (
                Song.objects.select_for_update(of=("self",))
                .select_related("primary_artist")
                .filter(pk=item["song_id"])
                .first()
            )
            if (
                song is None
                or song.primary_artist.deezer_id != item["expected_current_deezer_id"]
            ):
                return "skip_primary_changed_since_backfill"
            if not Artist.objects.filter(pk=item["restore_primary_id"]).exists():
                return "skip_old_primary_missing"
            Song.objects.filter(pk=song.pk).update(
                primary_artist_id=item["restore_primary_id"]
            )
        return "reverted"
