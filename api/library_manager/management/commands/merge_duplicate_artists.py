"""Merge duplicate Artist records created by the Spotify→Deezer migration.

The migration created new Artist records with deezer_id set, while the original
Spotify-imported records (from playlist syncs) were never merged. This command
finds split pairs (same name, one with deezer_id, one without) and merges them,
keeping the Spotify-originated record as canonical.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    ExternalListTrack,
    Song,
)
from library_manager.tasks.core import normalize_name

logger = logging.getLogger(__name__)

# Delay between Deezer API calls to avoid rate limiting
API_DELAY = 0.1


def _merge_song(source: Song, target: Song) -> None:
    """Merge source song into target, carrying over missing IDs and relationships.

    Follows the same pattern as _merge_artist: capture source values, transfer
    relationships, delete source (frees unique constraints), then carry over IDs.

    Must be called within a transaction.atomic() block.
    """
    carry_deezer_id = source.deezer_id if not target.deezer_id else None
    carry_gid = source.gid if not target.gid else None
    carry_youtube_id = source.youtube_id if not target.youtube_id else None
    carry_isrc = source.isrc if not target.isrc else None
    carry_album_id = source.album_id if not target.album_id else None  # type: ignore[attr-defined]

    # If source has better download quality, keep its download data
    carry_download = source.bitrate > target.bitrate
    dl_fields: dict = {}
    if carry_download:
        dl_fields = {
            "bitrate": source.bitrate,
            "file_path_ref_id": source.file_path_ref_id,  # type: ignore[attr-defined]
            "downloaded": source.downloaded,
            "download_provider": source.download_provider,
        }

    if source.deezer_id and target.deezer_id and source.deezer_id != target.deezer_id:
        logger.warning(
            "Merging songs with different deezer_ids: source=%d (deezer=%d) "
            "target=%d (deezer=%d)",
            source.id,
            source.deezer_id,
            target.id,
            target.deezer_id,
        )

    # Transfer ContributingArtist references (respect unique_together)
    for ca in ContributingArtist.objects.filter(song=source):
        if ContributingArtist.objects.filter(song=target, artist=ca.artist).exists():
            ca.delete()
        else:
            ca.song = target
            ca.save(update_fields=["song"])

    # Transfer ExternalListTrack references before deletion
    ExternalListTrack.objects.filter(song=source).update(song=target)

    # Delete source (frees unique constraints on gid/deezer_id/youtube_id)
    source.delete()

    # Carry over missing IDs and download data to target
    updated_fields: list[str] = []
    if carry_deezer_id:
        target.deezer_id = carry_deezer_id
        updated_fields.append("deezer_id")
    if carry_gid:
        target.gid = carry_gid
        updated_fields.append("gid")
    if carry_youtube_id:
        target.youtube_id = carry_youtube_id
        updated_fields.append("youtube_id")
    if carry_isrc:
        target.isrc = carry_isrc
        updated_fields.append("isrc")
    if carry_album_id:
        target.album_id = carry_album_id  # type: ignore[attr-defined]
        updated_fields.append("album")
    for field, value in dl_fields.items():
        setattr(target, field, value)
        updated_fields.append(field)
    if updated_fields:
        target.save(update_fields=updated_fields)


def _dedup_songs_for_artist(artist: Artist) -> int:
    """Find and merge duplicate songs under an artist (same ISRC + same album).

    Songs with the same ISRC on different albums are intentional (e.g. singles
    on compilations) and are left alone. Songs where both already have a
    deezer_id are also skipped — different deezer_ids mean different catalog
    entries (regional releases, remastered versions, etc.).
    """
    isrc_groups = (
        Song.objects.filter(primary_artist=artist, isrc__isnull=False)
        .exclude(isrc="")
        .values("isrc", "album_id")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
    )

    deduped = 0
    for group in isrc_groups:
        songs = list(
            Song.objects.filter(
                primary_artist=artist,
                isrc=group["isrc"],
                album_id=group["album_id"],
            ).order_by("-bitrate", "-id")
        )
        if len(songs) < 2:
            continue

        # Only merge songs where one lacks a deezer_id (true split from
        # Spotify vs Deezer creation paths). If both have deezer_id, they
        # are distinct catalog entries sharing an ISRC.
        has_deezer = [s for s in songs if s.deezer_id]
        no_deezer = [s for s in songs if not s.deezer_id]
        if not no_deezer:
            continue

        # Keep the best song with deezer_id as the target, merge no_deezer into it
        keeper = has_deezer[0] if has_deezer else songs[0]
        for dupe in no_deezer:
            _merge_song(dupe, keeper)
            deduped += 1

    return deduped


def _merge_artist(source: Artist, target: Artist, stdout: object) -> dict:
    """Merge source artist into target, reassigning all content.

    Returns a dict of stats (songs_moved, albums_moved, albums_merged, etc.).
    """
    source_id = source.id
    source_name = source.name
    source_deezer_id = source.deezer_id
    stats = {
        "songs_moved": 0,
        "songs_deduped": 0,
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
        # Build a normalized name → album lookup for the target's existing albums
        target_albums_by_norm: dict[str, Album] = {}
        for ta in Album.objects.filter(artist=target):
            target_albums_by_norm.setdefault(normalize_name(ta.name), ta)

        for album in Album.objects.filter(artist=source):
            existing = target_albums_by_norm.get(normalize_name(album.name))
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

        # 2b. Deduplicate songs with same ISRC on the same album
        stats["songs_deduped"] = _dedup_songs_for_artist(target)

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
        "%d songs moved, %d songs deduped, %d albums moved, %d albums merged, "
        "%d contributing moved, %d contributing deduped",
        source_name,
        source_id,
        source_deezer_id,
        target.id,
        stats["songs_moved"],
        stats["songs_deduped"],
        stats["albums_moved"],
        stats["albums_merged"],
        stats["contributing_moved"],
        stats["contributing_deduped"],
    )
    return stats


def _resolve_match_via_deezer(
    artist: Artist, has_deezer: list[Artist], provider: Any
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
            result = provider.get_track_by_isrc(isrc)
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
                result = provider.get_track_by_isrc(isrc)
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
    results = provider.search_artists(artist.name, limit=5)
    time.sleep(API_DELAY)
    normalized = normalize_name(artist.name)
    for r in results:
        if normalize_name(r.name) == normalized and r.deezer_id:
            match = next((a for a in has_deezer if a.deezer_id == r.deezer_id), None)
            if match:
                return match

    return None


class Command(BaseCommand):
    help = "Merge duplicate artist records from the Spotify→Deezer migration"

    def add_arguments(self, parser: Any) -> None:
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
        parser.add_argument(
            "--dedup-songs",
            action="store_true",
            help="Deduplicate songs sharing ISRC + artist + album (standalone mode)",
        )

    def _handle_dedup_songs(self, options: dict) -> None:
        dry_run = options["dry_run"]
        quiet = options["quiet"]
        limit = options["limit"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made"))

        self.stdout.write(
            "Scanning for duplicate songs (same ISRC + artist + album)..."
        )

        isrc_groups = (
            Song.objects.filter(isrc__isnull=False)
            .exclude(isrc="")
            .values("isrc", "primary_artist_id", "album_id")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .order_by("-cnt")
        )

        total_groups = isrc_groups.count()
        self.stdout.write(f"Found {total_groups} group(s) with duplicate songs")

        if not total_groups:
            return

        deduped = 0
        errors = 0
        groups_processed = 0

        for group in isrc_groups:
            if limit and groups_processed >= limit:
                break

            songs = list(
                Song.objects.filter(
                    isrc=group["isrc"],
                    primary_artist_id=group["primary_artist_id"],
                    album_id=group["album_id"],
                )
                .select_related("primary_artist", "album")
                .order_by("-bitrate", "-id")
            )
            if len(songs) < 2:
                continue

            # Only merge songs where one lacks a deezer_id (true split from
            # Spotify vs Deezer creation paths). If both have deezer_id, they
            # are distinct catalog entries sharing an ISRC.
            has_deezer = [s for s in songs if s.deezer_id]
            no_deezer = [s for s in songs if not s.deezer_id]
            if not no_deezer:
                continue

            keeper = has_deezer[0] if has_deezer else songs[0]
            mergeable = no_deezer

            if dry_run:
                if not quiet:
                    first_song = songs[0]
                    pa = first_song.primary_artist
                    artist_name = pa.name if pa else "Unknown"  # type: ignore[attr-defined]
                    alb = first_song.album
                    album_name = alb.name if alb else "N/A"  # type: ignore[attr-defined]
                    self.stdout.write(
                        f"  ISRC={group['isrc']} artist='{artist_name}' "
                        f"album='{album_name}': keep id={keeper.id} "
                        f"(deezer={keeper.deezer_id}), "
                        f"merge {[s.id for s in mergeable]}"
                    )
                deduped += len(mergeable)
                groups_processed += 1
                continue

            for dupe in mergeable:
                try:
                    with transaction.atomic():
                        _merge_song(dupe, keeper)
                    deduped += 1
                except Exception as e:
                    logger.exception(
                        "Failed to merge song %d into %d", dupe.id, keeper.id
                    )
                    if not quiet:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  Failed: song {dupe.id} → {keeper.id}: {e}"
                            )
                        )
                    errors += 1

            groups_processed += 1

        self.stdout.write("")
        action = "Would deduplicate" if dry_run else "Deduplicated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {deduped} song(s) across {groups_processed} group(s)"
            )
        )
        if errors:
            self.stdout.write(self.style.ERROR(f"Failed: {errors}"))

    def handle(self, *args: object, **options: object) -> None:
        if options["dedup_songs"]:
            self._handle_dedup_songs(options)
            return

        dry_run: bool = bool(options["dry_run"])
        limit: int | None = options.get("limit")  # type: ignore[assignment]
        quiet: bool = bool(options["quiet"])

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made"))

        # Build normalized-name groups to catch case/accent variants
        # (e.g. "GloRilla" vs "Glorilla", "Nour" vs "nour")
        norm_groups: dict[str, list[int]] = defaultdict(list)
        for artist in Artist.objects.all().only("id", "name"):
            norm_groups[normalize_name(artist.name)].append(artist.id)

        dup_groups = sorted(
            ((k, v) for k, v in norm_groups.items() if len(v) > 1),
            key=lambda x: x[0],
        )

        total_groups = len(dup_groups)
        self.stdout.write(
            f"Found {total_groups} normalized artist name(s) with duplicates"
        )

        merged_count = 0
        skipped_count = 0
        error_count = 0
        total_songs = 0
        total_albums = 0
        provider = None
        unmatched: list[tuple[str, int]] = []  # (norm_name, artist_id)
        failed: list[tuple[str, str]] = []  # (name, error)

        for i, (norm_name, artist_ids) in enumerate(dup_groups):
            if limit and i >= limit:
                break

            artists = list(Artist.objects.filter(id__in=artist_ids).order_by("id"))
            has_deezer = [a for a in artists if a.deezer_id is not None]
            no_deezer = [a for a in artists if a.deezer_id is None]
            name = artists[0].name  # representative name for logging

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

        # Cleanup pass: merge orphan records that have exactly 1 same-name
        # target with deezer_id AND no GID conflict. Different Spotify GIDs
        # indicate genuinely different artists sharing a common name (verified
        # by inspecting album catalogs across languages/genres).
        if unmatched and not dry_run:
            cleanup_count = 0
            still_unmatched: list[tuple[str, int]] = []

            # Build fresh normalized lookup (reflects merges from main pass)
            norm_to_deezer: dict[str, list[Artist]] = defaultdict(list)
            for a in Artist.objects.filter(deezer_id__isnull=False).only(
                "id", "name", "gid"
            ):
                norm_to_deezer[normalize_name(a.name)].append(a)

            for norm_name_key, artist_id in unmatched:
                try:
                    orphan = Artist.objects.get(id=artist_id)
                except Artist.DoesNotExist:
                    continue

                targets = [
                    a
                    for a in norm_to_deezer.get(norm_name_key, [])
                    if a.id != artist_id
                ]
                if len(targets) != 1:
                    still_unmatched.append((norm_name_key, artist_id))
                    continue

                target = targets[0]
                if orphan.gid and target.gid and orphan.gid != target.gid:
                    still_unmatched.append((norm_name_key, artist_id))
                    continue

                try:
                    stats = _merge_artist(orphan, target, self.stdout)
                    cleanup_count += 1
                    total_songs += stats["songs_moved"]
                    total_albums += stats["albums_moved"] + stats["albums_merged"]
                except Exception as e:
                    logger.exception("Failed to merge orphan '%s'", name)
                    failed.append((name, str(e)))
                    error_count += 1

            merged_count += cleanup_count
            unmatched = still_unmatched
            if cleanup_count:
                self.stdout.write(
                    f"\nCleanup pass: merged {cleanup_count} orphan "
                    f"record(s) into their sole name-matched artist"
                )

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
            if dry_run:
                gid_conflicts = 0
                no_gid_conflict = 0
                for uname, uid in unmatched:
                    try:
                        u_orphan = Artist.objects.get(id=uid)
                    except Artist.DoesNotExist:
                        continue
                    u_targets = list(
                        Artist.objects.filter(
                            name=uname, deezer_id__isnull=False
                        ).exclude(id=uid)
                    )
                    if len(u_targets) == 1:
                        t = u_targets[0]
                        if u_orphan.gid and t.gid and u_orphan.gid != t.gid:
                            gid_conflicts += 1
                        else:
                            no_gid_conflict += 1
                if no_gid_conflict:
                    self.stdout.write(
                        f"\n  Note: {no_gid_conflict} of these will be "
                        f"auto-merged during actual run"
                    )
                if gid_conflicts:
                    self.stdout.write(
                        f"  Note: {gid_conflicts} of these are different "
                        f"artists sharing a name (different Spotify GIDs)"
                    )

        if failed:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Failed merges ({len(failed)}):"))
            for name, error in failed:
                self.stdout.write(f"  '{name}': {error}")
