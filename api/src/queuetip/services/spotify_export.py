"""Async service: push an ExportSnapshot to a real Spotify playlist."""

from __future__ import annotations

import datetime as dt
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

TOKEN_REFRESH_LEEWAY_SECONDS = 60
TRACK_BATCH_SIZE = 100


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
        snapshot_id: int,
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
        tracks_and_skips = await sync_to_async(_collect_track_uris)(snapshot)
        track_uris, skipped_titles = tracks_and_skips

        name = playlist_name or _default_playlist_name(snapshot)
        playlist_url, playlist_id = await sync_to_async(_create_playlist)(
            access_token, link.service_user_id, name
        )
        await sync_to_async(_add_tracks_in_batches)(
            access_token, playlist_id, track_uris
        )

        return SpotifyExportResult(
            spotify_playlist_url=playlist_url,
            added_count=len(track_uris),
            skipped_count=len(skipped_titles),
            skipped_titles=skipped_titles,
        )


# ── Helpers (sync — wrapped by callers as needed) ────────────────────────────


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


def _collect_track_uris(snapshot: ExportSnapshot) -> tuple[list[str], list[str]]:
    """Build the Spotify URIs from snapshot tracks, separating skipped ones."""
    uris: list[str] = []
    skipped: list[str] = []
    tracks = snapshot.tracks.select_related("song", "song__primary_artist").order_by(
        "position"
    )
    for track in tracks:
        from library_manager.models import Song

        song = cast(Song, track.song)
        gid = (song.gid or "").strip()
        title = song.name
        artist = song.primary_artist.name if song.primary_artist_id else ""  # type: ignore[attr-defined]
        if not gid:
            skipped.append(f"{artist} — {title}".strip(" —"))
            continue
        uris.append(f"spotify:track:{gid}")
    return uris, skipped


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
