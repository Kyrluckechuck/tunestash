"""Merge duplicate Artist records created by the Spotify→Deezer migration.

The migration created new Artist records with deezer_id set, while the original
Spotify-imported records (from playlist syncs) were never merged. This command
finds split pairs (same name, one with deezer_id, one without) and merges them,
keeping the Spotify-originated record as canonical.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from library_manager.models import Album, Artist, ContributingArtist, Song

logger = logging.getLogger(__name__)

# Delay between Deezer API calls to avoid rate limiting
API_DELAY = 0.1


def _normalize_name(name: str) -> str:
    """Strip accents and lowercase for fuzzy name comparison."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _merge_artist(source: Artist, target: Artist, stdout: object) -> dict:
    """Merge source artist into target, reassigning all content.

    Returns a dict of stats (songs_moved, albums_moved, albums_merged, etc.).
    """
    source_id = source.id
    source_name = source.name
    source_deezer_id = source.deezer_id
    stats = {
        "songs_moved": 0,
        "albums_moved": 0,
        "albums_merged": 0,
        "contributing_moved": 0,
        "contributing_deduped": 0,
    }

    with transaction.atomic():
        # 1. Reassign songs by primary_artist
        stats["songs_moved"] = Song.objects.filter(primary_artist=source).update(
            primary_artist=target
        )

        # 2. Reassign albums (handle duplicate albums — same name on both artists)
        for album in Album.objects.filter(artist=source):
            existing = Album.objects.filter(artist=target, name=album.name).first()
            if existing:
                # Duplicate album — merge songs into existing, carry over IDs
                reassigned = Song.objects.filter(album=album).update(album=existing)

                carry_spotify_gid = (
                    album.spotify_gid if not existing.spotify_gid else None
                )
                carry_deezer_id = album.deezer_id if not existing.deezer_id else None
                carry_youtube_id = album.youtube_id if not existing.youtube_id else None
                carry_wanted = album.wanted and not existing.wanted

                album.delete()

                updated_fields: list[str] = []
                if carry_spotify_gid:
                    existing.spotify_gid = carry_spotify_gid
                    updated_fields.append("spotify_gid")
                if carry_deezer_id:
                    existing.deezer_id = carry_deezer_id
                    updated_fields.append("deezer_id")
                if carry_youtube_id:
                    existing.youtube_id = carry_youtube_id
                    updated_fields.append("youtube_id")
                if carry_wanted:
                    existing.wanted = True
                    updated_fields.append("wanted")
                if updated_fields:
                    existing.save(update_fields=updated_fields)

                stats["albums_merged"] += 1
                logger.info(
                    "Merged duplicate album '%s' (%d songs) into album id=%d",
                    album.name,
                    reassigned,
                    existing.id,
                )
            else:
                album.artist = target
                album.save(update_fields=["artist"])
                stats["albums_moved"] += 1

        # 3. Reassign ContributingArtist (respect unique_together)
        for ca in ContributingArtist.objects.filter(artist=source):
            if ContributingArtist.objects.filter(song=ca.song, artist=target).exists():
                ca.delete()
                stats["contributing_deduped"] += 1
            else:
                ca.artist = target
                ca.save(update_fields=["artist"])
                stats["contributing_moved"] += 1

        # 4. Capture source metadata before deletion
        carry_deezer = source.deezer_id if not target.deezer_id else None
        carry_gid = source.gid if not target.gid else None
        carry_youtube = source.youtube_id if not target.youtube_id else None
        carry_tracked = source.tracked and not target.tracked
        carry_synced = (
            source.last_synced_at
            if source.last_synced_at
            and (
                not target.last_synced_at
                or source.last_synced_at > target.last_synced_at
            )
            else None
        )
        carry_migration = (
            source.deezer_migration_status == "complete"
            and target.deezer_migration_status != "complete"
        )

        # 5. Delete source (frees unique constraints)
        source.delete()

        # 6. Carry over external IDs + metadata to target
        updated_fields = []
        if carry_deezer:
            target.deezer_id = carry_deezer
            updated_fields.append("deezer_id")
        if carry_gid:
            target.gid = carry_gid
            updated_fields.append("gid")
        if carry_youtube:
            target.youtube_id = carry_youtube
            updated_fields.append("youtube_id")
        if carry_tracked:
            target.tracked = True
            updated_fields.append("tracked")
        if carry_synced:
            target.last_synced_at = carry_synced
            updated_fields.append("last_synced_at")
        if carry_migration:
            target.deezer_migration_status = "complete"
            updated_fields.append("deezer_migration_status")
        if updated_fields:
            target.save(update_fields=updated_fields)

    logger.info(
        "Merged artist '%s' (id=%d, deezer_id=%s) into id=%d: "
        "%d songs, %d albums moved, %d albums merged, "
        "%d contributing moved, %d contributing deduped",
        source_name,
        source_id,
        source_deezer_id,
        target.id,
        stats["songs_moved"],
        stats["albums_moved"],
        stats["albums_merged"],
        stats["contributing_moved"],
        stats["contributing_deduped"],
    )
    return stats


