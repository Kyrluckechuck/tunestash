"""Queuetip GraphQL Query type."""

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.models import (
    Account,
    PlaylistExportTarget,
    SubsonicConnection,
)
from queuetip.permissions import require_member
from src.queuetip.resolution.catalog import catalog_search as _catalog_search

from ..context import QueuetipContext
from ..errors import AuthRequiredError
from ..graphql_types import (
    AccountType,
    BulkImportJobType,
    CatalogSearchResultType,
    ContributionType,
    PlaylistExportTargetType,
    PlaylistPreviewType,
    PlaylistType,
    PublicSettingsType,
    SubsonicConnectionType,
)
from ..services.bulk_import import BulkImportService
from ..services.contribution import ContributionService
from ..services.playlist import PlaylistService


def _require_account(info: Info[QueuetipContext, None]) -> Account:
    ctx = info.context
    if ctx.account is None:
        raise AuthRequiredError("Sign in to perform this action.")
    return ctx.account


@strawberry.type
class Query:
    """Root query for the Queuetip public API."""

    @strawberry.field
    async def me(self, info: Info[QueuetipContext, None]) -> AccountType | None:
        """Return the currently signed-in account, or null if anonymous."""
        ctx = info.context
        if ctx.account is None:
            return None
        account = ctx.account
        links = await sync_to_async(
            lambda: list(account.external_service_links.all())
        )()
        return AccountType.from_model(account, links=links)

    @strawberry.field
    def public_settings(self) -> PublicSettingsType:
        """Frontend-visible runtime config. No auth required."""
        from src.queuetip.schema.mutation import _signup_allowlist_required

        return PublicSettingsType(
            signup_allowlist_enforced=_signup_allowlist_required(),
        )

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
        id: strawberry.ID,
    ) -> PlaylistType:
        """Look up a playlist by id. Caller must be a member."""
        ctx = info.context
        if ctx.account is None:
            raise AuthRequiredError("Sign in to look up a playlist by id.")
        playlist = await PlaylistService.get_by_id(int(id))
        await sync_to_async(require_member)(ctx.account, playlist)
        members = await PlaylistService.list_memberships(playlist)
        return PlaylistType.from_model(playlist, members)

    @strawberry.field
    async def playlist_by_invite_token(
        self,
        invite_token: str,
    ) -> PlaylistPreviewType:
        """Look up a playlist preview by invite token. Anonymous-OK.

        Returns only public metadata and members — no engine_settings.
        This is the "preview before joining" experience for invite links.
        """
        playlist = await PlaylistService.get_by_invite_token(invite_token)
        members = await PlaylistService.list_memberships(playlist)
        return PlaylistPreviewType.from_model(playlist, members)

    @strawberry.field
    async def catalog_search(
        self, query: str, limit: int = 10
    ) -> list[CatalogSearchResultType]:
        """Deezer-backed track search, with in-library flagging. No auth required."""
        if not query.strip():
            return []
        limit = max(1, min(50, limit))
        hits = await _catalog_search(query, limit=limit)
        return [
            CatalogSearchResultType(
                deezer_id=hit.provider_id,
                title=hit.name,
                artist=hit.artist_name,
                isrc=getattr(hit, "isrc", None),
                in_library=hit.in_library,
            )
            for hit in hits
        ]

    @strawberry.field
    async def bulk_import_job(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> BulkImportJobType:
        """Look up a bulk-import job by id. Caller must be a playlist member."""
        account = _require_account(info)
        job = await BulkImportService.get(account, int(id))
        return BulkImportJobType.from_model(job)

    @strawberry.field
    async def playlist_contributions(
        self, info: Info[QueuetipContext, None], playlist_id: strawberry.ID
    ) -> list[ContributionType]:
        """Contributions for a playlist, ordered newest-first. Caller must be a member."""
        account = _require_account(info)
        contributions = await ContributionService.list_for_playlist(
            account, int(playlist_id)
        )
        return [
            ContributionType.from_model(c, list(c.votes.all())) for c in contributions
        ]

    @strawberry.field
    async def my_subsonic_connection(
        self, info: Info[QueuetipContext, None]
    ) -> SubsonicConnectionType | None:
        """Return the current user's Subsonic connection if they've added one.
        MVP: one connection per user, so this returns at most a single row."""
        account = _require_account(info)
        conn = await sync_to_async(
            lambda: SubsonicConnection.objects.filter(account=account).first()
        )()
        return SubsonicConnectionType.from_model(conn) if conn else None

    @strawberry.field
    async def my_playlist_sync_targets(
        self, info: Info[QueuetipContext, None], playlist_id: strawberry.ID
    ) -> list[PlaylistExportTargetType]:
        """Return the caller's export targets for this playlist (Spotify,
        Subsonic, future). One row per destination type at most."""
        account = _require_account(info)
        targets = await sync_to_async(
            lambda: list(
                PlaylistExportTarget.objects.filter(
                    account=account, playlist_id=int(playlist_id)
                ).select_related("spotify_link", "subsonic_connection")
            )
        )()
        return [PlaylistExportTargetType.from_model(t) for t in targets]
