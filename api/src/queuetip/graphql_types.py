"""Strawberry GraphQL types for Queuetip."""

import datetime
from typing import cast

import strawberry

from queuetip.models import (
    Account,
    BulkImportJob,
    Contribution,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
    PlaylistMembership,
    SubsonicConnection,
    Vote,
)


@strawberry.type
class PublicSettingsType:
    """Operator-visible runtime settings exposed to the public frontend.
    Only contains booleans/flags that affect UI rendering — no secrets,
    no operator-specific values."""

    signup_allowlist_enforced: bool


@strawberry.type
class ExternalServiceLinkType:
    """Summary of a linked external service (no secrets exposed)."""

    service: str
    service_user_id: str
    linked_at: datetime.datetime

    @classmethod
    def from_model(cls, link: ExternalServiceLink) -> "ExternalServiceLinkType":
        return cls(
            service=link.service,
            service_user_id=link.service_user_id,
            linked_at=link.created_at,
        )


@strawberry.type
class SubsonicConnectionType:
    """A user's Subsonic-compatible server connection (Navidrome etc.).

    Never exposes the password — only the identifying fields and verification
    status. The OpenSubsonic extension list lets the UI surface 'modern
    server detected' badges without round-tripping.
    """

    id: strawberry.ID
    label: str
    server_url: str
    username: str
    # "password" (classic Subsonic salted-MD5) or "api_key" (OpenSubsonic).
    # Surfaced so the UI can show which mode is in use and label the secret
    # field appropriately ("Password" vs "API key").
    auth_mode: str
    verification_status: str
    verification_error: str
    last_verified_at: datetime.datetime | None
    opensubsonic_extensions: list[str]
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, conn: SubsonicConnection) -> "SubsonicConnectionType":
        return cls(
            id=strawberry.ID(str(conn.id)),
            label=conn.label,
            server_url=conn.server_url,
            username=conn.username,
            auth_mode=conn.auth_mode,
            verification_status=conn.verification_status,
            verification_error=conn.verification_error,
            last_verified_at=conn.last_verified_at,
            opensubsonic_extensions=list(conn.opensubsonic_extensions or []),
            created_at=conn.created_at,
        )


@strawberry.type
class PlaylistExportTargetType:
    """A user's intent to mirror a queuetip playlist to one external service.

    Polymorphic over destination_type — `spotify_user_id` is set when
    destination_type='spotify', `subsonic_connection` when 'subsonic'.
    Frontend uses destination_type to pick the right details.
    """

    id: strawberry.ID
    playlist_id: strawberry.ID
    destination_type: str
    remote_playlist_id: str
    last_sync_status: str
    last_error: str
    last_synced_at: datetime.datetime | None
    unmatched_track_titles: list[str]
    matched_track_count: int
    total_track_count: int

    # Destination-specific details — at most one is populated per row.
    spotify_user_id: str | None
    subsonic_connection: SubsonicConnectionType | None

    @classmethod
    def from_model(cls, target: PlaylistExportTarget) -> "PlaylistExportTargetType":
        link = (
            cast(ExternalServiceLink, target.spotify_link)
            if target.spotify_link_id
            else None
        )
        conn = (
            cast(SubsonicConnection, target.subsonic_connection)
            if target.subsonic_connection_id
            else None
        )
        return cls(
            id=strawberry.ID(str(target.id)),
            playlist_id=strawberry.ID(str(target.playlist_id)),
            destination_type=target.destination_type,
            remote_playlist_id=target.remote_playlist_id,
            last_sync_status=target.last_sync_status,
            last_error=target.last_error,
            last_synced_at=target.last_synced_at,
            unmatched_track_titles=list(target.unmatched_track_titles or []),
            matched_track_count=target.matched_track_count,
            total_track_count=target.total_track_count,
            spotify_user_id=(link.service_user_id if link else None),
            subsonic_connection=(
                SubsonicConnectionType.from_model(conn) if conn else None
            ),
        )


@strawberry.type
class AccountType:
    """A Queuetip user account."""

    id: strawberry.ID
    display_name: str
    created_at: datetime.datetime
    external_services: list[ExternalServiceLinkType]

    @classmethod
    def from_model(
        cls,
        account: Account,
        links: list[ExternalServiceLink] | None = None,
    ) -> "AccountType":
        """Build an AccountType from a Django Account row.

        Pass pre-fetched ``links`` to avoid a lazy ORM hit in async resolvers.
        Callers that omit ``links`` (e.g. nested conversions) get an empty list,
        which is correct — those sites don't need external-service data.
        """
        return cls(
            id=strawberry.ID(str(account.id)),
            display_name=account.display_name,
            created_at=account.created_at,
            external_services=[
                ExternalServiceLinkType.from_model(lnk) for lnk in (links or [])
            ],
        )


@strawberry.type
class MembershipType:
    """A member's role on a playlist."""

    account: AccountType
    role: str
    joined_at: datetime.datetime

    @classmethod
    def from_model(cls, m: PlaylistMembership) -> "MembershipType":
        return cls(
            account=AccountType.from_model(cast(Account, m.account)),
            role=m.role,
            joined_at=m.joined_at,
        )


@strawberry.type
class EngineSettings:
    """The per-playlist selection-engine knobs. Read in 1B, used by Phase 2."""

    min_size: int
    max_size: int | None
    t_high: int
    t_low: int
    base: float
    p_floor: float


