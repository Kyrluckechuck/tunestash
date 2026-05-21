"""Queuetip core models — accounts, playlists, contributions, voting.

This Django app backs the Queuetip collaborative-playlist feature. It shares
TuneStash's database; `Contribution.song` is a real FK into `library_manager`.
"""

import secrets
import uuid
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django_stubs_ext.db.models import TypedModelMeta
else:
    TypedModelMeta = type


def generate_invite_token() -> str:
    """Return a URL-safe random token for a playlist invite link."""
    return secrets.token_urlsafe(16)


class Account(models.Model):
    """A Queuetip user. Unrelated to TuneStash's operator; not AUTH_USER_MODEL."""

    display_name: models.CharField = models.CharField(max_length=120)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    session_epoch: models.PositiveIntegerField = models.PositiveIntegerField(default=0)

    if TYPE_CHECKING:
        id: int
        external_service_links: "models.Manager[ExternalServiceLink]"

    class Meta(TypedModelMeta):
        app_label = "queuetip"

    def __str__(self) -> str:
        return self.display_name


class AuthIdentity(models.Model):
    """A login identity for an Account — one row per auth provider."""

    PROVIDER_MAGIC_LINK = "magic_link"
    PROVIDER_CHOICES = [(PROVIDER_MAGIC_LINK, "Magic link")]

    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="identities"
    )
    provider: models.CharField = models.CharField(
        max_length=32, choices=PROVIDER_CHOICES
    )
    identifier: models.CharField = models.CharField(max_length=254)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int
        account_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "identifier"],
                name="queuetip_authidentity_provider_identifier_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.identifier}"


class Playlist(models.Model):
    """A collaborative playlist. Engine knobs are stored now, used in Phase 2."""

    name: models.CharField = models.CharField(max_length=200)
    description: models.TextField = models.TextField(blank=True)
    created_by: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="created_playlists"
    )
    invite_token: models.CharField = models.CharField(
        max_length=64, unique=True, default=generate_invite_token
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    min_size: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=0
    )
    max_size: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    t_high: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=3
    )
    t_low: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=3
    )
    base: models.FloatField = models.FloatField(default=0.85)
    p_floor: models.FloatField = models.FloatField(default=0.15)

    if TYPE_CHECKING:
        id: int
        created_by_id: int
        memberships: "models.Manager[PlaylistMembership]"
        contributions: "models.Manager[Contribution]"
        import_jobs: "models.Manager[BulkImportJob]"
        export_snapshots: "models.Manager[ExportSnapshot]"

    class Meta(TypedModelMeta):
        app_label = "queuetip"

    def __str__(self) -> str:
        return self.name


class PlaylistMembership(models.Model):
    """Links an Account to a Playlist with a role."""

    ROLE_OWNER = "owner"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_OWNER, "Owner"), (ROLE_MEMBER, "Member")]

    playlist: models.ForeignKey = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="memberships"
    )
    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="memberships"
    )
    role: models.CharField = models.CharField(
        max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER
    )
    joined_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int
        playlist_id: int
        account_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "account"], name="queuetip_membership_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} {self.role} of {self.playlist}"


class Contribution(models.Model):
    """One song contributed to a playlist."""

    playlist: models.ForeignKey = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="contributions"
    )
    song: models.ForeignKey = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_contributions",
    )
    contributed_by: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="contributions"
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int
        playlist_id: int
        song_id: int
        contributed_by_id: int
        votes: "models.Manager[Vote]"

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "song"], name="queuetip_contribution_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.song} in {self.playlist}"


class Vote(models.Model):
    """A +1/-1 vote by an Account on a Contribution. No row = no vote."""

    contribution: models.ForeignKey = models.ForeignKey(
        Contribution, on_delete=models.CASCADE, related_name="votes"
    )
    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="votes"
    )
    value: models.SmallIntegerField = models.SmallIntegerField()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int
        contribution_id: int
        account_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["contribution", "account"], name="queuetip_vote_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(value__in=[-1, 1]),
                name="queuetip_vote_value_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.account} {self.value:+d} on {self.contribution_id}"


