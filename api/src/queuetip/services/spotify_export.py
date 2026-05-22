"""Async service: push a queuetip playlist's current state to Spotify.

Lifecycle (matches docs/queuetip/subsonic-sync-design.md):
  * One queuetip playlist → ONE Spotify playlist per (user, dest). Subsequent
    exports REPLACE the tracks of the same Spotify playlist; we never create
    a fresh playlist with a timestamped name.
  * If the user deletes the Spotify playlist, Spotify's PUT-tracks endpoint
    returns 404 → we mark the target REMOTE_DELETED. Automation halts until
    the user explicitly re-creates.
  * Snapshots are still created on each export as an audit log; they're no
    longer the primary identity of the exported playlist.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import cast

from django.utils import timezone

import httpx
from asgiref.sync import sync_to_async

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
)

from ..errors import NotFoundError
from ..services.export import ExportService
from ..spotify_oauth import (
    SPOTIFY_API_BASE,
    SpotifyOAuthError,
    refresh_access_token,
)

logger = logging.getLogger(__name__)

TOKEN_REFRESH_LEEWAY_SECONDS = 60
TRACK_BATCH_SIZE = 100
PREFLIGHT_BATCH_SIZE = 50  # Spotify /v1/tracks allows up to 50 ids per request


class SpotifyExportError(Exception):
    """Raised when the Spotify push fails (after token refresh attempts)."""


class RemotePlaylistDeletedError(SpotifyExportError):
    """Raised when Spotify returns 404 on an update — the remote playlist
    no longer exists. Per lifecycle Principle 2, automation halts and the
    user must explicitly recreate.
    """


@dataclass
class SpotifyExportResult:
    spotify_playlist_url: str
    added_count: int
    skipped_count: int
    skipped_titles: list[str] = field(default_factory=list)
    # True when this call created a new Spotify playlist; False when we
    # updated an existing one (which is the normal case after the first export).
    created_new: bool = False


class SpotifyExportService:
    """Stateless namespace for pushing a queuetip playlist's state to Spotify."""

    @staticmethod
    async def export(
        account: Account,
        snapshot_id: str,
        playlist_name: str | None = None,
        *,
        force_recreate: bool = False,
    ) -> SpotifyExportResult:
        """Push the snapshot's tracks to Spotify, reusing the same Spotify
        playlist on subsequent calls for the same (account, queuetip playlist).

        Set ``force_recreate=True`` to abandon an existing remote (e.g. after
        the user deleted it on Spotify and explicitly requested a fresh one).
        """
        # Membership + snapshot existence handled by ExportService.get.
        snapshot = await ExportService.get(account, snapshot_id)
        queuetip_playlist = cast(Playlist, snapshot.playlist)

        link = await sync_to_async(
            lambda: ExternalServiceLink.objects.filter(
                account=account,
                service=ExternalServiceLink.SERVICE_SPOTIFY,
            ).first()
        )()
        if link is None:
            raise NotFoundError(
                "Spotify is not linked. Connect Spotify in settings first."
            )

        # Find-or-create the export target. This is the row that turns
        # "create a fresh playlist every export" into "update the same one."
        target = await sync_to_async(_find_or_create_target)(
            account, queuetip_playlist, link
        )

        # Principle 2: if a previous sync detected the remote was deleted,
        # refuse to silently re-create. The caller must pass force_recreate
        # (or call the recreate mutation).
        if (
            target.last_sync_status == PlaylistExportTarget.STATUS_REMOTE_DELETED
            and not force_recreate
        ):
            raise RemotePlaylistDeletedError(
                "Spotify playlist was deleted. Click 'Recreate on Spotify' "
                "to start over."
            )
        if force_recreate:
            target.remote_playlist_id = ""

        access_token = await _ensure_fresh_token(link)

        # Pre-export: enrich any songs missing a gid via ISRC→Spotify bridge.
        await _enrich_missing_gids(snapshot)

        # Collect candidate URIs — songs that still have no gid after enrichment
        # are collected as skipped here.
        tracks_and_skips = await sync_to_async(_collect_track_candidates)(snapshot)
        candidates, skipped_titles = tracks_and_skips

        # Pre-flight: validate gids against Spotify's /v1/tracks endpoint.
        # Stale or deleted gids return null in the response — drop those too.
        valid_uris, stale_titles = await sync_to_async(_validate_and_collect_uris)(
            access_token, candidates
        )
        skipped_titles.extend(stale_titles)

        name = playlist_name or queuetip_playlist.name
        created_new = False

        try:
            if target.remote_playlist_id:
                # Update path: replace tracks atomically with PUT.
                # 404 here means the user deleted the playlist on Spotify.
                playlist_url = await sync_to_async(_replace_tracks)(
                    access_token, target.remote_playlist_id, valid_uris
                )
            else:
                # Create path: first export for this (user, playlist) pair,
                # OR force_recreate after a remote_deleted state.
                playlist_url, playlist_id = await sync_to_async(_create_playlist)(
                    access_token, link.service_user_id, name
                )
                await sync_to_async(_add_tracks_in_batches)(
                    access_token, playlist_id, valid_uris
                )
                target.remote_playlist_id = playlist_id
                created_new = True
        except RemotePlaylistDeletedError:
            await sync_to_async(_mark_remote_deleted)(target)
            raise

        await sync_to_async(_record_success)(
            target,
            matched_count=len(valid_uris),
            total_count=len(valid_uris) + len(skipped_titles),
            unmatched=skipped_titles,
        )

        return SpotifyExportResult(
            spotify_playlist_url=playlist_url,
            added_count=len(valid_uris),
            skipped_count=len(skipped_titles),
            skipped_titles=skipped_titles,
            created_new=created_new,
        )

    @staticmethod
    async def sync_target(target_id: int) -> "SpotifyExportResult":
        """Push a playlist's CURRENT contributions to its Spotify counterpart.

        Counterpart to `export()` — that one is snapshot-driven (manual export
        with an immutable frozen tracklist + audit log). This one is
        sync-driven: pulls the playlist's contributions in real time, pushes,
        updates the target's status fields. Used by the unified
        `sync_export_target` Celery task to give Spotify targets the same
        auto-sync semantics Subsonic targets have.

        No ExportSnapshot is created — auto-syncs aren't audit events.
        Manual exports via `exportToSpotify(snapshotId)` still produce
        snapshots; those continue to share the same idempotent target row.
        """
        target = await sync_to_async(
            lambda: PlaylistExportTarget.objects.select_related(
                "playlist", "spotify_link", "account"
            ).get(id=target_id, destination_type=PlaylistExportTarget.DEST_SPOTIFY)
        )()

        if target.last_sync_status == PlaylistExportTarget.STATUS_REMOTE_DELETED:
            raise RemotePlaylistDeletedError(
                "Spotify playlist was deleted. Click 'Recreate on Spotify' "
                "to start over."
            )

        link = cast(ExternalServiceLink, target.spotify_link)
        if link is None:
            raise NotFoundError(
                "Spotify is not linked. Connect Spotify in settings first."
            )

        playlist = cast(Playlist, target.playlist)
        access_token = await _ensure_fresh_token(link)

        # Roll the selection engine over the playlist's current contributions
        # — each push is a fresh random curation (queuetip's core mechanic).
        # We push the rolled subset, not every contribution.
        from .roll import roll_playlist

        roll = await sync_to_async(roll_playlist)(playlist)

        # Enrich the rolled songs missing a gid (ISRC → Spotify bridge).
        await _enrich_songs_missing_gids(roll.song_ids)

        candidates, skipped_titles = await sync_to_async(_collect_song_candidates)(
            roll.song_ids
        )
        valid_uris, stale_titles = await sync_to_async(_validate_and_collect_uris)(
            access_token, candidates
        )
        skipped_titles.extend(stale_titles)

        created_new = False
        try:
            if target.remote_playlist_id:
                playlist_url = await sync_to_async(_replace_tracks)(
                    access_token, target.remote_playlist_id, valid_uris
                )
            else:
                playlist_url, playlist_id = await sync_to_async(_create_playlist)(
                    access_token, link.service_user_id, playlist.name
                )
                await sync_to_async(_add_tracks_in_batches)(
                    access_token, playlist_id, valid_uris
                )
                target.remote_playlist_id = playlist_id
                created_new = True
        except RemotePlaylistDeletedError:
            await sync_to_async(_mark_remote_deleted)(target)
            raise

        await sync_to_async(_record_success)(
            target,
            matched_count=len(valid_uris),
            total_count=len(valid_uris) + len(skipped_titles),
            unmatched=skipped_titles,
        )

        return SpotifyExportResult(
            spotify_playlist_url=playlist_url,
            added_count=len(valid_uris),
            skipped_count=len(skipped_titles),
            skipped_titles=skipped_titles,
            created_new=created_new,
        )


