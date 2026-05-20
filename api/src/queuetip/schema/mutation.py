"""Queuetip GraphQL Mutation type."""

import re

from django.db import IntegrityError, transaction

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.models import Account, AuthIdentity, Contribution, Playlist, Vote

from ..auth import make_magic_link_token
from ..context import QueuetipContext
from ..email import send_magic_link_email
from ..errors import AuthRequiredError, NotFoundError, ValidationError
from ..graphql_types import (
    BulkImportJobType,
    ContributionResult,
    ContributionType,
    EngineSettingsInput,
    ExportOptionsInput,
    ExportSnapshotType,
    PlaylistType,
)
from ..services.bulk_import import BulkImportService
from ..services.contribution import ContributionService
from ..services.export import ExportService
from ..services.membership import MembershipService
from ..services.playlist import PlaylistService
from ..services.vote import VoteService

# Pragmatic email shape check — rejects obvious garbage before we create a row
# or hand the address to the mail backend. Not a full RFC 5322 validation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Matches Account.display_name max_length; a longer value would raise a
# DataError from the DB layer rather than a friendly result.
_DISPLAY_NAME_MAX = 120


@strawberry.type
class RequestMagicLinkResult:
    """Outcome of a magic-link request."""

    sent: bool
    message: str


@strawberry.type
class DeletePlaylistResult:
    """Outcome of a delete-style mutation."""

    deleted: bool


@strawberry.type
class RegenerateInviteResult:
    """The new invite token after regeneration."""

    invite_token: str


def _require_account(info: Info[QueuetipContext, None]) -> Account:
    """Return the signed-in account, or raise AuthRequiredError."""
    ctx = info.context
    if ctx.account is None:
        raise AuthRequiredError("Sign in to perform this action.")
    return ctx.account


async def _list_votes(contribution: Contribution) -> list[Vote]:
    """Fetch the votes for a contribution (pre-fetching account)."""
    return await sync_to_async(
        lambda: list(
            Vote.objects.filter(contribution=contribution).select_related("account")
        )
    )()


async def _load_contribution_view(contribution_id: int) -> ContributionType:
    """Reload a contribution with all relations needed for the GraphQL type."""

    def _load() -> tuple[Contribution, list[Vote]]:
        c = (
            Contribution.objects.select_related(
                "song", "song__primary_artist", "contributed_by"
            )
            .filter(id=contribution_id)
            .first()
        )
        if c is None:
            raise NotFoundError(f"No contribution with id={contribution_id}")
        votes = list(Vote.objects.filter(contribution=c).select_related("account"))
        return c, votes

    contribution, votes = await sync_to_async(_load)()
    return ContributionType.from_model(contribution, votes)


async def _build_playlist_type(playlist: Playlist) -> PlaylistType:
    """Compose a PlaylistType with pre-fetched memberships (no lazy load)."""
    members = await PlaylistService.list_memberships(playlist)
    return PlaylistType.from_model(playlist, members)


async def _load_snapshot_with_tracks(snapshot) -> "ExportSnapshotType":
    """Pre-fetch tracks (+song+artist) and playlist members before composing the GraphQL type."""
    from queuetip.models import ExportSnapshot, ExportSnapshotTrack, PlaylistMembership

    def _load() -> tuple[ExportSnapshot, list, list]:
        # Re-fetch snapshot with playlist__created_by to avoid lazy-load in conversion
        snap = ExportSnapshot.objects.select_related(
            "playlist", "playlist__created_by", "requested_by"
        ).get(id=snapshot.id)
        tracks = list(
            ExportSnapshotTrack.objects.filter(snapshot=snap)
            .select_related("song", "song__primary_artist")
            .order_by("position")
        )
        members = list(
            PlaylistMembership.objects.filter(playlist=snap.playlist)
            .select_related("account")
            .order_by("joined_at")
        )
        return snap, tracks, members

    snap, tracks, members = await sync_to_async(_load)()
    return ExportSnapshotType.from_model(snap, tracks, members)


