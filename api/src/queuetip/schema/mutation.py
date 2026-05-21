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
    ExportSnapshot,
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
    ExportOptionsInput,
    ExportSnapshotType,
    PlaylistExportTargetType,
    PlaylistType,
    SpotifyExportResultType,
    SubsonicConnectionType,
)
from ..services.bulk_import import BulkImportService
from ..services.contribution import ContributionService
from ..services.export import ExportService
from ..services.membership import MembershipService
from ..services.playlist import PlaylistService
from ..services.spotify_export import SpotifyExportService
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


async def _load_snapshot_with_tracks(snapshot: ExportSnapshot) -> "ExportSnapshotType":
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
class Mutation:
    """Root mutation for the Queuetip public API."""

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

    @strawberry.mutation
    async def export_to_spotify(
        self,
        info: Info[QueuetipContext, None],
        snapshot_id: strawberry.ID,
        playlist_name: str | None = None,
        force_recreate: bool = False,
    ) -> SpotifyExportResultType:
        """Sync the queuetip playlist behind this snapshot to its Spotify
        counterpart on the caller's account.

        First call creates a Spotify playlist; subsequent calls update the
        same playlist in place (no duplicate timestamped copies). If the user
        deletes the Spotify playlist, the next call raises an error and the
        UI offers a "Recreate on Spotify" action which re-calls with
        ``forceRecreate: true``.
        """
        account = _require_account(info)
        result = await SpotifyExportService.export(
            account,
            str(snapshot_id),
            playlist_name=playlist_name,
            force_recreate=force_recreate,
        )
        return SpotifyExportResultType(
            spotify_playlist_url=result.spotify_playlist_url,
            added_count=result.added_count,
            skipped_count=result.skipped_count,
            skipped_titles=result.skipped_titles,
            created_new=result.created_new,
        )

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
    ) -> SubsonicConnectionType:
        """Save a Subsonic-compatible server connection for the current user
        and immediately probe it (ping + OpenSubsonic extension detection).

        MVP: one connection per account. Adding a second replaces the first
        — destructive intent must be explicit, so this is enforced by the
        unique_together constraint rather than silent overwrite.
        """
        account = _require_account(info)
        conn = await sync_to_async(_create_subsonic_connection)(
            account, label, server_url, username, password
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
    ) -> SubsonicConnectionType:
        """Patch fields on an existing connection. Pass `password` only when
        rotating credentials — null leaves the stored encrypted password
        alone. Re-probes after any change."""
        account = _require_account(info)
        conn = await sync_to_async(_update_subsonic_connection)(
            account, int(id), label, server_url, username, password
        )
        # If they rotated the password we have the plaintext; otherwise we
        # need to decrypt to probe. The probe path handles both.
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
        sync_mode: str = PlaylistExportTarget.SYNC_MANUAL,
    ) -> PlaylistExportTargetType:
        """Opt the user in to syncing a queuetip playlist to their Subsonic
        server. Idempotent — re-calling returns the existing target rather
        than erroring on the unique constraint.

        Caller must be a member of the playlist. Each user has at most ONE
        Subsonic sync target per playlist (per Lifecycle Principle 1).
        """
        account = _require_account(info)
        target = await sync_to_async(_create_subsonic_sync_target)(
            account, int(playlist_id), int(connection_id), sync_mode
        )
        return PlaylistExportTargetType.from_model(target)

    @strawberry.mutation
    async def update_sync_target_mode(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
        sync_mode: str,
    ) -> PlaylistExportTargetType:
        """Toggle a sync target between manual and on_change."""
        account = _require_account(info)
        target = await sync_to_async(_update_target_mode)(account, int(id), sync_mode)
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
        # Run synchronously in a worker thread so the GraphQL response
        # contains the post-sync state — better UX than a fire-and-forget
        # task and a poll loop.
        if target.destination_type == PlaylistExportTarget.DEST_SUBSONIC:
            from ..services.subsonic_sync import (
                SubsonicSyncError,
                sync_subsonic_target,
            )

            try:
                await sync_to_async(sync_subsonic_target)(target.id)
            except SubsonicSyncError as exc:
                # Already recorded on the target; surface the message.
                raise ValidationError(str(exc)) from exc
            # Refresh after the sync ran.
            target = await sync_to_async(_resolve_owned_target)(account, int(id))
        else:
            raise ValidationError(
                "syncTargetNow is only wired for Subsonic targets in this release. "
                "Use exportToSpotify for Spotify exports."
            )
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
            from ..services.subsonic_sync import (
                SubsonicSyncError,
                sync_subsonic_target,
            )

            try:
                await sync_to_async(sync_subsonic_target)(target.id)
            except SubsonicSyncError as exc:
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
) -> SubsonicConnection:
    """Persist a new SubsonicConnection with the password encrypted."""
    if not server_url.strip():
        raise ValidationError("server_url is required")
    if not username.strip():
        raise ValidationError("username is required")
    if not password:
        raise ValidationError("password is required")
    # Hard-replace any prior connection — the model is unique_together on
    # account, so a second add must clobber. Doing this explicitly produces
    # a clearer behaviour than relying on the IntegrityError path.
    SubsonicConnection.objects.filter(account=account).delete()
    return SubsonicConnection.objects.create(
        account=account,
        label=label.strip() or "Subsonic",
        server_url=server_url.strip(),
        username=username.strip(),
        password_encrypted=encrypt_secret(password),
    )


def _update_subsonic_connection(
    account: Account,
    conn_id: int,
    label: str | None,
    server_url: str | None,
    username: str | None,
    password: str | None,
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
    sync_mode: str,
) -> PlaylistExportTarget:
    """Create-or-return the per-(account, playlist, subsonic) sync target.

    Idempotency: subsequent calls return the existing row rather than
    erroring. The sync_mode argument is honoured only on the first call;
    use updateSyncTargetMode to change it later.
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

    if sync_mode not in (
        PlaylistExportTarget.SYNC_MANUAL,
        PlaylistExportTarget.SYNC_ON_CHANGE,
    ):
        raise ValidationError(f"Invalid sync_mode: {sync_mode!r}")

    target, _ = PlaylistExportTarget.objects.get_or_create(
        account=account,
        playlist_id=playlist_id,
        destination_type=PlaylistExportTarget.DEST_SUBSONIC,
        defaults={
            "subsonic_connection": connection,
            "sync_mode": sync_mode,
        },
    )
    # If the user changed which Subsonic server they want to push to, swap
    # the FK. This is rare but harmless.
    if target.subsonic_connection_id != connection.id:
        target.subsonic_connection = connection
        target.save(update_fields=["subsonic_connection"])
    return target


def _update_target_mode(
    account: Account, target_id: int, sync_mode: str
) -> PlaylistExportTarget:
    if sync_mode not in (
        PlaylistExportTarget.SYNC_MANUAL,
        PlaylistExportTarget.SYNC_ON_CHANGE,
    ):
        raise ValidationError(f"Invalid sync_mode: {sync_mode!r}")
    target = _resolve_owned_target(account, target_id)
    target.sync_mode = sync_mode
    target.save(update_fields=["sync_mode"])
    return target


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
