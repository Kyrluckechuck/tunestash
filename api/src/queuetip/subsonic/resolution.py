"""Resolve a queuetip Song to a track ID on a user's Subsonic server.

The ladder mirrors Spotify export's resolution strategy: ISRC first (exact,
when the server exposes it), then title + artist (case-insensitive, trimmed),
then fuzzy title with strict artist match.

Returns the Subsonic track ID on success, or None when no match is found.
The sync service collects the None cases into `unmatched_track_titles` and
optionally queues downloads for them.

Why each step exists:
  1. ISRC — canonical track identifier. When both queuetip and the Subsonic
     server have the ISRC tagged, this is the only correct match.
  2. Title + artist exact — handles servers that don't expose ISRC (most
     classic Subsonic implementations). Strict match avoids false positives
     for tracks with similar titles by different artists.
  3. Fuzzy title with exact artist — last resort for minor punctuation /
     capitalization / "(Remastered)" variations. Constrained to the right
     artist so we don't pick a cover or sample.
"""

from __future__ import annotations

import logging
import re

from .client import SubsonicClient, SubsonicError

logger = logging.getLogger(__name__)

# A track is considered a fuzzy match only when at least this fraction of
# the queuetip title's significant characters appear in the candidate's title.
# Tuned conservative — false negatives are recoverable (user can fix the tag
# on Navidrome) but false positives put the wrong track in the user's playlist.
FUZZY_TITLE_THRESHOLD = 0.85


def resolve_song_to_subsonic_id(
    *,
    title: str,
    artist: str,
    isrc: str | None,
    client: SubsonicClient,
) -> str | None:
    """Walk the resolution ladder against the user's Subsonic server.

    Pure read-only — never mutates queuetip or remote state.

    The caller is expected to pass already-resolved title/artist strings
    rather than a Song object, so this module stays decoupled from the
    queuetip ORM models (easier to unit-test with no DB).
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title and not artist:
        return None

    # 1. ISRC exact match.
    if isrc:
        try:
            candidates = client.search_tracks(isrc, song_count=10)
        except SubsonicError as exc:
            logger.warning("[subsonic] ISRC search failed for %s: %s", isrc, exc)
        else:
            for cand in candidates:
                # Some servers return ISRC in lowercase, others uppercase.
                if cand.isrc and cand.isrc.lower() == isrc.lower():
                    return cand.id

    # 2. Title + artist exact match.
    if title:
        try:
            candidates = client.search_tracks(title, song_count=20)
        except SubsonicError as exc:
            logger.warning("[subsonic] title search failed for %s: %s", title, exc)
            return None

        norm_title = _normalize(title)
        norm_artist = _normalize(artist)

        # Pass A: exact normalized match on both title and artist.
        for cand in candidates:
            if _normalize(cand.title) == norm_title and (
                not norm_artist or _normalize(cand.artist) == norm_artist
            ):
                return cand.id

        # Pass B: fuzzy title with strict artist match. Skip if no artist
        # constraint — too risky on title alone.
        if norm_artist:
            for cand in candidates:
                if (
                    _normalize(cand.artist) == norm_artist
                    and _fuzzy_title_score(norm_title, _normalize(cand.title))
                    >= FUZZY_TITLE_THRESHOLD
                ):
                    return cand.id

    return None


def _normalize(value: str) -> str:
    """Lower-case, trim, collapse whitespace, strip punctuation that's noisy
    for matching ('()', dashes, dots, apostrophes).
    """
    lowered = value.lower().strip()
    # Replace punctuation with space, then collapse runs of whitespace.
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _fuzzy_title_score(left: str, right: str) -> float:
    """Simple substring-overlap heuristic. Not as precise as Levenshtein, but
    avoids the dependency and is sufficient for the kinds of variation we
    care about — '(Remastered)' suffixes, missing apostrophes, etc.

    Returns a value in [0.0, 1.0]. 1.0 means exact match after normalization.
    """
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    # If one fully contains the other (after normalization), score = ratio
    # of the shorter to the longer. Handles "Title" vs "Title (Remastered)".
    if left in right:
        return len(left) / len(right)
    if right in left:
        return len(right) / len(left)
    # Otherwise: ratio of common-token-prefix-length to longer string.
    left_tokens = left.split()
    right_tokens = right.split()
    common = 0
    for lt, rt in zip(left_tokens, right_tokens):
        if lt == rt:
            common += len(lt) + 1
        else:
            break
    return common / max(len(left), len(right))
