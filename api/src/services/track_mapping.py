"""Track mapping service — resolves external tracks to local/provider tracks.

Spotify track ids and Deezer track ids live in different namespaces. Every
result carries an explicit ``provider`` next to its ``provider_id`` so that no
consumer has to guess which one a string is, and a Deezer id can never be
queued as a Spotify gid (or the reverse).
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from library_manager.models import (
    Song,
    TrackMappingCache,
)
from src.providers.rate_limit import check_api_rate_limit

logger = logging.getLogger(__name__)

LISTENBRAINZ_LABS_BASE = "https://labs.api.listenbrainz.org"
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_USER_AGENT = "TuneStash/1.0 (https://github.com/tunestash)"

MIN_CONFIDENCE_THRESHOLD = 0.6

PROVIDER_SPOTIFY = "spotify"
PROVIDER_DEEZER = "deezer"

# Method recorded on a row whose mapping failed for a temporary reason; such
# rows are retried and never cached as "no match".
METHOD_ERROR = "error"


class TransientMappingError(Exception):
    """A provider was unavailable, so "not found" cannot be concluded."""


@dataclass(frozen=True)
class MappingResult:
    """Outcome of mapping one external track.

    ``provider_id`` is a Spotify track id when ``provider`` is ``"spotify"``
    and a Deezer track id (decimal string) when it is ``"deezer"``. ``song_id``
    is set when the track already exists locally, whichever namespace it was
    found through. ``retryable`` marks a temporary failure.
    """

    provider: Optional[str] = None
    provider_id: Optional[str] = None
    method: str = "pending"
    confidence: float = 0.0
    error: Optional[str] = None
    song_id: Optional[int] = None
    retryable: bool = False

    @property
    def mapped(self) -> bool:
        return self.song_id is not None or self.provider_id is not None


def _make_cache_key(artist: str, track: str) -> str:
    """Create a normalized lookup key for the cache."""
    return f"{artist.lower().strip()}::{track.lower().strip()}"


# =============================================================================
# Resolution Pipeline Steps
# =============================================================================


def check_local_song_db(artist_name: str, track_name: str) -> Optional[Song]:
    """Step 0: Check if the song already exists in our local DB."""
    # Try by exact artist+name match (case-insensitive)
    song = (
        Song.objects.filter(
            primary_artist__name__iexact=artist_name.strip(),
            name__iexact=track_name.strip(),
        )
        .select_related("primary_artist")
        .first()
    )
    if song:
        logger.debug(
            "[TRACK_MAPPING] Local DB match for '%s - %s' -> Song %s",
            artist_name,
            track_name,
            song.pk,
        )
    return song


def check_cache(
    artist_name: str, track_name: str, musicbrainz_id: Optional[str] = None
) -> Optional[TrackMappingCache]:
    """Step 1: Check the mapping cache."""
    if musicbrainz_id:
        cached = TrackMappingCache.objects.filter(musicbrainz_id=musicbrainz_id).first()
        if cached:
            return cached

    cache_key = _make_cache_key(artist_name, track_name)
    return TrackMappingCache.objects.filter(name_lookup_key=cache_key).first()


def resolve_via_listenbrainz_labs(
    mbids: list[str],
) -> dict[str, Optional[str]]:
    """Step 2: Batch resolve MBIDs to Spotify IDs via ListenBrainz Labs.

    Args:
        mbids: List of MusicBrainz IDs (up to 25 per request).

    Returns:
        Dict mapping MBID -> Spotify track ID, or None when Labs answered that
        it has none. An MBID whose batch failed is *absent* from the result: an
        outage is not a negative answer.
    """
    if not mbids:
        return {}

    check_api_rate_limit("listenbrainz_labs")

    results: dict[str, Optional[str]] = {}
    # Process in batches of 25
    for i in range(0, len(mbids), 25):
        batch = mbids[i : i + 25]
        try:
            payload = [{"recording_mbid": mbid} for mbid in batch]
            resp = requests.post(
                f"{LISTENBRAINZ_LABS_BASE}/spotify-id-from-mbid/json",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            answered: dict[str, Optional[str]] = {}
            for item in resp.json():
                mbid = item.get("recording_mbid", "")
                spotify_ids = item.get("spotify_track_ids") or []
                answered[mbid] = spotify_ids[0] if spotify_ids else None
            results.update(answered)
            for mbid in batch:
                # Labs omits recordings it has nothing for; a successful
                # response that lacks an MBID is a definitive "none".
                results.setdefault(mbid, None)
        except Exception as e:
            logger.warning("[TRACK_MAPPING] ListenBrainz Labs batch error: %s", e)

        if i + 25 < len(mbids):
            check_api_rate_limit("listenbrainz_labs")

    return results


def resolve_via_musicbrainz(mbid: str) -> Optional[int]:
    """Step 3: Resolve MBID -> ISRC via MusicBrainz, then look the ISRC up on Deezer.

    Returns the Deezer track id, or None when the recording has no ISRC or
    Deezer has no such track. Raises ``TransientMappingError`` when either
    service could not answer.
    """
    check_api_rate_limit("musicbrainz")

    try:
        resp = requests.get(
            f"{MUSICBRAINZ_API_BASE}/recording/{mbid}",
            params={"inc": "isrcs", "fmt": "json"},
            headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("[TRACK_MAPPING] MusicBrainz lookup error for %s: %s", mbid, e)
        raise TransientMappingError(f"MusicBrainz unavailable: {e}") from e

    isrcs = data.get("isrcs", [])
    if not isrcs:
        return None
    return _deezer_search_by_isrc(isrcs[0])


def _deezer_search_by_isrc(isrc: str) -> Optional[int]:
    """Search Deezer for a track by ISRC. Returns deezer_id or None."""
    try:
        from src.providers.deezer import DeezerMetadataProvider

        result = DeezerMetadataProvider().get_track_by_isrc(isrc, raise_errors=True)
    except Exception as e:
        logger.warning("[TRACK_MAPPING] Deezer ISRC search error for %s: %s", isrc, e)
        raise TransientMappingError(f"Deezer unavailable: {e}") from e
    return result.deezer_id if result else None


def resolve_via_deezer_search(
    artist_name: str, track_name: str
) -> tuple[Optional[int], float]:
    """Step 4: Search Deezer by artist+track name with confidence scoring.

    Returns:
        (deezer_track_id, confidence) — None and 0.0 if no match. Raises
        ``TransientMappingError`` when Deezer could not answer.
    """
    try:
        from downloader.track_matcher import score_track_match

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        results = provider.search_tracks(
            f"{artist_name} {track_name}", limit=5, raise_errors=True
        )
    except Exception as e:
        logger.warning(
            "[TRACK_MAPPING] Deezer search error for '%s - %s': %s",
            artist_name,
            track_name,
            e,
        )
        raise TransientMappingError(f"Deezer unavailable: {e}") from e

    if not results:
        return None, 0.0

    best_id: Optional[int] = None
    best_confidence = 0.0

    for item in results:
        confidence = score_track_match(
            search_title=track_name,
            search_artist=artist_name,
            result_title=item.name,
            result_artist=item.artist_name or "",
        )

        if confidence > best_confidence:
            best_confidence = confidence
            best_id = item.deezer_id

    return best_id, best_confidence


# =============================================================================
# Result construction
# =============================================================================


def _spotify_result(spotify_id: str, method: str, confidence: float) -> MappingResult:
    song = Song.objects.filter(gid=spotify_id).first()
    return MappingResult(
        provider=PROVIDER_SPOTIFY,
        provider_id=spotify_id,
        method=method,
        confidence=confidence,
        song_id=song.pk if song else None,
    )


def _deezer_result(deezer_id: int, method: str, confidence: float) -> MappingResult:
    song = Song.objects.filter(deezer_id=deezer_id).first()
    return MappingResult(
        provider=PROVIDER_DEEZER,
        provider_id=str(deezer_id),
        method=method,
        confidence=confidence,
        song_id=song.pk if song else None,
    )


def _local_result(song: Song) -> MappingResult:
    """A song that already exists locally, in whichever namespace it has."""
    if song.gid:
        provider, provider_id = PROVIDER_SPOTIFY, str(song.gid)
    elif song.deezer_id:
        provider, provider_id = PROVIDER_DEEZER, str(song.deezer_id)
    else:
        provider, provider_id = None, None
    return MappingResult(
        provider=provider,
        provider_id=provider_id,
        method="local_db",
        confidence=1.0,
        song_id=song.pk,
    )


def _cached_result(cached: TrackMappingCache) -> Optional[MappingResult]:
    """Interpret a positive cache row, keeping the two id namespaces apart.

    Older rows stored a Deezer id in ``spotify_track_id`` (as a decimal
    string); a Spotify id is never purely numeric.
    """
    method = f"cache_{cached.mapping_method}"
    spotify_id = cached.spotify_track_id
    if spotify_id and not spotify_id.isdigit():
        result = _spotify_result(spotify_id, method, cached.confidence)
        return result
    deezer_id = cached.deezer_track_id
    if deezer_id is None and spotify_id and spotify_id.isdigit():
        deezer_id = int(spotify_id)
    if deezer_id is not None:
        return _deezer_result(int(deezer_id), method, cached.confidence)
    return None


# =============================================================================
# Main Mapping Entry Point
# =============================================================================


class TrackMappingService:
    """Orchestrates the track mapping pipeline."""

    def map_track(
        self,
        artist_name: str,
        track_name: str,
        musicbrainz_id: Optional[str] = None,
    ) -> MappingResult:
        """Map a single track."""
        return self.map_tracks_batch([(artist_name, track_name, musicbrainz_id)])[0]

    def map_tracks_batch(
        self,
        tracks: list[tuple[str, str, Optional[str]]],
    ) -> list[MappingResult]:
        """Map a batch of tracks, using batch APIs where possible.

        Args:
            tracks: List of (artist_name, track_name, musicbrainz_id) tuples.

        Returns:
            One MappingResult per input track, in order.
        """
        results: list[Optional[MappingResult]] = [None] * len(tracks)
        # Tracks where a provider could not answer: never cached as no-match.
        transient: dict[int, str] = {}

        # Separate tracks that have MBIDs for batch resolution
        mbid_indices: dict[str, list[int]] = {}
        remaining_indices: list[int] = []

        for i, (artist, track, mbid) in enumerate(tracks):
            # Step 0: Local DB check
            song = check_local_song_db(artist, track)
            if song:
                results[i] = _local_result(song)
                continue

            # Step 1: Cache check
            cached = check_cache(artist, track, mbid)
            if cached:
                if cached.no_match:
                    results[i] = MappingResult(
                        method="cache_negative", error="Previously failed to map"
                    )
                    continue
                cached_result = _cached_result(cached)
                if cached_result is not None:
                    results[i] = cached_result
                    continue

            if mbid:
                mbid_indices.setdefault(mbid, []).append(i)
            else:
                remaining_indices.append(i)

        # Step 2: Batch MBID resolution via ListenBrainz Labs
        if mbid_indices:
            all_mbids = list(mbid_indices.keys())
            lb_results = resolve_via_listenbrainz_labs(all_mbids)

            for mbid, indices in mbid_indices.items():
                spotify_id = lb_results.get(mbid)
                if spotify_id:
                    for idx in indices:
                        artist, track, _ = tracks[idx]
                        self._cache_result(
                            artist,
                            track,
                            mbid,
                            "listenbrainz_labs",
                            1.0,
                            spotify_track_id=spotify_id,
                        )
                        results[idx] = _spotify_result(
                            spotify_id, "listenbrainz_labs", 1.0
                        )
                else:
                    if mbid not in lb_results:
                        for idx in indices:
                            transient[idx] = "ListenBrainz Labs unavailable"
                    # Fall through to individual resolution
                    remaining_indices.extend(indices)

        # Remaining tracks: individual resolution (Steps 3-4)
        for idx in remaining_indices:
            artist, track, mbid = tracks[idx]

            # Step 3: MBID -> MusicBrainz -> ISRC -> Deezer
            if mbid:
                try:
                    deezer_id = resolve_via_musicbrainz(mbid)
                except TransientMappingError as e:
                    transient[idx] = str(e)
                    deezer_id = None
                if deezer_id:
                    self._cache_result(
                        artist,
                        track,
                        mbid,
                        "musicbrainz_isrc",
                        1.0,
                        deezer_track_id=deezer_id,
                    )
                    results[idx] = _deezer_result(deezer_id, "musicbrainz_isrc", 1.0)
                    continue

            # Step 4: Deezer name search
            try:
                deezer_id, confidence = resolve_via_deezer_search(artist, track)
            except TransientMappingError as e:
                transient[idx] = str(e)
                deezer_id, confidence = None, 0.0
            if deezer_id and confidence >= MIN_CONFIDENCE_THRESHOLD:
                song = Song.objects.filter(deezer_id=deezer_id).first()
                self._cache_result(
                    artist,
                    track,
                    mbid,
                    "deezer_search",
                    confidence,
                    spotify_track_id=song.gid if song and song.gid else None,
                    deezer_track_id=deezer_id,
                )
                results[idx] = _deezer_result(deezer_id, "deezer_search", confidence)
            elif idx in transient:
                results[idx] = MappingResult(
                    method=METHOD_ERROR,
                    error=f"Temporary error, will retry: {transient[idx]}"[:255],
                    retryable=True,
                )
            else:
                # Every provider answered and none had a match: definitive.
                self._cache_negative(artist, track, mbid)
                error = (
                    f"No match (best confidence: {confidence:.2f})"
                    if deezer_id
                    else "No results from any resolution method"
                )
                results[idx] = MappingResult(method="none", error=error)

        return [r if r is not None else MappingResult() for r in results]

    def _cache_result(
        self,
        artist_name: str,
        track_name: str,
        musicbrainz_id: Optional[str],
        method: str,
        confidence: float,
        spotify_track_id: Optional[str] = None,
        deezer_track_id: Optional[int] = None,
    ) -> None:
        """Cache a positive mapping result, one id per namespace."""
        cache_key = _make_cache_key(artist_name, track_name)
        defaults = {
            "name_lookup_key": cache_key,
            "spotify_track_id": spotify_track_id,
            "deezer_track_id": deezer_track_id,
            "confidence": confidence,
            "mapping_method": method,
            "no_match": False,
        }
        try:
            if musicbrainz_id:
                TrackMappingCache.objects.update_or_create(
                    musicbrainz_id=musicbrainz_id,
                    defaults=defaults,
                )
            else:
                TrackMappingCache.objects.update_or_create(
                    name_lookup_key=cache_key,
                    defaults=defaults,
                )
        except Exception as e:
            logger.warning("[TRACK_MAPPING] Cache write error: %s", e)

    def _cache_negative(
        self,
        artist_name: str,
        track_name: str,
        musicbrainz_id: Optional[str],
    ) -> None:
        """Cache a definitive (no match) result."""
        cache_key = _make_cache_key(artist_name, track_name)
        try:
            if musicbrainz_id:
                TrackMappingCache.objects.update_or_create(
                    musicbrainz_id=musicbrainz_id,
                    defaults={
                        "name_lookup_key": cache_key,
                        "no_match": True,
                        "mapping_method": "none",
                        "confidence": 0.0,
                    },
                )
            else:
                TrackMappingCache.objects.update_or_create(
                    name_lookup_key=cache_key,
                    defaults={
                        "no_match": True,
                        "mapping_method": "none",
                        "confidence": 0.0,
                    },
                )
        except Exception as e:
            logger.warning("[TRACK_MAPPING] Cache write error: %s", e)
