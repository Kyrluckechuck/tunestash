"""Backfill contributors and lead primary artists on existing songs.

Source authority is the Deezer single-track response: only its complete
``contributors`` payload (anchored by provider ids) may replace a song's
identity. A failed or incomplete lookup leaves the row untouched.

Dry-run by default. ``--apply`` requires a new ``--audit-file`` (mode 0600).
Plans are fsynced before that batch's writes. Each song is committed in its own
transaction, and a per-song ``complete`` audit record is written and fsynced
only *after* the commit, so the printed cursor advances only past committed
work. Failures are recorded as ``failed`` with their own ids and are never
skipped by a resume: use ``--retry-failed`` with the same audit file.

File paths are never touched; ``path_would_change`` is reported so a reviewed
metadata-migration pass can handle it separately.
"""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from library_manager.artist_credits import (
    credits_for_track,
    normalize_artist_name,
    related_song_ids,
    replace_identity_if_unchanged,
    resolve_credits,
    same_name_different_id,
)
from library_manager.models import Artist, ContributingArtist, Song
from src.providers.metadata_base import ArtistCredit, TrackResult

CATEGORY_ALREADY_LEAD = "primary_is_lead"
CATEGORY_FEATURED = "featured_as_primary"
CATEGORY_SAME_NAME = "primary_name_matches_other_credit"
CATEGORY_UNRELATED = "primary_not_credited"
# Outcomes that may succeed on a later run; permanent skips (ISRC conflict)
# are final and do not hold the resume cursor back.
RETRYABLE_OUTCOMES = frozenset(
    {
        "skip_lookup_failed",
        "skip_incomplete_payload",
        "skip_resolution_failed",
        "skip_changed_concurrently",
    }
)


@dataclass
class SongPlan:
    song_id: int
    name: str
    status: str
    category: str = ""
    old_primary_id: int = 0
    old_primary_name: str = ""
    old_primary_deezer_id: Optional[int] = None
    lead_name: str = ""
    lead_deezer_id: Optional[int] = None
    credits: list[dict[str, Any]] = field(default_factory=list)
    existing_contributor_ids: list[int] = field(default_factory=list)
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    path_would_change: bool = False
    evidence_isrcs: list[str] = field(default_factory=list)
    ambiguous_credits: list[str] = field(default_factory=list)
    would_adopt: int = 0
    would_create: int = 0

    @property
    def changes_primary(self) -> bool:
        return self.status == "fix" and self.category != CATEGORY_ALREADY_LEAD


