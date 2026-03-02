import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

import django.core.validators
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import IntegerChoices, QuerySet, Sum, TextChoices
from django.utils import timezone

# TypedModelMeta is only needed for type checking with mypy
# At runtime, we can use type (regular metaclass) as a fallback
if TYPE_CHECKING:
    from django_stubs_ext.db.models import TypedModelMeta
else:
    TypedModelMeta = type

logger = logging.getLogger(__name__)

# Album selection configuration
#
# These are read from Django settings (Dynaconf-backed), which in turn load from
# `/config/settings.yaml` automatically in containers. Operators should configure
# values there. Environment variables can still override via Dynaconf if needed.
#
# Accepted formats in settings:
# - List, e.g. ["single", "album", "compilation"]
# - Comma-separated string, e.g. "single,album,compilation"


def _get_setting_list(name: str, default: list[str]) -> list[str]:
    value = getattr(settings, name, default)
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
        return parsed or default
    if isinstance(value, (list, tuple)):
        # Normalize to list[str]
        return [str(item) for item in value if str(item).strip()]
    return default


ALBUM_TYPES_TO_DOWNLOAD = _get_setting_list(
    "ALBUM_TYPES_TO_DOWNLOAD", ["single", "album", "compilation"]
)
ALBUM_GROUPS_TO_IGNORE = _get_setting_list("ALBUM_GROUPS_TO_IGNORE", ["appears_on"])


def truncate_name(name: str, max_length: int = 500) -> str:
    """Truncate a name to fit within max_length, preserving start and end.

    If the name exceeds max_length, truncates to: first 400 chars + "..." + last 96 chars.
    This preserves both the beginning (usually title) and end (often has important suffixes
    like remix info or featured artists).

    Args:
        name: The name to truncate
        max_length: Maximum length allowed (default 500 to match CharField max_length)

    Returns:
        The original name if short enough, or truncated version
    """
    if len(name) <= max_length:
        return name

    # first 400 + "..." + last 96 = 499 chars (leaves 1 char margin)
    prefix_len = 400
    suffix_len = 96
    separator = "..."

    return name[:prefix_len] + separator + name[-suffix_len:]


