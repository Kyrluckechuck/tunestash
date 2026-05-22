"""ingest_track — turn a TrackCandidate into a persisted Song and queue its download.

Identity is created synchronously so callers get a Song at once; the audio download is
queued asynchronously and its success is NOT a gate. Matching is ISRC-first; the create
path resolves Apple/ISRC-only candidates to a Deezer id (the Song model has no Apple id
column — its CheckConstraint requires gid, deezer_id, or youtube_id).
"""

from __future__ import annotations

from django.db import IntegrityError

from library_manager.models import Artist, Song, TrackingTier
from library_manager.tasks import download_deezer_track, download_track_by_spotify_gid
from src.providers.deezer import DeezerMetadataProvider
from src.queuetip.enrichment import (
    enrich_song_cross_platform,
    find_spotify_track_by_name_artist,
)
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError


def _deezer_id_from(source_id: str) -> int:
    try:
        return int(source_id)
    except (TypeError, ValueError) as exc:
        raise TrackNotFoundError(f"Invalid Deezer track id: {source_id!r}") from exc


def _find_existing_song(candidate: TrackCandidate) -> Song | None:
    if candidate.source == "spotify" and candidate.source_id:
        song = Song.objects.filter(gid=candidate.source_id).first()
        if song:
            return song
    if candidate.source == "deezer" and candidate.source_id:
        song = Song.objects.filter(
            deezer_id=_deezer_id_from(candidate.source_id)
        ).first()
        if song:
            return song
    if candidate.isrc:
        song = Song.objects.filter(isrc=candidate.isrc).first()
        if song:
            return song
        # Cross-platform: the same recording can carry different ISRCs per
        # platform. A prior import may have recorded this ISRC as an alternate
        # on the row whose primary ISRC came from another platform.
        song = Song.objects.filter(alternate_isrcs__contains=[candidate.isrc]).first()
        if song:
            return song
    return None


def _get_or_create_artist(
    candidate: TrackCandidate, fallback_external_id: str, artist_deezer_id: int | None
) -> Artist:
    if artist_deezer_id:
        existing = Artist.objects.filter(deezer_id=artist_deezer_id).first()
        if existing:
            return existing
        artist, _ = Artist.objects.get_or_create(
            deezer_id=artist_deezer_id,
            defaults={
                "name": candidate.artist_name,
                "tracking_tier": TrackingTier.UNTRACKED,
            },
        )
        return artist
    # No known artist id (e.g. a Spotify candidate — TrackCandidate carries no
    # artist id). Fall back to a synthetic placeholder gid, matching the existing
    # TuneStash pattern for id-less artists.
    artist, _ = Artist.objects.get_or_create(
        gid=f"queuetip-unknown-{fallback_external_id}",
        defaults={
            "name": candidate.artist_name,
            "tracking_tier": TrackingTier.UNTRACKED,
        },
    )
    return artist


def _create_song(candidate: TrackCandidate) -> Song:
    gid: str | None = None
    deezer_id: int | None = None
    artist_deezer_id: int | None = None
    primary_isrc: str | None = candidate.isrc
    alternate_isrc: str | None = None

    if candidate.source == "spotify" and candidate.source_id:
        gid = candidate.source_id
    elif candidate.source == "deezer" and candidate.source_id:
        deezer_id = _deezer_id_from(candidate.source_id)
    else:
        # Apple (no Song-supported id) — resolve via ISRC -> Deezer.
        if candidate.isrc:
            result = DeezerMetadataProvider().get_track_by_isrc(candidate.isrc)
            if result and result.deezer_id:
                deezer_id = result.deezer_id
                artist_deezer_id = result.artist_deezer_id
                # The resolved deezer_id may already belong to an existing Song
                # (one added earlier without ISRC stored) — check before creating.
                existing = Song.objects.filter(deezer_id=deezer_id).first()
                if existing:
                    return existing

    # ISRC-exact bridging failed. Platforms often assign different ISRCs to the
    # same recording (Apple vs Spotify/Deezer), so fall back to a verified
    # name+artist search to find a storable id.
    if gid is None and deezer_id is None:
        match = find_spotify_track_by_name_artist(
            candidate.track_name, candidate.artist_name
        )
        if match:
            gid, canonical_isrc = match
            # Prefer reusing an existing row (by the resolved gid or its
            # canonical ISRC) and record the source ISRC as an alternate, so a
            # repeat import of this platform's copy matches by ISRC next time.
            existing = Song.objects.filter(gid=gid).first()
            if existing is None and canonical_isrc:
                existing = Song.objects.filter(isrc=canonical_isrc).first()
            if existing is not None:
                _record_alternate_isrc(existing, candidate.isrc)
                return existing
            if canonical_isrc:
                primary_isrc = canonical_isrc
                if candidate.isrc and candidate.isrc != canonical_isrc:
                    alternate_isrc = candidate.isrc

    if gid is None and deezer_id is None:
        raise TrackNotFoundError(
            f"Could not resolve '{candidate.track_name}' to a storable track"
        )

    artist = _get_or_create_artist(candidate, str(gid or deezer_id), artist_deezer_id)
    try:
        return Song.objects.create(
            name=candidate.track_name,
            gid=gid,
            deezer_id=deezer_id,
            isrc=primary_isrc,
            alternate_isrcs=[alternate_isrc] if alternate_isrc else [],
            primary_artist=artist,
        )
    except IntegrityError:
        # A concurrent ingest of the same track won the race on Song.gid
        # (unique). Re-fetch the winner instead of failing this import.
        existing = _find_existing_song(candidate)
        if existing is not None:
            return existing
        raise


def _record_alternate_isrc(song: Song, isrc: str | None) -> None:
    """Add `isrc` to song.alternate_isrcs (deduped; skip if it's the primary)."""
    if not isrc or isrc == song.isrc:
        return
    alts = list(song.alternate_isrcs or [])
    if isrc in alts:
        return
    alts.append(isrc)
    Song.objects.filter(id=song.id).update(alternate_isrcs=alts)


_QUEUETIP_DOWNLOAD_QUEUE = "queuetip-downloads"
_QUEUETIP_DOWNLOAD_PRIORITY = 9  # Highest priority; these are user-triggered.


def _queue_download(song: Song) -> None:
    if song.downloaded:
        return
    if song.deezer_id:
        download_deezer_track.apply_async(
            args=[song.id],
            queue=_QUEUETIP_DOWNLOAD_QUEUE,
            priority=_QUEUETIP_DOWNLOAD_PRIORITY,
        )
    elif song.gid:
        download_track_by_spotify_gid.apply_async(
            args=[song.gid],
            queue=_QUEUETIP_DOWNLOAD_QUEUE,
            priority=_QUEUETIP_DOWNLOAD_PRIORITY,
        )
    # youtube-only songs: no single-track download task exists for that source.
    # Queuing a download is never a gate for ingest, so a silent skip is correct.


def ingest_track(candidate: TrackCandidate) -> Song:
    """Match or create a Song for `candidate`, queue its download, return the Song."""
    song = _find_existing_song(candidate)
    if song is None:
        song = _create_song(candidate)
    song = enrich_song_cross_platform(song)
    _queue_download(song)
    return song
