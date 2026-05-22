"""Queuetip GraphQL Mutation type."""

import datetime
import os
import re
from typing import cast

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

import strawberry
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.models import (
    Account,
    AuthIdentity,
    Contribution,
    ExternalServiceLink,
    MagicLinkRequestLog,
    Playlist,
    PlaylistExportTarget,
    PlaylistMembership,
    SubsonicConnection,
    Vote,
)

from ..auth import make_magic_link_token
from ..client_ip import get_client_ip
from ..context import QueuetipContext
from ..crypto import encrypt_secret
from ..email import send_magic_link_email
from ..errors import AuthRequiredError, NotFoundError, ValidationError
from ..graphql_types import (
    BulkImportJobType,
    ContributionResult,
    ContributionType,
    EngineSettingsInput,
    PlaylistExportTargetType,
    PlaylistType,
    SubsonicConnectionType,
)
from ..services.bulk_import import BulkImportService
from ..services.contribution import ContributionService
from ..services.membership import MembershipService
from ..services.playlist import PlaylistService
from ..services.vote import VoteService
from ..subsonic import SubsonicAuthError, SubsonicClient, SubsonicError

# Pragmatic email shape check — rejects obvious garbage before we create a row
# or hand the address to the mail backend. Not a full RFC 5322 validation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Matches Account.display_name max_length; a longer value would raise a
# DataError from the DB layer rather than a friendly result.
_DISPLAY_NAME_MAX = 120

# Sliding-window rate limits for magic-link requests.
# Per-email: 5 requests per 5 minutes. Per-IP: 100 per hour.
# The per-IP cap is intentionally high because automated test clients all
# share the same emulated IP address ("testclient").
_ML_PER_EMAIL_LIMIT = 5
_ML_PER_EMAIL_WINDOW = datetime.timedelta(minutes=5)
_ML_PER_IP_LIMIT = 100
_ML_PER_IP_WINDOW = datetime.timedelta(hours=1)

# Generous per-admin cap on inviteToQueuetip — enough to bound a compromised
# session without blocking legitimate manual onboarding.
_ADMIN_INVITES_PER_HOUR = 30


def _check_magic_link_throttle(email: str, ip: str) -> bool:
    """Return True if this request is within rate limits and record it.

    Returns False (without recording) if either the per-email or per-IP
    limit has been exceeded within its sliding window.
    """
    now = timezone.now()
    email_since = now - _ML_PER_EMAIL_WINDOW
    ip_since = now - _ML_PER_IP_WINDOW

    if (
        MagicLinkRequestLog.objects.filter(
            identifier=email, created_at__gte=email_since
        ).count()
        >= _ML_PER_EMAIL_LIMIT
    ):
        return False

    if (
        MagicLinkRequestLog.objects.filter(
            ip_address=ip, created_at__gte=ip_since
        ).count()
        >= _ML_PER_IP_LIMIT
    ):
        return False

    MagicLinkRequestLog.objects.create(identifier=email, ip_address=ip)
    return True


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
class SignOutEverywhereResult:
    """Outcome of the signOutEverywhere mutation."""

    success: bool


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


def _signup_allowlist_required() -> bool:
    """True iff the sign-up allowlist gate is enforced.

    Reads the QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST env var directly because
    dynaconf's HookableSettings wrapper doesn't expose module-level settings
    added after its instantiation — so `dj_settings.QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST`
    raises AttributeError and the env-var escape hatch would silently never work.
    Fail-safe default: enforce when the env var isn't set.
    """
    return os.getenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "true").lower() != "false"


def _is_email_allowed(email: str) -> bool:
    """Return True if `email` may create a new Queuetip account.

    When the allowlist is disabled via QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST=False,
    all emails are permitted. Otherwise only emails with a matching row in
    QueuetipSignupAllowlist pass. Existing accounts bypass this entirely because
    the identity lookup short-circuits before this is called.
    """
    if not _signup_allowlist_required():
        return True
    from queuetip.models import QueuetipSignupAllowlist  # local import avoids circular

    return QueuetipSignupAllowlist.objects.filter(email=email).exists()


