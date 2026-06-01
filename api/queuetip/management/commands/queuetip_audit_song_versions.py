"""Audit likely wrong-version Song mappings for Queuetip playlists.

Finds suspicious cases where ISRC is shared across titles that look like
different variants (plain vs remix/versioned), which is a common source of
wrong-track exports when a library has mixed tagging quality.
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.core.management.base import BaseCommand

from library_manager.models import Song
from queuetip.models import Contribution

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

        # Group by (artist, isrc) so we compare variants of the same recording
        # as tagged in the local DB.
        grouped: dict[tuple[int | None, str], list[Song]] = defaultdict(list)
        for s in qs.select_related("primary_artist", "album"):
            grouped[(s.primary_artist_id, s.isrc)].append(s)

        suspicious: list[tuple[str, list[Song]]] = []
        for (artist_id, isrc), songs in grouped.items():
            if len(songs) < 2:
                continue
            kinds = {_kind(s.name) for s in songs}
            if "plain" in kinds and ("remix" in kinds or "versioned" in kinds):
                artist_name = (
                    songs[0].primary_artist.name if songs[0].primary_artist else "?"
                )
                suspicious.append((f"{artist_name} | {isrc}", songs))

        suspicious.sort(key=lambda item: item[0])
        shown = suspicious[:limit]

        if not shown:
            self.stdout.write(
                self.style.SUCCESS("No suspicious ISRC/version collisions found.")
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {len(suspicious)} suspicious ISRC/version collision groups "
                f"(showing {len(shown)}):"
            )
        )
        for key, songs in shown:
            self.stdout.write(f"\n- {key}")
            for s in sorted(songs, key=lambda x: x.id):
                album = s.album.name if s.album else "-"
                path = s.file_path or "-"
                self.stdout.write(
                    f"  song_id={s.id} kind={_kind(s.name):9} title={s.name!r} "
                    f"album={album!r} downloaded={s.downloaded} path={path!r}"
                )