# Create your models here.
class FilePath(models.Model):
    """Deduplicated file paths to save storage space."""

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    path: models.TextField = models.TextField(unique=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "file_paths"
        indexes = [
            models.Index(fields=["path"]),
        ]

    def __str__(self) -> str:
        return str(self.path)


class Artist(models.Model):
    """
    Represents a music artist tracked in the library.

    Fields:
        id: Internal database primary key
        name: Artist display name
        gid: Spotify Artist ID (22-character base62 string, e.g., "4iV5W9uYEdYUVa79Axb7Rh")
             IMPORTANT: This MUST be a valid Spotify ID, not a UUID or other identifier.
             Use this field for all Spotify API calls.
        tracked: Whether to automatically sync new releases for this artist
        added_at: Timestamp when artist was first added to library
        last_synced_at: Last time artist's albums were synced from Spotify
        last_downloaded_at: Last time any content was downloaded for this artist
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    name: models.CharField = models.CharField(max_length=500)
    gid: models.CharField = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="Spotify Artist ID (22-char base62, e.g., '4iV5W9uYEdYUVa79Axb7Rh')",
    )
    deezer_id: models.BigIntegerField = models.BigIntegerField(
        unique=True, null=True, blank=True, help_text="Deezer artist ID"
    )
    youtube_id: models.CharField = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="YouTube Music channel ID",
    )
    tracked: models.BooleanField = models.BooleanField(default=False)
    added_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_synced_at: models.DateTimeField = models.DateTimeField(default=None, null=True)
    last_downloaded_at: models.DateTimeField = models.DateTimeField(
        default=None, null=True
    )
    deezer_migration_status: models.CharField = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("complete", "Complete"),
            ("failed", "Failed"),
        ],
        null=True,
        blank=True,
        db_index=True,
    )

    def clean(self) -> None:
        """Validate model fields before saving."""
        from library_manager.validators import is_valid_spotify_id

        super().clean()
        if self.gid and not is_valid_spotify_id(self.gid):
            raise ValueError(
                f"Invalid Spotify artist GID: '{self.gid}'. "
                f"Expected 22-character base62 ID, got {len(self.gid)}-character string."
            )

    @property
    def number_songs(self) -> int:
        return ContributingArtist.objects.filter(artist=self).count()

    @property
    def spotify_uri(self) -> str:
        if not self.gid:
            return ""
        return f"spotify:artist:{self.gid}"

    @property
    def albums(self) -> dict:
        album_base = Album.objects.filter(
            artist=self, album_type__in=ALBUM_TYPES_TO_DOWNLOAD
        ).exclude(album_group__in=ALBUM_GROUPS_TO_IGNORE)
        return {
            "known": album_base.count(),
            "missing": album_base.filter(wanted=True, downloaded=False).count(),
            "downloaded": album_base.filter(downloaded=True).count(),
            "songs": {
                "missing": album_base.filter(wanted=True, downloaded=False).aggregate(
                    Sum("total_tracks")
                )["total_tracks__sum"]
                or 0,
            },
        }

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "artists"
        indexes = [
            models.Index(fields=["gid"]),
            models.Index(fields=["tracked"]),
            models.Index(fields=["deezer_id"], name="idx_artist_deezer_id"),
            models.Index(fields=["youtube_id"], name="idx_artist_youtube_id"),
        ]
        constraints = [
            models.CheckConstraint(
                check=~(
                    models.Q(gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="artist_has_at_least_one_external_id",
            ),
        ]

    def __str__(self) -> str:
        gid_display = self.gid or "no-spotify-id"
        return f"name: {self.name} | gid: {gid_display} | tracked: {self.tracked}"


class FailureReason(TextChoices):
    """Categorizes why a song download failed for smart retry logic.

    NULL means no failure has occurred (saves storage vs storing a "none" value).
    """

    # Temporary failures - retry frequently
    TEMPORARY_ERROR = "temporary", "Temporary error (network, rate limit, auth)"

    # Semi-permanent failures - use exponential backoff
    SPOTIFY_NOT_FOUND = "spotify_404", "Song not found on Spotify"
    YTM_NO_MATCH = "ytm_no_match", "No YouTube Music match found"

    # Permanent failures - very long backoff (30+ days)
    BOTH_UNAVAILABLE = "both_unavailable", "Unavailable on both Spotify and YTM"


class DownloadProvider(IntegerChoices):
    """Provider used to download a song.

    Uses IntegerChoices for storage efficiency (2 bytes vs 7-20 bytes for CharField).
    """

    UNKNOWN = 0, "Unknown"
    SPOTDL = 1, "spotdl (YouTube Music)"
    TIDAL = 2, "Tidal"
    QOBUZ = 3, "Qobuz"
    YOUTUBE = 4, "YouTube Music (yt-dlp)"


class UpgradeAttemptResult(IntegerChoices):
    """Result of an upgrade attempt for a song.

    Used to track whether we should retry upgrading on a given provider.
    """

    NOT_FOUND = 0, "Song not available on provider"
    API_ERROR = 1, "Provider API error (temporary - can retry)"
    NOT_AN_UPGRADE = 2, "Downloaded file was not higher quality"
    SUCCESS = 3, "Successfully upgraded"


# pylint: disable=R0902
class Song(models.Model):
    """
    Represents a music track/song.

    Fields:
        id: Internal database primary key
        name: Song/track title
        gid: Spotify Track ID (22-character base62 string, e.g., "6rqhFgbbKwnb9MLmUQDhG6")
             IMPORTANT: This MUST be a valid Spotify ID, not a UUID or hex-encoded GID.
             Use this field for all Spotify API calls.
        isrc: International Standard Recording Code (e.g., "USRC11234567")
              Identifies the specific recording. Same recording on different albums
              will have the same ISRC. Not unique in DB since we track per-album copies.
        primary_artist: Main artist for this track
        album: Album this song belongs to (FK to Album, nullable for legacy data)
        created_at: When the song was first added
        failed_count: Number of failed download attempts
        bitrate: Audio bitrate of downloaded file
        unavailable: Whether song is unavailable on Spotify
        file_path_ref: Reference to file path (if downloaded)
        downloaded: Whether the song has been downloaded
        last_download_attempt: When the song was last queued for download (for rate limiting)
        failure_reason: Categorized reason for last failure (for smart retry backoff)
        last_failed_at: When the song last failed (for exponential backoff calculation)
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    name: models.CharField = models.CharField(max_length=500)
    gid: models.CharField = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="Spotify Track ID (22-char base62, e.g., '6rqhFgbbKwnb9MLmUQDhG6')",
    )
    deezer_id: models.BigIntegerField = models.BigIntegerField(
        unique=True, null=True, blank=True, help_text="Deezer track ID"
    )
    youtube_id: models.CharField = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="YouTube Music video ID",
    )
    isrc: models.CharField = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        help_text="International Standard Recording Code (e.g., 'USRC11234567')",
    )
    primary_artist: models.ForeignKey = models.ForeignKey(
        Artist, on_delete=models.CASCADE
    )
    album: models.ForeignKey = models.ForeignKey(
        "Album",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="songs",
        help_text="Album this song belongs to (nullable for legacy songs pending backfill)",
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    failed_count: models.IntegerField = models.IntegerField(default=0)
    bitrate: models.IntegerField = models.IntegerField(default=0)
    unavailable: models.BooleanField = models.BooleanField(default=False)
    file_path_ref: models.ForeignKey = models.ForeignKey(
        FilePath, on_delete=models.SET_NULL, null=True, blank=True, related_name="songs"
    )
    downloaded: models.BooleanField = models.BooleanField(default=False)
    last_download_attempt: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, help_text="When the song was last queued for download"
    )
    failure_reason: models.CharField = models.CharField(
        max_length=20,
        choices=FailureReason.choices,
        null=True,
        blank=True,
        help_text="Categorized reason for last failure (NULL = no failure)",
    )
    last_failed_at: models.DateTimeField = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the song last failed (for exponential backoff calculation)",
    )
    download_provider: models.SmallIntegerField = models.SmallIntegerField(
        choices=DownloadProvider.choices,
        default=DownloadProvider.SPOTDL,
        help_text="Provider used to download this song",
    )

    def clean(self) -> None:
        """Validate model fields before saving."""
        from library_manager.validators import is_valid_spotify_id

        super().clean()
        if self.gid and not is_valid_spotify_id(self.gid):
            raise ValueError(
                f"Invalid Spotify track GID: '{self.gid}'. "
                f"Expected 22-character base62 ID, got {len(self.gid)}-character string."
            )

    @property
    def file_path(self) -> str | None:
        """Get the file path string for backward compatibility."""
        return self.file_path_ref.path if self.file_path_ref else None

    @property
    def path(self) -> Path | None:
        """Get the file path as a Path object for filesystem operations."""
        return Path(self.file_path_ref.path) if self.file_path_ref else None

    @file_path.setter  # type: ignore[no-redef,misc]
    def file_path(self, path: str | None) -> None:
        """Set the file path using the existing method."""
        self.set_file_path(path)

    def set_file_path(self, path: str | None) -> None:
        """Set the file path, creating/reusing FilePath object."""
        if path is None:
            self.file_path_ref = None
        else:
            file_path_obj, created = FilePath.objects.get_or_create(path=path)
            self.file_path_ref = file_path_obj

    @property
    def contributing_artists(self) -> "QuerySet[ContributingArtist]":
        return ContributingArtist.objects.filter(song=self).exclude(
            artist=self.primary_artist
        )

    @property
    def spotify_uri(self) -> str:
        if not self.gid:
            return ""
        return f"spotify:track:{self.gid}"

    def increment_failed_count(
        self, reason: "FailureReason" = FailureReason.TEMPORARY_ERROR
    ) -> None:
        """Increment the failed count and update failure tracking fields.

        Args:
            reason: The categorized reason for the failure. Used for smart retry
                    backoff - permanent failures get longer delays between retries.
        """
        self.failed_count += 1
        self.failure_reason = reason
        self.last_failed_at = timezone.now()

        # Upgrade to BOTH_UNAVAILABLE if it was a Spotify 404 and still failing
        if (
            self.failure_reason == FailureReason.SPOTIFY_NOT_FOUND
            and self.failed_count >= 3
        ):
            self.failure_reason = FailureReason.BOTH_UNAVAILABLE

        if self.failed_count > 3:
            self.unavailable = True
        self.save()

    def get_retry_backoff_days(self) -> int:
        """Calculate how many days to wait before retrying this song.

        Returns:
            Number of days to wait based on failure_reason and failed_count.
            - None (no failure): 0 days
            - TEMPORARY_ERROR: 1 day base, doubles each failure (max 7 days)
            - SPOTIFY_NOT_FOUND/YTM_NO_MATCH: 2 day base, doubles each failure (max 30 days)
            - BOTH_UNAVAILABLE: 30 days flat
        """
        if self.failure_reason is None:
            return 0

        if self.failure_reason == FailureReason.BOTH_UNAVAILABLE:
            return 30

        if self.failure_reason == FailureReason.TEMPORARY_ERROR:
            # Exponential backoff: 1, 2, 4, 7 (capped) days
            return int(min(2 ** (self.failed_count - 1), 7))

        # SPOTIFY_NOT_FOUND or YTM_NO_MATCH - slower backoff
        # 2, 4, 8, 16, 30 (capped) days
        return int(min(2**self.failed_count, 30))

    def is_ready_for_retry(self) -> bool:
        """Check if enough time has passed since last failure to retry.

        Returns:
            True if the song should be retried, False if still in backoff period.
        """
        if self.failed_count == 0 or self.last_failed_at is None:
            return True

        from datetime import timedelta

        backoff_days = self.get_retry_backoff_days()
        next_retry_at = self.last_failed_at + timedelta(days=backoff_days)
        return bool(timezone.now() >= next_retry_at)

    def mark_downloaded(
        self,
        bitrate: int,
        file_path: str,
        provider: Optional[int] = None,
    ) -> None:
        """Mark the song as successfully downloaded, clearing failure tracking.

        Args:
            bitrate: Audio bitrate of the downloaded file
            file_path: Path to the downloaded file
            provider: DownloadProvider integer value (e.g., DownloadProvider.SPOTDL)
        """
        self.downloaded = True
        self.bitrate = bitrate
        self.set_file_path(file_path)
        if provider is not None:
            self.download_provider = provider
        # Clear failure tracking on success (NULL saves storage)
        self.failed_count = 0
        self.failure_reason = None
        self.last_failed_at = None
        self.unavailable = False
        self.save()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to truncate name if too long for database field."""
        if self.name:
            self.name = truncate_name(self.name, max_length=500)
        super().save(*args, **kwargs)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "songs"
        indexes = [
            models.Index(fields=["gid"]),
            models.Index(fields=["deezer_id"], name="idx_song_deezer_id"),
            models.Index(fields=["youtube_id"], name="idx_song_youtube_id"),
        ]
        constraints = [
            models.CheckConstraint(
                check=~(
                    models.Q(gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="song_has_at_least_one_external_id",
            ),
        ]

    def __str__(self) -> str:
        gid_display = self.gid or "no-spotify-id"
        return (
            f"name: {self.name} | gid: {gid_display} "
            f"| primary_artist: '{self.primary_artist}'"
        )


class ContributingArtist(models.Model):
    song: models.ForeignKey = models.ForeignKey(Song, on_delete=models.CASCADE)
    artist: models.ForeignKey = models.ForeignKey(Artist, on_delete=models.CASCADE)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "contributing_artists"
        unique_together = (
            "song",
            "artist",
        )

    def __str__(self) -> str:
        return f"S: {self.song.name} | A: {self.artist.name}"


class DownloadHistory(models.Model):
    url: models.CharField = models.CharField(max_length=2048)
    added_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    completed_at: models.DateTimeField = models.DateTimeField(default=None, null=True)
    progress: models.SmallIntegerField = models.SmallIntegerField(
        default=0,
        validators=[
            django.core.validators.MinValueValidator(1),
            django.core.validators.MaxValueValidator(1000),
        ],
    )

    @property
    def progress_percent(self) -> float:
        return float(self.progress) / 10.0

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "download_history"


class TaskHistory(models.Model):
    TASK_TYPES = [
        ("SYNC", "Sync"),
        ("DOWNLOAD", "Download"),
        ("FETCH", "Fetch"),
    ]

    ENTITY_TYPES = [
        ("ARTIST", "Artist"),
        ("ALBUM", "Album"),
        ("PLAYLIST", "Playlist"),
        ("TRACK", "Track"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
    ]

    task_id: models.CharField = models.CharField(max_length=255, unique=True)
    type: models.CharField = models.CharField(max_length=20, choices=TASK_TYPES)
    entity_id: models.CharField = models.CharField(max_length=255)
    entity_type: models.CharField = models.CharField(
        max_length=20, choices=ENTITY_TYPES
    )
    status: models.CharField = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="PENDING"
    )
    started_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    completed_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    error_message: models.TextField = models.TextField(null=True, blank=True)
    duration_seconds: models.IntegerField = models.IntegerField(null=True, blank=True)
    progress_percentage: models.FloatField = models.FloatField(default=0.0)
    log_messages: models.JSONField = models.JSONField(default=list, blank=True)
    last_heartbeat: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    timeout_minutes: models.IntegerField = models.IntegerField(
        default=30
    )  # Default 30 minute timeout

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "task_history"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "-started_at"]),
            models.Index(fields=["type", "-started_at"]),
            models.Index(fields=["entity_type", "-started_at"]),
            models.Index(fields=["completed_at"]),
            # Index for time-based filtering (recent tasks lookup)
            models.Index(fields=["-started_at", "-id"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} - {self.entity_type} {self.entity_id} ({self.status})"

    def add_log_message(self, message: str, max_logs: int = 50) -> None:
        """Add a log message to the task history with automatic truncation"""
        if not self.log_messages:
            self.log_messages = []

        # Add new log message
        self.log_messages.append(
            {"timestamp": timezone.now().isoformat(), "message": message}
        )

        # Truncate if we exceed max_logs
        if len(self.log_messages) > max_logs:
            self.log_messages = self.log_messages[-max_logs:]

        self.save(update_fields=["log_messages"])

    def mark_completed(self, duration_seconds: Optional[int] = None) -> None:
        """Mark the task as completed"""
        self.status = "COMPLETED"
        self.completed_at = timezone.now()
        if duration_seconds is None:
            duration_seconds = int(
                (self.completed_at - self.started_at).total_seconds()
            )
        self.duration_seconds = duration_seconds
        self.progress_percentage = 100.0
        self.save()

    def mark_failed(self, error_message: Optional[str] = None) -> None:
        """Mark the task as failed"""
        self.status = "FAILED"
        self.completed_at = timezone.now()
        if error_message:
            self.error_message = error_message
        self.duration_seconds = int(
            (self.completed_at - self.started_at).total_seconds()
        )
        self.save()

    def update_progress(self, percentage: float) -> None:
        """Update the progress percentage"""
        self.progress_percentage = min(100.0, max(0.0, percentage))
        self.save(update_fields=["progress_percentage"])

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp (no log message added)"""
        self.last_heartbeat = timezone.now()
        self.save(update_fields=["last_heartbeat"])

    def get_expected_duration_minutes(self) -> int:
        """Get expected duration based on task type and entity"""
        if self.type == "SYNC":
            return 15  # Sync operations can take time with large discographies
        if self.type == "DOWNLOAD":
            if self.entity_type == "PLAYLIST":
                return 120  # Playlists can have hundreds of songs - 2 hours
            if self.entity_type == "ALBUM":
                return 60  # Albums can be large/slow downloads - 1 hour
            if self.entity_type == "ARTIST":
                return 180  # Artist downloads can be massive - 3 hours
        if self.type == "FETCH":
            return 10  # Fetch operations should be fast but API can be slow
        return 120  # Default fallback - 2 hours for unknown tasks

    def is_stuck(self) -> bool:
        """Check if the task is stuck using multiple detection methods"""
        from datetime import timedelta

        from django.utils import timezone

        if self.status != "RUNNING":
            return False

        # Method 0: Orphaned task detection (heartbeat never updated after task started)
        # This catches tasks that were interrupted by container restarts
        time_since_start = timezone.now() - self.started_at

        # If heartbeat is nearly identical to started_at (within 1 second),
        # and task has been "running" for > 10 minutes, it's likely orphaned
        heartbeat_delta = (self.last_heartbeat - self.started_at).total_seconds()
        if heartbeat_delta < 1.0 and time_since_start > timedelta(minutes=10):
            return True  # Orphaned task - heartbeat was never updated

        # Method 1: Heartbeat timeout (only for very long timeouts - indicates dead container)
        expected_duration = self.get_expected_duration_minutes()
        timeout_threshold = timezone.now() - timedelta(minutes=expected_duration)
        if self.last_heartbeat < timeout_threshold:
            return True

        # Method 2: Progress-based detection (more sensitive - indicates stuck process)
        if self.log_messages:
            last_log = max(self.log_messages, key=lambda x: x.get("timestamp", ""))
            if last_log.get("timestamp"):
                try:
                    from datetime import datetime

                    last_log_dt = datetime.fromisoformat(
                        last_log["timestamp"].replace("Z", "+00:00")
                    )
                    # If no progress for 30 minutes, check if heartbeat is more recent
                    progress_gap = timezone.now() - last_log_dt
                    if progress_gap > timedelta(minutes=30):
                        # But if heartbeat is recent (within 45 min), give benefit of doubt
                        heartbeat_gap = timezone.now() - self.last_heartbeat
                        if heartbeat_gap > timedelta(minutes=45):
                            return True  # Both progress and heartbeat are stale
                        # Otherwise: old progress but recent heartbeat - probably long download
                except Exception:
                    pass

        # Method 3: Very old tasks without any progress logs (dead on arrival)
        if not self.log_messages and self.started_at:
            # If task has been running for 1 hour without any logs, it's probably dead
            if time_since_start > timedelta(hours=1):
                return True

        return False

    def mark_stuck(self, reason: str = "Task timeout") -> None:
        """Mark the task as stuck/failed due to timeout"""
        from django.utils import timezone

        self.status = "FAILED"
        self.completed_at = timezone.now()
        self.error_message = f"{reason} - Last heartbeat: {self.last_heartbeat}"
        self.duration_seconds = int(
            (self.completed_at - self.started_at).total_seconds()
        )
        self.save()

    @classmethod
    def cleanup_stuck_tasks(cls) -> int:
        """Find and mark stuck tasks as failed"""
        stuck_tasks = cls.objects.filter(status="RUNNING")
        stuck_count = 0

        for task in stuck_tasks:
            if task.is_stuck():
                task.mark_stuck("Task timeout - automatic cleanup")
                stuck_count += 1

        return stuck_count

    @classmethod
    def cleanup_old_tasks(cls, days_to_keep: int = 30) -> int:
        """Remove completed/failed tasks older than specified days"""
        from datetime import timedelta

        cutoff_date = timezone.now() - timedelta(days=days_to_keep)
        deleted_count = cls.objects.filter(
            status__in=["COMPLETED", "FAILED"], started_at__lt=cutoff_date
        ).delete()[0]
        return deleted_count

    @classmethod
    def get_storage_stats(cls) -> dict:
        """Get storage statistics for TaskHistory"""
        total_tasks = cls.objects.count()
        completed_tasks = cls.objects.filter(status="COMPLETED").count()
        failed_tasks = cls.objects.filter(status="FAILED").count()
        running_tasks = cls.objects.filter(status="RUNNING").count()
        pending_tasks = cls.objects.filter(status="PENDING").count()

        # Calculate average log messages per task
        tasks_with_logs = cls.objects.filter(log_messages__isnull=False).exclude(
            log_messages=[]
        )
        avg_logs = 0.0
        if tasks_with_logs.exists():
            total_logs = sum(len(task.log_messages) for task in tasks_with_logs)
            avg_logs = total_logs / tasks_with_logs.count()

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "running_tasks": running_tasks,
            "pending_tasks": pending_tasks,
            "average_logs_per_task": round(avg_logs, 2),
            "tasks_with_logs": tasks_with_logs.count(),
        }