# ── Helpers (sync — wrapped by callers as needed) ────────────────────────────


async def _enrich_missing_gids(snapshot: ExportSnapshot) -> None:
    """Enrich songs that are missing a gid before the export run."""
    from library_manager.models import Song as SongModel
    from src.queuetip.enrichment import enrich_song_cross_platform

    tracks = await sync_to_async(
        lambda: list(snapshot.tracks.select_related("song").order_by("position"))
    )()
    for track in tracks:
        song = cast(SongModel, track.song)
        if not (song.gid or "").strip():
            try:
                await sync_to_async(enrich_song_cross_platform)(song)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "[EXPORT] Enrichment failed for song %s: %s", song.id, exc
                )


async def _enrich_songs_missing_gids(song_ids: list[int]) -> None:
    """Enrich the given songs' missing gids before pushing (ISRC → Spotify).
    Operates on a rolled selection's song ids rather than a snapshot."""
    from library_manager.models import Song as SongModel
    from src.queuetip.enrichment import enrich_song_cross_platform

    songs = await sync_to_async(
        lambda: list(SongModel.objects.filter(id__in=song_ids))
    )()
    for song in songs:
        if not (song.gid or "").strip():
            try:
                await sync_to_async(enrich_song_cross_platform)(song)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "[EXPORT] Enrichment failed for song %s: %s", song.id, exc
                )


