"""Mark backlog albums as wanted=False when they're known-redundant.

Three independent categories:

1. --isrc-redundant: every ISRC-bearing track in the album already has a
   downloaded twin on a different album by the same artist (Spotify-single
   re-releases of tracks that are also on the parent album).

2. --spotify-only: deezer_id IS NULL — can't be downloaded via the
   Deezer-first pipeline regardless of intent. Includes legitimate
   Spotify-exclusive content (Spotify Singles series) and metadata noise.

3. --compilations: name patterns suggesting a compilation, live recording,
   or DJ-mix (best of, greatest hits, anthology, live at, mixed by, etc.),
   excluding Deluxe-style re-releases that often have legitimate bonus
   tracks.

Default dry-run; pass --apply to update. Setting wanted=False is reversible
via the per-album UI toggle if you want to retry a specific album later.
"""

from collections import defaultdict
from typing import Iterable

from django.core.management.base import BaseCommand
from django.db.models import Q

from library_manager.models import Album, Song

# Patterns that strongly suggest a non-original release. Conservatively chosen
# to avoid catching real albums (e.g., not "remix" alone, since that's often
# a track on a real EP). Intentionally NOT included: deluxe, expanded,
# anniversary, remastered, reissue, extended edition — those often have
# legitimate bonus content.
COMPILATION_INCLUDE = [
    "compilation",
    "collection",
    "best of ",
    "greatest hits",
    "anthology",
    "the essential",
    " hits ",
    "mixed by",
    "live at",
    "live in",
    "rarities",
    "b-sides",
]
COMPILATION_EXCLUDE = [
    "deluxe",
    "expanded",
    "anniversary",
    "remastered",
    "extended edition",
    "reissue",
]


class Command(BaseCommand):
    help = (
        "Mark backlog albums as wanted=False when they fall into known-redundant "
        "categories (ISRC duplicates, Spotify-only metadata, compilations/live)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--isrc-redundant",
            action="store_true",
            help="Mark albums where every ISRC has a downloaded twin elsewhere",
        )
        parser.add_argument(
            "--spotify-only",
            action="store_true",
            help="Mark albums with no deezer_id (cannot be sourced via Deezer)",
        )
        parser.add_argument(
            "--compilations",
            action="store_true",
            help=(
                "Mark albums matching compilation/live name patterns "
                "(excludes Deluxe-style re-releases)"
            ),
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Shorthand for --isrc-redundant --spotify-only --compilations",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually perform the update (default is dry-run)",
        )

    def handle(self, *args, **options) -> None:
        do_isrc = options["isrc_redundant"] or options["all"]
        do_spotify = options["spotify_only"] or options["all"]
        do_compilations = options["compilations"] or options["all"]
        apply_changes = options["apply"]

        if not (do_isrc or do_spotify or do_compilations):
            self.stdout.write(
                self.style.ERROR(
                    "No category selected. Pass --isrc-redundant, "
                    "--spotify-only, --compilations, or --all."
                )
            )
            return

        backlog = Album.objects.filter(
            artist__tracking_tier__gte=1, wanted=True, downloaded=False
        )

        all_target_ids: set[int] = set()

        if do_isrc:
            ids = self._find_isrc_redundant(backlog)
            self.stdout.write(f"ISRC-redundant: {len(ids)} albums")
            all_target_ids |= ids

        if do_spotify:
            ids = set(
                backlog.filter(deezer_id__isnull=True).values_list("id", flat=True)
            )
            self.stdout.write(f"Spotify-only (no deezer_id): {len(ids)} albums")
            all_target_ids |= ids

        if do_compilations:
            ids = self._find_compilations(backlog)
            self.stdout.write(f"Compilations/live (excl Deluxe): {len(ids)} albums")
            all_target_ids |= ids

        self.stdout.write("")
        self.stdout.write(
            f"Total unique albums to mark wanted=False: {len(all_target_ids)}"
        )

        if not all_target_ids:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        # Show a few samples
        self.stdout.write("Sample (first 10):")
        for a in Album.objects.filter(id__in=list(all_target_ids)[:10]):
            self.stdout.write(
                f"  id={a.id} {a.name[:60]!r} "
                f"type={a.album_type} fc={a.failed_count}"
            )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN — no changes made. Pass --apply to actually update."
                )
            )
            return

        updated = Album.objects.filter(id__in=all_target_ids).update(wanted=False)
        self.stdout.write(
            self.style.SUCCESS(f"Set wanted=False on {updated} album(s).")
        )

    def _find_isrc_redundant(self, backlog: Iterable[Album]) -> set[int]:
        """Find backlog albums where every ISRC has a downloaded twin elsewhere
        by the same artist."""
        # Build artist_id → set((isrc, album_id)) for downloaded songs
        dl_isrcs_by_artist: dict[int, set[tuple[str, int]]] = defaultdict(set)
        qs = (
            Song.objects.filter(downloaded=True)
            .exclude(isrc__isnull=True)
            .exclude(isrc="")
            .values("primary_artist_id", "isrc", "album_id")
            .iterator()
        )
        for s in qs:
            dl_isrcs_by_artist[s["primary_artist_id"]].add((s["isrc"], s["album_id"]))

        target_ids: set[int] = set()
        for album in backlog.iterator():
            backlog_isrcs = list(
                Song.objects.filter(album_id=album.id)
                .exclude(isrc__isnull=True)
                .exclude(isrc="")
                .values_list("isrc", flat=True)
            )
            if not backlog_isrcs:
                continue
            dl_isrcs = {
                isrc
                for isrc, alb_id in dl_isrcs_by_artist.get(album.artist_id, set())
                if alb_id != album.id
            }
            if all(isrc in dl_isrcs for isrc in backlog_isrcs):
                target_ids.add(album.id)
        return target_ids

    def _find_compilations(self, backlog) -> set[int]:
        """Find backlog albums matching compilation/live name patterns,
        excluding Deluxe-style re-releases."""
        include_q = Q()
        for kw in COMPILATION_INCLUDE:
            include_q |= Q(name__icontains=kw)
        exclude_q = Q()
        for kw in COMPILATION_EXCLUDE:
            exclude_q |= Q(name__icontains=kw)
        return set(
            backlog.filter(include_q).exclude(exclude_q).values_list("id", flat=True)
        )