def _resolve_match_via_deezer(
    artist: Artist, has_deezer: list[Artist], provider: object
) -> Artist | None:
    """Use Deezer API to find which has_deezer record matches the given artist.

    Tries ISRC reverse-lookup first, then falls back to name search.
    """
    # Strategy 1: ISRC reverse-lookup
    songs_with_isrc = (
        Song.objects.filter(primary_artist=artist, isrc__isnull=False)
        .exclude(isrc="")
        .values_list("isrc", flat=True)[:4]
    )
    isrcs = list(songs_with_isrc)

    if isrcs:
        votes: list[int] = []
        for isrc in isrcs[:2]:
            result = provider.get_track_by_isrc(isrc)  # type: ignore[union-attr]
            time.sleep(API_DELAY)
            if result and result.artist_deezer_id:
                votes.append(result.artist_deezer_id)

        if len(votes) >= 2 and votes[0] == votes[1]:
            match = next((a for a in has_deezer if a.deezer_id == votes[0]), None)
            if match:
                return match

        # Check remaining ISRCs if no agreement
        if len(votes) < 2 or votes[0] != votes[1]:
            for isrc in isrcs[2:]:
                result = provider.get_track_by_isrc(isrc)  # type: ignore[union-attr]
                time.sleep(API_DELAY)
                if result and result.artist_deezer_id:
                    votes.append(result.artist_deezer_id)

        if votes:
            counts = Counter(votes)
            winner, winner_count = counts.most_common(1)[0]
            if winner_count >= 2:
                match = next((a for a in has_deezer if a.deezer_id == winner), None)
                if match:
                    return match

    # Strategy 2: Name search
    results = provider.search_artists(artist.name, limit=5)  # type: ignore[union-attr]
    time.sleep(API_DELAY)
    normalized = _normalize_name(artist.name)
    for r in results:
        if _normalize_name(r.name) == normalized and r.deezer_id:
            match = next((a for a in has_deezer if a.deezer_id == r.deezer_id), None)
            if match:
                return match

    return None


