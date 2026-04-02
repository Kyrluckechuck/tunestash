"""Shared track matching module.

Provides scoring functions for comparing a search query (title + artist)
against candidate results from download providers. Designed to be the
single source of truth for match quality decisions across playlist sync,
M3U resolution, and individual track downloads.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

_PAREN_TAG_RE = re.compile(r"\s*[\(\[][^\)\]]+[\)\]]")
_TRADEMARK_RE = re.compile(r"[™®©]")
_NON_ALNUM_RE = re.compile(r"[^\w\s]")
_MULTI_SPACE_RE = re.compile(r"\s+")

_LANGUAGE_MARKERS = {
    "spanish",
    "espanol",
    "en espanol",
    "version en espanol",
    "spanish version",
    "italian",
    "italiana",
    "versione italiana",
    "french",
    "french version",
    "version francaise",
    "german",
    "german version",
    "deutsche version",
    "japanese",
    "japanese version",
    "korean",
    "korean version",
    "portuguese",
    "portuguese version",
    "hindi",
    "hindi version",
    "chinese",
    "chinese version",
    "arabic",
    "arabic version",
    "russian",
    "russian version",
    "turkish",
    "turkish version",
}

_VARIANT_MARKERS = {
    "remix",
    "acoustic",
    "live",
    "instrumental",
    "demo",
    "radio edit",
    "radio version",
    "radio mix",
    "club mix",
    "club version",
    "extended",
    "extended mix",
    "stripped",
    "unplugged",
    "a cappella",
    "acapella",
    "karaoke",
    "sped up",
    "slowed",
}

_MINOR_MARKERS = {
    "remaster",
    "remastered",
    "deluxe",
    "bonus",
    "bonus track",
    "anniversary",
    "expanded",
    "special edition",
}

_FEAT_RE = re.compile(r"^(feat\.?|ft\.?|featuring)\s+", re.IGNORECASE)


def extract_title_tags(title: str) -> tuple[str, list[str]]:
    """Extract parenthetical/bracket tags from a song title.

    Returns (core_title, [tag1, tag2, ...]) where tags are lowercased
    inner text from (...) and [...] blocks.
    """
    tags: list[str] = []
    for match in _PAREN_TAG_RE.finditer(title):
        raw = match.group()
        inner = raw.strip()
        # Strip the outer parens/brackets
        inner = inner[1:-1].strip()
        if inner:
            tags.append(inner.lower())

    core = _PAREN_TAG_RE.sub("", title).strip()
    return core, tags


def normalize_for_matching(name: str) -> str:
    """Normalize a string for fuzzy comparison.

    Handles accent stripping, punctuation removal, trademark symbols,
    and ampersand/and equivalence.
    """
    s = name.replace("&", " and ")
    s = _TRADEMARK_RE.sub("", s)
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s.lower()


def _classify_tag(tag: str) -> Optional[str]:
    """Classify a tag into a severity category."""
    normalized = tag.strip().lower()

    if _FEAT_RE.match(normalized):
        return "feat"

    for marker in _LANGUAGE_MARKERS:
        if marker in normalized:
            return "language"

    for marker in _VARIANT_MARKERS:
        if marker in normalized:
            return "variant"

    for marker in _MINOR_MARKERS:
        if marker in normalized:
            return "minor"

    return None


def compute_tag_penalty(source_tags: list[str], result_tags: list[str]) -> float:
    """Compute a penalty score for mismatched tags between source and result.

    Higher penalty = worse match. Capped at 0.5.
    Compares (category, normalized_text) pairs so that two different
    variants (e.g., Remix vs Acoustic) are correctly penalized.
    """
    source_pairs = set()
    for t in source_tags:
        cls = _classify_tag(t)
        if cls and cls != "feat":
            source_pairs.add((cls, normalize_for_matching(t)))

    result_pairs = set()
    for t in result_tags:
        cls = _classify_tag(t)
        if cls and cls != "feat":
            result_pairs.add((cls, normalize_for_matching(t)))

    if source_pairs == result_pairs:
        return 0.0

    penalty = 0.0

    # Tags present in result but not in source
    for cls, _ in result_pairs - source_pairs:
        if cls == "language":
            penalty += 0.35
        elif cls == "variant":
            penalty += 0.25
        elif cls == "minor":
            penalty += 0.08

    # Tags present in source but not in result
    for cls, _ in source_pairs - result_pairs:
        if cls == "language":
            penalty += 0.30
        elif cls == "variant":
            penalty += 0.15
        elif cls == "minor":
            penalty += 0.05

    return min(penalty, 0.5)


def score_track_match(
    search_title: str,
    search_artist: str,
    result_title: str,
    result_artist: str,
    *,
    search_isrc: Optional[str] = None,
    result_isrc: Optional[str] = None,
    search_duration_s: Optional[float] = None,
    result_duration_s: Optional[float] = None,
    duration_tolerance_s: float = 10.0,
) -> float:
    """Score how well a search result matches a search query.

    Returns a float in [0, 1] where 1.0 is a perfect match.
    """
    # Extract tags and get core titles
    source_core, source_tags = extract_title_tags(search_title)
    result_core, result_tags = extract_title_tags(result_title)

    norm_source_title = normalize_for_matching(source_core)
    norm_result_title = normalize_for_matching(result_core)
    norm_source_artist = normalize_for_matching(search_artist)
    norm_result_artist = normalize_for_matching(result_artist)

    title_sim = SequenceMatcher(None, norm_source_title, norm_result_title).ratio()
    artist_sim = SequenceMatcher(None, norm_source_artist, norm_result_artist).ratio()

    weighted_score = 0.0
    weights_used = 0.0

    # Title: weight 0.35
    weighted_score += 0.35 * title_sim
    weights_used += 0.35

    # Artist: weight 0.35
    weighted_score += 0.35 * artist_sim
    weights_used += 0.35

    # ISRC: weight 0.20 (only if both provided)
    if search_isrc and result_isrc:
        isrc_match = 1.0 if search_isrc.upper() == result_isrc.upper() else 0.0
        weighted_score += 0.20 * isrc_match
        weights_used += 0.20

    # Duration: weight 0.10 (only if both provided)
    if search_duration_s is not None and result_duration_s is not None:
        diff = abs(search_duration_s - result_duration_s)
        if diff <= duration_tolerance_s:
            duration_sim = 1.0 - (diff / duration_tolerance_s)
        else:
            duration_sim = 0.0
        weighted_score += 0.10 * duration_sim
        weights_used += 0.10

    # Normalize by weights actually used
    if weights_used > 0:
        score = weighted_score / weights_used
    else:
        score = 0.0

    # Apply tag penalty
    tag_penalty = compute_tag_penalty(source_tags, result_tags)
    score -= tag_penalty

    return max(0.0, min(1.0, score))


# Single > Album > EP > Compilation > Other
_ALBUM_TYPE_RANK: dict[str, int] = {
    "single": 5,
    "album": 4,
    "ep": 3,
    "compilation": 2,
}


def album_type_score(album_type: Optional[str]) -> int:
    """Return a preference rank for an album type. Higher is better."""
    if not album_type:
        return 1
    return _ALBUM_TYPE_RANK.get(album_type.lower(), 1)
