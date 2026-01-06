"""Service for library statistics and completion metrics."""

from dataclasses import dataclass

from django.db.models import Count, Q

from asgiref.sync import sync_to_async

from library_manager.models import Album, Artist, Song


@dataclass
class LibraryStats:  # pylint: disable=too-many-instance-attributes
    """Aggregate statistics for the music library."""

    # Song counts (full library)
    total_songs: int
    downloaded_songs: int
    missing_songs: int  # Not downloaded and not failed
    failed_songs: int
    unavailable_songs: int

    # Album counts (full library)
    total_albums: int
    downloaded_albums: int
    partial_albums: int  # Some songs downloaded
    missing_albums: int  # No songs downloaded

    # Artist counts
    total_artists: int
    tracked_artists: int

    # Derived metrics (full library)
    song_completion_percentage: float
    album_completion_percentage: float

    # "Desired" = songs/albums from tracked artists
    desired_songs: int
    desired_downloaded: int
    desired_missing: int
    desired_failed: int
    desired_unavailable: int
    desired_completion_percentage: float

    # Album stats for tracked artists
    desired_albums: int
    desired_albums_downloaded: int
    desired_albums_partial: int
    desired_albums_missing: int
    desired_album_completion_percentage: float


class LibraryStatsService:
    """Service for computing library statistics."""

    async def get_stats(self) -> LibraryStats:
        """Get comprehensive library statistics."""
        return await sync_to_async(self._compute_stats, thread_sensitive=True)()

    def _compute_stats(self) -> LibraryStats:
        """Compute all library statistics synchronously."""
        # Song statistics
        # Use distinct names to avoid collision with model field names
        song_stats = Song.objects.aggregate(
            total_count=Count("id"),
            downloaded_count=Count("id", filter=Q(downloaded=True)),
            failed_count=Count("id", filter=Q(failed_count__gt=0, downloaded=False)),
            unavailable_count=Count("id", filter=Q(unavailable=True)),
        )

        total_songs = song_stats["total_count"] or 0
        downloaded_songs = song_stats["downloaded_count"] or 0
        failed_songs = song_stats["failed_count"] or 0
        unavailable_songs = song_stats["unavailable_count"] or 0

        # Missing = not downloaded AND not failed (still attemptable)
        missing_songs = total_songs - downloaded_songs - failed_songs

        # Album statistics - an album is "downloaded" if all its songs are downloaded
        album_stats = self._compute_album_stats()

        # Artist statistics
        artist_stats = Artist.objects.aggregate(
            total=Count("id"),
            tracked=Count("id", filter=Q(tracked=True)),
        )

        total_artists = artist_stats["total"] or 0
        tracked_artists = artist_stats["tracked"] or 0

        # "Desired" songs: songs from tracked artists
        desired_stats = Song.objects.filter(primary_artist__tracked=True).aggregate(
            total_count=Count("id"),
            downloaded_count=Count("id", filter=Q(downloaded=True)),
            failed_count=Count("id", filter=Q(failed_count__gt=0, downloaded=False)),
            unavailable_count=Count("id", filter=Q(unavailable=True)),
        )

        desired_songs = desired_stats["total_count"] or 0
        desired_downloaded = desired_stats["downloaded_count"] or 0
        desired_failed = desired_stats["failed_count"] or 0
        desired_unavailable = desired_stats["unavailable_count"] or 0
        desired_missing = desired_songs - desired_downloaded - desired_failed

        # Album stats for tracked artists only
        desired_album_stats = self._compute_album_stats(tracked_only=True)

        # Compute percentages
        song_completion_pct = (
            (downloaded_songs / total_songs * 100) if total_songs > 0 else 0.0
        )
        album_completion_pct = (
            (album_stats["downloaded"] / album_stats["total"] * 100)
            if album_stats["total"] > 0
            else 0.0
        )
        desired_completion_pct = (
            (desired_downloaded / desired_songs * 100) if desired_songs > 0 else 0.0
        )
        desired_album_completion_pct = (
            (desired_album_stats["downloaded"] / desired_album_stats["total"] * 100)
            if desired_album_stats["total"] > 0
            else 0.0
        )

        return LibraryStats(
            total_songs=total_songs,
            downloaded_songs=downloaded_songs,
            missing_songs=missing_songs,
            failed_songs=failed_songs,
            unavailable_songs=unavailable_songs,
            total_albums=album_stats["total"],
            downloaded_albums=album_stats["downloaded"],
            partial_albums=album_stats["partial"],
            missing_albums=album_stats["missing"],
            total_artists=total_artists,
            tracked_artists=tracked_artists,
            song_completion_percentage=round(song_completion_pct, 1),
            album_completion_percentage=round(album_completion_pct, 1),
            desired_songs=desired_songs,
            desired_downloaded=desired_downloaded,
            desired_missing=desired_missing,
            desired_failed=desired_failed,
            desired_unavailable=desired_unavailable,
            desired_completion_percentage=round(desired_completion_pct, 1),
            desired_albums=desired_album_stats["total"],
            desired_albums_downloaded=desired_album_stats["downloaded"],
            desired_albums_partial=desired_album_stats["partial"],
            desired_albums_missing=desired_album_stats["missing"],
            desired_album_completion_percentage=round(desired_album_completion_pct, 1),
        )

    def _compute_album_stats(self, tracked_only: bool = False) -> dict:
        """
        Compute album download statistics.

        Uses the Song.album FK to compute actual download progress per album:
        - "downloaded": Albums where all linked songs are downloaded
        - "partial": Albums where some (but not all) linked songs are downloaded
        - "missing": Albums where no linked songs are downloaded

        Note: Albums without any linked songs use the Album.downloaded flag as fallback.

        Args:
            tracked_only: If True, only include albums from tracked artists.
        """
        # Start with base queryset, optionally filtering by tracked artists
        queryset = Album.objects.all()
        if tracked_only:
            queryset = queryset.filter(artist__tracked=True)

        # Annotate albums with song download counts
        albums_with_counts = queryset.annotate(
            linked_songs=Count("songs"),
            downloaded_songs=Count("songs", filter=Q(songs__downloaded=True)),
        ).values("id", "downloaded", "linked_songs", "downloaded_songs")

        total = 0
        downloaded = 0
        partial = 0
        missing = 0

        for album in albums_with_counts:
            total += 1
            linked = album["linked_songs"]
            dl_count = album["downloaded_songs"]

            if linked == 0:
                # No songs linked yet - fall back to album.downloaded flag
                if album["downloaded"]:
                    downloaded += 1
                else:
                    missing += 1
            elif dl_count == linked:
                # All linked songs downloaded
                downloaded += 1
            elif dl_count > 0:
                # Some but not all songs downloaded
                partial += 1
            else:
                # No songs downloaded
                missing += 1

        return {
            "total": total,
            "downloaded": downloaded,
            "partial": partial,
            "missing": missing,
        }
