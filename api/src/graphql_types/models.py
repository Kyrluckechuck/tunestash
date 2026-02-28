from enum import Enum
from typing import List, Optional

import strawberry

from .scalars import DateTime


@strawberry.enum
class DownloadStatus(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@strawberry.enum
class TaskStatus(Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


@strawberry.enum
class TaskType(Enum):
    SYNC = "SYNC"
    DOWNLOAD = "DOWNLOAD"
    FETCH = "FETCH"


@strawberry.enum
class EntityType(Enum):
    ARTIST = "ARTIST"
    ALBUM = "ALBUM"
    PLAYLIST = "PLAYLIST"
    TRACK = "TRACK"


@strawberry.enum
class DownloadProvider(Enum):
    """Provider used to download a song."""

    UNKNOWN = "UNKNOWN"
    SPOTDL = "SPOTDL"
    TIDAL = "TIDAL"
    QOBUZ = "QOBUZ"


@strawberry.type
class Artist:
    id: int
    name: str
    gid: Optional[str]
    spotify_uri: Optional[str]
    is_tracked: bool
    last_synced: Optional[DateTime]
    last_downloaded: Optional[DateTime] = None
    added_at: Optional[DateTime] = None
    undownloaded_count: int = 0
    album_count: int = 0
    downloaded_album_count: int = 0
    song_count: int = 0
    failed_song_count: int = 0


@strawberry.type
class Album:
    id: int
    name: str
    spotify_gid: Optional[str]
    total_tracks: int
    wanted: bool
    downloaded: bool
    album_type: Optional[str]
    album_group: Optional[str]
    artist: Optional[str]
    artist_id: Optional[int]
    artist_gid: Optional[str]


@strawberry.type
class Song:
    id: int
    name: str
    gid: Optional[str]
    primary_artist: str
    primary_artist_id: int
    primary_artist_gid: Optional[str]
    created_at: DateTime
    failed_count: int
    bitrate: int
    unavailable: bool
    file_path: Optional[str]
    downloaded: bool
    spotify_uri: Optional[str]
    download_provider: Optional[DownloadProvider] = None


@strawberry.type
class Track:
    id: str
    name: str
    album_id: str
    artist_ids: List[str]
    duration_ms: int
    track_number: int
    disc_number: int
    spotify_url: str
    is_downloaded: bool
    download_status: Optional[DownloadStatus]


@strawberry.type
class Playlist:
    id: int
    name: str
    url: str
    status: str
    status_message: Optional[str]
    enabled: bool  # Computed from status for backwards compatibility
    auto_track_artists: bool
    last_synced_at: Optional[DateTime]


@strawberry.type
class DownloadProgress:
    entity_id: str
    entity_type: str
    progress: float
    status: DownloadStatus
    message: Optional[str]


@strawberry.type
class DownloadHistory:
    id: str
    entity_id: str
    entity_type: str  # "TRACK" | "ALBUM" | "PLAYLIST"
    status: DownloadStatus
    started_at: DateTime
    completed_at: Optional[DateTime]
    error_message: Optional[str]


@strawberry.type
class TaskHistory:
    id: str
    task_id: str
    type: TaskType
    entity_id: str
    entity_type: EntityType
    status: TaskStatus
    started_at: DateTime
    completed_at: Optional[DateTime]
    duration_seconds: Optional[int]
    progress_percentage: Optional[float]
    log_messages: List[str]


@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str]
    end_cursor: Optional[str]


@strawberry.type
class ArtistConnection:
    edges: List[Artist]
    page_info: PageInfo
    total_count: int


@strawberry.type
class AlbumConnection:
    edges: List[Album]
    page_info: PageInfo
    total_count: int


@strawberry.type
class PlaylistConnection:
    edges: List[Playlist]
    page_info: PageInfo
    total_count: int


@strawberry.type
class SongConnection:
    edges: List[Song]
    page_info: PageInfo
    total_count: int


@strawberry.type
class HistoryConnection:
    edges: List["HistoryEdge"]
    page_info: PageInfo
    total_count: int


@strawberry.type
class HistoryEdge:
    node: DownloadHistory
    cursor: str


@strawberry.type
class TaskHistoryConnection:
    edges: List["TaskHistoryEdge"]
    page_info: PageInfo
    total_count: int


@strawberry.type
class TaskHistoryEdge:
    node: TaskHistory
    cursor: str


@strawberry.input
class TrackArtistInput:
    artist_id: str
    auto_download: bool = False


@strawberry.input
class TrackPlaylistInput:
    playlist_id: str
    auto_track_artists: bool = False


@strawberry.input
class UpdateArtistInput:
    artist_id: str
    is_tracked: Optional[bool] = None
    auto_download: Optional[bool] = None


@strawberry.input
class UpdateAlbumInput:
    album_id: str
    is_wanted: Optional[bool] = None


@strawberry.type
class MutationResult:
    success: bool
    message: str
    artist: Optional[Artist] = None
    album: Optional[Album] = None
    playlist: Optional[Playlist] = None


@strawberry.input
class UpdatePlaylistInput:
    playlist_id: str
    is_tracked: Optional[bool] = None
    auto_track_artists: Optional[bool] = None


@strawberry.type
class PendingTask:
    """A pending task in the Celery queue with resolved entity details."""

    task_id: str
    task_name: str
    display_name: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    entity_name: Optional[str]
    status: str
    created_at: Optional[str]


@strawberry.type
class TaskCount:
    task_name: str
    count: int


@strawberry.type
class QueueStatus:
    total_pending_tasks: int
    task_counts: List[TaskCount]
    pending_tasks: List[PendingTask]
    queue_size: int


@strawberry.type
class PeriodicTask:
    """A scheduled periodic task from Celery Beat."""

    id: int
    name: str
    task: str
    enabled: bool
    is_core: bool  # Core tasks (cleanup, stale task detection) shouldn't be toggled
    description: Optional[str]
    schedule_description: str
    last_run_at: Optional[DateTime]
    total_run_count: int


@strawberry.type
class OneOffTask:
    """A one-off maintenance task that can be triggered manually."""

    id: str
    name: str
    description: str
    category: str  # e.g., "maintenance", "data-migration", "cleanup"


@strawberry.type
class UpgradeStats:
    """Statistics about low-quality song upgrades."""

    total_low_quality: int  # Total songs below quality threshold
    upgradeable: int  # Songs with untried providers
    upgraded: int  # Successfully upgraded songs
    not_upgradeable: int  # All providers returned NOT_FOUND


@strawberry.type
class AuthenticationStatus:
    """Authentication status for YouTube Music Premium downloads and Spotify access."""

    # YouTube Music authentication (for high-quality audio downloads)
    cookies_valid: bool
    cookies_error_type: Optional[str] = None  # 'missing', 'malformed', 'expired'
    cookies_error_message: Optional[str] = None
    cookies_expire_in_days: Optional[int] = None
    po_token_configured: bool = False
    po_token_valid: bool = False
    po_token_error_message: Optional[str] = None

    # Spotify authentication mode (for playlist access)
    spotify_user_auth_enabled: bool = False
    spotify_auth_mode: str = (
        "public"  # 'public' (public playlists only) or 'user-authenticated' (includes private)
    )

    # Spotify OAuth token status (when using user-authenticated mode)
    spotify_token_valid: bool = True
    spotify_token_expired: bool = False
    spotify_token_expires_in_hours: Optional[int] = None
    spotify_token_error_message: Optional[str] = None


@strawberry.type
class SpotifyRateLimitStatus:
    """Spotify API rate limit status."""

    # True only when Spotify has returned a 429 (actually blocked)
    is_rate_limited: bool
    rate_limited_until: Optional[DateTime] = None
    seconds_until_clear: Optional[int] = None
    # True when we're proactively delaying tasks to avoid hitting limits
    is_throttling: bool = False
    current_delay_seconds: float = 0.0
    # Legacy fields for backwards compatibility
    window_call_count: int
    window_max_calls: int
    window_usage_percent: float
    # Detailed tier information
    burst_calls: int = 0
    burst_max: int = 25
    sustained_calls: int = 0
    sustained_max: int = 100
    hourly_calls: int = 0
    hourly_max: int = 600


@strawberry.type
class StorageStatus:
    """Storage health status for the music output directory."""

    path: str
    exists: bool
    is_writable: bool
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None
    available_gb: Optional[float] = None
    usage_percent: Optional[float] = None
    is_low: bool = False
    is_critically_low: bool = False
    error_message: Optional[str] = None


@strawberry.type
class SystemHealth:
    """Overall system health status."""

    can_download: bool
    download_blocker_reason: Optional[str] = None
    authentication: AuthenticationStatus
    spotify_rate_limit: SpotifyRateLimitStatus
    storage: StorageStatus


# Catalog Search Result Types
# These represent search results from Deezer's API (not our local database)


@strawberry.type
class CatalogSearchArtist:
    """Artist result from catalog search."""

    provider_id: str
    name: str
    image_url: Optional[str]
    external_url: Optional[str]
    in_library: bool
    local_id: Optional[int]
    is_tracked: bool


@strawberry.type
class CatalogSearchAlbum:
    """Album result from catalog search."""

    provider_id: str
    name: str
    image_url: Optional[str]
    external_url: Optional[str]
    artist_name: str
    artist_provider_id: str
    release_date: Optional[str]
    album_type: str
    total_tracks: int
    in_library: bool
    local_id: Optional[int]


@strawberry.type
class CatalogSearchTrack:
    """Track result from catalog search."""

    provider_id: str
    name: str
    external_url: Optional[str]
    artist_name: str
    artist_provider_id: str
    album_name: str
    album_provider_id: str
    duration_ms: int
    in_library: bool
    local_id: Optional[int]


@strawberry.type
class CatalogSearchResults:
    """Combined search results from catalog API."""

    artists: List[CatalogSearchArtist]
    albums: List[CatalogSearchAlbum]
    tracks: List[CatalogSearchTrack]


@strawberry.type
class SpotifyPlaylistInfo:
    """Playlist info fetched directly from Spotify by URL/URI."""

    name: str
    owner_name: Optional[str]
    track_count: int
    image_url: Optional[str]


@strawberry.type
class LibraryStats:
    """Aggregate statistics for the music library."""

    # Song counts (full library)
    total_songs: int
    downloaded_songs: int
    missing_songs: int  # Not downloaded and not failed
    failed_songs: int
    unavailable_songs: int

    # Album counts (full library)
    total_albums: int
    downloaded_albums: int  # All songs downloaded
    partial_albums: int  # Some songs downloaded
    missing_albums: int  # No songs downloaded

    # Artist counts
    total_artists: int
    tracked_artists: int

    # Completion percentages - full library (rounded to 1 decimal)
    song_completion_percentage: float
    album_completion_percentage: float

    # "Desired" = songs from tracked artists
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


# =============================================================================
# Metadata Update Types
# =============================================================================


@strawberry.enum
class MetadataUpdateStatus(Enum):
    """Status of a pending metadata update."""

    PENDING = "PENDING"
    APPLIED = "APPLIED"
    DISMISSED = "DISMISSED"


@strawberry.enum
class MetadataEntityType(Enum):
    """Type of entity for metadata updates."""

    ARTIST = "ARTIST"
    ALBUM = "ALBUM"
    SONG = "SONG"


@strawberry.type
class MetadataUpdate:
    """A detected metadata change that the user can apply or dismiss."""

    id: int
    entity_type: MetadataEntityType
    entity_id: int
    entity_name: str
    field_name: str
    old_value: str
    new_value: str
    status: MetadataUpdateStatus
    detected_at: DateTime
    resolved_at: Optional[DateTime]
    affected_songs_count: int


@strawberry.type
class MetadataUpdateSummary:
    """Summary counts for metadata updates."""

    artist_updates: int
    album_updates: int
    song_updates: int
    total_affected_songs: int


@strawberry.type
class MetadataUpdateConnection:
    """Connection type for metadata updates with summary."""

    edges: List[MetadataUpdate]
    summary: MetadataUpdateSummary


@strawberry.type
class MetadataCheckResult:
    """Result of a manual metadata check operation."""

    success: bool
    message: str
    change_detected: bool
    old_value: Optional[str] = None
    new_value: Optional[str] = None


# =============================================================================
# Application Metrics Types
# =============================================================================


@strawberry.type
class MetricTimePoint:
    """A single data point in a time series."""

    timestamp: DateTime
    value: float
    count: int


@strawberry.type
class MetricSummary:
    """Summary statistics for a single metric."""

    name: str
    total: float
    count: int
    first_recorded: Optional[DateTime]
    last_recorded: Optional[DateTime]


@strawberry.type
class MetricTimeSeries:
    """Time series data for a metric."""

    name: str
    period: str  # "hour" or "day"
    data: List[MetricTimePoint]


@strawberry.type
class FallbackMetrics:
    """Aggregated metrics for fallback download provider usage."""

    total_attempts: int
    total_successes: int
    total_failures: int
    success_rate: float
    time_series: List[MetricTimePoint]
    failure_reasons: List["FailureReasonCount"]


@strawberry.type
class FailureReasonCount:
    """Count of failures by reason."""

    reason: str
    count: int


# =============================================================================
# External List Types
# =============================================================================


@strawberry.type
class ExternalListType:
    """An external music list from Last.fm or ListenBrainz."""

    id: int
    name: str
    source: str
    list_type: str
    username: str
    period: Optional[str]
    list_identifier: Optional[str]
    status: str
    status_message: Optional[str]
    auto_track_artists: bool
    last_synced_at: Optional[DateTime]
    created_at: Optional[DateTime]
    total_tracks: int
    mapped_tracks: int
    failed_tracks: int


@strawberry.type
class ExternalListConnection:
    edges: List[ExternalListType]
    page_info: PageInfo
    total_count: int
