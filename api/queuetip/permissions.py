"""Permission helpers for Queuetip operations.

Pure functions over (account, playlist) — no async, no GraphQL. Service-layer
callers wrap these in `sync_to_async` like any other ORM call.
"""

from __future__ import annotations

from .models import Account, Playlist, PlaylistMembership


class PermissionDeniedError(Exception):
    """Raised when an account lacks the required role for an action."""


def get_membership(
    account: Account | None, playlist: Playlist | None
) -> PlaylistMembership | None:
    """Return the account's membership in the playlist, or None."""
    if account is None or playlist is None:
        return None
    return PlaylistMembership.objects.filter(playlist=playlist, account=account).first()


def require_member(account: Account | None, playlist: Playlist) -> PlaylistMembership:
    """Return the membership, or raise PermissionDeniedError."""
    membership = get_membership(account, playlist)
    if membership is None:
        raise PermissionDeniedError("You must be a member of this playlist.")
    return membership


def require_owner(account: Account | None, playlist: Playlist) -> PlaylistMembership:
    """Return the membership iff role is owner, else raise PermissionDeniedError."""
    membership = require_member(account, playlist)
    if membership.role != PlaylistMembership.ROLE_OWNER:
        raise PermissionDeniedError("Only the owner can perform this action.")
    return membership
