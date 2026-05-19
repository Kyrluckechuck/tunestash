"""Queuetip GraphQL Query type."""

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.models import Account
from queuetip.permissions import require_member
from src.queuetip.resolution.catalog import catalog_search as _catalog_search

from ..context import QueuetipContext
from ..errors import AuthRequiredError, ValidationError
from ..graphql_types import (
    AccountType,
    BulkImportJobType,
    CatalogSearchResultType,
    ExportSnapshotType,
    PlaylistType,
)
from ..services.bulk_import import BulkImportService
from ..services.export import ExportService
from ..services.playlist import PlaylistService


def _require_account(info: Info[QueuetipContext, None]) -> Account:
    ctx = info.context
    if ctx.account is None:
        raise AuthRequiredError("Sign in to perform this action.")
    return ctx.account


async def _load_snapshot_with_tracks(snapshot) -> ExportSnapshotType:
    """Pre-fetch tracks (+song+artist) before composing the GraphQL type."""
    from queuetip.models import ExportSnapshotTrack

    def _load():
        return list(
            ExportSnapshotTrack.objects.filter(snapshot=snapshot)
            .select_related("song", "song__primary_artist")
            .order_by("position")
        )

    tracks = await sync_to_async(_load)()
    return ExportSnapshotType.from_model(snapshot, tracks)


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
    async def export(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> ExportSnapshotType:
        """Fetch a single ExportSnapshot. Caller must be a playlist member."""
        account = _require_account(info)
        snapshot = await ExportService.get(account, int(id))
        return await _load_snapshot_with_tracks(snapshot)

    @strawberry.field
    async def my_playlist_exports(
        self, info: Info[QueuetipContext, None], playlist_id: strawberry.ID
    ) -> list[ExportSnapshotType]:
        """List a playlist's exports (newest first). Caller must be a member."""
        account = _require_account(info)
        snapshots = await ExportService.list_for_playlist(account, int(playlist_id))
        result: list[ExportSnapshotType] = []
        for s in snapshots:
            result.append(await _load_snapshot_with_tracks(s))
        return result
