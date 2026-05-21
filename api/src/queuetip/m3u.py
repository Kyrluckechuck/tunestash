"""Pure m3u rendering for ExportSnapshots.

Emits extended m3u (#EXTM3U) with `#EXTINF:-1,Artist - Title` per track
followed by a streamable URL. URLs are built against the requesting user's
Subsonic connection — a portable, universally playable file (any URL-aware
media player can open it).

Previously emitted local file paths, which were only useful to clients with
filesystem access to the music share. That mode is gone — the niche
self-hoster who wanted file paths can run a custom export against the DB.

#EXTINF duration is `-1` (EXTM3U convention for "unknown") because Song
has no duration field.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import cast

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
    SubsonicConnection,
)

from .crypto import CryptoError, decrypt_secret
from .subsonic import SubsonicClient, SubsonicError
from .subsonic.resolution import resolve_song_to_subsonic_id

logger = logging.getLogger(__name__)


class M3uExportError(Exception):
    """Raised when the m3u export cannot proceed (e.g. no Subsonic connection)."""


def render_m3u(snapshot: ExportSnapshot, *, requester: Account | None = None) -> str:
    """Render an ExportSnapshot as extended m3u text with Subsonic stream URLs.

    `requester` is the account whose Subsonic connection should provide the
    stream URLs. Falls back to the snapshot's `requested_by` when not given
    (lets the m3u route work for the user who created the snapshot).

    Raises M3uExportError if the requester has no Subsonic connection
    configured. Tracks that don't resolve on the Subsonic server are
    emitted as comments rather than dropped silently — the file stays a
    record of what was wanted, even when some tracks aren't streamable.
    """
    account = requester or cast(Account, snapshot.requested_by)
    conn = SubsonicConnection.objects.filter(account=account).first()
    if conn is None:
        raise M3uExportError(
            "Connect a Subsonic server in settings to export m3u — the file "
            "embeds streaming URLs from your server."
        )

    try:
        password = decrypt_secret(conn.password_encrypted)
    except CryptoError as exc:
        raise M3uExportError(f"Could not access Subsonic credentials: {exc}") from exc

    client = SubsonicClient(
        server_url=conn.server_url,
        username=conn.username,
        password=password,
    )

    playlist_name = cast(Playlist, snapshot.playlist).name
    lines: list[str] = [
        "#EXTM3U",
        f'# Queuetip export — playlist "{playlist_name}" — snapshot {snapshot.id}',
        f"# Stream URLs from {conn.label} ({conn.server_url})",
    ]
    tracks = snapshot.tracks.select_related("song", "song__primary_artist").order_by(
        "position"
    )
    for track in cast(list[ExportSnapshotTrack], tracks):
        from library_manager.models import Song

        song = cast(Song, track.song)
        artist_name = (
            song.primary_artist.name  # type: ignore[attr-defined]
            if song.primary_artist_id and song.primary_artist  # type: ignore[attr-defined]
            else ""
        )
        label = f"{artist_name} - {song.name}".strip(" -")

        try:
            remote_id = resolve_song_to_subsonic_id(
                title=song.name,
                artist=artist_name,
                isrc=(song.isrc or None) if hasattr(song, "isrc") else None,
                client=client,
            )
        except SubsonicError as exc:
            logger.warning("[m3u] resolution failed for song %s: %s", song.id, exc)
            remote_id = None

        if not remote_id:
            lines.append(f"# unmatched: {label}")
            continue

        lines.append(f"#EXTINF:-1,{label}")
        lines.append(_build_stream_url(conn, password, remote_id))
    return "\n".join(lines) + "\n"


def _build_stream_url(conn: SubsonicConnection, password: str, song_id: str) -> str:
    """Build a salted-MD5 authenticated /rest/stream URL for one track.

    The URL embeds a fixed token tied to this export-time salt. It works
    until the user changes their Subsonic password (then re-export). This
    is how every Subsonic ecosystem .m3u works in practice — treat the
    file as a sensitive credential carrier.
    """
    salt = secrets.token_hex(8)
    token = hashlib.md5(  # nosec: B324 — Subsonic protocol mandates MD5
        (password + salt).encode("utf-8")
    ).hexdigest()
    base = conn.server_url.rstrip("/")
    params = [
        ("id", song_id),
        ("u", conn.username),
        ("t", token),
        ("s", salt),
        ("v", "1.16.1"),
        ("c", "queuetip"),
    ]
    query = "&".join(f"{k}={v}" for k, v in params)
    return f"{base}/rest/stream.view?{query}"