class Album(models.Model):
    """
    Represents a music album/release.

    Fields:
        id: Internal database primary key (auto-generated)
        spotify_gid: Spotify Album ID (22-character base62 string, e.g., "7K3BhSpAxZBzniskgIPUYj")
                     IMPORTANT: This MUST be a valid Spotify ID, not a hex-encoded GID.
        artist: Foreign key to Artist (using artist.gid)
        spotify_uri: Full Spotify URI
        downloaded: Whether all tracks have been downloaded
        total_tracks: Number of tracks on the album
        wanted: Whether this album should be downloaded
        name: Album title
        failed_count: Number of failed download attempts
        album_type: Type (album, single, compilation)
        album_group: Group (album, appears_on, etc.)
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    spotify_gid: models.CharField = models.CharField(
        max_length=2048,
        unique=True,
        null=True,
        blank=True,
        help_text="Spotify Album ID (22-char base62, e.g., '7K3BhSpAxZBzniskgIPUYj')",
    )
    deezer_id: models.BigIntegerField = models.BigIntegerField(
        unique=True, null=True, blank=True, help_text="Deezer album ID"
    )
    youtube_id: models.CharField = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="YouTube Music album/playlist ID",
    )
    artist: models.ForeignKey = models.ForeignKey(Artist, on_delete=models.CASCADE)
    spotify_uri: models.CharField = models.CharField(max_length=2048, blank=True)
    downloaded: models.BooleanField = models.BooleanField(default=False)
    total_tracks: models.IntegerField = models.IntegerField(default=0)
    wanted: models.BooleanField = models.BooleanField(default=True)
    name: models.CharField = models.CharField(max_length=2048)
    failed_count: models.IntegerField = models.IntegerField(default=0)
    album_type: models.CharField = models.CharField(max_length=100, null=True)
    album_group: models.CharField = models.CharField(max_length=100, null=True)

    @property
    def desired_album_type(self) -> bool:
        return (
            self.album_type in ALBUM_TYPES_TO_DOWNLOAD
            and self.album_group not in ALBUM_GROUPS_TO_IGNORE
        )

    def __str__(self) -> str:
        return (
            f"name: {self.name} | artist: {self.artist} | downloaded: {self.downloaded}"
        )

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "albums"
        indexes = [
            models.Index(fields=["deezer_id"], name="idx_album_deezer_id"),
            models.Index(fields=["youtube_id"], name="idx_album_youtube_id"),
        ]
        constraints = [
            models.CheckConstraint(
                check=~(
                    models.Q(spotify_gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="album_has_at_least_one_external_id",
            ),
        ]


class PlaylistStatus(models.TextChoices):
    """Status choices for tracked playlists."""

    ACTIVE = "active", "Active"
    DISABLED_BY_USER = "disabled_by_user", "Disabled by user"
    SPOTIFY_API_RESTRICTED = (
        "spotify_api_restricted",
        "Spotify API restricted (algorithmic playlists)",
    )
    NOT_FOUND = "not_found", "Not found (deleted or private)"


class TrackedPlaylist(models.Model):
    name: models.CharField = models.CharField(max_length=2048)
    url: models.CharField = models.CharField(max_length=2048, unique=True)
    status: models.CharField = models.CharField(
        max_length=30,
        choices=PlaylistStatus.choices,
        default=PlaylistStatus.ACTIVE,
    )
    status_message: models.CharField = models.CharField(
        max_length=255, null=True, blank=True
    )
    auto_track_artists: models.BooleanField = models.BooleanField(default=False)
    last_synced_at: models.DateTimeField = models.DateTimeField(default=None, null=True)
    snapshot_id: models.CharField = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Spotify playlist version identifier for efficient change detection",
    )

    @property
    def enabled(self) -> bool:
        """Backwards-compatible property: playlist is enabled if status is ACTIVE."""
        return bool(self.status == PlaylistStatus.ACTIVE)

    def __str__(self) -> str:
        return f"name: {self.name} | url: {self.url} | status: {self.status}"

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "playlists"


class SpotifyOAuthToken(models.Model):
    """
    Stores Spotify OAuth tokens for accessing private playlists.

    This is a singleton model - only one row should exist.
    Tokens are automatically refreshed when they expire.
    """

    # OAuth tokens
    access_token: models.TextField = models.TextField()
    refresh_token: models.TextField = models.TextField()
    token_type: models.CharField = models.CharField(max_length=50, default="Bearer")
    expires_at: models.DateTimeField = models.DateTimeField()

    # OAuth scope granted
    scope: models.TextField = models.TextField(
        default="playlist-read-private user-library-read user-follow-read"
    )

    # Metadata
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Spotify OAuth Token (expires: {self.expires_at})"

    def is_expired(self) -> bool:
        """
        Check if the access token has expired or will expire soon.

        Returns True if expired or expires within 5 minutes, to trigger proactive refresh.
        """
        from datetime import timedelta

        # Refresh proactively when token has less than 5 minutes left
        threshold = timezone.now() + timedelta(minutes=5)
        return bool(threshold >= self.expires_at)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "spotify_oauth_tokens"


class SpotifyRateLimitState(models.Model):
    """
    Multi-tier rate limiter for Spotify API with adaptive backoff.

    Implements three tiers of rate limiting to avoid both short-term and long-term bans:

    1. BURST (30-second window): Allows short bursts of activity
       - Max 25 calls per 30 seconds (~50/min)
       - Prevents immediate 429 responses

    2. SUSTAINED (5-minute window): Controls medium-term throughput
       - Max 100 calls per 5 minutes (20/min average)
       - Prevents accumulation that triggers moderate bans

    3. HOURLY (1-hour window): Guards against long-term quota exhaustion
       - Max 600 calls per hour (10/min average)
       - Prevents the multi-hour bans seen with sustained high usage

    Additionally implements exponential backoff: when any tier is exceeded,
    a "pressure" counter increases, adding progressive delays. This pressure
    decays over time when usage is low.
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)

    # Singleton key - only one row should exist
    key: models.CharField = models.CharField(
        max_length=50, unique=True, default="spotify_rate_limit"
    )

    # Timestamp of last API call (used for calculating delays)
    last_call_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    # BURST tier: 30-second window
    burst_call_count: models.IntegerField = models.IntegerField(default=0)
    burst_window_start: models.DateTimeField = models.DateTimeField(
        default=timezone.now
    )

    # SUSTAINED tier: 5-minute window
    sustained_call_count: models.IntegerField = models.IntegerField(default=0)
    sustained_window_start: models.DateTimeField = models.DateTimeField(
        default=timezone.now
    )

    # HOURLY tier: 1-hour window
    hourly_call_count: models.IntegerField = models.IntegerField(default=0)
    hourly_window_start: models.DateTimeField = models.DateTimeField(
        default=timezone.now
    )

    # Backoff pressure: increases when limits are hit, decays over time
    # Each unit adds 100ms delay to all requests
    backoff_pressure: models.IntegerField = models.IntegerField(default=0)
    last_pressure_decay: models.DateTimeField = models.DateTimeField(
        default=timezone.now
    )

    # If rate limited by Spotify 429, when we can resume
    rate_limited_until: models.DateTimeField = models.DateTimeField(
        null=True, blank=True
    )

    # Legacy field for backwards compatibility (maps to burst_call_count)
    @property
    def window_call_count(self) -> int:
        return int(self.burst_call_count)

    @property
    def window_start_at(self) -> datetime:
        return cast(datetime, self.burst_window_start)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "spotify_rate_limit_state"

    def __str__(self) -> str:
        return (
            f"Spotify Rate Limit State "
            f"(burst: {self.burst_call_count}/{self.BURST_MAX_CALLS}, "
            f"sustained: {self.sustained_call_count}/{self.SUSTAINED_MAX_CALLS}, "
            f"hourly: {self.hourly_call_count}/{self.HOURLY_MAX_CALLS}, "
            f"pressure: {self.backoff_pressure})"
        )

    # ==========================================================================
    # TIER CONFIGURATION
    # ==========================================================================

    # BURST tier: prevents immediate 429s
    BURST_WINDOW_SECONDS = 30
    BURST_MAX_CALLS = 25  # ~50/min peak

    # SUSTAINED tier: prevents medium-term bans
    SUSTAINED_WINDOW_SECONDS = 300  # 5 minutes
    SUSTAINED_MAX_CALLS = 100  # 20/min average

    # HOURLY tier: prevents long-term bans
    HOURLY_WINDOW_SECONDS = 3600  # 1 hour
    HOURLY_MAX_CALLS = 600  # 10/min average

    # Minimum delay between any two calls (milliseconds)
    MIN_DELAY_BETWEEN_CALLS_MS = 200

    # Backoff configuration
    BACKOFF_DELAY_PER_PRESSURE_MS = 100  # Each pressure unit adds 100ms
    BACKOFF_MAX_PRESSURE = 50  # Max 5 seconds of backoff delay
    BACKOFF_DECAY_INTERVAL_SECONDS = 60  # Decay pressure every 60s of low usage
    BACKOFF_DECAY_AMOUNT = 1  # Reduce pressure by 1 each decay interval

    # Legacy constant for backwards compatibility
    WINDOW_SECONDS = BURST_WINDOW_SECONDS
    MAX_CALLS_PER_WINDOW = BURST_MAX_CALLS

    @classmethod
    def get_instance(cls) -> "SpotifyRateLimitState":
        """Get or create the singleton rate limit state."""
        instance, _ = cls.objects.get_or_create(key="spotify_rate_limit")
        return instance

    @classmethod
    def record_call(cls) -> None:
        """
        Record that an API call was made.

        Updates all three tiers and handles window resets.
        Uses database-level locking to ensure accurate counts across workers.
        """
        from django.db import transaction

        with transaction.atomic():
            instance = cls.objects.select_for_update().get_or_create(
                key="spotify_rate_limit"
            )[0]
            now = timezone.now()

            # Reset BURST window if elapsed
            burst_elapsed = (now - instance.burst_window_start).total_seconds()
            if burst_elapsed >= cls.BURST_WINDOW_SECONDS:
                instance.burst_window_start = now
                instance.burst_call_count = 1
            else:
                instance.burst_call_count += 1

            # Reset SUSTAINED window if elapsed
            sustained_elapsed = (now - instance.sustained_window_start).total_seconds()
            if sustained_elapsed >= cls.SUSTAINED_WINDOW_SECONDS:
                instance.sustained_window_start = now
                instance.sustained_call_count = 1
            else:
                instance.sustained_call_count += 1

            # Reset HOURLY window if elapsed
            hourly_elapsed = (now - instance.hourly_window_start).total_seconds()
            if hourly_elapsed >= cls.HOURLY_WINDOW_SECONDS:
                instance.hourly_window_start = now
                instance.hourly_call_count = 1
            else:
                instance.hourly_call_count += 1

            # Decay backoff pressure if enough time has passed with low usage
            pressure_decay_elapsed = (
                now - instance.last_pressure_decay
            ).total_seconds()
            if pressure_decay_elapsed >= cls.BACKOFF_DECAY_INTERVAL_SECONDS:
                # Only decay if we're under 50% of burst limit (low usage)
                if instance.burst_call_count < cls.BURST_MAX_CALLS // 2:
                    instance.backoff_pressure = max(
                        0, instance.backoff_pressure - cls.BACKOFF_DECAY_AMOUNT
                    )
                instance.last_pressure_decay = now

            instance.last_call_at = now
            instance.save()

    @classmethod
    def get_delay_seconds(cls) -> float:
        """
        Calculate how long to wait before the next API call.

        Checks all three tiers and returns the longest required delay.
        Also applies backoff pressure delay on top of any tier delay.
        """
        from django.db import transaction

        with transaction.atomic():
            instance = cls.objects.select_for_update().get_or_create(
                key="spotify_rate_limit"
            )[0]
            now = timezone.now()

            # If we're rate limited by Spotify, return time until we can resume
            if instance.rate_limited_until and instance.rate_limited_until > now:
                delay = float((instance.rate_limited_until - now).total_seconds())
                logger.warning(
                    f"[SPOTIFY API] Blocked by Spotify 429 - must wait {delay:.0f}s"
                )
                return delay

            # Track delays with their source for logging
            delay_sources: list[tuple[float, str]] = []

            # Check BURST tier
            burst_elapsed = (now - instance.burst_window_start).total_seconds()
            if burst_elapsed < cls.BURST_WINDOW_SECONDS:
                if instance.burst_call_count >= cls.BURST_MAX_CALLS:
                    burst_delay = cls.BURST_WINDOW_SECONDS - burst_elapsed
                    delay_sources.append(
                        (
                            burst_delay,
                            f"burst {instance.burst_call_count}/{cls.BURST_MAX_CALLS}",
                        )
                    )

            # Check SUSTAINED tier
            sustained_elapsed = (now - instance.sustained_window_start).total_seconds()
            if sustained_elapsed < cls.SUSTAINED_WINDOW_SECONDS:
                if instance.sustained_call_count >= cls.SUSTAINED_MAX_CALLS:
                    sustained_delay = cls.SUSTAINED_WINDOW_SECONDS - sustained_elapsed
                    delay_sources.append(
                        (
                            sustained_delay,
                            f"sustained {instance.sustained_call_count}/{cls.SUSTAINED_MAX_CALLS}",
                        )
                    )

            # Check HOURLY tier
            hourly_elapsed = (now - instance.hourly_window_start).total_seconds()
            if hourly_elapsed < cls.HOURLY_WINDOW_SECONDS:
                if instance.hourly_call_count >= cls.HOURLY_MAX_CALLS:
                    hourly_delay = cls.HOURLY_WINDOW_SECONDS - hourly_elapsed
                    delay_sources.append(
                        (
                            hourly_delay,
                            f"hourly {instance.hourly_call_count}/{cls.HOURLY_MAX_CALLS}",
                        )
                    )

            # Enforce minimum delay between calls (don't log this, too noisy)
            time_since_last = (now - instance.last_call_at).total_seconds()
            min_delay = cls.MIN_DELAY_BETWEEN_CALLS_MS / 1000.0
            if time_since_last < min_delay:
                delay_sources.append((min_delay - time_since_last, ""))

            # Apply backoff pressure delay
            if instance.backoff_pressure > 0:
                pressure_delay = (
                    instance.backoff_pressure
                    * cls.BACKOFF_DELAY_PER_PRESSURE_MS
                    / 1000.0
                )
                delay_sources.append(
                    (pressure_delay, f"backoff pressure={instance.backoff_pressure}")
                )

            if not delay_sources:
                return 0.0

            # Find the maximum delay and its source
            max_delay, max_source = max(delay_sources, key=lambda x: x[0])

            # Log significant delays (> 5 seconds) to help with debugging
            if max_delay > 5.0 and max_source:
                logger.info(
                    f"[SPOTIFY API] Rate limit delay: {max_delay:.1f}s "
                    f"(reason: {max_source})"
                )

            return max_delay

    @classmethod
    def increase_pressure(cls, amount: int = 1) -> None:
        """
        Increase backoff pressure when approaching limits.

        Called when we're getting close to any tier's limit to proactively slow down.
        """
        from django.db import transaction

        with transaction.atomic():
            instance = cls.objects.select_for_update().get_or_create(
                key="spotify_rate_limit"
            )[0]
            instance.backoff_pressure = min(
                cls.BACKOFF_MAX_PRESSURE, instance.backoff_pressure + amount
            )
            instance.save()

    @classmethod
    def set_rate_limited(cls, retry_after_seconds: int) -> None:
        """
        Record that we've been rate limited by Spotify.

        Called when we receive a 429 response with Retry-After header.
        Also significantly increases backoff pressure since we got caught.
        """
        from django.db import transaction

        with transaction.atomic():
            instance = cls.objects.select_for_update().get_or_create(
                key="spotify_rate_limit"
            )[0]
            instance.rate_limited_until = timezone.now() + timezone.timedelta(
                seconds=retry_after_seconds
            )
            # Significantly increase pressure after a 429
            instance.backoff_pressure = min(
                cls.BACKOFF_MAX_PRESSURE, instance.backoff_pressure + 10
            )
            # Reset all windows
            instance.burst_call_count = 0
            instance.burst_window_start = timezone.now()
            instance.sustained_call_count = 0
            instance.sustained_window_start = timezone.now()
            instance.hourly_call_count = 0
            instance.hourly_window_start = timezone.now()
            instance.save()

    @classmethod
    def get_status(cls) -> dict:
        """
        Get current rate limit status for display purposes.

        Returns comprehensive status across all tiers.
        """
        try:
            instance = cls.objects.filter(key="spotify_rate_limit").first()
            if not instance:
                return {
                    "is_rate_limited": False,
                    "rate_limited_until": None,
                    "seconds_until_clear": None,
                    "window_call_count": 0,
                    "window_max_calls": cls.BURST_MAX_CALLS,
                    "window_usage_percent": 0.0,
                    "burst_calls": 0,
                    "burst_max": cls.BURST_MAX_CALLS,
                    "sustained_calls": 0,
                    "sustained_max": cls.SUSTAINED_MAX_CALLS,
                    "hourly_calls": 0,
                    "hourly_max": cls.HOURLY_MAX_CALLS,
                    "backoff_pressure": 0,
                }

            now = timezone.now()

            # Check if actively rate limited
            is_rate_limited = bool(
                instance.rate_limited_until and instance.rate_limited_until > now
            )
            seconds_until_clear = None
            if is_rate_limited and instance.rate_limited_until:
                seconds_until_clear = int(
                    (instance.rate_limited_until - now).total_seconds()
                )

            # Calculate current counts (accounting for window resets)
            burst_elapsed = (now - instance.burst_window_start).total_seconds()
            burst_calls = (
                0
                if burst_elapsed >= cls.BURST_WINDOW_SECONDS
                else instance.burst_call_count
            )

            sustained_elapsed = (now - instance.sustained_window_start).total_seconds()
            sustained_calls = (
                0
                if sustained_elapsed >= cls.SUSTAINED_WINDOW_SECONDS
                else instance.sustained_call_count
            )

            hourly_elapsed = (now - instance.hourly_window_start).total_seconds()
            hourly_calls = (
                0
                if hourly_elapsed >= cls.HOURLY_WINDOW_SECONDS
                else instance.hourly_call_count
            )

            # Legacy compatibility
            window_usage_percent = (burst_calls / cls.BURST_MAX_CALLS) * 100

            return {
                "is_rate_limited": is_rate_limited,
                "rate_limited_until": (
                    instance.rate_limited_until if is_rate_limited else None
                ),
                "seconds_until_clear": seconds_until_clear,
                "window_call_count": burst_calls,
                "window_max_calls": cls.BURST_MAX_CALLS,
                "window_usage_percent": round(window_usage_percent, 1),
                "burst_calls": burst_calls,
                "burst_max": cls.BURST_MAX_CALLS,
                "sustained_calls": sustained_calls,
                "sustained_max": cls.SUSTAINED_MAX_CALLS,
                "hourly_calls": hourly_calls,
                "hourly_max": cls.HOURLY_MAX_CALLS,
                "backoff_pressure": instance.backoff_pressure,
            }
        except Exception:
            # Return safe defaults if anything goes wrong
            return {
                "is_rate_limited": False,
                "rate_limited_until": None,
                "seconds_until_clear": None,
                "window_call_count": 0,
                "window_max_calls": cls.BURST_MAX_CALLS,
                "window_usage_percent": 0.0,
                "burst_calls": 0,
                "burst_max": cls.BURST_MAX_CALLS,
                "sustained_calls": 0,
                "sustained_max": cls.SUSTAINED_MAX_CALLS,
                "hourly_calls": 0,
                "hourly_max": cls.HOURLY_MAX_CALLS,
                "backoff_pressure": 0,
            }


