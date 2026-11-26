# mypy: disable-error-code=attr-defined
# mypy: disable-error-code=no-any-return
"""Re-download specific songs so the matcher can pick a different recording.

The current downloaded file is treated as a rejected provider candidate, which
makes the next download attempt skip it. Dry-run by default; --apply requires a
new --audit-file written (0600, fsynced) before any write.
"""

import csv
import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from downloader.providers.base import rejected_key
from downloader.track_matcher import score_track_match

from library_manager.models import ContributingArtist, DownloadProvider, Song
from library_manager.tasks import TaskPriority

logger = logging.getLogger(__name__)

# A match that scores this high on both the persisted provider confidence and
# an independent re-score of its evidence is not worth re-downloading.
_HIGH_CONFIDENCE = 0.9
_MAX_REJECTED_MATCHES = 20

_MATCH_FIELDS = (
    "matched_provider",
    "matched_provider_track_id",
    "matched_title",
    "matched_artist",
    "matched_duration_ms",
    "matched_isrc",
    "match_confidence",
    "matched_at",
)


@dataclass
class RedownloadPlan:
    song: Song
    file_to_remove: Path | None
    rejected_entry: dict[str, str] | None
    reason: str
    queue_by_gid: bool
    artist_names: list[str] = field(default_factory=list)
    clear_updates: dict[str, Any] = field(default_factory=dict)

    @property
    def audit_record(self) -> dict[str, Any]:
        return {
            "id": self.song.id,
            "name": self.song.name,
            "reason": self.reason,
            "primary_artist": self.song.primary_artist.name,
            "contributing_artists": self.artist_names,
            "current_file": self.song.file_path,
            "matched": {
                field_name: getattr(self.song, field_name)
                for field_name in _MATCH_FIELDS
            },
            "rejected_entry": self.rejected_entry,
            "remove_file": str(self.file_to_remove) if self.file_to_remove else None,
            "queue_by_gid": self.queue_by_gid,
            "rollback": {
                "downloaded": self.song.downloaded,
                "bitrate": self.song.bitrate,
                "file_path_ref_id": self.song.file_path_ref_id,
                "failed_count": self.song.failed_count,
                "failure_reason": self.song.failure_reason,
                "rejected_matches": list(self.song.rejected_matches or []),
                **{
                    field_name: getattr(self.song, field_name)
                    for field_name in _MATCH_FIELDS
                },
            },
        }


def _expected_credit(song: Song, contributors: list[str]) -> str:
    """Build a full artist credit so featured artists are part of the score."""
    names = [song.primary_artist.name, *contributors]
    return ", ".join(names)


def current_match_is_high_confidence(song: Song, contributors: list[str]) -> bool:
    """True when the persisted match still looks right to the current matcher."""
    if not song.matched_title or not song.matched_provider_track_id:
        return False
    if song.match_confidence is None or song.match_confidence < _HIGH_CONFIDENCE:
        return False
    score = score_track_match(
        song.name,
        _expected_credit(song, contributors),
        song.matched_title,
        song.matched_artist or "",
        search_isrc=song.isrc,
        result_isrc=song.matched_isrc,
        search_alternate_isrcs=song.alternate_isrcs,
    )
    return score >= _HIGH_CONFIDENCE