def _collect_track_candidates(
    snapshot: ExportSnapshot,
) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Build (song_id, gid, label) for all tracks; songs without gid go to skipped.

    Returns (candidates, skipped_titles) where candidates is a list of
    (song_id, gid, label) tuples for songs that have a gid after enrichment.
    """
    from library_manager.models import Song as SongModel

    candidates: list[tuple[int, str, str]] = []
    skipped: list[str] = []
    tracks = snapshot.tracks.select_related("song", "song__primary_artist").order_by(
        "position"
    )
    for track in tracks:
        song = cast(SongModel, track.song)
        # Re-read from DB to pick up any enrichment writes.
        song.refresh_from_db()
        gid = (song.gid or "").strip()
        title = song.name
        artist = song.primary_artist.name if song.primary_artist_id else ""  # type: ignore[attr-defined]
        label = f"{artist} — {title}".strip(" —")
        if not gid:
            skipped.append(label)
            continue
        candidates.append((song.id, gid, label))
    return candidates, skipped


def _collect_song_candidates(
    song_ids: list[int],
) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Build (song_id, gid, label) for a rolled selection's songs; songs
    without a gid (after enrichment) go to skipped. Preserves roll order."""
    from library_manager.models import Song as SongModel

    candidates: list[tuple[int, str, str]] = []
    skipped: list[str] = []
    order = {sid: i for i, sid in enumerate(song_ids)}
    songs = sorted(
        SongModel.objects.filter(id__in=song_ids).select_related("primary_artist"),
        key=lambda s: order.get(s.id, 0),
    )
    for song in songs:
        gid = (song.gid or "").strip()
        artist = song.primary_artist.name if song.primary_artist_id else ""  # type: ignore[attr-defined]
        label = f"{artist} — {song.name}".strip(" —")
        if not gid:
            skipped.append(label)
            continue
        candidates.append((song.id, gid, label))
    return candidates, skipped