class MetadataUpdateStatus(TextChoices):
    """Status choices for pending metadata updates."""

    PENDING = "pending", "Pending"
    APPLIED = "applied", "Applied"
    DISMISSED = "dismissed", "Dismissed"


class PendingMetadataUpdate(models.Model):
    """
    Tracks metadata changes detected from Spotify that user can opt to apply.

    When we detect that an artist, album, or song name has changed on Spotify
    (compared to what we have stored locally), we create a record here instead
    of automatically updating. The user can then review and choose to apply
    the change (triggering a re-download with updated metadata) or dismiss it.

    Uses Django's ContentType framework for polymorphic references to
    Artist, Album, or Song models.
    """

    # Polymorphic reference to Artist, Album, or Song
    content_type: models.ForeignKey = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="Type of entity (Artist, Album, or Song)",
    )
    object_id: models.BigIntegerField = models.BigIntegerField(
        help_text="ID of the entity"
    )
    content_object = GenericForeignKey("content_type", "object_id")

    # What changed
    field_name: models.CharField = models.CharField(
        max_length=50,
        default="name",
        help_text="Field that changed (currently only 'name' supported)",
    )
    old_value: models.CharField = models.CharField(
        max_length=500, help_text="Value at time of download"
    )
    new_value: models.CharField = models.CharField(
        max_length=500, help_text="Current value from Spotify"
    )

    # Status tracking
    status: models.CharField = models.CharField(
        max_length=20,
        choices=MetadataUpdateStatus.choices,
        default=MetadataUpdateStatus.PENDING,
    )
    detected_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    resolved_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return (
            f"{self.content_type.model} #{self.object_id}: "
            f"'{self.old_value}' → '{self.new_value}' ({self.status})"
        )

    def mark_applied(self) -> None:
        """Mark this update as applied by the user."""
        self.status = MetadataUpdateStatus.APPLIED
        self.resolved_at = timezone.now()
        self.save()

    def mark_dismissed(self) -> None:
        """Mark this update as dismissed by the user."""
        self.status = MetadataUpdateStatus.DISMISSED
        self.resolved_at = timezone.now()
        self.save()

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "pending_metadata_updates"
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "field_name"],
                name="unique_pending_update_per_entity_field",
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["content_type", "status"]),
            models.Index(fields=["detected_at"]),
        ]


