"""Async service: push an ExportSnapshot to a real Spotify playlist."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import cast

from django.utils import timezone

import httpx
from asgiref.sync import sync_to_async

from queuetip.models import Account, ExportSnapshot, ExternalServiceLink, Playlist

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


@dataclass
class SpotifyExportResult:
    spotify_playlist_url: str
    added_count: int
    skipped_count: int
    skipped_titles: list[str] = field(default_factory=list)


class SpotifyExportService:
    """Stateless namespace for pushing snapshots to Spotify."""

    @staticmethod
    async def export(
        account: Account,
        snapshot_id: str,
        playlist_name: str | None = None,
    ) -> SpotifyExportResult:
        # Membership + snapshot existence handled by ExportService.get.
        snapshot = await ExportService.get(account, snapshot_id)

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

        name = playlist_name or _default_playlist_name(snapshot)
        playlist_url, playlist_id = await sync_to_async(_create_playlist)(
            access_token, link.service_user_id, name
        )
        await sync_to_async(_add_tracks_in_batches)(
            access_token, playlist_id, valid_uris
        )

        return SpotifyExportResult(
            spotify_playlist_url=playlist_url,
            added_count=len(valid_uris),
            skipped_count=len(skipped_titles),
            skipped_titles=skipped_titles,
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


def _default_playlist_name(snapshot: ExportSnapshot) -> str:
    when = snapshot.created_at.strftime("%Y-%m-%d %H:%M")
    return f"{cast(Playlist, snapshot.playlist).name} — {when}"


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