class BulkImportJob(models.Model):
    """Tracks one async bulk-import run so the importer can poll for results."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    playlist: models.ForeignKey = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="import_jobs"
    )
    requested_by: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="import_jobs"
    )
    source_url: models.URLField = models.URLField(max_length=500)
    status: models.CharField = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    # Set by the task once the source playlist is resolved. Null while pending
    # (source not yet fetched) so the UI can distinguish "waiting to start" from
    # "in progress with X of Y processed."
    total_tracks: models.PositiveIntegerField = models.PositiveIntegerField(
        null=True, blank=True
    )
    added_count: models.PositiveIntegerField = models.PositiveIntegerField(default=0)
    skipped_count: models.PositiveIntegerField = models.PositiveIntegerField(default=0)
    unresolved_count: models.PositiveIntegerField = models.PositiveIntegerField(
        default=0
    )
    unresolved_titles: models.JSONField = models.JSONField(default=list)
    error: models.TextField = models.TextField(blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    finished_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    if TYPE_CHECKING:
        id: int
        playlist_id: int
        requested_by_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"

    def __str__(self) -> str:
        return f"Import {self.status} for {self.playlist} ({self.source_url})"


class ExportSnapshot(models.Model):
    """Immutable materialization of a playlist's contributions to a tracklist."""

    id: uuid.UUID = models.UUIDField(  # type: ignore[assignment]
        primary_key=True, default=uuid.uuid4, editable=False
    )
    playlist: models.ForeignKey = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="export_snapshots"
    )
    requested_by: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="export_snapshots"
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    parameters: models.JSONField = models.JSONField(default=dict)
    rng_seed: models.BigIntegerField = models.BigIntegerField()
    warning_message: models.TextField = models.TextField(blank=True)

    if TYPE_CHECKING:
        playlist_id: int
        requested_by_id: int
        tracks: "models.Manager[ExportSnapshotTrack]"

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ExportSnapshot {self.id} of {self.playlist}"


class ExportSnapshotTrack(models.Model):
    """One track in an ExportSnapshot, with the reason it's included."""

    REASON_GUARANTEED = "guaranteed"
    REASON_ROLLED_IN = "rolled_in"
    REASON_TOPPED_UP = "topped_up"
    REASON_CHOICES = [
        (REASON_GUARANTEED, "Guaranteed (net >= t_high)"),
        (REASON_ROLLED_IN, "Rolled in"),
        (REASON_TOPPED_UP, "Topped up to min_size"),
    ]

    snapshot: models.ForeignKey = models.ForeignKey(
        ExportSnapshot, on_delete=models.CASCADE, related_name="tracks"
    )
    song: models.ForeignKey = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_export_tracks",
    )
    position: models.PositiveIntegerField = models.PositiveIntegerField()
    inclusion_reason: models.CharField = models.CharField(
        max_length=16, choices=REASON_CHOICES
    )
    roll_probability: models.FloatField = models.FloatField()

    if TYPE_CHECKING:
        id: int
        snapshot_id: uuid.UUID
        song_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "position"],
                name="queuetip_export_track_position_unique",
            )
        ]


class QueuetipSignupAllowlist(models.Model):
    """Operator-managed allowlist of emails that may sign up to Queuetip.

    Gated by the `QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST` setting (default True).
    Existing accounts (those with an `AuthIdentity` row) sign in normally —
    the allowlist only affects new signups.
    """

    email: models.EmailField = models.EmailField(unique=True, max_length=254)
    note: models.CharField = models.CharField(max_length=200, blank=True)
    added_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        ordering = ["-added_at"]

    def __str__(self) -> str:
        return self.email


