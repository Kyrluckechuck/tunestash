"""Manually link an Artist record to a Deezer artist ID.

For artists whose names differ fundamentally between Spotify and Deezer
(cross-language names, name variants with suffixes), the automated resolve
pipeline can't match them. This command allows manual linking with Deezer
API validation.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from library_manager.models import Album, Artist, Song
from library_manager.tasks.core import normalize_name


class Command(BaseCommand):
    help = "Manually link an Artist record to a Deezer artist ID"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "artist_id",
            nargs="?",
            type=int,
            help="Database ID of the Artist record",
        )
        parser.add_argument(
            "deezer_id",
            nargs="?",
            type=int,
            help="Deezer artist ID to assign",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the link without saving",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow overwriting an existing deezer_id",
        )
        parser.add_argument(
            "--show-unlinked",
            action="store_true",
            help="List artists without deezer_id that have downloaded songs",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Limit --show-unlinked output (default 50)",
        )

    def _handle_show_unlinked(self, limit: int) -> None:
        artists = (
            Artist.objects.filter(deezer_id__isnull=True)
            .annotate(
                dl_count=Count("song", filter=Q(song__downloaded=True)),
                total_songs=Count("song"),
                album_count=Count("album", distinct=True),
            )
            .filter(dl_count__gt=0)
            .order_by("-dl_count")[:limit]
        )

        rows = list(artists)
        if not rows:
            self.stdout.write("No unlinked artists with downloaded songs.")
            return

        self.stdout.write(f"\nUnlinked artists with downloaded songs (top {limit}):\n")
        self.stdout.write(
            f"{'ID':>6}  {'Name':<40}  {'DL Songs':>8}  "
            f"{'Albums':>6}  {'Tracked':>7}"
        )
        self.stdout.write("-" * 75)

        for a in rows:
            self.stdout.write(
                f"{a.id:>6}  {a.name[:40]:<40}  {a.dl_count:>8}  "
                f"{a.album_count:>6}  {'Yes' if a.tracking_tier >= 1 else 'No':>7}"
            )

        self.stdout.write(f"\nTotal: {len(rows)} artist(s)")

    def _handle_link(self, artist_id: int, deezer_id: int, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        force: bool = options["force"]

        # 1. Look up artist
        try:
            artist = Artist.objects.get(id=artist_id)
        except Artist.DoesNotExist as exc:
            raise CommandError(f"Artist with id={artist_id} not found") from exc

        # 2. Check existing deezer_id
        if artist.deezer_id is not None and not force:
            raise CommandError(
                f"Artist '{artist.name}' (id={artist.id}) already has "
                f"deezer_id={artist.deezer_id}. Use --force to overwrite."
            )
        if artist.deezer_id is not None and force:
            self.stdout.write(
                self.style.WARNING(f"Overwriting existing deezer_id={artist.deezer_id}")
            )

        # 3. Check if deezer_id is claimed by another artist
        conflict = (
            Artist.objects.filter(deezer_id=deezer_id).exclude(id=artist_id).first()
        )
        if conflict:
            raise CommandError(
                f"Deezer ID {deezer_id} is already assigned to "
                f"'{conflict.name}' (id={conflict.id})"
            )

        # 4. Validate against Deezer API
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        result = provider.get_artist(deezer_id)
        if result is None:
            raise CommandError(
                f"Deezer ID {deezer_id} does not exist or could not be fetched"
            )

        # 5. Display confirmation
        song_count = Song.objects.filter(primary_artist=artist).count()
        album_count = Album.objects.filter(artist=artist).count()

        self.stdout.write("")
        self.stdout.write("Local artist:")
        self.stdout.write(f"  Name:    {artist.name}")
        self.stdout.write(f"  ID:      {artist.id}")
        self.stdout.write(f"  GID:     {artist.gid or '(none)'}")
        self.stdout.write(f"  Songs:   {song_count}")
        self.stdout.write(f"  Albums:  {album_count}")
        self.stdout.write("")
        self.stdout.write("Deezer artist:")
        self.stdout.write(f"  Name:    {result.name}")
        self.stdout.write(f"  ID:      {deezer_id}")

        # Name comparison
        local_norm = normalize_name(artist.name)
        deezer_norm = normalize_name(result.name)
        if local_norm == deezer_norm:
            self.stdout.write(
                self.style.SUCCESS(f"\n  Names match (normalized: '{local_norm}')")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"\n  Names differ: '{local_norm}' vs '{deezer_norm}'"
                )
            )

        # 6. Dry run stops here
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN — no changes made"))
            return

        # 7. Update artist
        artist.deezer_id = deezer_id
        artist.deezer_migration_status = "complete"
        artist.save(update_fields=["deezer_id", "deezer_migration_status"])

        # 8. Success
        self.stdout.write(
            self.style.SUCCESS(
                f"\nLinked '{artist.name}' (id={artist.id}) "
                f"→ Deezer '{result.name}' (id={deezer_id})"
            )
        )

    def handle(self, *args: object, **options: Any) -> None:
        if options["show_unlinked"]:
            self._handle_show_unlinked(options["limit"])
            return

        artist_id = options.get("artist_id")
        deezer_id = options.get("deezer_id")

        if artist_id is None or deezer_id is None:
            raise CommandError(
                "Both artist_id and deezer_id are required. "
                "Usage: link_artist <artist_id> <deezer_id>"
            )

        self._handle_link(artist_id, deezer_id, **options)
