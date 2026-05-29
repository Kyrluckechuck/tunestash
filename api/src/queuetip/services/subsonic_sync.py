"""Push a queuetip playlist's current state to a user's Subsonic server.

Mirrors the lifecycle invariants of SpotifyExportService (see
spotify_export.py) — find-or-create target, idempotent overwrite, halt on
remote_deleted. The mechanics differ only in:

  * Auth: salted-MD5 each call, password Fernet-decrypted from the
    SubsonicConnection row.
  * Track resolution: SubsonicClient.search_tracks ladder rather than
    Spotify's /v1/search.
  * Update semantics: Subsonic's updatePlaylist is incremental; the client
    wrapper turns it into a single atomic overwrite (see
    SubsonicClient.overwrite_playlist).
  * Unmatched-tracks side effect: queue downloads via the existing
    library_manager.tasks helpers so missing tracks may appear on the
    server before the next sync.

This module is sync (no async/await) — callers are Celery tasks. Wrapping
the Django ORM and the sync httpx client in async would invert their
natural shape with no benefit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import cast

from django.utils import timezone

from queuetip.models import (
    Account,
    Playlist,
    PlaylistExportTarget,
    SubsonicConnection,
)

from ..crypto import CryptoError, decrypt_secret
from ..subsonic import (
    SubsonicAuthError,
    SubsonicClient,
    SubsonicError,
    SubsonicNotFoundError,
    resolve_song_to_subsonic_id,
)

logger = logging.getLogger(__name__)


@dataclass
class SubsonicSyncResult:
    matched_count: int
    total_count: int
    unmatched_titles: list[str] = field(default_factory=list)
    queued_downloads: list[int] = field(default_factory=list)  # song ids


class SubsonicSyncError(Exception):
    """Raised when the sync run fails for a reason the caller should surface
    (auth, connection refused, server crash). Track-resolution misses do NOT
    raise — they're reported via SubsonicSyncResult.unmatched_titles.
    """


def sync_subsonic_target(target_id: int) -> SubsonicSyncResult:
    """Resolve queuetip songs on the playlist behind `target_id` and push the
    matched set to the user's Subsonic server.

    Idempotent: subsequent calls overwrite the same remote playlist
    (Lifecycle Principle 1). If the remote is gone (Principle 2), this
    raises SubsonicSyncError after marking the target REMOTE_DELETED.
    """
    try:
        target = PlaylistExportTarget.objects.select_related(
            "playlist", "subsonic_connection", "account"
        ).get(id=target_id, destination_type=PlaylistExportTarget.DEST_SUBSONIC)
    except PlaylistExportTarget.DoesNotExist:
        raise SubsonicSyncError(
            f"Subsonic sync target {target_id} not found."
        ) from None

    if target.last_sync_status == PlaylistExportTarget.STATUS_REMOTE_DELETED:
        raise SubsonicSyncError(
            "Subsonic playlist was deleted. Re-create from the queuetip UI."
        )

    connection = cast(SubsonicConnection, target.subsonic_connection)
    if connection is None:
        raise SubsonicSyncError(
            "Sync target has no Subsonic connection — CHECK constraint violated."
        )

    try:
        password = decrypt_secret(connection.password_encrypted)
    except CryptoError as exc:
        _record_failure(target, f"Could not decrypt credentials: {exc}")
        raise SubsonicSyncError(str(exc)) from exc

    client = SubsonicClient(
        server_url=connection.server_url,
        username=connection.username,
        password=password,
        auth_mode=connection.auth_mode,
    )

    # Roll the selection engine over the playlist's CURRENT contributions.
    # Each sync is a fresh random curation (queuetip's core mechanic) — we
    # push the rolled subset, not every contribution. `account` enables the
    # exclude-my-downvotes filter; here we roll without it (the playlist
    # owner's perspective isn't meaningful for a shared remote).
    from .roll import roll_playlist

    playlist = cast(Playlist, target.playlist)
    roll = roll_playlist(
        playlist,
        account=cast(Account, target.account),
        exclude_my_downvotes=target.exclude_my_downvotes,
        min_score_threshold=target.min_score_threshold,
        target_size_override=target.target_size_override,
    )

    # Fetch the rolled songs in the engine's chosen order, with the relations
    # the resolver needs. Preserve roll order via a position map.
    from library_manager.models import Song as SongModel

    order = {sid: i for i, sid in enumerate(roll.song_ids)}
    songs = sorted(
        SongModel.objects.filter(id__in=roll.song_ids).select_related("primary_artist"),
        key=lambda s: order.get(s.id, 0),
    )

    matched_ids: list[str] = []
    unmatched_titles: list[str] = []
    queued_downloads: list[int] = []

    for song in songs:
        artist_name = (
            song.primary_artist.name if song.primary_artist_id else ""  # type: ignore[attr-defined]
        )
        # Resolution misses must never abort the whole sync — a missing track
        # is a normal condition (user hasn't downloaded it into Navidrome yet).
        try:
            remote_id = resolve_song_to_subsonic_id(
                title=song.name,
                artist=artist_name,
                isrc=song.isrc or None,
                client=client,
                file_path=song.file_path,
            )
        except SubsonicAuthError as exc:
            _record_failure(target, f"Authentication failed: {exc}")
            raise SubsonicSyncError(str(exc)) from exc
        except SubsonicError as exc:
            # Transient — log and skip, don't fail the whole sync.
            logger.warning(
                "[subsonic-sync] resolution failed for song %s: %s",
                song.id,
                exc,
            )
            remote_id = None

        if remote_id:
            matched_ids.append(remote_id)
        else:
            label = f"{artist_name} — {song.name}".strip(" —")
            unmatched_titles.append(label)
            queued = _maybe_queue_download(song)
            if queued:
                queued_downloads.append(song.id)

    # Push to the remote — create-or-update.
    try:
        if target.remote_playlist_id:
            client.overwrite_playlist(target.remote_playlist_id, matched_ids)
        else:
            target.remote_playlist_id = client.create_playlist(
                playlist.name, matched_ids
            )
    except SubsonicNotFoundError as exc:
        _mark_remote_deleted(target)
        raise SubsonicSyncError(
            "Subsonic playlist was deleted. Re-create from the queuetip UI."
        ) from exc
    except SubsonicAuthError as exc:
        _record_failure(target, f"Authentication failed: {exc}")
        raise SubsonicSyncError(str(exc)) from exc
    except SubsonicError as exc:
        _record_failure(target, f"Subsonic push failed: {exc}")
        raise SubsonicSyncError(str(exc)) from exc

    _record_success(
        target,
        matched_count=len(matched_ids),
        total_count=len(roll.song_ids),
        unmatched_titles=unmatched_titles,
    )

    return SubsonicSyncResult(
        matched_count=len(matched_ids),
        total_count=len(roll.song_ids),
        unmatched_titles=unmatched_titles,
        queued_downloads=queued_downloads,
    )


# ── Persistence helpers ─────────────────────────────────────────────────────


def _record_success(
    target: PlaylistExportTarget,
    *,
    matched_count: int,
    total_count: int,
    unmatched_titles: list[str],
) -> None:
    target.last_synced_at = timezone.now()
    target.last_error = ""
    target.matched_track_count = matched_count
    target.total_track_count = total_count
    target.unmatched_track_titles = unmatched_titles
    target.last_sync_status = (
        PlaylistExportTarget.STATUS_PARTIAL
        if unmatched_titles
        else PlaylistExportTarget.STATUS_OK
    )
    target.save(
        update_fields=[
            "remote_playlist_id",
            "last_synced_at",
            "last_error",
            "matched_track_count",
            "total_track_count",
            "unmatched_track_titles",
            "last_sync_status",
        ]
    )


def _record_failure(target: PlaylistExportTarget, message: str) -> None:
    target.last_synced_at = timezone.now()
    target.last_sync_status = PlaylistExportTarget.STATUS_FAILED
    target.last_error = message
    target.save(update_fields=["last_synced_at", "last_sync_status", "last_error"])


def _mark_remote_deleted(target: PlaylistExportTarget) -> None:
    target.last_synced_at = timezone.now()
    target.last_sync_status = PlaylistExportTarget.STATUS_REMOTE_DELETED
    target.last_error = (
        "The Subsonic playlist was deleted. Click 'Recreate on Subsonic' to start over."
    )
    target.save(update_fields=["last_synced_at", "last_sync_status", "last_error"])


def _maybe_queue_download(song) -> bool:  # type: ignore[no-untyped-def]
    """Queue a TuneStash download for an unmatched song so it may appear on
    the user's Navidrome before the next sync.

    Returns True when a download was actually queued (deduped via
    is_task_pending_or_running). Best-effort — any failure is logged and
    treated as "didn't queue."
    """
    try:
        from library_manager.helpers import (
            generate_task_id,
            is_task_pending_or_running,
        )
        from library_manager.tasks import (
            download_deezer_track,
            download_track_by_spotify_gid,
        )
    except ImportError as exc:
        logger.debug("[subsonic-sync] download helpers unavailable: %s", exc)
        return False

    def _queue(task_name: str, key: str, task, args: list) -> bool:  # type: ignore[no-untyped-def]
        task_id = generate_task_id(task_name, key)
        is_pending, _ = is_task_pending_or_running(task_id)
        if is_pending:
            return False
        try:
            task.apply_async(args=args, task_id=task_id)
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "[subsonic-sync] failed to queue %s for %s: %s", task_name, key, exc
            )
            return False

    gid = (getattr(song, "gid", "") or "").strip()
    if gid:
        return _queue(
            "download_track_by_spotify_gid", gid, download_track_by_spotify_gid, [gid]
        )

    deezer_id = getattr(song, "deezer_id", None)
    if deezer_id:
        return _queue(
            "download_deezer_track",
            str(deezer_id),
            download_deezer_track,
            [int(deezer_id)],
        )

    return False
