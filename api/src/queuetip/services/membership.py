"""Async service for playlist membership: join, leave, kick, promote."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import PermissionDeniedError, require_member, require_owner

from ..errors import NotFoundError


class MembershipService:
    """Stateless namespace for membership operations."""

    @staticmethod
    async def join(account: Account, invite_token: str) -> PlaylistMembership:
        """Add `account` to the playlist named by `invite_token` as a member.

        Idempotent — joining a playlist you're already in returns the existing
        membership.
        """

        def _join() -> PlaylistMembership:
            playlist = Playlist.objects.filter(invite_token=invite_token).first()
            if playlist is None:
                raise NotFoundError("No playlist for that invite token.")
            try:
                with transaction.atomic():
                    return PlaylistMembership.objects.create(
                        playlist=playlist,
                        account=account,
                        role=PlaylistMembership.ROLE_MEMBER,
                    )
            except IntegrityError:
                # Already a member — return the existing row.
                return PlaylistMembership.objects.get(
                    playlist=playlist, account=account
                )

        return await sync_to_async(_join)()

    @staticmethod
    async def leave(account: Account, playlist_id: int) -> None:
        """Remove the caller's own membership.

        An owner cannot leave a playlist that has other members — they must
        kick everyone else or promote another owner first. (Sole-owner self-
        leave is allowed and falls through to cascade-delete via Playlist
        deletion in the design; for v1 we simply require the owner to
        delete the playlist instead.)
        """

        def _leave() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            membership = require_member(account, playlist)
            if membership.role == PlaylistMembership.ROLE_OWNER:
                others = (
                    PlaylistMembership.objects.filter(playlist=playlist)
                    .exclude(account=account)
                    .exists()
                )
                if others:
                    raise PermissionDeniedError(
                        "Owners cannot leave a playlist with other members. "
                        "Promote another owner or delete the playlist."
                    )
            membership.delete()

        await sync_to_async(_leave)()

    @staticmethod
    async def kick(actor: Account, playlist_id: int, target_account_id: int) -> None:
        """Owner-only. Removes the target's membership. Cannot kick yourself."""

        def _kick() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(actor, playlist)
            if target_account_id == actor.id:
                raise PermissionDeniedError(
                    "Use 'leave' to remove yourself; you cannot kick yourself."
                )
            target_membership = PlaylistMembership.objects.filter(
                playlist=playlist, account_id=target_account_id
            ).first()
            if target_membership is None:
                raise NotFoundError("That account is not a member.")
            target_membership.delete()

        await sync_to_async(_kick)()

    @staticmethod
    async def promote(
        actor: Account, playlist_id: int, target_account_id: int
    ) -> PlaylistMembership:
        """Owner-only. Promotes a member to owner role (co-owner)."""

        def _promote() -> PlaylistMembership:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(actor, playlist)
            target_membership = PlaylistMembership.objects.filter(
                playlist=playlist, account_id=target_account_id
            ).first()
            if target_membership is None:
                raise NotFoundError("That account is not a member.")
            target_membership.role = PlaylistMembership.ROLE_OWNER
            target_membership.save(update_fields=["role"])
            return target_membership

        return await sync_to_async(_promote)()