class Command(BaseCommand):
    help = "Merge duplicate artist records from the Spotify→Deezer migration"

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be merged without making changes",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Process at most N groups (for testing)",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Only show summary and problem records, not every merge",
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = options["dry_run"]
        limit = options["limit"]
        quiet = options["quiet"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made"))

        # Find all artist names with duplicates
        dup_names = (
            Artist.objects.values("name")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .order_by("name")
        )

        total_groups = dup_names.count()
        self.stdout.write(f"Found {total_groups} artist name(s) with duplicates")

        merged_count = 0
        skipped_count = 0
        error_count = 0
        total_songs = 0
        total_albums = 0
        provider = None
        unmatched: list[tuple[str, int]] = []  # (name, artist_id)
        failed: list[tuple[str, str]] = []  # (name, error)

        for i, entry in enumerate(dup_names):
            if limit and i >= limit:
                break

            name = entry["name"]
            artists = list(Artist.objects.filter(name=name).order_by("id"))
            has_deezer = [a for a in artists if a.deezer_id is not None]
            no_deezer = [a for a in artists if a.deezer_id is None]

            # Skip if no split (all have or all lack deezer_id)
            if not has_deezer or not no_deezer:
                skipped_count += 1
                continue

            # SIMPLE CASE: 1 has_deezer + 1 no_deezer
            if len(has_deezer) == 1 and len(no_deezer) == 1:
                target = no_deezer[0]
                source = has_deezer[0]

                if dry_run:
                    song_count = Song.objects.filter(primary_artist=source).count()
                    album_count = Album.objects.filter(artist=source).count()
                    if not quiet:
                        self.stdout.write(
                            f"  [SIMPLE] '{name}': merge id={source.id} "
                            f"(deezer_id={source.deezer_id}, {song_count} songs, "
                            f"{album_count} albums) → id={target.id} "
                            f"(gid={target.gid})"
                        )
                    total_songs += song_count
                    total_albums += album_count
                    merged_count += 1
                    continue

                try:
                    stats = _merge_artist(source, target, self.stdout)
                    merged_count += 1
                    total_songs += stats["songs_moved"]
                    total_albums += stats["albums_moved"] + stats["albums_merged"]
                except Exception as e:
                    logger.exception("Failed to merge artist '%s'", name)
                    failed.append((name, str(e)))
                    error_count += 1

            # COMPLEX CASE: multiple has_deezer and/or multiple no_deezer
            else:
                if provider is None:
                    from src.providers.deezer import DeezerMetadataProvider

                    provider = DeezerMetadataProvider()
                    if not quiet:
                        self.stdout.write("Initialized Deezer API for complex groups")

                for nd_artist in no_deezer:
                    match = _resolve_match_via_deezer(nd_artist, has_deezer, provider)
                    if not match:
                        unmatched.append((name, nd_artist.id))
                        skipped_count += 1
                        continue

                    if dry_run:
                        song_count = Song.objects.filter(primary_artist=match).count()
                        album_count = Album.objects.filter(artist=match).count()
                        if not quiet:
                            self.stdout.write(
                                f"  [COMPLEX] '{name}': merge id={match.id} "
                                f"(deezer_id={match.deezer_id}, "
                                f"{song_count} songs, "
                                f"{album_count} albums) → id={nd_artist.id} "
                                f"(gid={nd_artist.gid})"
                            )
                        has_deezer.remove(match)
                        total_songs += song_count
                        total_albums += album_count
                        merged_count += 1
                        continue

                    try:
                        stats = _merge_artist(match, nd_artist, self.stdout)
                        has_deezer.remove(match)
                        merged_count += 1
                        total_songs += stats["songs_moved"]
                        total_albums += stats["albums_moved"] + stats["albums_merged"]
                    except Exception as e:
                        logger.exception("Failed to merge artist '%s' (complex)", name)
                        failed.append((name, str(e)))
                        error_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 60)
        action = "Would merge" if dry_run else "Merged"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {merged_count} artist pair(s) "
                f"({total_songs} songs, {total_albums} albums affected)"
            )
        )
        if skipped_count:
            self.stdout.write(f"Skipped (no split): {skipped_count}")

        if unmatched:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Unmatched artists ({len(unmatched)}) — "
                    "could not find Deezer match for complex groups:"
                )
            )
            for name, artist_id in unmatched:
                song_count = Song.objects.filter(primary_artist_id=artist_id).count()
                album_count = Album.objects.filter(artist_id=artist_id).count()
                self.stdout.write(
                    f"  '{name}' (id={artist_id}, "
                    f"{song_count} songs, {album_count} albums)"
                )

        if failed:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Failed merges ({len(failed)}):"))
            for name, error in failed:
                self.stdout.write(f"  '{name}': {error}")
