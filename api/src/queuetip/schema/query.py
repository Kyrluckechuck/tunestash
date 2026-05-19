"""Queuetip GraphQL Query type."""

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.permissions import require_member

from ..context import QueuetipContext
from ..errors import AuthRequiredError, ValidationError
from ..graphql_types import AccountType, PlaylistType
from ..services.playlist import PlaylistService


@strawberry.type
class Query:
    """Root query for the Queuetip public API."""

    @strawberry.field
    def me(self, info: Info[QueuetipContext, None]) -> AccountType | None:
        """Return the currently signed-in account, or null if anonymous."""
        ctx = info.context
        if ctx.account is None:
            return None
        return AccountType.from_model(ctx.account)

    @strawberry.field
    async def my_playlists(
        self, info: Info[QueuetipContext, None]
    ) -> list[PlaylistType]:
        """Playlists the current account is a member of."""
        ctx = info.context
        if ctx.account is None:
            raise AuthRequiredError("Sign in to see your playlists.")
        playlists = await PlaylistService.list_for_account(ctx.account)
        result: list[PlaylistType] = []
        for p in playlists:
            members = await PlaylistService.list_memberships(p)
            result.append(PlaylistType.from_model(p, members))
        return result

    @strawberry.field
    async def playlist(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID | None = None,
        invite_token: str | None = None,
    ) -> PlaylistType:
        """Look up a playlist by id (auth required) or invite token (anonymous OK).

        The invite-token path is the unauthenticated "preview before joining"
        experience: anyone with the link can read playlist metadata + members.
        The id path requires membership.
        """
        ctx = info.context
        if invite_token is not None and id is not None:
            raise ValidationError("Provide exactly one of id or inviteToken.")
        if invite_token is not None:
            playlist = await PlaylistService.get_by_invite_token(invite_token)
        elif id is not None:
            if ctx.account is None:
                raise AuthRequiredError("Sign in to look up a playlist by id.")
            playlist = await PlaylistService.get_by_id(int(id))
            await sync_to_async(require_member)(ctx.account, playlist)
        else:
            raise ValidationError("Provide either id or inviteToken.")
        members = await PlaylistService.list_memberships(playlist)
        return PlaylistType.from_model(playlist, members)
