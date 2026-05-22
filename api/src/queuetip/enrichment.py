"""Cross-platform ID enrichment for Song records.

All functions are synchronous. Callers in async contexts must wrap with
sync_to_async. Failures from Spotify/Deezer are caught and logged so that
enrichment is always a best-effort operation — it must never raise to callers.
"""

from __future__ import annotations

import logging
from typing import Any

from library_manager.models import Song

logger = logging.getLogger(__name__)

ISRC_BATCH_SIZE = 50  # Spotify /v1/tracks supports up to 50 ids per request


def get_spotify_gid_by_isrc(isrc: str) -> str | None:
    """Search Spotify for a track by ISRC. Returns the track id or None.

    ISRC search can return multiple hits (re-releases of the same recording).
    We take the first result — all hits are semantically the same recording.
    """
    try:
        from downloader.spotipy_tasks import PublicSpotifyClient

        client = PublicSpotifyClient()
        if client.sp is None:
            logger.debug(
                "[ENRICHMENT] PublicSpotifyClient not configured, skipping ISRC→gid"
            )
            return None
        results: dict[str, Any] = dict(
            client.sp.search(q=f"isrc:{isrc}", type="track", limit=1) or {}
        )
        tracks = results.get("tracks") or {}
        items = (tracks.get("items") or []) if isinstance(tracks, dict) else []
        if not items:
            return None
        first_item = items[0]
        if not isinstance(first_item, dict):
            return None
        return str(first_item["id"]) if first_item.get("id") else None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[ENRICHMENT] ISRC→gid lookup failed for %s: %s", isrc, exc)
        return None


def get_spotify_track_isrc(gid: str) -> str | None:
    """Fetch the ISRC for a Spotify track id. Returns the ISRC or None."""
    try:
        from downloader.spotipy_tasks import PublicSpotifyClient

        client = PublicSpotifyClient()
        if client.sp is None:
            logger.debug(
                "[ENRICHMENT] PublicSpotifyClient not configured, skipping gid→ISRC"
            )
            return None
        track: dict[str, Any] = dict(client.sp.track(gid) or {})
        external_ids = track.get("external_ids") or {}
        isrc = external_ids.get("isrc") if isinstance(external_ids, dict) else None
        return str(isrc) if isrc else None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[ENRICHMENT] gid→ISRC lookup failed for %s: %s", gid, exc)
        return None


def get_deezer_id_by_isrc(isrc: str) -> int | None:
    """Search Deezer for a track by ISRC. Returns the deezer_id or None."""
    try:
        from src.providers.deezer import DeezerMetadataProvider

        result = DeezerMetadataProvider().get_track_by_isrc(isrc)
        return result.deezer_id if result and result.deezer_id else None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "[ENRICHMENT] ISRC→deezer_id lookup failed for %s: %s", isrc, exc
        )
        return None


def enrich_song_cross_platform(song: Song) -> Song:
    """Fill in missing gid / deezer_id / isrc on *song* via ISRC bridges.

    Logic:
    - gid present + isrc empty  → fetch Spotify track → save isrc.
    - isrc present + gid empty  → ISRC→Spotify search → save gid.
    - isrc present + deezer_id empty → ISRC→Deezer → save deezer_id.

    Idempotent. Uses Song.objects.filter(id=song.id).update(**fields) so two
    concurrent enrichments don't clobber each other. Returns a refreshed Song.
    """
    updates: dict[str, Any] = {}

    isrc: str | None = song.isrc or None
    gid: str | None = song.gid or None
    deezer_id: int | None = song.deezer_id or None

    # Step 1: If we have a gid but no isrc, fetch the ISRC from Spotify.
    if gid and not isrc:
        fetched_isrc = get_spotify_track_isrc(gid)
        if fetched_isrc:
            isrc = fetched_isrc
            updates["isrc"] = isrc
            logger.debug("[ENRICHMENT] Song %s: gid→isrc %s", song.id, isrc)

    # Step 2: If we have an isrc but no gid, resolve gid via ISRC search.
    if isrc and not gid:
        fetched_gid = get_spotify_gid_by_isrc(isrc)
        if fetched_gid:
            gid = fetched_gid
            updates["gid"] = gid
            logger.debug("[ENRICHMENT] Song %s: isrc→gid %s", song.id, gid)

    # Step 3: If we have an isrc but no deezer_id, resolve via ISRC→Deezer.
    if isrc and not deezer_id:
        fetched_deezer_id = get_deezer_id_by_isrc(isrc)
        if fetched_deezer_id:
            updates["deezer_id"] = fetched_deezer_id
            logger.debug(
                "[ENRICHMENT] Song %s: isrc→deezer_id %s", song.id, fetched_deezer_id
            )

    if updates:
        Song.objects.filter(id=song.id).update(**updates)
        song.refresh_from_db()

    return song
