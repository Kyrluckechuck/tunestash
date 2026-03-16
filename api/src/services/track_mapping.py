"""Track mapping service — resolves external tracks to Spotify IDs."""

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

import requests

from library_manager.models import (
    Song,
    TrackMappingCache,
)
from library_manager.tasks.core import normalize_name
from src.providers.rate_limit import check_api_rate_limit

logger = logging.getLogger(__name__)

LISTENBRAINZ_LABS_BASE = "https://labs.api.listenbrainz.org"
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_USER_AGENT = "TuneStash/1.0 (https://github.com/tunestash)"

MIN_CONFIDENCE_THRESHOLD = 0.6

# Compiled regexes for stripping feat/remix tags during track matching
_FEAT_BRACKET_RE = re.compile(
    r"\s*[\(\[](feat\.?|ft\.?|featuring)\s+[^\)\]]*[\)\]]", re.IGNORECASE
)
_FEAT_SUFFIX_RE = re.compile(r"\s*(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_REMASTER_RE = re.compile(
    r"\s*[\(\[](remaster(ed)?|deluxe|bonus)[^\)\]]*[\)\]]", re.IGNORECASE
)


def _normalize_name_for_track_matching(name: str) -> str:
    """Normalize a name for track matching, extending the base normalize_name.

    In addition to accent/punctuation/case normalization, this strips
    feat/ft/featuring tags and remaster/deluxe/bonus suffixes that are
    irrelevant for matching tracks across providers.
    """
    name = normalize_name(name)
    name = _FEAT_BRACKET_RE.sub("", name)
    name = _FEAT_SUFFIX_RE.sub("", name)
    name = _REMASTER_RE.sub("", name)
    return name.strip()


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
            song.gid,
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
        Dict mapping MBID -> Spotify track ID (or None if not found).
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
            for item in resp.json():
                mbid = item.get("recording_mbid", "")
                spotify_ids = item.get("spotify_track_ids") or []
                results[mbid] = spotify_ids[0] if spotify_ids else None
        except Exception as e:
            logger.warning("[TRACK_MAPPING] ListenBrainz Labs batch error: %s", e)
            for mbid in batch:
                results.setdefault(mbid, None)

        if i + 25 < len(mbids):
            check_api_rate_limit("listenbrainz_labs")

    return results