class MagicLinkRequestLog(models.Model):
    """Rate-limit audit log for magic-link requests.

    One row per request attempt. Old rows are not purged automatically — the
    sliding-window check only reads the recent window so unbounded growth is
    acceptable for v1 volumes. Add a periodic cleanup task if volume warrants.
    """

    identifier: models.CharField = models.CharField(max_length=254)
    ip_address: models.CharField = models.CharField(max_length=45)
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, db_index=True
    )

    if TYPE_CHECKING:
        id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"

    def __str__(self) -> str:
        return f"{self.identifier} from {self.ip_address} at {self.created_at}"


class ExternalServiceLink(models.Model):
    """A linked external-service identity (Spotify, future: Apple) per Account.

    Stores OAuth tokens for pushing exports to the user's own external account.
    Tokens are plain text in DB for v1 (matches TuneStash's existing pattern);
    encryption-at-rest is a future hardening.
    """

    SERVICE_SPOTIFY = "spotify"
    SERVICE_CHOICES = [(SERVICE_SPOTIFY, "Spotify")]

    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="external_service_links"
    )
    service: models.CharField = models.CharField(max_length=16, choices=SERVICE_CHOICES)
    access_token: models.TextField = models.TextField()
    refresh_token: models.TextField = models.TextField()
    expires_at: models.DateTimeField = models.DateTimeField()
    scope: models.CharField = models.CharField(max_length=512, blank=True)
    service_user_id: models.CharField = models.CharField(max_length=255)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    if TYPE_CHECKING:
        id: int
        account_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "service"],
                name="queuetip_external_service_link_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} → {self.service} ({self.service_user_id})"