async def _request_magic_link(  # pylint: disable=too-many-return-statements
    email: str, display_name: str | None, ip: str = "unknown"
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

    allowed = await sync_to_async(_check_magic_link_throttle)(email, ip)
    if not allowed:
        return RequestMagicLinkResult(
            sent=False, message="Too many requests. Try again later."
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
            # Don't reveal whether the email is registered: an attacker could
            # enumerate accounts by observing which addresses return "no account"
            # vs "check your email". Both paths return a consistent message.
            return RequestMagicLinkResult(
                sent=False,
                message="If that email is registered, a sign-in link has been sent. "
                "If you're new, provide a display name to sign up.",
            )
        if len(clean_name) > _DISPLAY_NAME_MAX:
            return RequestMagicLinkResult(
                sent=False,
                message=f"Display name is too long "
                f"(max {_DISPLAY_NAME_MAX} characters).",
            )

        allowed = await sync_to_async(_is_email_allowed)(email)
        if not allowed:
            # Neutral message — indistinguishable from the unknown-email branch so
            # observers cannot determine whether an email is allowlisted or not.
            return RequestMagicLinkResult(
                sent=False,
                message="If that email is registered, a sign-in link has been sent. "
                "If you're new and your email is approved, you'll get a link too.",
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
            account = cast(Account, identity.account)
    else:
        account = cast(Account, identity.account)

    assert account is not None
    token = make_magic_link_token(account.id)
    await sync_to_async(send_magic_link_email)(email, token)
    return RequestMagicLinkResult(
        sent=True, message="Check your email for a sign-in link."
    )


@strawberry.type
class Mutation:  # pylint: disable=too-many-public-methods
    """Root mutation for the Queuetip public API.

    A GraphQL root type naturally accumulates many resolver methods (one per
    mutation); the public-method cap doesn't apply meaningfully here.
    """

    @strawberry.mutation
    async def request_magic_link(
        self,
        info: Info[QueuetipContext, None],
        email: str,
        display_name: str | None = None,
    ) -> RequestMagicLinkResult:
        """Request a magic-link sign-in email. Creates an account if needed."""
        req = info.context.request
        ip = get_client_ip(req) if req is not None else "unknown"
        return await _request_magic_link(email, display_name, ip=ip)

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
    async def invite_to_queuetip(
        self, info: Info[QueuetipContext, None], email: str
    ) -> RequestMagicLinkResult:
        """Admin-only: allowlist an email and email them a sign-up invite.

        Lets a Queuetip admin (per the queuetip_admin_emails setting) onboard
        new users from the public UI, without needing TuneStash admin access.
        """
        from django.conf import settings as dj_settings

        from queuetip.models import QueuetipSignupAllowlist
        from queuetip.permissions import PermissionDeniedError, is_queuetip_admin
        from src.services import mail

        account = _require_account(info)
        address = (email or "").strip().lower()

        def _do() -> RequestMagicLinkResult:
            if not is_queuetip_admin(account):
                raise PermissionDeniedError("Admin access required.")
            if not _EMAIL_RE.match(address):
                return RequestMagicLinkResult(
                    sent=False, message="Enter a valid email address."
                )
            # Per-admin sliding-window rate limit: bounds runaway abuse from a
            # compromised admin session without blocking legitimate manual use.
            from datetime import timedelta

            from django.utils import timezone

            recent = QueuetipSignupAllowlist.objects.filter(
                invited_by=account,
                added_at__gte=timezone.now() - timedelta(hours=1),
            ).count()
            if recent >= _ADMIN_INVITES_PER_HOUR:
                return RequestMagicLinkResult(
                    sent=False,
                    message="Too many invites in the last hour. Try again later.",
                )
            QueuetipSignupAllowlist.objects.get_or_create(
                email=address,
                defaults={
                    "note": f"Invited by {account.display_name}",
                    "invited_by": account,
                },
            )
            signup_url = getattr(
                dj_settings, "QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001"
            ).rstrip("/")
            try:
                mail.send_message(
                    subject="You're invited to Queuetip",
                    body=(
                        "You've been invited to Queuetip.\n\n"
                        f"Sign up with this email ({address}) here:\n{signup_url}\n"
                    ),
                    to=address,
                    html_body=mail.render_email(
                        eyebrow="Queuetip",
                        heading="You're invited to Queuetip",
                        paragraphs=[
                            "You've been invited to Queuetip — collaborative "
                            "playlists you build together.",
                            f"Sign up with this email ({address}) to get started.",
                        ],
                        button=("Sign up", signup_url),
                    ),
                )
            except Exception as exc:  # pylint: disable=broad-except
                return RequestMagicLinkResult(
                    sent=True,
                    message=(
                        f"{address} allowlisted, but the invite email failed "
                        f"({exc}). Share {signup_url} with them directly."
                    ),
                )
            return RequestMagicLinkResult(sent=True, message=f"Invited {address}.")

        return await sync_to_async(_do)()

    @strawberry.mutation
    async def remove_queuetip_invite(
        self, info: Info[QueuetipContext, None], email: str
    ) -> RequestMagicLinkResult:
        """Admin-only: remove an email from the Queuetip signup allowlist."""
        from queuetip.models import QueuetipSignupAllowlist
        from queuetip.permissions import PermissionDeniedError, is_queuetip_admin

        account = _require_account(info)
        address = (email or "").strip().lower()

        def _do() -> RequestMagicLinkResult:
            if not is_queuetip_admin(account):
                raise PermissionDeniedError("Admin access required.")
            deleted, _ = QueuetipSignupAllowlist.objects.filter(email=address).delete()
            if deleted:
                return RequestMagicLinkResult(
                    sent=True, message=f"Removed {address} from the allowlist."
                )
            return RequestMagicLinkResult(
                sent=False, message=f"{address} was not on the allowlist."
            )

        return await sync_to_async(_do)()

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
    async def sign_out_everywhere(
        self, info: Info[QueuetipContext, None]
    ) -> SignOutEverywhereResult:
        """Invalidate all active sessions for the current account by bumping the
        session epoch. The current session is immediately invalidated — subsequent
        requests with the same cookie will be treated as anonymous.
        """
        account = _require_account(info)

        def _bump_epoch() -> None:
            Account.objects.filter(id=account.id).update(
                session_epoch=F("session_epoch") + 1
            )

        await sync_to_async(_bump_epoch)()
        return SignOutEverywhereResult(success=True)

    # ── Subsonic connection management ──────────────────────────────────────

    @strawberry.mutation
    async def add_subsonic_connection(
        self,
        info: Info[QueuetipContext, None],
        label: str,
        server_url: str,
        username: str,
        password: str,
        auth_mode: str = SubsonicConnection.AUTH_PASSWORD,
    ) -> SubsonicConnectionType:
        """Save a Subsonic-compatible server connection for the current user
        and immediately probe it (ping + OpenSubsonic extension detection).

        `auth_mode` is "password" (classic Subsonic, salted-MD5) or
        "api_key" (OpenSubsonic — Navidrome 0.50+ etc.). In API-key mode the
        `password` parameter carries the API key generated in Navidrome's UI.
        MVP: one connection per account. Adding a second replaces the first
        — destructive intent must be explicit, so this is enforced by the
        unique_together constraint rather than silent overwrite.
        """
        account = _require_account(info)
        conn = await sync_to_async(_create_subsonic_connection)(
            account, label, server_url, username, password, auth_mode
        )
        # Probe synchronously so the user sees status immediately. Failures
        # don't roll back the row — they're recorded for diagnosis.
        await sync_to_async(_probe_subsonic_connection)(conn, password)
        return SubsonicConnectionType.from_model(conn)

    @strawberry.mutation
    async def update_subsonic_connection(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
        label: str | None = None,
        server_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auth_mode: str | None = None,
    ) -> SubsonicConnectionType:
        """Patch fields on an existing connection. Pass `password` only when
        rotating credentials — null leaves the stored encrypted secret alone.
        Pass `auth_mode` to switch between password and API-key auth (the
        caller MUST also pass the new credential matching the new mode).
        Re-probes after any change."""
        account = _require_account(info)
        conn = await sync_to_async(_update_subsonic_connection)(
            account, int(id), label, server_url, username, password, auth_mode
        )
        await sync_to_async(_probe_subsonic_connection)(conn, password)
        return SubsonicConnectionType.from_model(conn)

    @strawberry.mutation
    async def remove_subsonic_connection(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
    ) -> bool:
        """Delete the connection. Cascades to any sync targets pointing at it
        (they become orphaned and stop syncing) — the user removes targets
        first if they want to clean up remote playlists too."""
        account = _require_account(info)

        def _delete() -> int:
            return SubsonicConnection.objects.filter(
                id=int(id), account=account
            ).delete()[0]

        deleted = await sync_to_async(_delete)()
        if not deleted:
            raise NotFoundError(f"Subsonic connection {id} not found")
        return True

    @strawberry.mutation
    async def test_subsonic_connection(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
    ) -> SubsonicConnectionType:
        """Re-run the verification probe against the stored credentials.
        Refreshes verification_status, OpenSubsonic extensions, and any
        verification_error."""
        account = _require_account(info)
        conn = await sync_to_async(
            lambda: SubsonicConnection.objects.filter(
                id=int(id), account=account
            ).first()
        )()
        if conn is None:
            raise NotFoundError(f"Subsonic connection {id} not found")
        await sync_to_async(_probe_subsonic_connection)(conn, None)
        return SubsonicConnectionType.from_model(conn)

    # ── Export targets (Subsonic + future) ──────────────────────────────────

    @strawberry.mutation
    async def create_subsonic_sync_target(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        connection_id: strawberry.ID,
    ) -> PlaylistExportTargetType:
        """Register a Subsonic destination for a playlist. Idempotent —
        re-calling returns the existing target rather than erroring on the
        unique constraint.

        Caller must be a member of the playlist. Each user has at most ONE
        Subsonic target per playlist (per Lifecycle Principle 1). Pushing is
        a separate, manual action (syncTargetNow / 'Reshuffle & push').
        """
        account = _require_account(info)
        target = await sync_to_async(_create_subsonic_sync_target)(
            account, int(playlist_id), int(connection_id)
        )
        return PlaylistExportTargetType.from_model(target)

    @strawberry.mutation
    async def create_spotify_export_target(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
    ) -> PlaylistExportTargetType:
        """Register a Spotify destination for a playlist, using the caller's
        linked Spotify account. Idempotent. Pushing is a separate manual
        action (syncTargetNow / 'Reshuffle & push')."""
        account = _require_account(info)
        target = await sync_to_async(_create_spotify_export_target)(
            account, int(playlist_id)
        )
        return PlaylistExportTargetType.from_model(target)

    @strawberry.mutation
    async def remove_sync_target(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
        delete_remote: bool = False,
    ) -> bool:
        """Stop syncing this playlist. Defaults to leaving the remote
        playlist alone (just stops queuetip from updating it). If
        delete_remote=true AND the target is a Subsonic destination, also
        delete the playlist on the user's Subsonic server."""
        account = _require_account(info)
        await sync_to_async(_remove_target)(account, int(id), delete_remote)
        return True

    @strawberry.mutation
    async def sync_target_now(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
    ) -> PlaylistExportTargetType:
        """Trigger a sync run immediately and wait for the result. Used by
        the 'Sync now' UI button. Long-running tasks return after the run."""
        account = _require_account(info)
        target = await sync_to_async(_resolve_owned_target)(account, int(id))
        # Run synchronously so the GraphQL response contains the post-sync
        # state — better UX than a fire-and-forget task and a poll loop.
        if target.destination_type == PlaylistExportTarget.DEST_SUBSONIC:
            from ..services.subsonic_sync import SubsonicSyncError, sync_subsonic_target

            try:
                await sync_to_async(sync_subsonic_target)(target.id)
            except SubsonicSyncError as exc:
                raise ValidationError(str(exc)) from exc
        elif target.destination_type == PlaylistExportTarget.DEST_SPOTIFY:
            from ..services.spotify_export import (
                RemotePlaylistDeletedError,
                SpotifyExportError,
                SpotifyExportService,
            )

            try:
                await SpotifyExportService.sync_target(target.id)
            except RemotePlaylistDeletedError as exc:
                raise ValidationError(str(exc)) from exc
            except SpotifyExportError as exc:
                raise ValidationError(str(exc)) from exc
        else:
            raise ValidationError(
                f"Unknown destination_type: {target.destination_type}"
            )

        # Refresh after the sync ran so we return post-sync state.
        target = await sync_to_async(_resolve_owned_target)(account, int(id))
        return PlaylistExportTargetType.from_model(target)

    @strawberry.mutation
    async def recreate_sync_target_remote(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
    ) -> PlaylistExportTargetType:
        """Recover from STATUS_REMOTE_DELETED by clearing remote_playlist_id
        and triggering a fresh create. The explicit-intent escape hatch
        required by Lifecycle Principle 2."""
        account = _require_account(info)

        def _clear_and_sync() -> PlaylistExportTarget:
            target = _resolve_owned_target(account, int(id))
            target.remote_playlist_id = ""
            target.last_sync_status = PlaylistExportTarget.STATUS_PENDING
            target.last_error = ""
            target.save(
                update_fields=[
                    "remote_playlist_id",
                    "last_sync_status",
                    "last_error",
                ]
            )
            return target

        target = await sync_to_async(_clear_and_sync)()

        if target.destination_type == PlaylistExportTarget.DEST_SUBSONIC:
            from ..services.subsonic_sync import SubsonicSyncError, sync_subsonic_target

            try:
                await sync_to_async(sync_subsonic_target)(target.id)
            except SubsonicSyncError as exc:
                raise ValidationError(str(exc)) from exc
        elif target.destination_type == PlaylistExportTarget.DEST_SPOTIFY:
            from ..services.spotify_export import (
                SpotifyExportError,
                SpotifyExportService,
            )

            try:
                await SpotifyExportService.sync_target(target.id)
            except SpotifyExportError as exc:
                raise ValidationError(str(exc)) from exc

        target = await sync_to_async(_resolve_owned_target)(account, int(id))
        return PlaylistExportTargetType.from_model(target)


# ── Helpers for Subsonic mutations (sync) ──────────────────────────────────


def _create_subsonic_connection(
    account: Account,
    label: str,
    server_url: str,
    username: str,
    password: str,
    auth_mode: str = SubsonicConnection.AUTH_PASSWORD,
) -> SubsonicConnection:
    """Persist a new SubsonicConnection with the secret Fernet-encrypted."""
    if not server_url.strip():
        raise ValidationError("server_url is required")
    if not username.strip() and auth_mode == SubsonicConnection.AUTH_PASSWORD:
        # API-key auth in OpenSubsonic identifies the user from the key alone,
        # so username can be empty for that mode. For password auth we need it.
        raise ValidationError("username is required for password auth")
    if not password:
        raise ValidationError("password (or API key) is required")
    if auth_mode not in (
        SubsonicConnection.AUTH_PASSWORD,
        SubsonicConnection.AUTH_API_KEY,
    ):
        raise ValidationError(f"Invalid auth_mode: {auth_mode!r}")
    # Reject a second connection rather than replacing it. Deleting the prior
    # row would CASCADE to its PlaylistExportTargets (on_delete=CASCADE),
    # silently destroying the user's sync targets and orphaning their remote
    # playlists. Editing an existing connection goes through
    # updateSubsonicConnection, which the settings UI uses when one exists.
    if SubsonicConnection.objects.filter(account=account).exists():
        raise ValidationError(
            "A Subsonic connection already exists for this account. "
            "Update it instead of adding a new one."
        )
    return SubsonicConnection.objects.create(
        account=account,
        label=label.strip() or "Subsonic",
        server_url=server_url.strip(),
        username=username.strip(),
        password_encrypted=encrypt_secret(password),
        auth_mode=auth_mode,
    )


def _update_subsonic_connection(
    account: Account,
    conn_id: int,
    label: str | None,
    server_url: str | None,
    username: str | None,
    password: str | None,
    auth_mode: str | None,
) -> SubsonicConnection:
    conn = SubsonicConnection.objects.filter(id=conn_id, account=account).first()
    if conn is None:
        raise NotFoundError(f"Subsonic connection {conn_id} not found")
    if label is not None:
        conn.label = label.strip() or conn.label
    if server_url is not None:
        conn.server_url = server_url.strip() or conn.server_url
    if username is not None:
        conn.username = username.strip() or conn.username
    if password:
        conn.password_encrypted = encrypt_secret(password)
    if auth_mode is not None:
        if auth_mode not in (
            SubsonicConnection.AUTH_PASSWORD,
            SubsonicConnection.AUTH_API_KEY,
        ):
            raise ValidationError(f"Invalid auth_mode: {auth_mode!r}")
        conn.auth_mode = auth_mode
    conn.save()
    return conn


def _probe_subsonic_connection(
    conn: SubsonicConnection, plaintext_password: str | None
) -> None:
    """Ping + OpenSubsonic capability probe. Writes results onto the row.
    Never raises — failures are recorded as verification_status='failed'."""
    from ..crypto import CryptoError, decrypt_secret

    if plaintext_password is None:
        try:
            plaintext_password = decrypt_secret(conn.password_encrypted)
        except CryptoError as exc:
            conn.verification_status = SubsonicConnection.STATUS_FAILED
            conn.verification_error = f"Could not decrypt stored password: {exc}"
            conn.last_verified_at = timezone.now()
            conn.save(
                update_fields=[
                    "verification_status",
                    "verification_error",
                    "last_verified_at",
                ]
            )
            return

    client = SubsonicClient(
        server_url=conn.server_url,
        username=conn.username,
        password=plaintext_password,
        auth_mode=conn.auth_mode,
    )
    try:
        client.ping()
    except SubsonicAuthError as exc:
        conn.verification_status = SubsonicConnection.STATUS_FAILED
        conn.verification_error = f"Authentication failed: {exc}"
    except SubsonicError as exc:
        conn.verification_status = SubsonicConnection.STATUS_FAILED
        conn.verification_error = f"Connection failed: {exc}"
    else:
        conn.verification_status = SubsonicConnection.STATUS_OK
        conn.verification_error = ""
        # Best-effort capability probe. Empty list = classic Subsonic or
        # endpoint not exposed; neither blocks the connection.
        try:
            conn.opensubsonic_extensions = client.get_open_subsonic_extensions()
        except Exception:  # pylint: disable=broad-except
            conn.opensubsonic_extensions = []
    conn.last_verified_at = timezone.now()
    conn.save(
        update_fields=[
            "verification_status",
            "verification_error",
            "opensubsonic_extensions",
            "last_verified_at",
        ]
    )


def _create_subsonic_sync_target(
    account: Account,
    playlist_id: int,
    connection_id: int,
) -> PlaylistExportTarget:
    """Create-or-return the per-(account, playlist, subsonic) target.

    Idempotency: subsequent calls return the existing row rather than
    erroring on the unique constraint.
    """
    membership = PlaylistMembership.objects.filter(
        account=account, playlist_id=playlist_id
    ).first()
    if membership is None:
        raise NotFoundError(f"Playlist {playlist_id} not found")

    connection = SubsonicConnection.objects.filter(
        id=connection_id, account=account
    ).first()
    if connection is None:
        raise NotFoundError(f"Subsonic connection {connection_id} not found")

    target, _ = PlaylistExportTarget.objects.get_or_create(
        account=account,
        playlist_id=playlist_id,
        destination_type=PlaylistExportTarget.DEST_SUBSONIC,
        defaults={"subsonic_connection": connection},
    )
    # If the user changed which Subsonic server they want to push to, swap
    # the FK. This is rare but harmless.
    if target.subsonic_connection_id != connection.id:
        target.subsonic_connection = connection
        target.save(update_fields=["subsonic_connection"])
    # Re-fetch with the credential relations prefetched — PlaylistExportTargetType
    # .from_model traverses them, and the async resolver can't lazy-load.
    return _select_related_target(target.id)


def _create_spotify_export_target(
    account: Account,
    playlist_id: int,
) -> PlaylistExportTarget:
    """Create-or-return the per-(account, playlist, spotify) target, using the
    caller's linked Spotify account. Idempotent."""
    membership = PlaylistMembership.objects.filter(
        account=account, playlist_id=playlist_id
    ).first()
    if membership is None:
        raise NotFoundError(f"Playlist {playlist_id} not found")

    link = ExternalServiceLink.objects.filter(
        account=account, service=ExternalServiceLink.SERVICE_SPOTIFY
    ).first()
    if link is None:
        raise NotFoundError("Spotify is not linked. Connect Spotify in settings first.")

    target, _ = PlaylistExportTarget.objects.get_or_create(
        account=account,
        playlist_id=playlist_id,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        defaults={"spotify_link": link},
    )
    if target.spotify_link_id != link.id:
        target.spotify_link = link
        target.save(update_fields=["spotify_link"])
    return _select_related_target(target.id)


def _select_related_target(target_id: int) -> PlaylistExportTarget:
    """Fetch a target with both credential FKs prefetched so converting it to
    the GraphQL type in an async resolver doesn't trigger a lazy DB load."""
    return PlaylistExportTarget.objects.select_related(
        "spotify_link", "subsonic_connection"
    ).get(id=target_id)


def _remove_target(account: Account, target_id: int, delete_remote: bool) -> None:
    target = _resolve_owned_target(account, target_id)
    if (
        delete_remote
        and target.destination_type == PlaylistExportTarget.DEST_SUBSONIC
        and target.remote_playlist_id
        and target.subsonic_connection_id
    ):
        from ..crypto import CryptoError, decrypt_secret

        conn = cast(SubsonicConnection, target.subsonic_connection)
        try:
            password = decrypt_secret(conn.password_encrypted)
            client = SubsonicClient(
                server_url=conn.server_url,
                username=conn.username,
                password=password,
                auth_mode=conn.auth_mode,
            )
            client.delete_playlist(target.remote_playlist_id)
        except (CryptoError, SubsonicError):
            # Best-effort cleanup — proceed to delete the local row even if
            # the remote delete failed (user can clean it up manually).
            pass
    target.delete()


def _resolve_owned_target(account: Account, target_id: int) -> PlaylistExportTarget:
    target = (
        PlaylistExportTarget.objects.filter(id=target_id, account=account)
        .select_related("playlist", "spotify_link", "subsonic_connection")
        .first()
    )
    if target is None:
        raise NotFoundError(f"Sync target {target_id} not found")
    return target
