"""Async service for playlist CRUD + invite-token regeneration."""

from __future__ import annotations

from django.db import transaction

from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership, generate_invite_token
from queuetip.permissions import require_owner

from ..errors import NotFoundError

_UNSET = object()


class PlaylistService:
    """Stateless namespace for playlist operations. All methods are async."""

    @staticmethod
    async def create(owner: Account, name: str, description: str) -> Playlist:
        """Create a playlist and the owner membership in one transaction."""

        def _create() -> Playlist:
            with transaction.atomic():
                playlist = Playlist.objects.create(
                    name=name.strip(), description=description, created_by=owner
                )
                PlaylistMembership.objects.create(
                    playlist=playlist,
                    account=owner,
                    role=PlaylistMembership.ROLE_OWNER,
                )
            return playlist

        return await sync_to_async(_create)()

    @staticmethod
    async def get_by_id(playlist_id: int) -> Playlist:
        playlist = await sync_to_async(
            lambda: Playlist.objects.select_related("created_by")
            .filter(id=playlist_id)
            .first()
        )()
        if playlist is None:
            raise NotFoundError(f"No playlist with id={playlist_id}")
        return playlist

    @staticmethod
    async def get_by_invite_token(token: str) -> Playlist:
        playlist = await sync_to_async(
            lambda: Playlist.objects.select_related("created_by")
            .filter(invite_token=token)
            .first()
        )()
        if playlist is None:
            raise NotFoundError("No playlist for that invite token.")
        return playlist

    @staticmethod
    async def list_for_account(account: Account) -> list[Playlist]:
        return await sync_to_async(
            lambda: list(
                Playlist.objects.filter(memberships__account=account)
                .select_related("created_by")
                .order_by("-created_at")
                .distinct()
            )
        )()

    @staticmethod
    async def list_memberships(playlist: Playlist) -> list[PlaylistMembership]:
        return await sync_to_async(
            lambda: list(
                playlist.memberships.select_related("account").order_by("joined_at")
            )
        )()

    @staticmethod
    async def update_settings(
        account: Account,
        playlist_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        min_size: int | None = None,
        max_size: object = _UNSET,
        t_high: int | None = None,
        t_low: int | None = None,
        base: float | None = None,
        p_floor: float | None = None,
    ) -> Playlist:
        """Owner-only partial update. `max_size` uses sentinel to allow set-null."""

        def _update() -> Playlist:
            playlist = (
                Playlist.objects.select_related("created_by")
                .filter(id=playlist_id)
                .first()
            )
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            if name is not None:
                playlist.name = name.strip()
            if description is not None:
                playlist.description = description
            if min_size is not None:
                playlist.min_size = min_size
            if max_size is not _UNSET:
                playlist.max_size = max_size  # may be None
            if t_high is not None:
                playlist.t_high = t_high
            if t_low is not None:
                playlist.t_low = t_low
            if base is not None:
                playlist.base = base
            if p_floor is not None:
                playlist.p_floor = p_floor
            playlist.save()
            return playlist

        return await sync_to_async(_update)()

    @staticmethod
    async def regenerate_invite_token(account: Account, playlist_id: int) -> str:
        """Owner-only. Generates a new token and returns it."""

        def _regen() -> str:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            playlist.invite_token = generate_invite_token()
            playlist.save(update_fields=["invite_token"])
            return playlist.invite_token

        return await sync_to_async(_regen)()

    @staticmethod
    async def delete(account: Account, playlist_id: int) -> None:
        """Owner-only. Cascades memberships/contributions/votes via FK CASCADE."""

        def _delete() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            playlist.delete()

        await sync_to_async(_delete)()
