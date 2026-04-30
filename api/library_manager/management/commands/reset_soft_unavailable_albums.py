"""Reset Album.unavailable=False on albums marked unavailable due to soft failures.

Companion to the model change that narrowed Album.unavailable to mean "Deezer
has no metadata for this album" (DEEZER_NO_TRACKS only). Historical data has
~1,000+ albums marked unavailable=True from the prior auto-flag-at-fc>=3
behavior; this command rehabilitates them so they re-enter the periodic
queue and the per-album backoff curve takes over for deprioritization.

Defaults to dry-run; pass --apply to actually update.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from library_manager.models import Album, AlbumFailureReason


class Command(BaseCommand):
    help = (
        "Reset unavailable=False on albums marked unavailable due to soft "
        "failures (anything except DEEZER_NO_TRACKS)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually perform the update (default is dry-run)",
        )

    def handle(self, *args, **options) -> None:
        apply_changes = options["apply"]

        soft_unavailable = Album.objects.filter(unavailable=True).exclude(
            failure_reason=AlbumFailureReason.DEEZER_NO_TRACKS
        )
        total = soft_unavailable.count()

        hard_count = Album.objects.filter(
            unavailable=True, failure_reason=AlbumFailureReason.DEEZER_NO_TRACKS
        ).count()

        self.stdout.write(
            f"Found {total} albums with unavailable=True and a soft failure_reason "
            f"(eligible for reset)."
        )
        self.stdout.write(
            f"Leaving {hard_count} DEEZER_NO_TRACKS albums untouched (legitimate "
            f"hard verdicts)."
        )

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        # Group breakdown for visibility
        by_reason = (
            soft_unavailable.values("failure_reason")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        self.stdout.write("Breakdown by failure_reason:")
        for row in by_reason:
            label = row["failure_reason"] or "(null)"
            self.stdout.write(f"  {label}: {row['n']}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN — no changes made. Pass --apply to actually update."
                )
            )
            return

        updated = soft_unavailable.update(unavailable=False)
        self.stdout.write(
            self.style.SUCCESS(f"Reset unavailable=False on {updated} album(s).")
        )
