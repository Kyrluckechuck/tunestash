"""Audit likely wrong-version Song mappings for Queuetip playlists.

Finds suspicious cases where ISRC is shared across titles that look like
different variants (plain vs remix/versioned), which is a common source of
wrong-track exports when a library has mixed tagging quality.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db.models import Case, Count, IntegerField, Max, Q, QuerySet, Value, When

from library_manager.models import Song
from queuetip.models import Contribution

_VARIANT_REGEX = r"(remix|mix|edit|vip|remaster|remastered|live|acoustic|instrumental|demo|mono|stereo)"
_REMIX_RE = re.compile(r"\b(remix|mix|edit|vip)\b", re.IGNORECASE)
_VERSION_RE = re.compile(
    r"\b(remaster|remastered|live|acoustic|instrumental|demo|mono|stereo)\b",
    re.IGNORECASE,
)


def _kind(title: str) -> str:
    if _REMIX_RE.search(title):
        return "remix"
    if _VERSION_RE.search(title):
        return "versioned"
    return "plain"


class Command(BaseCommand):
    help = "Audit suspicious ISRC/title variant collisions in Queuetip songs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--playlist-id",
            type=int,
            default=None,
            help="Limit audit to songs contributed to one playlist.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max suspicious groups to print.",
        )

    def handle(self, *args, **options):
        playlist_id = options["playlist_id"]
        limit = options["limit"]

        if playlist_id:
            song_ids = Contribution.objects.filter(playlist_id=playlist_id).values_list(
                "song_id", flat=True
            )
            qs = Song.objects.filter(id__in=song_ids, isrc__isnull=False).exclude(
                isrc=""
            )
        else:
            qs = Song.objects.filter(isrc__isnull=False).exclude(isrc="")

        suspicious_groups = self._suspicious_groups(qs)
        total_count = suspicious_groups.count()
        if total_count == 0:
            self.stdout.write(
                self.style.SUCCESS("No suspicious ISRC/version collisions found.")
            )
            return

        shown_groups = list(suspicious_groups[:limit])
        self.stdout.write(
            self.style.WARNING(
                f"Found {total_count} suspicious ISRC/version collision groups "
                f"(showing {len(shown_groups)}):"
            )
        )

        for group in shown_groups:
            songs = list(
                qs.filter(
                    primary_artist_id=group["primary_artist_id"],
                    isrc=group["isrc"],
                )
                .select_related("primary_artist", "album", "file_path_ref")
                .order_by("id")
            )
            first_song = songs[0]
            artist_name = (
                first_song.primary_artist.name if first_song.primary_artist else "?"
            )
            key = f"{artist_name} | {group['isrc']}"
            self.stdout.write(f"\n- {key}")
            for s in songs:
                album = s.album.name if s.album else "-"
                path = s.file_path or "-"
                self.stdout.write(
                    f"  song_id={s.id} kind={_kind(s.name):9} title={s.name!r} "
                    f"album={album!r} downloaded={s.downloaded} path={path!r}"
                )

    def _suspicious_groups(self, qs: QuerySet[Song]) -> QuerySet[dict[str, object]]:
        return (
            qs.values("primary_artist_id", "isrc")
            .annotate(
                song_count=Count("id"),
                has_variant=Max(
                    Case(
                        When(
                            name__iregex=_VARIANT_REGEX,
                            then=Value(1),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                has_plain=Max(
                    Case(
                        When(
                            ~Q(name__iregex=_VARIANT_REGEX),
                            then=Value(1),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
            )
            .filter(song_count__gt=1, has_plain=1, has_variant=1)
            .order_by("primary_artist_id", "isrc")
        )