def _validate_and_collect_uris(
    access_token: str,
    candidates: list[tuple[int, str, str]],
) -> tuple[list[str], list[str]]:
    """Validate gids via /v1/tracks?ids=... (batches of 50).

    Spotify returns null in the tracks array for gids that no longer exist.
    Those are treated as stale and moved to skipped_titles.

    Returns (valid_uris, stale_titles).
    """
    if not candidates:
        return [], []

    valid_uris: list[str] = []
    stale_titles: list[str] = []

    for start in range(0, len(candidates), PREFLIGHT_BATCH_SIZE):
        batch = candidates[start : start + PREFLIGHT_BATCH_SIZE]
        gids = [gid for _, gid, _ in batch]
        labels = {gid: label for _, gid, label in batch}

        try:
            response = httpx.get(
                f"{SPOTIFY_API_BASE}/tracks",
                params={"ids": ",".join(gids)},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "[EXPORT] Pre-flight /v1/tracks returned %s — treating batch as valid",
                    response.status_code,
                )
                # Don't skip on API errors; fall through to add the batch as-is.
                for _, gid, _ in batch:
                    valid_uris.append(f"spotify:track:{gid}")
                continue

            payload = dict(response.json())
            tracks_list = list(payload.get("tracks") or [])
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "[EXPORT] Pre-flight validation failed: %s — skipping check", exc
            )
            for _, gid, _ in batch:
                valid_uris.append(f"spotify:track:{gid}")
            continue

        for i, item in enumerate(tracks_list):
            gid = gids[i]
            if item is None:
                stale_titles.append(labels[gid])
                logger.debug("[EXPORT] Stale gid dropped: %s", gid)
            else:
                valid_uris.append(f"spotify:track:{gid}")

    return valid_uris, stale_titles


async def _ensure_fresh_token(link: ExternalServiceLink) -> str:
    """Refresh the access token if it's near expiry. Returns the current token."""
    if link.expires_at > timezone.now() + dt.timedelta(
        seconds=TOKEN_REFRESH_LEEWAY_SECONDS
    ):
        return str(link.access_token)

    def _refresh_and_save() -> str:
        try:
            tokens = refresh_access_token(link.refresh_token)
        except SpotifyOAuthError as exc:
            raise SpotifyExportError(
                f"Could not refresh Spotify access. Please re-link Spotify. ({exc})"
            ) from exc
        link.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            link.refresh_token = tokens["refresh_token"]
        link.expires_at = timezone.now() + dt.timedelta(
            seconds=int(tokens["expires_in"])
        )
        link.save(update_fields=["access_token", "refresh_token", "expires_at"])
        return str(link.access_token)

    return await sync_to_async(_refresh_and_save)()


def _find_or_create_target(
    account: Account,
    playlist: Playlist,
    link: ExternalServiceLink,
) -> PlaylistExportTarget:
    """Return the (account, playlist, spotify) export target, creating it
    on first export.  The credential FK is set on creation and updated if the
    user has re-linked Spotify since the last export."""
    target, _ = PlaylistExportTarget.objects.get_or_create(
        account=account,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        defaults={"spotify_link": link},
    )
    # If the user re-linked Spotify, point the target at the new credential.
    if target.spotify_link_id != link.id:
        target.spotify_link = link
        target.save(update_fields=["spotify_link"])
    return target


