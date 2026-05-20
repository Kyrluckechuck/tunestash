"""Queuetip core models — accounts, playlists, contributions, voting.

This Django app backs the Queuetip collaborative-playlist feature. It shares
TuneStash's database; `Contribution.song` is a real FK into `library_manager`.
"""

import secrets

from django.db import models


def generate_invite_token() -> str:
    """Return a URL-safe random token for a playlist invite link."""
    return secrets.token_urlsafe(16)


class Account(models.Model):
    """A Queuetip user. Unrelated to TuneStash's operator; not AUTH_USER_MODEL."""

    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.display_name


class AuthIdentity(models.Model):
    """A login identity for an Account — one row per auth provider."""

    PROVIDER_MAGIC_LINK = "magic_link"
    PROVIDER_CHOICES = [(PROVIDER_MAGIC_LINK, "Magic link")]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="identities"
    )
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    identifier = models.CharField(max_length=254)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
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

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="created_playlists"
    )
    invite_token = models.CharField(
        max_length=64, unique=True, default=generate_invite_token
    )
    created_at = models.DateTimeField(auto_now_add=True)
    min_size = models.PositiveSmallIntegerField(default=0)
    max_size = models.PositiveSmallIntegerField(null=True, blank=True)
    t_high = models.PositiveSmallIntegerField(default=3)
    t_low = models.PositiveSmallIntegerField(default=3)
    base = models.FloatField(default=0.85)
    p_floor = models.FloatField(default=0.15)

    def __str__(self) -> str:
        return self.name


class PlaylistMembership(models.Model):
    """Links an Account to a Playlist with a role."""

    ROLE_OWNER = "owner"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_OWNER, "Owner"), (ROLE_MEMBER, "Member")]

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="memberships"
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "account"], name="queuetip_membership_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} {self.role} of {self.playlist}"


class Contribution(models.Model):
    """One song contributed to a playlist."""

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="contributions"
    )
    song = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_contributions",
    )
    contributed_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="contributions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "song"], name="queuetip_contribution_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.song} in {self.playlist}"


class Vote(models.Model):
    """A +1/-1 vote by an Account on a Contribution. No row = no vote."""

    contribution = models.ForeignKey(
        Contribution, on_delete=models.CASCADE, related_name="votes"
    )
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
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

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="import_jobs"
    )
    requested_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="import_jobs"
    )
    source_url = models.URLField(max_length=500)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    added_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    unresolved_count = models.PositiveIntegerField(default=0)
    unresolved_titles = models.JSONField(default=list)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Import {self.status} for {self.playlist} ({self.source_url})"


class ExportSnapshot(models.Model):
    """Immutable materialization of a playlist's contributions to a tracklist."""

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="export_snapshots"
    )
    requested_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="export_snapshots"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    parameters = models.JSONField(default=dict)
    rng_seed = models.BigIntegerField()
    warning_message = models.TextField(blank=True)

    class Meta:
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

    snapshot = models.ForeignKey(
        ExportSnapshot, on_delete=models.CASCADE, related_name="tracks"
    )
    song = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_export_tracks",
    )
    position = models.PositiveIntegerField()
    inclusion_reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    roll_probability = models.FloatField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "position"],
                name="queuetip_export_track_position_unique",
            )
        ]


class ExternalServiceLink(models.Model):
    """A linked external-service identity (Spotify, future: Apple) per Account.

    Stores OAuth tokens for pushing exports to the user's own external account.
    Tokens are plain text in DB for v1 (matches TuneStash's existing pattern);
    encryption-at-rest is a future hardening.
    """

    SERVICE_SPOTIFY = "spotify"
    SERVICE_CHOICES = [(SERVICE_SPOTIFY, "Spotify")]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="external_service_links"
    )
    service = models.CharField(max_length=16, choices=SERVICE_CHOICES)
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    scope = models.CharField(max_length=512, blank=True)
    service_user_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "service"],
                name="queuetip_external_service_link_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} → {self.service} ({self.service_user_id})"
