"""Strawberry GraphQL types for Queuetip."""

import datetime

import strawberry

from queuetip.models import Account, Playlist, PlaylistMembership


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