class SubsonicConnection(models.Model):
    """A user's connection to their own Subsonic-compatible server (Navidrome etc.).

    Reserved for the upcoming Subsonic playlist-sync feature. Defined in this
    PR so the schema for PlaylistExportTarget's polymorphic FK can compile
    without coordinating a second migration when the sync feature lands.

    Password is Fernet-encrypted with QUEUETIP_SUBSONIC_FERNET_KEY (see
    `src.queuetip.crypto`). Salted-MD5 auth (Subsonic's lowest-common
    denominator, works against every implementation) is computed per-request.
    """

    STATUS_OK = "ok"
    STATUS_FAILED = "failed"
    STATUS_UNKNOWN = "unknown"
    STATUS_CHOICES = [
        (STATUS_OK, "Verified"),
        (STATUS_FAILED, "Failed"),
        (STATUS_UNKNOWN, "Not verified"),
    ]

    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="subsonic_connections"
    )
    label: models.CharField = models.CharField(max_length=80)
    server_url: models.URLField = models.URLField(max_length=500)
    username: models.CharField = models.CharField(max_length=120)
    password_encrypted: models.BinaryField = models.BinaryField()
    last_verified_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    verification_status: models.CharField = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_UNKNOWN
    )
    verification_error: models.TextField = models.TextField(blank=True)
    # OpenSubsonic extensions advertised by the server's
    # /rest/getOpenSubsonicExtensions response (empty list = classic Subsonic
    # or pre-probe). Populated by testSubsonicConnection; consumed for
    # capability-aware behaviour (e.g. preferring ISRC matching when the
    # server reliably returns it).
    opensubsonic_extensions: models.JSONField = models.JSONField(default=list)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    if TYPE_CHECKING:
        id: int
        account_id: int

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        # MVP: one connection per account. Multi-connection is a later
        # optimization; unique_together keeps the simple "my Subsonic" semantics.
        constraints = [
            models.UniqueConstraint(
                fields=["account"],
                name="queuetip_subsonic_connection_unique_per_account",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} → {self.label} ({self.server_url})"


class PlaylistExportTarget(models.Model):
    """A user's intent to mirror a collaborative playlist to one external service.

    One row per (account, playlist, destination_type). The polymorphic
    credential FK (`spotify_link` xor `subsonic_connection`) selects which
    service we sync to. The CHECK constraint enforces the xor at the DB level.

    Lifecycle (see docs/queuetip/subsonic-sync-design.md):
      1. ONE queuetip playlist ↔ ONE remote playlist per (user, destination)
         — subsequent syncs UPDATE `remote_playlist_id`, never create new.
      2. If the remote is deleted, status → REMOTE_DELETED, automation halts,
         user must explicitly recreate.
      3. Idempotent overwrite — queuetip is source of truth for synced
         playlists; manual edits on the remote get replaced on next sync.
    """

    DEST_SPOTIFY = "spotify"
    DEST_SUBSONIC = "subsonic"
    DESTINATION_CHOICES = [
        (DEST_SPOTIFY, "Spotify"),
        (DEST_SUBSONIC, "Subsonic"),
    ]

    SYNC_MANUAL = "manual"
    SYNC_ON_CHANGE = "on_change"
    SYNC_MODE_CHOICES = [
        (SYNC_MANUAL, "Manual"),
        (SYNC_ON_CHANGE, "Auto-sync on changes"),
    ]

    STATUS_PENDING = "pending"
    STATUS_OK = "ok"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_REMOTE_DELETED = "remote_deleted"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_OK, "Synced"),
        (STATUS_PARTIAL, "Synced (some tracks unmatched)"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REMOTE_DELETED, "Remote deleted — re-link required"),
    ]

    account: models.ForeignKey = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="export_targets"
    )
    playlist: models.ForeignKey = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="export_targets"
    )
    destination_type: models.CharField = models.CharField(
        max_length=16, choices=DESTINATION_CHOICES
    )

    # Exactly one of these is non-null; CHECK constraint below enforces the
    # invariant matching destination_type. We use two explicit FKs (rather
    # than a GenericForeignKey) because the credentials live in stable, known
    # models and the simpler shape is easier to query and validate.
    spotify_link: models.ForeignKey = models.ForeignKey(
        ExternalServiceLink,
        on_delete=models.CASCADE,
        related_name="export_targets",
        null=True,
        blank=True,
    )
    subsonic_connection: models.ForeignKey = models.ForeignKey(
        SubsonicConnection,
        on_delete=models.CASCADE,
        related_name="export_targets",
        null=True,
        blank=True,
    )

    # Empty until the first successful create on the remote. After that it's
    # stable for the lifetime of the remote playlist (no timestamped suffixes,
    # no duplicates — that's the entire point of this model).
    remote_playlist_id: models.CharField = models.CharField(max_length=200, blank=True)

    sync_mode: models.CharField = models.CharField(
        max_length=16, choices=SYNC_MODE_CHOICES, default=SYNC_MANUAL
    )
    last_synced_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    last_sync_status: models.CharField = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    last_error: models.TextField = models.TextField(blank=True)
    unmatched_track_titles: models.JSONField = models.JSONField(default=list)
    matched_track_count: models.PositiveIntegerField = models.PositiveIntegerField(
        default=0
    )
    total_track_count: models.PositiveIntegerField = models.PositiveIntegerField(
        default=0
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        id: int
        account_id: int
        playlist_id: int
        spotify_link_id: int | None
        subsonic_connection_id: int | None

    class Meta(TypedModelMeta):
        app_label = "queuetip"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "playlist", "destination_type"],
                name="queuetip_export_target_unique_per_dest",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        destination_type="spotify",
                        spotify_link__isnull=False,
                        subsonic_connection__isnull=True,
                    )
                    | models.Q(
                        destination_type="subsonic",
                        subsonic_connection__isnull=False,
                        spotify_link__isnull=True,
                    )
                ),
                name="queuetip_export_target_dest_fk_matches",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sync_mode", "last_sync_status"],
                name="qt_export_target_auto_sync_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.account} → {self.playlist} ({self.destination_type}, "
            f"{self.last_sync_status})"
        )