class MetricType(TextChoices):
    """Types of metrics that can be recorded."""

    COUNTER = "counter", "Counter"  # Incrementing values (downloads, failures)
    GAUGE = "gauge", "Gauge"  # Point-in-time values (queue depth, memory)


# pylint: disable=R0902
class AppMetric(models.Model):
    """
    Generic metrics storage for operational insights.

    Used to track things like fallback download success rates, endpoint
    reliability, and other operational metrics that help understand
    system behavior over time.
    """

    name: models.CharField = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Metric name, e.g., 'fallback.tidal.success'",
    )
    metric_type: models.CharField = models.CharField(
        max_length=20,
        choices=MetricType.choices,
        default=MetricType.COUNTER,
    )
    value: models.DecimalField = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="Metric value",
    )
    labels: models.JSONField = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional labels for filtering, e.g., {'provider': 'tidal'}",
    )
    recorded_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    def __str__(self) -> str:
        labels_str = f" {self.labels}" if self.labels else ""
        return f"{self.name}={self.value}{labels_str} @ {self.recorded_at}"

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "app_metrics"
        indexes = [
            models.Index(fields=["name", "recorded_at"]),
            models.Index(fields=["recorded_at"]),
        ]


class SongUpgradeAttempt(models.Model):
    """
    Tracks individual upgrade attempts for songs.

    When attempting to upgrade a low-quality song (e.g., 128kbps from spotdl)
    to higher quality using Tidal or Qobuz, we record each attempt here.
    This allows us to:
    - Skip providers that already returned NOT_FOUND for this song
    - Retry providers that had temporary API_ERROR
    - Not re-attempt providers that returned NOT_AN_UPGRADE
    """

    song: models.ForeignKey = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name="upgrade_attempts",
    )
    provider: models.SmallIntegerField = models.SmallIntegerField(
        choices=DownloadProvider.choices,
        help_text="Provider that was attempted",
    )
    attempted_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    result: models.SmallIntegerField = models.SmallIntegerField(
        choices=UpgradeAttemptResult.choices,
        help_text="Outcome of the upgrade attempt",
    )
    original_bitrate: models.IntegerField = models.IntegerField(
        null=True,
        blank=True,
        help_text="Bitrate of the song before this attempt",
    )
    new_bitrate: models.IntegerField = models.IntegerField(
        null=True,
        blank=True,
        help_text="Bitrate of downloaded file (if download succeeded)",
    )
    error_message: models.TextField = models.TextField(
        blank=True,
        default="",
        help_text="Error details for failed attempts",
    )

    def __str__(self) -> str:
        result_label = UpgradeAttemptResult(self.result).label
        provider_label = DownloadProvider(self.provider).label
        return f"Song {self.song_id} via {provider_label}: {result_label}"

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "song_upgrade_attempts"
        indexes = [
            models.Index(fields=["song", "provider"]),
            models.Index(fields=["result"]),
            models.Index(fields=["attempted_at"]),
        ]


