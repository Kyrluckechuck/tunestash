"""Permission helpers for Queuetip operations.

Pure functions over (account, playlist) — no async, no GraphQL. Service-layer
callers wrap these in `sync_to_async` like any other ORM call.
"""

from __future__ import annotations

from .models import Account, AuthIdentity, Playlist, PlaylistMembership


def account_email(account: Account | None) -> str | None:
    """The account's magic-link email, or None."""
    if account is None:
        return None
    ident = AuthIdentity.objects.filter(
        account=account, provider=AuthIdentity.PROVIDER_MAGIC_LINK
    ).first()
    return ident.identifier if ident else None


def is_queuetip_admin(account: Account | None) -> bool:
    """True if the account's email is in the queuetip_admin_emails setting.

    Admins can invite new users from the public Queuetip UI. The allowlist of
    admin emails is a DB-backed app setting (empty by default), so it's set
    once from TuneStash's Settings page rather than baked into code.
    """
    from src.app_settings.registry import get_setting

    raw = get_setting("queuetip_admin_emails") or ""
    admins = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if not admins:
        return False
    email = account_email(account)
    return bool(email and email.lower() in admins)


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