def resolve_via_musicbrainz(mbid: str) -> Optional[str]:
    """Step 3: Resolve MBID -> ISRC via MusicBrainz, then search Spotify by ISRC.

    Returns Spotify track ID if found, None otherwise.
    """
    check_api_rate_limit("musicbrainz")

    try:
        resp = requests.get(
            f"{MUSICBRAINZ_API_BASE}/recording/{mbid}",
            params={"inc": "isrcs", "fmt": "json"},
            headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        isrcs = data.get("isrcs", [])
        if not isrcs:
            return None

        isrc = isrcs[0]
        deezer_id = _deezer_search_by_isrc(isrc)
        if deezer_id:
            # Return the deezer_id as a string for pipeline compatibility
            return str(deezer_id)
        return None
    except Exception as e:
        logger.warning("[TRACK_MAPPING] MusicBrainz lookup error for %s: %s", mbid, e)
        return None


def _deezer_search_by_isrc(isrc: str) -> Optional[int]:
    """Search Deezer for a track by ISRC. Returns deezer_id or None."""
    try:
        from src.providers.deezer import DeezerMetadataProvider

        result = DeezerMetadataProvider().get_track_by_isrc(isrc)
        return result.deezer_id if result else None
    except Exception as e:
        logger.warning("[TRACK_MAPPING] Deezer ISRC search error for %s: %s", isrc, e)
        return None


def resolve_via_deezer_search(
    artist_name: str, track_name: str
) -> tuple[Optional[int], float]:
    """Step 4: Search Deezer by artist+track name with confidence scoring.

    Returns:
        (deezer_track_id, confidence) — None and 0.0 if no match.
    """
    try:
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        results = provider.search_tracks(f"{artist_name} {track_name}", limit=5)

        if not results:
            return None, 0.0

        norm_artist = _normalize_name_for_track_matching(artist_name)
        norm_track = _normalize_name_for_track_matching(track_name)

        best_id: Optional[int] = None
        best_confidence = 0.0

        for item in results:
            item_track = _normalize_name_for_track_matching(item.name)
            item_artist = _normalize_name_for_track_matching(item.artist_name or "")

            artist_sim = SequenceMatcher(None, norm_artist, item_artist).ratio()
            track_sim = SequenceMatcher(None, norm_track, item_track).ratio()

            if artist_sim >= 0.95 and track_sim >= 0.95:
                confidence = 1.0
            elif artist_sim >= 0.85 and track_sim >= 0.85:
                confidence = 0.9
            elif artist_sim >= 0.7 and track_sim >= 0.7:
                confidence = 0.7
            else:
                confidence = (artist_sim + track_sim) / 2.0

            if confidence > best_confidence:
                best_confidence = confidence
                best_id = item.deezer_id

        return best_id, best_confidence
    except Exception as e:
        logger.warning(
            "[TRACK_MAPPING] Deezer search error for '%s - %s': %s",
            artist_name,
            track_name,
            e,
        )
        return None, 0.0


# =============================================================================
# Main Mapping Entry Point
# =============================================================================


class TrackMappingService:
    """Orchestrates the track mapping pipeline."""

    def map_track(  # pylint: disable=too-many-return-statements
        self,
        artist_name: str,
        track_name: str,
        musicbrainz_id: Optional[str] = None,
    ) -> tuple[Optional[str], str, float, Optional[str]]:
        """Map a single track to a Spotify ID.

        Returns:
            (spotify_track_id, mapping_method, confidence, error_message)
        """
        # Step 0: Check local Song DB
        song = check_local_song_db(artist_name, track_name)
        if song:
            return song.gid, "local_db", 1.0, None

        # Step 1: Check cache
        cached = check_cache(artist_name, track_name, musicbrainz_id)
        if cached:
            if cached.no_match:
                return None, "cache_negative", 0.0, "Previously failed to map"
            if cached.spotify_track_id:
                return (
                    cached.spotify_track_id,
                    f"cache_{cached.mapping_method}",
                    cached.confidence,
                    None,
                )

        # Step 2: MBID -> ListenBrainz Labs
        if musicbrainz_id:
            lb_results = resolve_via_listenbrainz_labs([musicbrainz_id])
            spotify_id = lb_results.get(musicbrainz_id)
            if spotify_id:
                self._cache_result(
                    artist_name,
                    track_name,
                    musicbrainz_id,
                    spotify_id,
                    "listenbrainz_labs",
                    1.0,
                )
                return spotify_id, "listenbrainz_labs", 1.0, None

            # Step 3: MBID -> MusicBrainz -> ISRC -> Spotify
            spotify_id = resolve_via_musicbrainz(musicbrainz_id)
            if spotify_id:
                self._cache_result(
                    artist_name,
                    track_name,
                    musicbrainz_id,
                    spotify_id,
                    "musicbrainz_isrc",
                    1.0,
                )
                return spotify_id, "musicbrainz_isrc", 1.0, None

        # Step 4: Name-based Deezer search
        deezer_id, confidence = resolve_via_deezer_search(artist_name, track_name)
        if deezer_id and confidence >= MIN_CONFIDENCE_THRESHOLD:
            # Match Song by deezer_id to get gid for backwards compatibility
            song = Song.objects.filter(deezer_id=deezer_id).first()
            result_id = song.gid if song and song.gid else str(deezer_id)
            self._cache_result(
                artist_name,
                track_name,
                musicbrainz_id,
                result_id,
                "deezer_search",
                confidence,
                deezer_track_id=deezer_id,
            )
            return result_id, "deezer_search", confidence, None

        # No match found — cache negative result
        self._cache_negative(artist_name, track_name, musicbrainz_id)
        error = (
            f"No match (best confidence: {confidence:.2f})"
            if deezer_id
            else "No results from any resolution method"
        )
        return None, "none", 0.0, error

    def map_tracks_batch(
        self,
        tracks: list[tuple[str, str, Optional[str]]],
    ) -> list[tuple[Optional[str], str, float, Optional[str]]]:
        """Map a batch of tracks, using batch APIs where possible.

        Args:
            tracks: List of (artist_name, track_name, musicbrainz_id) tuples.

        Returns:
            List of (spotify_track_id, method, confidence, error) tuples.
        """
        results: list[tuple[Optional[str], str, float, Optional[str]]] = [
            (None, "pending", 0.0, None)
        ] * len(tracks)

        # Separate tracks that have MBIDs for batch resolution
        mbid_indices: dict[str, list[int]] = {}
        remaining_indices: list[int] = []

        for i, (artist, track, mbid) in enumerate(tracks):
            # Step 0: Local DB check
            song = check_local_song_db(artist, track)
            if song:
                results[i] = (song.gid, "local_db", 1.0, None)
                continue

            # Step 1: Cache check
            cached = check_cache(artist, track, mbid)
            if cached:
                if cached.no_match:
                    results[i] = (
                        None,
                        "cache_negative",
                        0.0,
                        "Previously failed to map",
                    )
                elif cached.spotify_track_id:
                    results[i] = (
                        cached.spotify_track_id,
                        f"cache_{cached.mapping_method}",
                        cached.confidence,
                        None,
                    )
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
                            spotify_id,
                            "listenbrainz_labs",
                            1.0,
                        )
                        results[idx] = (spotify_id, "listenbrainz_labs", 1.0, None)
                else:
                    # Fall through to individual resolution
                    remaining_indices.extend(indices)

        # Remaining tracks: individual resolution (Steps 3-4)
        for idx in remaining_indices:
            artist, track, mbid = tracks[idx]

            # Already resolved?
            if results[idx][1] != "pending":
                continue

            # Step 3: MBID -> MusicBrainz
            if mbid:
                spotify_id = resolve_via_musicbrainz(mbid)
                if spotify_id:
                    self._cache_result(
                        artist,
                        track,
                        mbid,
                        spotify_id,
                        "musicbrainz_isrc",
                        1.0,
                    )
                    results[idx] = (spotify_id, "musicbrainz_isrc", 1.0, None)
                    continue

            # Step 4: Deezer name search
            deezer_id, confidence = resolve_via_deezer_search(artist, track)
            if deezer_id and confidence >= MIN_CONFIDENCE_THRESHOLD:
                song = Song.objects.filter(deezer_id=deezer_id).first()
                result_id = song.gid if song and song.gid else str(deezer_id)
                self._cache_result(
                    artist,
                    track,
                    mbid,
                    result_id,
                    "deezer_search",
                    confidence,
                    deezer_track_id=deezer_id,
                )
                results[idx] = (result_id, "deezer_search", confidence, None)
            else:
                self._cache_negative(artist, track, mbid)
                error = (
                    f"No match (best confidence: {confidence:.2f})"
                    if deezer_id
                    else "No results from any resolution method"
                )
                results[idx] = (None, "none", 0.0, error)

        return results

    def _cache_result(
        self,
        artist_name: str,
        track_name: str,
        musicbrainz_id: Optional[str],
        spotify_track_id: str,
        method: str,
        confidence: float,
        deezer_track_id: Optional[int] = None,
    ) -> None:
        """Cache a positive mapping result."""
        cache_key = _make_cache_key(artist_name, track_name)
        defaults = {
            "name_lookup_key": cache_key,
            "spotify_track_id": spotify_track_id,
            "confidence": confidence,
            "mapping_method": method,
            "no_match": False,
        }
        if deezer_track_id is not None:
            defaults["deezer_track_id"] = deezer_track_id
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
        """Cache a negative (no match) result."""
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