class NotificationState(models.Model):
    """Tracks cooldown state for notification alerts.

    One row per alert type, recording when the last notification was sent
    to prevent notification spam during persistent error conditions.
    """

    alert_type: models.CharField = models.CharField(max_length=50, unique=True)
    last_sent_at: models.DateTimeField = models.DateTimeField()
    last_message: models.TextField = models.TextField(blank=True, default="")

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "notification_state"

    def __str__(self) -> str:
        return f"{self.alert_type} (last sent: {self.last_sent_at})"


# =============================================================================
# External Music List Tracking (Last.fm, ListenBrainz)
# =============================================================================


class ExternalListSource(TextChoices):
    LASTFM = "lastfm", "Last.fm"
    LISTENBRAINZ = "listenbrainz", "ListenBrainz"
    YOUTUBE_MUSIC = "youtube_music", "YouTube Music"


class ExternalListType(TextChoices):
    LOVED_TRACKS = "loved", "Loved/Favorited Tracks"
    TOP_TRACKS = "top", "Top Tracks"
    PLAYLIST = "playlist", "Playlist"
    CHART = "chart", "Chart"


class ExternalListStatus(TextChoices):
    ACTIVE = "active", "Active"
    DISABLED_BY_USER = "disabled_by_user", "Disabled by user"
    AUTH_ERROR = "auth_error", "Authentication error"
    NOT_FOUND = "not_found", "User not found"
    SYNC_ERROR = "sync_error", "Sync error"