@strawberry.input
class EngineSettingsInput:
    """Updates to a playlist's engine knobs. All fields optional (partial update).

    `max_size` uses `strawberry.UNSET` as its default so the API can distinguish
    "leave unchanged" (UNSET) from "set to null" (None).
    """

    min_size: int | None = None
    max_size: int | None = strawberry.UNSET
    t_high: int | None = None
    t_low: int | None = None
    base: float | None = None
    p_floor: float | None = None


@strawberry.type
class PlaylistPreviewType:
    """Minimal playlist data returned to anonymous invite-link visitors.

    Intentionally omits engine_settings — those are internal owner config
    that guests don't need to see before joining.
    """

    id: strawberry.ID
    name: str
    description: str
    invite_token: str
    created_by: AccountType
    created_at: datetime.datetime
    members: list[MembershipType]

    @classmethod
    def from_model(
        cls,
        playlist: Playlist,
        memberships: list[PlaylistMembership],
    ) -> "PlaylistPreviewType":
        return cls(
            id=strawberry.ID(str(playlist.id)),
            name=playlist.name,
            description=playlist.description,
            invite_token=playlist.invite_token,
            created_by=AccountType.from_model(cast(Account, playlist.created_by)),
            created_at=playlist.created_at,
            members=[MembershipType.from_model(m) for m in memberships],
        )


@strawberry.type
class PlaylistType:
    """A Queuetip playlist with engine knobs and member list."""

    id: strawberry.ID
    name: str
    description: str
    invite_token: str
    created_by: AccountType
    created_at: datetime.datetime
    engine_settings: EngineSettings
    members: list[MembershipType]

    @classmethod
    def from_model(
        cls,
        playlist: Playlist,
        memberships: list[PlaylistMembership],
    ) -> "PlaylistType":
        return cls(
            id=strawberry.ID(str(playlist.id)),
            name=playlist.name,
            description=playlist.description,
            invite_token=playlist.invite_token,
            created_by=AccountType.from_model(cast(Account, playlist.created_by)),
            created_at=playlist.created_at,
            engine_settings=EngineSettings(
                min_size=playlist.min_size,
                max_size=playlist.max_size,
                t_high=playlist.t_high,
                t_low=playlist.t_low,
                base=playlist.base,
                p_floor=playlist.p_floor,
            ),
            members=[MembershipType.from_model(m) for m in memberships],
        )


@strawberry.type
class VoteType:
    """One vote on a contribution."""

    account: AccountType
    value: int
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, v: Vote) -> "VoteType":
        return cls(
            account=AccountType.from_model(cast(Account, v.account)),
            value=v.value,
            created_at=v.created_at,
        )


@strawberry.type
class SongRef:
    """Minimal song identity exposed to the public API.

    Avoids leaking TuneStash's full Song shape (downloaded/file_path etc.).
    Phase 2 may expand this.
    """

    id: strawberry.ID
    title: str
    artist: str
    isrc: str | None


@strawberry.type
class ContributionType:
    """A contributed song in a playlist, with its votes."""

    id: strawberry.ID
    song: SongRef
    contributed_by: AccountType
    created_at: datetime.datetime
    votes: list[VoteType]
    net_score: int

    @classmethod
    def from_model(
        cls, contribution: Contribution, votes: list[Vote]
    ) -> "ContributionType":
        from library_manager.models import Song

        song = cast(Song, contribution.song)
        return cls(
            id=strawberry.ID(str(contribution.id)),
            song=SongRef(
                id=strawberry.ID(str(song.id)),
                title=song.name,
                artist=song.primary_artist.name,  # type: ignore[attr-defined]
                isrc=song.isrc or None,
            ),
            contributed_by=AccountType.from_model(
                cast(Account, contribution.contributed_by)
            ),
            created_at=contribution.created_at,
            votes=[VoteType.from_model(v) for v in votes],
            net_score=sum(v.value for v in votes),
        )


@strawberry.type
class ContributionResult:
    """Outcome of a contribute mutation.

    `already_present=True` means the song was already in the playlist — the
    client can show "upvote existing?" UX. The returned `contribution` is the
    existing row in that case.
    """

    contribution: ContributionType
    already_present: bool


@strawberry.type
class CatalogSearchResultType:
    """One catalog search hit, with library-presence flag."""

    deezer_id: str
    title: str
    artist: str
    isrc: str | None
    in_library: bool


@strawberry.type
class BulkImportJobType:
    """An async bulk-import run's state, for polling."""

    id: strawberry.ID
    source_url: str
    status: str
    # Null while the task is still resolving the source playlist; set once the
    # task knows the candidate count so the UI can show "X / Y processed."
    total_tracks: int | None
    added_count: int
    skipped_count: int
    unresolved_count: int
    unresolved_titles: list[str]
    error: str
    created_at: datetime.datetime
    finished_at: datetime.datetime | None

    @classmethod
    def from_model(cls, job: BulkImportJob) -> "BulkImportJobType":
        return cls(
            id=strawberry.ID(str(job.id)),
            source_url=job.source_url,
            status=job.status,
            total_tracks=job.total_tracks,
            added_count=job.added_count,
            skipped_count=job.skipped_count,
            unresolved_count=job.unresolved_count,
            unresolved_titles=list(job.unresolved_titles or []),
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )
