"""Queuetip GraphQL Mutation type."""

import re

from django.db import IntegrityError, transaction

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.models import Account, AuthIdentity, Playlist

from ..auth import make_magic_link_token
from ..context import QueuetipContext
from ..email import send_magic_link_email
from ..errors import AuthRequiredError, ValidationError
from ..graphql_types import EngineSettingsInput, PlaylistType
from ..services.membership import MembershipService
from ..services.playlist import PlaylistService

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


async def _build_playlist_type(playlist: Playlist) -> PlaylistType:
    """Compose a PlaylistType with pre-fetched memberships (no lazy load)."""
    members = await PlaylistService.list_memberships(playlist)
    return PlaylistType.from_model(playlist, members)


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