class TrackMappingStatus(TextChoices):
    PENDING = "pending", "Pending mapping"
    MAPPED = "mapped", "Successfully mapped to Spotify"
    FAILED = "failed", "Mapping failed"


class ExternalList(models.Model):
    """An external music list from Last.fm or ListenBrainz.

    Tracks loved tracks, top tracks, playlists, or charts from external sources.
    Synced periodically, with tracks resolved to Spotify IDs via the mapping pipeline.
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    name: models.CharField = models.CharField(max_length=500)
    source: models.CharField = models.CharField(
        max_length=20, choices=ExternalListSource.choices
    )
    list_type: models.CharField = models.CharField(
        max_length=20, choices=ExternalListType.choices
    )
    username: models.CharField = models.CharField(max_length=255)
    period: models.CharField = models.CharField(max_length=20, null=True, blank=True)
    list_identifier: models.CharField = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text=(
            "Source-specific ID: ListenBrainz playlist MBID, "
            "chart tag, country code, or 'global'"
        ),
    )
    status: models.CharField = models.CharField(
        max_length=30,
        choices=ExternalListStatus.choices,
        default=ExternalListStatus.ACTIVE,
    )
    status_message: models.CharField = models.CharField(
        max_length=255, null=True, blank=True
    )
    auto_track_artists: models.BooleanField = models.BooleanField(default=False)
    content_hash: models.CharField = models.CharField(
        max_length=64, null=True, blank=True
    )
    last_synced_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    total_tracks: models.IntegerField = models.IntegerField(default=0)
    mapped_tracks: models.IntegerField = models.IntegerField(default=0)
    failed_tracks: models.IntegerField = models.IntegerField(default=0)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "external_lists"
        unique_together = (
            "source",
            "list_type",
            "username",
            "period",
            "list_identifier",
        )

    def __str__(self) -> str:
        return (
            f"{self.get_source_display()} {self.get_list_type_display()}: "
            f"{self.username} ({self.status})"
        )


class ExternalListTrack(models.Model):
    """Junction model tracking per-track mapping state for an external list."""

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    external_list: models.ForeignKey = models.ForeignKey(
        ExternalList, on_delete=models.CASCADE, related_name="tracks"
    )
    artist_name: models.CharField = models.CharField(max_length=500)
    track_name: models.CharField = models.CharField(max_length=500)
    musicbrainz_id: models.CharField = models.CharField(
        max_length=36, null=True, blank=True
    )
    mapping_status: models.CharField = models.CharField(
        max_length=20,
        choices=TrackMappingStatus.choices,
        default=TrackMappingStatus.PENDING,
    )
    spotify_track_id: models.CharField = models.CharField(
        max_length=120, null=True, blank=True
    )
    mapping_confidence: models.FloatField = models.FloatField(null=True, blank=True)
    mapping_method: models.CharField = models.CharField(
        max_length=30, null=True, blank=True
    )
    mapping_error: models.CharField = models.CharField(
        max_length=255, null=True, blank=True
    )
    song: models.ForeignKey = models.ForeignKey(
        "Song", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    mapped_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "external_list_tracks"
        unique_together = ("external_list", "artist_name", "track_name")
        indexes = [
            models.Index(fields=["mapping_status"]),
            models.Index(fields=["external_list", "mapping_status"]),
            models.Index(fields=["spotify_track_id"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.artist_name} - {self.track_name} "
            f"({self.get_mapping_status_display()})"
        )


class TrackMappingCache(models.Model):
    """Cross-list cache for track mapping results.

    Avoids redundant API calls when the same track appears in multiple lists.
    Positive results cached indefinitely; negatives expire after 90 days.
    """

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    musicbrainz_id: models.CharField = models.CharField(
        max_length=36, null=True, blank=True, unique=True
    )
    name_lookup_key: models.CharField = models.CharField(
        max_length=1024, null=True, blank=True, unique=True
    )
    spotify_track_id: models.CharField = models.CharField(
        max_length=120, null=True, blank=True
    )
    isrc: models.CharField = models.CharField(max_length=20, null=True, blank=True)
    confidence: models.FloatField = models.FloatField(default=1.0)
    mapping_method: models.CharField = models.CharField(max_length=30)
    no_match: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "track_mapping_cache"

    def __str__(self) -> str:
        key = self.musicbrainz_id or self.name_lookup_key or "unknown"
        if self.no_match:
            return f"TrackMappingCache({key}) -> NO MATCH"
        return f"TrackMappingCache({key}) -> {self.spotify_track_id}"


class APIRateLimitState(models.Model):
    """Generalized rate limiter for external APIs (Last.fm, MusicBrainz, ListenBrainz).

    Each API gets its own row with configurable limits.
    The existing SpotifyRateLimitState remains separate for its multi-tier logic.
    """

    api_name: models.CharField = models.CharField(max_length=50, unique=True)
    max_requests_per_second: models.FloatField = models.FloatField()
    is_rate_limited: models.BooleanField = models.BooleanField(default=False)
    limited_until: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    request_count: models.IntegerField = models.IntegerField(default=0)
    window_start: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # Default rates per API
    DEFAULT_RATES: dict[str, float] = {
        "lastfm": 5.0,
        "musicbrainz": 1.0,
        "listenbrainz": 2.0,
        "listenbrainz_labs": 1.0,
    }

    class Meta(TypedModelMeta):
        app_label = "library_manager"
        db_table = "api_rate_limit_state"

    def __str__(self) -> str:
        status = "RATE LIMITED" if self.is_rate_limited else "OK"
        return (
            f"{self.api_name}: {status} "
            f"({self.request_count} calls, "
            f"max {self.max_requests_per_second}/s)"
        )
