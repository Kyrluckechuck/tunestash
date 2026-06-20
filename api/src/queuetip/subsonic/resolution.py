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

from .client import SubsonicClient, SubsonicError, SubsonicTrack

logger = logging.getLogger(__name__)

# A track is considered a fuzzy match only when at least this fraction of
# the queuetip title's significant characters appear in the candidate's title.
# Tuned conservative — false negatives are recoverable (user can fix the tag
# on Navidrome) but false positives put the wrong track in the user's playlist.
FUZZY_TITLE_THRESHOLD = 0.85

# Version / variant markers we should preserve in canonical song identity.
# We use this only to prevent risky plain-title ↔ remix/version matches in
# non-authoritative rungs (title/artist + fuzzy).
_REMIX_MARKER_RE = re.compile(r"\b(remix|mix|edit|vip)\b", re.IGNORECASE)
_VERSION_MARKER_RE = re.compile(
    r"\b(remaster|remastered|live|acoustic|instrumental|demo|mono|stereo)\b",
    re.IGNORECASE,
)
_TRAILING_PAREN_SUFFIX_RE = re.compile(r"\s*[\(\[][^\)\]]+[\)\]]\s*$")


def resolve_song_to_subsonic_id(
    *,
    title: str,
    artist: str,
    isrc: str | None,
    client: SubsonicClient,
    file_path: str | None = None,
) -> str | None:
    """Walk the resolution ladder against the user's Subsonic server.

    Pure read-only — never mutates queuetip or remote state.

    Precedence (most → least confident):
      1. File path — when TuneStash and the Subsonic server share the music
         mount, the queuetip Song.file_path matches a candidate's server
         path. This is a same-file match, definitive, immune to tag drift.
         Navidrome may expose normalized filenames, so we also accept a shared
         artist/album directory plus exact title/artist match before ISRC.
      2. ISRC exact (when the server populates + indexes it).
      3. Title + artist exact (artist matched against the credited-artist
         list, version-qualifier suffixes stripped).
      4. Fuzzy title + artist.
      5. Base-title fallback + artist — last resort for release naming drift
         where the same recording is indexed without an appended subtitle.

    The caller passes already-resolved strings rather than a Song object so
    this module stays decoupled from the ORM (easy to unit-test, no DB).
    `file_path` is optional — omit it for non-shared-library setups.
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title and not artist:
        return None

    norm_title = _normalize(title)
    norm_artist = _normalize(artist)

    # Gather candidates from several searches, deduped by id. ISRC search
    # first (cheap, sometimes definitive), then "title artist" (biases the
    # server's relevance toward the right recording for common titles), then
    # bare title (catches differing artist strings on compilations).
    seen: dict[str, SubsonicTrack] = {}

    def _add(query: str, count: int) -> None:
        try:
            for cand in client.search_tracks(query, song_count=count):
                seen.setdefault(cand.id, cand)
        except SubsonicError as exc:
            logger.warning("[subsonic] search failed for %s: %s", query, exc)

    if isrc:
        _add(isrc, 10)
    if title:
        _add(f"{title} {artist}".strip(), 50)
        _add(title, 50)
    # No early-out on an empty candidate list: each rung simply iterates
    # nothing and we fall through to the final `return None`.
    candidates = list(seen.values())

    # Rung 1: file-path (same-file) match — highest confidence.
    if file_path:
        path_match = _resolve_by_path(
            candidates,
            file_path=file_path,
            norm_title=norm_title,
            norm_artist=norm_artist,
            wanted_kind=_title_variant_kind(title),
        )
        if path_match:
            return path_match

    # Rung 2: ISRC exact match.
    if isrc:
        isrc_match = _resolve_by_isrc(candidates, isrc)
        if isrc_match:
            return isrc_match

    # Rung 3: exact normalized title + artist-list membership.
    if title:
        return _resolve_by_title(candidates, title, norm_title, norm_artist)

    return None


def _resolve_by_isrc(candidates: list[SubsonicTrack], isrc: str) -> str | None:
    for cand in candidates:
        if cand.isrc and cand.isrc.lower() == isrc.lower():
            return cand.id
    return None


def _resolve_by_title(
    candidates: list[SubsonicTrack],
    title: str,
    norm_title: str,
    norm_artist: str,
) -> str | None:
    wanted_kind = _title_variant_kind(title)
    for cand in candidates:
        if (
            _normalize(cand.title) == norm_title
            and _artist_matches(norm_artist, cand)
            and _title_variant_kind(cand.title) == wanted_kind
        ):
            return cand.id

    # Rung 4: fuzzy title + artist-list membership. Skip without an artist
    # constraint — too risky on title alone.
    if norm_artist:
        for cand in candidates:
            if (
                _artist_matches(norm_artist, cand)
                and _title_variant_kind(cand.title) == wanted_kind
                and _fuzzy_title_score(norm_title, _normalize(cand.title))
                >= FUZZY_TITLE_THRESHOLD
            ):
                return cand.id

    # Rung 5: base-title fallback. If the exact version is missing on the
    # server, allow a same-artist match on the title with trailing
    # parenthetical/bracket suffixes removed. This keeps "exact first" but
    # lets release naming drift fall back to the underlying recording.
    if norm_artist and wanted_kind == "plain":
        fallback_title = _normalize(_strip_trailing_suffixes(title))
        for cand in candidates:
            if (
                _artist_matches(norm_artist, cand)
                and _title_variant_kind(cand.title) == "plain"
                and _normalize(_strip_trailing_suffixes(cand.title)) == fallback_title
            ):
                return cand.id
    return None


def _resolve_by_path(
    candidates: list[SubsonicTrack],
    *,
    file_path: str,
    norm_title: str,
    norm_artist: str,
    wanted_kind: str,
) -> str | None:
    for cand in candidates:
        if cand.path and _paths_match(file_path, cand.path):
            return cand.id
    for cand in candidates:
        if (
            cand.path
            and _path_directory_matches(file_path, cand.path)
            and _normalize(cand.title) == norm_title
            and _artist_matches(norm_artist, cand)
            and _title_variant_kind(cand.title) == wanted_kind
        ):
            return cand.id
    return None


def _paths_match(tunestash_path: str, server_relative_path: str) -> bool:
    """True if a queuetip Song.file_path and a Subsonic server path point at
    the same file on a shared mount.

    The server returns a path relative to ITS music root
    (``Artist/Album/01 - Track.m4a``); TuneStash stores an absolute path
    (``/mnt/music/Artist/Album/01 - Track.m4a``). On a shared mount the
    absolute path ends with the relative one — that suffix match is the whole
    point of this rung.

    We deliberately do NOT fall back to a basename-only match: two different
    recordings can share a filename across albums (``01 - Intro.m4a``,
    ``Help!.m4a`` on a compilation vs the original), and matching on filename
    alone would route the wrong track into the playlist. A non-shared-library
    setup simply falls through to the content rungs (ISRC / title+artist).
    """
    ts = tunestash_path.strip().replace("\\", "/").lower()
    rel = server_relative_path.strip().replace("\\", "/").lstrip("/").lower()
    if not ts or not rel:
        return False
    return ts.endswith("/" + rel) or ts == rel


def _path_directory_matches(tunestash_path: str, server_relative_path: str) -> bool:
    ts_parts = _path_parts(tunestash_path)
    rel_parts = _path_parts(server_relative_path)
    if len(ts_parts) < 2 or len(rel_parts) < 2:
        return False
    ts_dir = ts_parts[:-1]
    rel_dir = rel_parts[:-1]
    return len(rel_dir) <= len(ts_dir) and ts_dir[-len(rel_dir) :] == rel_dir


def _path_parts(value: str) -> list[str]:
    normalized = value.strip().replace("\\", "/").strip("/").lower()
    return [part for part in normalized.split("/") if part]


def _artist_matches(norm_artist: str, cand: SubsonicTrack) -> bool:
    """True if the queuetip primary artist matches the candidate.

    Matches against the candidate's structured artist LIST (not just the
    display string), so a queuetip primary artist like "Maejor" matches a
    Navidrome track credited "Maejor • Juicy J • Justin Bieber" — the SAME
    recording with featured artists. Crucially this does NOT match a cover
    by a different artist (e.g. queuetip "Reel 2 Real" won't match a
    will.i.am version), preserving precision against wrong-version matches.

    An empty queuetip artist matches anything (caller gates fuzzy on a
    non-empty artist, so this only relaxes the exact-title path).
    """
    if not norm_artist:
        return True
    # Build the candidate's credited-artist set from the structured list,
    # falling back to the display string.
    names = cand.artists or [cand.artist]
    candidate_artists = {_normalize(n) for n in names if n}
    if norm_artist in candidate_artists:
        return True
    # Also accept the full display string match (single-artist tracks where
    # the list wasn't returned).
    return _normalize(cand.artist) == norm_artist


def _normalize(value: str) -> str:
    """Lower-case, trim, collapse whitespace, strip noisy punctuation.

    Two non-obvious decisions:
      * Apostrophes are DELETED rather than substituted with space, so
        "Don't" → "dont" matches "Dont" → "dont". Substituting would split
        "Don't" into "don t" which then doesn't match "Dont".
      * Only a TRAILING parenthetical that contains a version keyword is
        stripped ("Bohemian Rhapsody (Remastered)" → "bohemian rhapsody",
        "Song (2011 Remaster)" → "song"). Leading or embedded parentheticals
        carry meaning and MUST survive — stripping all of them would turn
        "(Don't Fear) The Reaper" into "the reaper" and "Jump (For My Love)"
        into "jump", producing wrong-track matches.
    """
    lowered = value.lower().strip()
    # Delete apostrophes (both curly and straight) before generic punctuation
    # substitution so "don't" collapses to "dont" not "don t".
    lowered = lowered.replace("'", "").replace("’", "")
    # Replace remaining punctuation with space, then collapse whitespace.
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _title_variant_kind(value: str) -> str:
    """Classify a title into plain/remix/versioned.

    This is used to prevent unsafe fallback matches between different variants
    of the same base title when ISRC/path are unavailable.
    """
    if _REMIX_MARKER_RE.search(value):
        return "remix"
    if _VERSION_MARKER_RE.search(value):
        return "versioned"
    return "plain"


def _strip_trailing_suffixes(value: str) -> str:
    """Remove trailing parenthetical/bracket suffixes.

    Used only for the final fallback rung when exact title matching fails.
    """
    stripped = value.strip()
    while True:
        next_value = _TRAILING_PAREN_SUFFIX_RE.sub("", stripped).strip()
        if next_value == stripped:
            return stripped
        stripped = next_value


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