class Command(BaseCommand):
    help = (
        "Re-download songs with the current match marked as rejected. "
        "Dry-run by default; --apply requires a new --audit-file."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--song", type=int, action="append", default=[])
        parser.add_argument("--from-csv")
        parser.add_argument("--column", default="song_id")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-file")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download even when the current match scores high",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        song_ids = self._song_ids(options)
        if not song_ids:
            raise CommandError("pass --song <id> or --from-csv <path>")
        if options["apply"] and not options["audit_file"]:
            raise CommandError("--apply requires --audit-file")
        if not options["apply"] and options["audit_file"]:
            raise CommandError("--audit-file only applies with --apply")

        plans: list[RedownloadPlan] = []
        skipped: list[tuple[int, str]] = []
        for song_id in song_ids:
            plan, skip_reason = self._build_plan(song_id, force=options["force"])
            if plan is None:
                skipped.append((song_id, skip_reason))
            else:
                plans.append(plan)

        if not options["apply"]:
            self.stdout.write("DRY RUN — no changes made")
            for plan in plans:
                self._print_plan(plan)
            for song_id, reason in skipped:
                self.stdout.write(f"song {song_id}: skipped ({reason})")
            self.stdout.write(
                f"Planned {len(plans)} re-download(s); {len(skipped)} skipped"
            )
            self._simulate(plans)
            self.stdout.write("Constraint simulation passed (writes rolled back)")
            return

        audit_path = Path(options["audit_file"])
        if audit_path.exists():
            raise CommandError(f"audit file already exists: {audit_path}")
        records = [plan.audit_record for plan in plans]
        self._write_audit(audit_path, records)
        self.stdout.write(f"Audit written and fsynced: {audit_path}")
        for plan in plans:
            self._print_plan(plan)

        applied = 0
        queued = 0
        with transaction.atomic():
            locked = {
                song.id: song
                for song in Song.objects.select_for_update().filter(
                    id__in=[plan.song.id for plan in plans]
                )
            }
            for plan in plans:
                self._apply_plan(locked[plan.song.id], plan)
                applied += 1

        from library_manager import helpers

        for plan in plans:
            if plan.queue_by_gid and plan.song.gid:
                published = helpers.enqueue_download_track_by_spotify_gid(
                    plan.song.gid, priority=TaskPriority.TRACK_DOWNLOAD
                )
            else:
                published = helpers.enqueue_download_deezer_track(
                    plan.song.id, priority=TaskPriority.TRACK_DOWNLOAD
                )
            if published:
                queued += 1
            else:
                self.stdout.write(
                    f"song {plan.song.id}: re-queue skipped (already active)"
                )
        for song_id, reason in skipped:
            self.stdout.write(f"song {song_id}: skipped ({reason})")
        self.stdout.write(
            f"Applied {applied} re-download(s); queued {queued} download(s)"
        )

    def _song_ids(self, options: dict[str, Any]) -> list[int]:
        raw: list[Any] = list(options["song"] or [])
        if options["from_csv"]:
            if raw:
                raise CommandError("--song and --from-csv are mutually exclusive")
            raw = self._read_csv(Path(options["from_csv"]), options["column"])
        song_ids: list[int] = []
        for value in raw:
            try:
                song_ids.append(int(value))
            except (TypeError, ValueError) as exc:
                raise CommandError(f"invalid song id: {value!r}") from exc
        return list(dict.fromkeys(song_ids))

    def _read_csv(self, path: Path, column: str) -> list[str]:
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or column not in reader.fieldnames:
                    raise CommandError(
                        f"CSV {path} has no column {column!r}: {reader.fieldnames}"
                    )
                return [row[column] for row in reader if row.get(column)]
        except OSError as exc:
            raise CommandError(f"cannot read CSV {path}: {exc}") from exc

    def _build_plan(
        self, song_id: int, *, force: bool
    ) -> tuple[RedownloadPlan | None, str]:
        try:
            song = Song.objects.select_related("primary_artist", "file_path_ref").get(
                pk=song_id
            )
        except Song.DoesNotExist as exc:
            raise CommandError(f"song {song_id} does not exist") from exc
        contributors = list(
            ContributingArtist.objects.filter(song=song)
            .exclude(artist=song.primary_artist)
            .values_list("artist__name", flat=True)
        )
        if not force and current_match_is_high_confidence(song, contributors):
            return None, "current match passes the matcher with high confidence"

        rejected_entry = self._rejected_entry(song)
        if rejected_entry is None and not song.file_path and not song.matched_provider:
            return None, "no known provider result or file to reject"

        file_to_remove = None
        if song.file_path_ref:
            path = Path(song.file_path_ref.path)
            root = Path(
                getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")
            ).resolve()
            if path.resolve().is_relative_to(root) and not (
                Song.objects.filter(file_path_ref=song.file_path_ref)
                .exclude(id=song.id)
                .exists()
            ):
                file_to_remove = path

        clear_updates: dict[str, Any] = {}
        if song.downloaded:
            clear_updates["downloaded"] = False
        if song.bitrate:
            clear_updates["bitrate"] = 0
        if song.failed_count:
            clear_updates["failed_count"] = 0
        if song.failure_reason:
            clear_updates["failure_reason"] = None
        if song.last_failed_at:
            clear_updates["last_failed_at"] = None
        for field_name in _MATCH_FIELDS:
            if getattr(song, field_name) is not None:
                clear_updates[field_name] = None
        if file_to_remove and song.file_path_ref:
            clear_updates["file_path_ref"] = None

        reason = "explicit re-download request"
        if rejected_entry:
            reason = f"reject current {rejected_entry['provider']} candidate"
        return (
            RedownloadPlan(
                song=song,
                file_to_remove=file_to_remove,
                rejected_entry=rejected_entry,
                reason=reason,
                queue_by_gid=bool(song.deezer_id is None and song.gid),
                artist_names=contributors,
                clear_updates=clear_updates,
            ),
            "",
        )

    def _rejected_entry(self, song: Song) -> dict[str, str] | None:
        """Remember the current match, or the current file's provider id."""
        if song.matched_provider and song.matched_provider_track_id:
            return {
                "provider": song.matched_provider,
                "provider_track_id": song.matched_provider_track_id,
                "reason": "redownload: replaced wrong recording",
                "at": timezone.now().isoformat(),
            }
        # Legacy downloads have no matched_* evidence. youtube_id is the only
        # field that holds a real provider candidate id; deezer_id is a catalog
        # id from a different namespace and would never exclude a provider
        # result, so it must not be borrowed as one.
        if song.youtube_id and song.download_provider in (
            DownloadProvider.SPOTDL,
            DownloadProvider.YOUTUBE,
        ):
            return {
                "provider": "youtube",
                "provider_track_id": song.youtube_id,
                "reason": "redownload: replaced current file",
                "at": timezone.now().isoformat(),
            }
        return None

    def _print_plan(self, plan: RedownloadPlan) -> None:
        song = plan.song
        names = ", ".join([song.primary_artist.name, *plan.artist_names])
        self.stdout.write(
            f"song {song.id} ({song.name}) artists: {names}; "
            f"file: {song.file_path or 'none'}"
        )
        matched = ", ".join(
            f"{name}={getattr(song, name)}"
            for name in _MATCH_FIELDS
            if getattr(song, name) is not None
        )
        self.stdout.write(f"  matched: {matched or 'none'}")
        self.stdout.write(f"  reason: {plan.reason}")
        if plan.rejected_entry:
            self.stdout.write(
                "  reject: "
                f"{rejected_key(plan.rejected_entry['provider'], plan.rejected_entry['provider_track_id'])}"
            )
        if plan.file_to_remove:
            self.stdout.write(f"  remove file: {plan.file_to_remove}")
        else:
            self.stdout.write("  keep file (shared or outside music root)")
        self.stdout.write(
            f"  re-queue: {'by Spotify gid' if plan.queue_by_gid else 'by song id'}"
        )

    def _write_audit(self, path: Path, records: list[dict[str, Any]]) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, cls=DjangoJSONEncoder, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    def _simulate(self, plans: list[RedownloadPlan]) -> None:
        try:
            with transaction.atomic():
                locked = {
                    song.id: song
                    for song in Song.objects.select_for_update().filter(
                        id__in=[plan.song.id for plan in plans]
                    )
                }
                for plan in plans:
                    self._apply_plan(locked[plan.song.id], plan, simulate=True)
                transaction.set_rollback(True)
        except Exception as exc:  # pylint: disable=broad-except
            raise CommandError(f"dry-run simulation would fail: {exc}") from exc

    def _apply_plan(
        self, song: Song, plan: RedownloadPlan, *, simulate: bool = False
    ) -> None:
        existing = list(song.rejected_matches or [])
        if plan.rejected_entry:
            key = rejected_key(
                plan.rejected_entry["provider"],
                plan.rejected_entry["provider_track_id"],
            )
            if not any(
                rejected_key(
                    str(entry.get("provider") or ""),
                    str(entry.get("provider_track_id") or ""),
                )
                == key
                for entry in existing
            ):
                existing.append(plan.rejected_entry)
                song.rejected_matches = existing[-_MAX_REJECTED_MATCHES:]
                if not simulate:
                    song.save(update_fields=["rejected_matches"])
        if plan.clear_updates:
            for field_name, value in plan.clear_updates.items():
                setattr(song, field_name, value)
            if not simulate:
                song.save(update_fields=list(plan.clear_updates))
        if not simulate and plan.file_to_remove and plan.file_to_remove.is_file():
            plan.file_to_remove.unlink()
