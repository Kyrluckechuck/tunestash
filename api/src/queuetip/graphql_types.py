"""Strawberry GraphQL types for Queuetip."""

import datetime
import json

from django.conf import settings as dj_settings

import strawberry

from queuetip.models import (
    Account,
    BulkImportJob,
    Contribution,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
    PlaylistMembership,
    Vote,
)


@strawberry.type
class AccountType:
    """A Queuetip user account."""

    id: strawberry.ID
    display_name: str
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, account: Account) -> "AccountType":
        """Build an AccountType from a Django Account row."""
        return cls(
            id=strawberry.ID(str(account.id)),
            display_name=account.display_name,
            created_at=account.created_at,
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
            account=AccountType.from_model(m.account),
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
    max_size: int | None = strawberry.UNSET  # type: ignore[assignment]
    t_high: int | None = None
    t_low: int | None = None
    base: float | None = None
    p_floor: float | None = None


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
            created_by=AccountType.from_model(playlist.created_by),
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
            account=AccountType.from_model(v.account),
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
        song = contribution.song
        return cls(
            id=strawberry.ID(str(contribution.id)),
            song=SongRef(
                id=strawberry.ID(str(song.id)),
                title=song.name,
                artist=song.primary_artist.name,
                isrc=song.isrc or None,
            ),
            contributed_by=AccountType.from_model(contribution.contributed_by),
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
            added_count=job.added_count,
            skipped_count=job.skipped_count,
            unresolved_count=job.unresolved_count,
            unresolved_titles=list(job.unresolved_titles or []),
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )


@strawberry.type
class ExportSnapshotTrackType:
    """One track in a materialized snapshot."""

    id: strawberry.ID
    song: SongRef
    position: int
    inclusion_reason: str
    roll_probability: float

    @classmethod
    def from_model(cls, t: ExportSnapshotTrack) -> "ExportSnapshotTrackType":
        return cls(
            id=strawberry.ID(str(t.id)),
            song=SongRef(
                id=strawberry.ID(str(t.song.id)),
                title=t.song.name,
                artist=t.song.primary_artist.name,
                isrc=t.song.isrc or None,
            ),
            position=t.position,
            inclusion_reason=t.inclusion_reason,
            roll_probability=t.roll_probability,
        )


@strawberry.input
class ExportOptionsInput:
    """Personal filters applied to one export. v1 has just the downvote filter."""

    exclude_my_downvotes: bool = False


@strawberry.type
class ExportSnapshotType:
    """A materialized export — immutable artifact, replayable from its seed."""

    id: strawberry.ID
    requested_by: AccountType
    created_at: datetime.datetime
    parameters: str  # JSON-stringified, opaque to clients
    rng_seed: str  # rendered as str to avoid JS number-precision issues with BigInt
    warning_message: str
    tracks: list[ExportSnapshotTrackType]
    m3u_url: str
    playlist: PlaylistType

    @classmethod
    def from_model(
        cls,
        snapshot: ExportSnapshot,
        tracks: list[ExportSnapshotTrack],
        playlist_members: list[PlaylistMembership],
    ) -> "ExportSnapshotType":
        base = getattr(
            dj_settings, "QUEUETIP_PUBLIC_URL", "http://localhost:5050"
        ).rstrip("/")
        return cls(
            id=strawberry.ID(str(snapshot.id)),
            requested_by=AccountType.from_model(snapshot.requested_by),
            created_at=snapshot.created_at,
            parameters=json.dumps(snapshot.parameters or {}),
            rng_seed=str(snapshot.rng_seed),
            warning_message=snapshot.warning_message,
            tracks=[ExportSnapshotTrackType.from_model(t) for t in tracks],
            m3u_url=f"{base}/exports/{snapshot.id}.m3u",
            playlist=PlaylistType.from_model(snapshot.playlist, playlist_members),
        )