def _record_success(
    target: PlaylistExportTarget,
    *,
    matched_count: int,
    total_count: int,
    unmatched: list[str],
) -> None:
    target.last_synced_at = timezone.now()
    target.last_error = ""
    target.matched_track_count = matched_count
    target.total_track_count = total_count
    target.unmatched_track_titles = unmatched
    target.last_sync_status = (
        PlaylistExportTarget.STATUS_PARTIAL
        if unmatched
        else PlaylistExportTarget.STATUS_OK
    )
    target.save(
        update_fields=[
            "remote_playlist_id",  # set on first export
            "last_synced_at",
            "last_error",
            "matched_track_count",
            "total_track_count",
            "unmatched_track_titles",
            "last_sync_status",
        ]
    )


def _mark_remote_deleted(target: PlaylistExportTarget) -> None:
    """User deleted the Spotify playlist out from under us. Halt automation
    and surface the state — never silently re-create (lifecycle Principle 2)."""
    target.last_sync_status = PlaylistExportTarget.STATUS_REMOTE_DELETED
    target.last_error = (
        "The Spotify playlist was deleted. Click 'Recreate on Spotify' to start over."
    )
    target.last_synced_at = timezone.now()
    target.save(update_fields=["last_sync_status", "last_error", "last_synced_at"])


def _replace_tracks(access_token: str, playlist_id: str, uris: list[str]) -> str:
    """Replace all tracks on an existing Spotify playlist with the given URIs.

    Spotify's PUT /v1/playlists/{id}/tracks accepts up to 100 URIs atomically.
    For lists larger than 100, the first batch PUTs (replace), subsequent
    batches POST (append).

    Returns the playlist's external URL.

    Raises RemotePlaylistDeletedError on 404 — the user deleted the playlist.
    """
    if not uris:
        # Replace with an empty list.
        response = httpx.put(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"uris": []},
            timeout=15.0,
        )
        if response.status_code == 404:
            raise RemotePlaylistDeletedError(playlist_id)
        if response.status_code not in (200, 201):
            raise SpotifyExportError(
                f"Replacing Spotify playlist tracks failed: "
                f"{response.status_code} {response.text}"
            )
        return f"https://open.spotify.com/playlist/{playlist_id}"

    first_batch = uris[:TRACK_BATCH_SIZE]
    response = httpx.put(
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"uris": first_batch},
        timeout=15.0,
    )
    if response.status_code == 404:
        raise RemotePlaylistDeletedError(playlist_id)
    if response.status_code not in (200, 201):
        raise SpotifyExportError(
            f"Replacing Spotify playlist tracks failed: "
            f"{response.status_code} {response.text}"
        )

    # Spotify caps PUT at 100 URIs. For larger playlists, append remainder.
    if len(uris) > TRACK_BATCH_SIZE:
        _add_tracks_in_batches(access_token, playlist_id, uris[TRACK_BATCH_SIZE:])

    return f"https://open.spotify.com/playlist/{playlist_id}"


def _create_playlist(access_token: str, user_id: str, name: str) -> tuple[str, str]:
    response = httpx.post(
        f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"name": name, "public": False, "description": "Created by Queuetip"},
        timeout=15.0,
    )
    if response.status_code not in (200, 201):
        raise SpotifyExportError(
            f"Creating Spotify playlist failed: {response.status_code} {response.text}"
        )
    payload = response.json()
    playlist_id = payload["id"]
    playlist_url = payload.get("external_urls", {}).get(
        "spotify", f"https://open.spotify.com/playlist/{playlist_id}"
    )
    return playlist_url, playlist_id


def _add_tracks_in_batches(
    access_token: str, playlist_id: str, uris: list[str]
) -> None:
    if not uris:
        return
    for start in range(0, len(uris), TRACK_BATCH_SIZE):
        batch = uris[start : start + TRACK_BATCH_SIZE]
        response = httpx.post(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"uris": batch},
            timeout=15.0,
        )
        if response.status_code not in (200, 201):
            raise SpotifyExportError(
                f"Adding tracks to Spotify playlist failed: "
                f"{response.status_code} {response.text}"
            )