async def _request_magic_link(
    email: str, display_name: str | None
) -> RequestMagicLinkResult:
    """Find or create an account for `email` and email it a sign-in link.

    An unknown email with no display name cannot sign up — it gets a result
    with `sent=False` asking for a name. Known emails ignore `display_name`.
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return RequestMagicLinkResult(
            sent=False, message="That doesn't look like a valid email address."
        )

    def find_identity() -> AuthIdentity | None:
        return (
            AuthIdentity.objects.filter(
                provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=email
            )
            .select_related("account")
            .first()
        )

    identity = await sync_to_async(find_identity)()

    if identity is None:
        clean_name = display_name.strip() if display_name else ""
        if not clean_name:
            return RequestMagicLinkResult(
                sent=False,
                message="No account exists for that email. "
                "Provide a display name to sign up.",
            )
        if len(clean_name) > _DISPLAY_NAME_MAX:
            return RequestMagicLinkResult(
                sent=False,
                message=f"Display name is too long "
                f"(max {_DISPLAY_NAME_MAX} characters).",
            )

        def create_account() -> Account | None:
            # Account + AuthIdentity must land together: an Account with no
            # identity can never be signed into. atomic() rolls back both if
            # the second insert fails. A concurrent signup for the same email
            # loses the unique-constraint race — return None and re-query.
            try:
                with transaction.atomic():
                    account = Account.objects.create(display_name=clean_name)
                    AuthIdentity.objects.create(
                        account=account,
                        provider=AuthIdentity.PROVIDER_MAGIC_LINK,
                        identifier=email,
                    )
                return account
            except IntegrityError:
                return None

        account = await sync_to_async(create_account)()
        if account is None:
            identity = await sync_to_async(find_identity)()
            if identity is None:
                return RequestMagicLinkResult(
                    sent=False,
                    message="Something went wrong signing up. Please try again.",
                )
            account = identity.account
    else:
        account = identity.account

    token = make_magic_link_token(account.id)
    await sync_to_async(send_magic_link_email)(email, token)
    return RequestMagicLinkResult(
        sent=True, message="Check your email for a sign-in link."
    )


@strawberry.type
class Mutation:
    """Root mutation for the Queuetip public API."""

    @strawberry.mutation
    async def request_magic_link(
        self, email: str, display_name: str | None = None
    ) -> RequestMagicLinkResult:
        """Request a magic-link sign-in email. Creates an account if needed."""
        return await _request_magic_link(email, display_name)

    @strawberry.mutation
    async def create_playlist(
        self,
        info: Info[QueuetipContext, None],
        name: str,
        description: str = "",
    ) -> PlaylistType:
        """Create a new playlist owned by the current account."""
        account = _require_account(info)
        if not name.strip():
            raise ValidationError("Playlist name cannot be empty.")
        playlist = await PlaylistService.create(
            account, name=name, description=description
        )
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def update_playlist_settings(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
        name: str | None = None,
        description: str | None = None,
        engine: EngineSettingsInput | None = None,
    ) -> PlaylistType:
        """Owner-only partial update of name/description/engine knobs."""
        account = _require_account(info)
        kwargs: dict = {}
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if engine is not None:
            if engine.min_size is not None:
                kwargs["min_size"] = engine.min_size
            # `max_size` uses strawberry.UNSET to distinguish "unchanged" from
            # "explicitly null". Only forward to the service when set.
            if engine.max_size is not strawberry.UNSET:
                kwargs["max_size"] = engine.max_size
            if engine.t_high is not None:
                kwargs["t_high"] = engine.t_high
            if engine.t_low is not None:
                kwargs["t_low"] = engine.t_low
            if engine.base is not None:
                kwargs["base"] = engine.base
            if engine.p_floor is not None:
                kwargs["p_floor"] = engine.p_floor
        playlist = await PlaylistService.update_settings(account, int(id), **kwargs)
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def regenerate_invite_token(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> RegenerateInviteResult:
        """Owner-only. Generate a new invite token (invalidates the old one)."""
        account = _require_account(info)
        token = await PlaylistService.regenerate_invite_token(account, int(id))
        return RegenerateInviteResult(invite_token=token)

    @strawberry.mutation
    async def delete_playlist(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        """Owner-only. Permanently delete the playlist."""
        account = _require_account(info)
        await PlaylistService.delete(account, int(id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def join_playlist(
        self, info: Info[QueuetipContext, None], invite_token: str
    ) -> PlaylistType:
        """Join a playlist using its invite token. Idempotent."""
        account = _require_account(info)
        await MembershipService.join(account, invite_token)
        playlist = await PlaylistService.get_by_invite_token(invite_token)
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def leave_playlist(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        """Leave a playlist. Owners with other members must promote/delete first."""
        account = _require_account(info)
        await MembershipService.leave(account, int(id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def kick_member(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        account_id: strawberry.ID,
    ) -> DeletePlaylistResult:
        """Owner-only. Remove another account's membership."""
        actor = _require_account(info)
        await MembershipService.kick(actor, int(playlist_id), int(account_id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def promote_member(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        account_id: strawberry.ID,
    ) -> PlaylistType:
        """Owner-only. Promote a member to owner role (co-owner)."""
        actor = _require_account(info)
        await MembershipService.promote(actor, int(playlist_id), int(account_id))
        playlist = await PlaylistService.get_by_id(int(playlist_id))
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def contribute_from_search(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        deezer_track_id: str,
    ) -> ContributionResult:
        """Contribute a song picked from `catalogSearch` (by Deezer track id)."""
        account = _require_account(info)
        contribution, already_present = (
            await ContributionService.contribute_from_search(
                account, int(playlist_id), deezer_track_id
            )
        )
        votes = await _list_votes(contribution)
        return ContributionResult(
            contribution=ContributionType.from_model(contribution, votes),
            already_present=already_present,
        )

    @strawberry.mutation
    async def contribute_from_link(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        url: str,
    ) -> ContributionResult:
        """Contribute a song by pasting its Spotify / Apple / Deezer URL."""
        account = _require_account(info)
        contribution, already_present = await ContributionService.contribute_from_link(
            account, int(playlist_id), url
        )
        votes = await _list_votes(contribution)
        return ContributionResult(
            contribution=ContributionType.from_model(contribution, votes),
            already_present=already_present,
        )

    @strawberry.mutation
    async def remove_contribution(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        """Remove a contribution. Owner may remove any; member only their own."""
        account = _require_account(info)
        await ContributionService.remove_contribution(account, int(id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def cast_vote(
        self,
        info: Info[QueuetipContext, None],
        contribution_id: strawberry.ID,
        value: int,
    ) -> ContributionType:
        """Cast a +1 or -1 vote on a contribution. Re-cast replaces the value."""
        account = _require_account(info)
        await VoteService.cast_vote(account, int(contribution_id), value)
        return await _load_contribution_view(int(contribution_id))

    @strawberry.mutation
    async def clear_vote(
        self, info: Info[QueuetipContext, None], contribution_id: strawberry.ID
    ) -> ContributionType:
        """Clear the caller's vote on a contribution. Idempotent."""
        account = _require_account(info)
        await VoteService.clear_vote(account, int(contribution_id))
        return await _load_contribution_view(int(contribution_id))

    @strawberry.mutation
    async def bulk_import_playlist(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        url: str,
    ) -> BulkImportJobType:
        """Queue an async import of a public Spotify/Apple playlist URL.

        Returns the BulkImportJob; poll `bulkImportJob(id)` for progress.
        """
        account = _require_account(info)
        job = await BulkImportService.start(account, int(playlist_id), url)
        return BulkImportJobType.from_model(job)

    @strawberry.mutation
    async def create_export(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        options: ExportOptionsInput | None = None,
    ) -> ExportSnapshotType:
        """Materialize a playlist into a new ExportSnapshot."""
        account = _require_account(info)
        exclude_downvotes = bool(options and options.exclude_my_downvotes)
        snapshot = await ExportService.create(
            account, int(playlist_id), exclude_my_downvotes=exclude_downvotes
        )
        return await _load_snapshot_with_tracks(snapshot)