class Command(BaseCommand):
    help = (
        "Replace song credits from complete Deezer source payloads. "
        "Dry-run by default; --apply requires a new --audit-file."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None
        self._sleep = 0.0
        self._lookups = 0
        self._cache: dict[str, Any] = {}

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-file")
        parser.add_argument("--song", type=int, action="append", default=[])
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--limit", type=int, default=0, help="Max songs (0=all)")
        parser.add_argument("--after-id", type=int, default=0, help="Resume point")
        parser.add_argument(
            "--sleep", type=float, default=0.25, help="Seconds between lookups"
        )
        parser.add_argument("--cache-file", help="JSON cache of Deezer lookups")
        parser.add_argument("--show", type=int, default=20, help="Rows to print")
        parser.add_argument("--include-undownloaded", action="store_true")
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry ids recorded as failed in --audit-file",
        )

    # -- lookups ---------------------------------------------------------

    def _load_cache(self, path: Optional[str]) -> dict[str, Any]:
        if path and Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
        return {}

    def _save_cache(self, path: Optional[str]) -> None:
        if not path:
            return
        tmp = f"{path}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self._cache, handle)
        os.replace(tmp, path)

    def _fetch_track(self, deezer_id: int) -> Optional[TrackResult]:
        """One uncached Deezer lookup (patched in tests)."""
        import deezer  # pylint: disable=import-outside-toplevel

        from src.providers.deezer import (  # pylint: disable=import-outside-toplevel
            _to_track_result,
        )

        if self._client is None:
            self._client = deezer.Client()
        try:
            return _to_track_result(self._client.get_track(deezer_id))
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _lookup(self, deezer_id: int) -> Optional[TrackResult]:
        key = str(deezer_id)
        if key in self._cache:
            raw = self._cache[key]
            return TrackResult(
                name=raw["name"],
                artist_name=raw["artist_name"],
                deezer_id=deezer_id,
                isrc=raw.get("isrc"),
                artist_deezer_id=raw.get("artist_deezer_id"),
                credits=[ArtistCredit(**c) for c in raw["credits"]],
            )
        if self._lookups and self._sleep:
            time.sleep(self._sleep)
        self._lookups += 1
        track = self._fetch_track(deezer_id)
        if track is None or not track.credits:
            return None
        self._cache[key] = {
            "name": track.name,
            "artist_name": track.artist_name,
            "isrc": track.isrc,
            "artist_deezer_id": track.artist_deezer_id,
            "credits": [asdict(c) for c in track.credits],
        }
        return track

    # -- planning --------------------------------------------------------

    def _candidates(self, options: dict[str, Any], after_id: int) -> Any:
        qs = Song.objects.filter(deezer_id__isnull=False)
        if options["song"]:
            qs = qs.filter(id__in=options["song"])
        if not options["include_undownloaded"]:
            qs = qs.filter(downloaded=True)
        # Default: recheck every Deezer-id song. A contributor row alone does
        # not prove the full source credits were ever fetched and verified.
        return qs.filter(id__gt=after_id).select_related(
            "primary_artist", "file_path_ref"
        )

    def _path_change(self, song: Song, lead_name: str) -> tuple[Optional[str], bool]:
        if not song.file_path_ref:
            return None, False
        from types import SimpleNamespace

        from library_manager.tasks.metadata import (  # pylint: disable=import-outside-toplevel
            _metadata_destination,
        )

        # A shallow Django-model copy recursively copies related objects and
        # can hang; the path helper only reads these three attributes.
        probe = SimpleNamespace(
            primary_artist=Artist(name=lead_name),
            album=song.album,
            name=song.name,
        )
        try:
            destination = str(_metadata_destination(probe, Path(song.file_path)))
        except Exception:  # pylint: disable=broad-exception-caught
            return None, False
        return destination, destination != song.file_path

    def _plan_song(self, song: Song) -> SongPlan:
        plan = SongPlan(
            song_id=song.pk,
            name=song.name,
            status="unchanged",
            old_primary_id=song.primary_artist_id,
            old_primary_name=song.primary_artist.name,
            old_primary_deezer_id=song.primary_artist.deezer_id,
            old_path=song.file_path,
            existing_contributor_ids=list(
                ContributingArtist.objects.filter(song=song).values_list(
                    "artist_id", flat=True
                )
            ),
        )
        track = self._lookup(int(song.deezer_id))
        if track is None:
            plan.status = "skip_lookup_failed"
            return plan
        if not all(c.deezer_id is not None for c in track.credits):
            # Incomplete payload: never replace verified source data.
            plan.status = "skip_incomplete_payload"
            return plan
        if not track.isrc or not self._isrc_ok(song, track.isrc):
            plan.status = "skip_isrc_conflict"
            return plan

        # The same lead rule as ingestion: the provider's track artist, else
        # the first "main" credit, never raw contributor position.
        credits = credits_for_track(track, fetch_missing=False)
        lead = credits[0]
        old = song.primary_artist
        plan.lead_name, plan.lead_deezer_id = lead.name, lead.deezer_id
        plan.credits = [asdict(c) for c in credits]
        if same_name_different_id(old, lead):
            # Possibly a duplicate Deezer page of the same artist: keep the
            # primary, create nothing, report for manual review.
            plan.status = "skip_same_name_different_id"
            return plan
        plan.evidence_isrcs = sorted(
            {i for i in [song.isrc, *(song.alternate_isrcs or []), track.isrc] if i}
        )

        # Read-only resolution: which credits exist, would be adopted onto a
        # verified same-name row, would be created, or are ambiguous.
        resolutions = resolve_credits(
            credits,
            plan.evidence_isrcs,
            create=False,
            exclude_song_ids=related_song_ids(song.pk),
        )
        plan.would_adopt = sum(r.status == "would_adopt" for r in resolutions)
        plan.would_create = sum(r.status == "would_create" for r in resolutions)
        plan.ambiguous_credits = [
            c.name for c, r in zip(credits, resolutions) if r.status == "ambiguous"
        ]
        if plan.ambiguous_credits:
            # An unverified same-name artist exists: leave the song unchanged
            # and report it for manual linking rather than create a duplicate.
            plan.status = "skip_ambiguous_artist"
            return plan
        plan.status = "fix"

        lead_artist = resolutions[0].artist
        if old.deezer_id == lead.deezer_id or (
            lead_artist is not None and lead_artist.pk == old.pk
        ):
            plan.category = CATEGORY_ALREADY_LEAD
        elif old.deezer_id in {c.deezer_id for c in credits}:
            plan.category = CATEGORY_FEATURED
        elif old.deezer_id is not None and normalize_artist_name(old.name) in {
            normalize_artist_name(c.name) for c in credits
        }:
            # Same name, different provider id: report only, never merge.
            plan.category = CATEGORY_SAME_NAME
        else:
            plan.category = CATEGORY_UNRELATED

        if plan.changes_primary:
            plan.new_path, plan.path_would_change = self._path_change(song, lead.name)
        return plan

    @staticmethod
    def _isrc_ok(song: Song, candidate: str) -> bool:
        from library_manager.tasks.song_identity import isrc_is_compatible

        return isrc_is_compatible(song, candidate)

    # -- applying --------------------------------------------------------

    def _apply_plan(self, plan: SongPlan) -> str:
        """Swap identity inside one transaction, guarded by the pre-image.

        Artists are resolved (created or adopted) only after the guard passes
        and inside the same transaction, so a stale or ambiguous plan leaves
        no orphan or duplicate Artist rows.
        """
        credits = [ArtistCredit(**c) for c in plan.credits]
        if not all(c.deezer_id is not None for c in credits):
            return "skip_incomplete_payload"
        expected = (plan.old_primary_id, frozenset(plan.existing_contributor_ids))
        outcome = replace_identity_if_unchanged(
            plan.song_id, expected, credits, plan.evidence_isrcs
        )
        return {
            "applied": "applied",
            "ambiguous": "skip_ambiguous_artist",
            "same_name_different_id": "skip_same_name_different_id",
        }.get(outcome, "skip_changed_concurrently")

    def _write_audit_line(self, handle: Any, record: dict[str, Any]) -> None:
        handle.write(json.dumps(record, cls=DjangoJSONEncoder) + "\n")

    def _write_and_sync(self, handle: Any, record: dict[str, Any]) -> None:
        """Write one audit line and make it durable before returning."""
        self._write_audit_line(handle, record)
        handle.flush()
        os.fsync(handle.fileno())

    # -- entry point -----------------------------------------------------

    def handle(self, *args: Any, **options: Any) -> None:
        apply = options["apply"]
        audit_file = options["audit_file"]
        if apply and not audit_file:
            raise CommandError("--apply requires --audit-file")
        if not apply and audit_file:
            raise CommandError("--audit-file only applies with --apply")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        self._sleep = options["sleep"]
        self._lookups = 0
        self._cache = self._load_cache(options["cache_file"])
        pending_failed = (
            set(self._failed_ids(audit_file)) if options["retry_failed"] else set()
        )

        audit_handle = None
        if apply:
            audit_path = Path(audit_file)
            if audit_path.exists() and not options["retry_failed"]:
                raise CommandError(f"audit file already exists: {audit_path}")
            mode = "a" if options["retry_failed"] else "x"
            if mode == "x":
                fd = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                audit_handle = os.fdopen(fd, "w", encoding="utf-8")
                os.chmod(audit_path, stat.S_IRUSR | stat.S_IWUSR)
                self._write_and_sync(
                    audit_handle,
                    {
                        "record": "header",
                        "command": "backfill_artist_credits",
                        "after_id": options["after_id"],
                        "batch_size": options["batch_size"],
                    },
                )
            else:
                audit_handle = open(  # pylint: disable=consider-using-with
                    audit_path, "a", encoding="utf-8"
                )

        counts: dict[str, int] = {}
        shown = 0
        processed = 0
        committed_id = options["after_id"]
        scan_id = options["after_id"]
        blocked = False
        limit = options["limit"]
        self.stdout.write(
            "APPLY" if apply else "DRY RUN — no changes made, no audit file written"
        )
        try:
            while True:
                size = options["batch_size"]
                if limit:
                    size = min(size, limit - processed)
                    if size <= 0:
                        break
                if pending_failed:
                    batch = list(
                        Song.objects.filter(id__in=pending_failed).order_by("id")[:size]
                    )
                else:
                    batch = list(
                        self._candidates(options, scan_id).order_by("id")[:size]
                    )
                if not batch:
                    break
                plans = [self._plan_song(song) for song in batch]
                processed += len(batch)
                scan_id = max(scan_id, batch[-1].pk)

                if audit_handle is not None:
                    for plan in plans:
                        self._write_audit_line(audit_handle, asdict(plan))
                    audit_handle.flush()
                    os.fsync(audit_handle.fileno())

                for plan in plans:
                    show_row = (
                        plan.status
                        in (
                            "fix",
                            "skip_ambiguous_artist",
                            "skip_same_name_different_id",
                        )
                        and shown < options["show"]
                    )
                    shown += int(show_row)
                    outcome = self._record_outcome(plan, apply, counts, show_row)
                    pending_failed.discard(plan.song_id)
                    failed = outcome in RETRYABLE_OUTCOMES
                    # The resumable cursor never passes a song that still needs
                    # a retry; later successes are simply re-planned (idempotent).
                    blocked = blocked or failed
                    if not blocked:
                        committed_id = max(committed_id, plan.song_id)
                    if audit_handle is not None:
                        self._write_and_sync(
                            audit_handle,
                            {
                                "record": (
                                    "failed"
                                    if failed
                                    else ("complete" if apply else "dry_run")
                                ),
                                "song_id": plan.song_id,
                                "outcome": outcome,
                                "cursor": committed_id,
                            },
                        )
                self._save_cache(options["cache_file"])
                self.stdout.write(f"batch done; committed_id={committed_id}")
        finally:
            if audit_handle is not None:
                audit_handle.close()

        self._summary(counts, processed, committed_id)

    @staticmethod
    def _failed_ids(audit_file: Optional[str]) -> list[int]:
        if not audit_file or not Path(audit_file).exists():
            return []
        ids = []
        for line in Path(audit_file).read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record") == "failed":
                ids.append(int(record["song_id"]))
        return ids

    def _record_outcome(
        self, plan: SongPlan, apply: bool, counts: dict[str, int], show_row: bool
    ) -> str:
        outcome = plan.status
        if plan.status == "fix":
            outcome = plan.category
            if apply:
                result = self._apply_plan(plan)
                if result != "applied":
                    outcome = result
        counts[outcome] = counts.get(outcome, 0) + 1
        if plan.changes_primary and plan.path_would_change:
            counts["path_would_change"] = counts.get("path_would_change", 0) + 1
        for key, amount in (
            ("artists_to_adopt", plan.would_adopt),
            ("artists_to_create", plan.would_create),
        ):
            if amount and plan.status == "fix":
                counts[key] = counts.get(key, 0) + amount
        if show_row:
            self._print_plan(plan)
        return outcome

    def _print_plan(self, plan: SongPlan) -> None:
        if plan.status == "skip_same_name_different_id":
            self.stdout.write(
                f"  song {plan.song_id} [same_name_different_id, unchanged] "
                f"primary {plan.old_primary_name!r} (deezer {plan.old_primary_deezer_id}) "
                f"vs credited lead {plan.lead_name!r} (deezer {plan.lead_deezer_id})"
            )
            return
        if plan.status == "skip_ambiguous_artist":
            self.stdout.write(
                f"  song {plan.song_id} [ambiguous, unchanged] unverified "
                f"same-name artist row(s) for {plan.ambiguous_credits}"
            )
            return
        arrow = (
            f"primary {plan.old_primary_name!r} -> {plan.lead_name!r}"
            if plan.changes_primary
            else f"primary stays {plan.old_primary_name!r}"
        )
        self.stdout.write(
            f"  song {plan.song_id} [{plan.category}] {arrow}; "
            f"{len(plan.credits)} credits; path_would_change={plan.path_would_change}"
        )

    def _summary(self, counts: dict[str, int], processed: int, cursor: int) -> None:
        self.stdout.write(
            f"songs examined: {processed}; Deezer lookups: {self._lookups}"
        )
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")
        self.stdout.write(f"resume with --after-id {cursor}")
