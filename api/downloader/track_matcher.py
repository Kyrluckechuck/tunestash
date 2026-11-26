"""Shared track matching module.

Provides scoring functions for comparing a search query (title + artist)
against candidate results from download providers. Designed to be the
single source of truth for match quality decisions across playlist sync,
M3U resolution, and individual track downloads.
"""

import re
import unicodedata
from collections.abc import Iterable
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

# Each family lists descriptors that mean the same version. Longer aliases
# come first so "extended mix" is not reduced to a bare "extended".
_VARIANT_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("remix", ("remix",)),
    ("acoustic", ("acoustic version", "acoustic")),
    ("live", ("live version", "live")),
    ("instrumental", ("instrumental version", "instrumental")),
    ("demo", ("demo",)),
    ("radio", ("radio edit", "radio version", "radio mix")),
    ("club", ("club mix", "club version")),
    ("extended", ("extended mix", "extended version", "extended")),
    ("stripped", ("stripped",)),
    ("unplugged", ("unplugged",)),
    ("a cappella", ("a cappella", "acapella")),
    ("karaoke", ("karaoke",)),
    ("sped up", ("sped up",)),
    ("slowed", ("slowed",)),
    ("piano", ("piano version", "piano")),
    ("mix cut", ("mix cut",)),
    ("mixed", ("mixed",)),
)

# Bare descriptors are variants only when they are the whole tag. Otherwise
# ordinary titles such as "(Piano Man)" or "(Mixed Emotions)" are misclassified.
_BARE_ONLY_VARIANT_MARKERS = {"piano", "mixed"}

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

# Artist credits use many separators across providers: commas and ampersands
# in metadata, bullets from YouTube Music, "feat"/"ft" in titles. Split on all
# of them so a collaboration is compared by its members rather than as one
# long string that fuzzily resembles an unrelated solo artist.
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|;|/|\||•|\+|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\band\b|\bx\b|\bvs\.?\b)\s*",
    re.IGNORECASE,
)
# Only these separators unambiguously introduce another credited artist.
# "&", "+", "/", "x" and "vs" stay intact so duo/band names such as
# "Hall & Oates", "Sultan + Shepard", "NIIKO X SWAE" and "AC/DC" are not
# mistaken for explicit multi-artist source credits.
_STRONG_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|;|\||•|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*",
    re.IGNORECASE,
)
_LEADING_THE_RE = re.compile(r"^the\s+")
_DASH_SUFFIX_RE = re.compile(r"\s[-–—]\s")

# Version words unambiguous enough to detect even without parentheses, so
# "Mixed" does not silently equal "Mix Cut" just because the characters are
# close. Single generic words such as "live" are intentionally excluded.
_STANDALONE_VARIANT_MARKERS = (
    "mix cut",
    "piano version",
    "extended mix",
    "extended version",
    "radio edit",
    "radio version",
    "radio mix",
    "live version",
    "club mix",
    "club version",
    "sped up",
    "slowed",
)

# A version/language conflict is disqualifying at every caller threshold
# (currently 0.6-0.7) without raising those thresholds for normal matches.
_VERSION_CONFLICT_CAP = 0.5

# A disagreeing ISRC alone still passes (regional/master duplicates are common).
# Only an independent identity conflict triggers the extra penalty; a duration
# difference accepted by the hard gate (max 8s, 5%) must not create a second,
# stricter gate here. Beyond that gate the provider rejects the candidate anyway.
_ISRC_CONFLICT_EXTRA_PENALTY = 0.35
_ISRC_CONFLICT_CAP = 0.5
_DURATION_GATE_MIN_S = 8.0
_DURATION_GATE_FRACTION = 0.05

# YouTube often lists only the lead artist of a collaboration. Missing a few
# featured credits only nudges the score down. Losing every featured credit
# costs more, but exact signals still pass a 0.7-threshold provider; another
# conflicting signal is needed to push the score below the acceptance line.
_MISSING_FEATURED_PENALTY = 0.05
_MISSING_ALL_FEATURED_PENALTY = 0.25


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

    # Spotify-style "Song - Foo Remix". Only a suffix that is a recognized
    # version/language/minor descriptor becomes a tag; any other hyphen is part
    # of the title ("Part 2 - The Return").
    dash_tags: list[str] = []
    while True:
        separators = list(_DASH_SUFFIX_RE.finditer(core))
        if not separators:
            break
        last = separators[-1]
        suffix = core[last.end() :].strip()
        if not core[: last.start()].strip() or not _classify_tag(suffix):
            break
        dash_tags.append(suffix.lower())
        core = core[: last.start()].strip()
    tags.extend(reversed(dash_tags))
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


# Stylized stage names commonly substitute punctuation for letters (P!nk,
# Ke$ha). Apply only these narrow, recognizable substitutions; arbitrary
# punctuation stripping would create unsafe aliases.
_ARTIST_ALIAS_TRANSLATION = str.maketrans(
    {
        "!": "i",
        "$": "s",
        "@": "a",
        "0": "o",
        "3": "e",
    }
)


def _normalize_artist_alias(artist: str) -> str:
    return normalize_for_matching(artist.translate(_ARTIST_ALIAS_TRANSLATION))


def _compact_artist_alias(artist: str) -> str:
    return re.sub(r"\s+", "", _normalize_artist_alias(artist))


def _artist_credit_tokens(artist: str) -> set[str]:
    """Split an artist credit into normalized individual artist names."""
    tokens: set[str] = set()
    for part in _ARTIST_SPLIT_RE.split(artist):
        normalized = _normalize_artist_alias(part)
        normalized = _LEADING_THE_RE.sub("", normalized).strip()
        if normalized:
            tokens.add(normalized)
    return tokens


def _token_appears_in(token: str, other: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", other) is not None


def _credit_is_band_alias(subset: set[str], superset: set[str]) -> bool:
    """Match a band's short credit to its members' full names.

    "Hall & Oates" versus "Daryl Hall & John Oates" needs every short-credit
    member to appear in a longer-credit member. Requiring at least two members
    keeps single-word lookalikes such as "Pink" versus "Pink Floyd" distinct.
    """
    if len(subset) < 2:
        return False
    return all(
        any(_token_appears_in(token, other) for other in superset) for token in subset
    )


def _artists_are_alias_equivalent(search_artist: str, result_artist: str) -> bool:
    """Return whether credits are the same name with benign spelling variation."""
    search_norm = _normalize_artist_alias(search_artist)
    result_norm = _normalize_artist_alias(result_artist)
    if not search_norm or not result_norm:
        return False
    if search_norm == result_norm:
        return True
    if _compact_artist_alias(search_artist) == _compact_artist_alias(result_artist):
        return True

    search_tokens = _artist_credit_tokens(search_artist)
    result_tokens = _artist_credit_tokens(result_artist)
    if search_tokens & result_tokens:
        return True
    if _credit_is_band_alias(search_tokens, result_tokens):
        return True
    if _credit_is_band_alias(result_tokens, search_tokens):
        return True

    # Tolerate small spelling differences within a single credit, but not the
    # much larger gap between unrelated names.
    for search_token in search_tokens:
        for result_token in result_tokens:
            if SequenceMatcher(None, search_token, result_token).ratio() >= 0.9:
                return True
    return False


def artists_are_compatible(search_artist: str, result_artist: str) -> bool:
    """Return whether two artist credits can refer to the same recording.

    This is a hard gate rather than another fuzzy contribution: a partially
    similar title must not let two clearly unrelated artists through. Missing
    artist data is left to the aggregate score.
    """
    search_norm = _normalize_artist_alias(search_artist)
    result_norm = _normalize_artist_alias(result_artist)
    if not search_norm or not result_norm:
        return True
    return _artists_are_alias_equivalent(search_artist, result_artist)


def _artist_credit_parts(credit: str, splitter: re.Pattern[str]) -> list[str]:
    """Split a credit into normalized names using the given separator set."""
    parts: list[str] = []
    for part in splitter.split(credit):
        normalized = _LEADING_THE_RE.sub("", _normalize_artist_alias(part)).strip()
        if normalized:
            parts.append(normalized)
    return parts


def _primary_and_featured(credit: str) -> tuple[str, list[str]]:
    """Return (primary artist, featured artists) from a credit string."""
    parts = _artist_credit_parts(credit, _STRONG_ARTIST_SPLIT_RE)
    if not parts:
        return "", []
    return parts[0], parts[1:]


def _all_credit_artists(credit: str) -> list[str]:
    """Return every credited artist name, including ampersand collaborations."""
    return _artist_credit_parts(credit, _ARTIST_SPLIT_RE)


def _artist_is_one_of(name: str, candidates: Iterable[str]) -> bool:
    return any(
        _artists_are_alias_equivalent(name, candidate) for candidate in candidates
    )


def _remixer_named_in_title(artist: str, title: str) -> bool:
    """Return whether a candidate lead is the remixer named in the source title."""
    _, tags = extract_title_tags(title)
    for tag in tags:
        if not any(
            category == "variant" and key.startswith("remix")
            for category, key in _tag_identity_keys(tag)
        ):
            continue
        normalized = normalize_for_matching(tag)
        remainder = re.sub(r"\b(?:remix(?:ed)?|by|version|edit|mix)\b", " ", normalized)
        remainder = _MULTI_SPACE_RE.sub(" ", remainder).strip()
        if not remainder:
            continue
        if _artists_are_alias_equivalent(artist, remainder):
            return True
        if any(
            _artists_are_alias_equivalent(artist, part) for part in remainder.split()
        ):
            return True
    return False


def _credit_structure_compatible(
    search_artist: str, result_artist: str, title: str
) -> bool:
    """Return whether the candidate credits the expected primary correctly.

    Only a source that explicitly lists multiple artists gives enough evidence
    to call an extra candidate artist a different version: normal source
    metadata carries just the primary, so unknown collaborators there are
    expected rather than suspicious. For such complete credits, a result led
    by another artist is rejected unless every other candidate artist is also
    expected, or the lead is the remixer named in the source title.
    """
    expected_artists = _artist_credit_parts(search_artist, _STRONG_ARTIST_SPLIT_RE)
    if len(expected_artists) < 2:
        return True

    expected_primary = expected_artists[0]
    candidate_primary, _ = _primary_and_featured(result_artist)
    if not candidate_primary:
        return True
    if _artists_are_alias_equivalent(expected_primary, candidate_primary):
        return True
    if _remixer_named_in_title(candidate_primary, title):
        return True

    candidate_artists = _all_credit_artists(result_artist)
    if not _artist_is_one_of(expected_primary, candidate_artists):
        return False
    return all(
        _artist_is_one_of(candidate, expected_artists)
        for candidate in candidate_artists
        if not _artists_are_alias_equivalent(candidate, expected_primary)
    )


def _missing_featured_penalty(search_artist: str, result_artist: str) -> float:
    """Penalize a result that omits expected featured artists."""
    _, expected_featured = _primary_and_featured(search_artist)
    if not expected_featured:
        return 0.0
    candidate_artists = _all_credit_artists(result_artist)
    if not candidate_artists:
        return 0.0
    matched = sum(
        _artist_is_one_of(featured, candidate_artists) for featured in expected_featured
    )
    missing = len(expected_featured) - matched
    if missing == 0:
        return 0.0
    if matched == 0:
        return _MISSING_ALL_FEATURED_PENALTY
    return _MISSING_FEATURED_PENALTY * missing


def _variant_marker_match(normalized_tag: str, marker: str) -> Optional[re.Match]:
    """Find a variant descriptor, with exact matching for bare generic words."""
    if marker in _BARE_ONLY_VARIANT_MARKERS:
        return re.fullmatch(re.escape(marker), normalized_tag)
    return re.search(
        rf"(?<!\w){re.escape(marker)}(?!\w)",
        normalized_tag,
    )


def _canonical_variant_keys(
    normalized_tag: str, raw_tag: Optional[str] = None
) -> set[str]:
    """Map equivalent version descriptors to one key.

    "Extended Mix" and "Extended Version" share a key, as do edit/version
    pairs. Named variants keep their qualifier: different remixers and demo
    years stay distinct. A live recording keeps its venue so two different
    venues remain distinct. A trailing "s" is only a possessive when the raw
    tag actually used "'s"; a real word such as "Mr S" is kept.
    """
    is_possessive = bool(raw_tag and re.search(r"['\u2019]s\b", raw_tag, re.IGNORECASE))
    # Split "Demo2019" so the descriptor and its qualifier are both visible.
    normalized_tag = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized_tag)
    normalized_tag = _MULTI_SPACE_RE.sub(" ", normalized_tag).strip()

    keys: set[str] = set()
    for family, aliases in _VARIANT_FAMILIES:
        for alias in aliases:
            match = _variant_marker_match(normalized_tag, alias)
            if not match:
                continue
            if family == "live":
                remainder = (
                    normalized_tag[: match.start()]
                    + " "
                    + normalized_tag[match.end() :]
                )
                remainder = re.sub(
                    r"^(?:version|edit)\b\s*", "", remainder.strip()
                ).strip()
                remainder = re.sub(r"^from\b", "at", remainder).strip()
                if re.match(r"^(?:at|in)\b", remainder):
                    keys.add(f"live {remainder}")
                else:
                    keys.add("live")
            elif family in ("remix", "demo"):
                remainder = (
                    normalized_tag[: match.start()]
                    + " "
                    + normalized_tag[match.end() :]
                ).strip()
                remainder = re.sub(r"^(?:by|from)\b\s*", "", remainder)
                if is_possessive:
                    remainder = re.sub(r"\s+s$", "", remainder)
                remainder = re.sub(r"\b(?:version|edit|mix)\b", " ", remainder).strip()
                remainder = _MULTI_SPACE_RE.sub(" ", remainder).strip()
                keys.add(f"{family} {remainder}".strip())
            else:
                keys.add(family)
            break
    return keys


def _tag_identity_keys(tag: str) -> set[tuple[str, str]]:
    """Return canonical (category, key) pairs for a tag."""
    category = _classify_tag(tag)
    if not category or category == "feat":
        return set()

    normalized = normalize_for_matching(tag)
    if category == "variant":
        return {("variant", key) for key in _canonical_variant_keys(normalized, tag)}
    return {(category, normalized)}


def _version_signature(title: str, tags: list[str]) -> set[tuple[str, str]]:
    """Collect variant/language distinctions from tags and unambiguous title words."""
    signature: set[tuple[str, str]] = set()
    for tag in tags:
        signature.update(
            pair
            for pair in _tag_identity_keys(tag)
            if pair[0] in ("variant", "language")
        )

    normalized_title = normalize_for_matching(title)
    normalized_tags = [normalize_for_matching(tag) for tag in tags]
    for marker in _STANDALONE_VARIANT_MARKERS:
        if not _variant_marker_match(normalized_title, marker):
            continue
        # A tag already parsed this marker and may carry a qualifier (for
        # example "Live Version at Wembley"). Adding the bare marker key again
        # would create a false conflict with "Live at Wembley".
        if any(marker in normalized_tag for normalized_tag in normalized_tags):
            continue
        signature.update(("variant", key) for key in _canonical_variant_keys(marker))
    return signature


def has_version_conflict(
    search_title: str,
    result_title: str,
    search_tags: list[str],
    result_tags: list[str],
) -> bool:
    """Return whether the source and result request different versions.

    Minor differences such as a remaster are deliberately ignored; variant and
    language differences are not. This is independent of ISRC/duration so a
    wrong version cannot be accepted just because those signals are absent.
    """
    return _version_signature(search_title, search_tags) != _version_signature(
        result_title, result_tags
    )


def _classify_tag(tag: str) -> Optional[str]:
    """Classify a tag into a severity category."""
    normalized = tag.strip().lower()

    if _FEAT_RE.match(normalized):
        return "feat"

    for marker in _LANGUAGE_MARKERS:
        if marker in normalized:
            return "language"

    if _canonical_variant_keys(normalized):
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
    for tag in source_tags:
        source_pairs.update(_tag_identity_keys(tag))

    result_pairs = set()
    for tag in result_tags:
        result_pairs.update(_tag_identity_keys(tag))

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


def _normalize_isrc(isrc: str) -> str:
    """Normalize provider ISRC whitespace/case once for every comparison."""
    return isrc.strip().upper()


def score_track_match(
    search_title: str,
    search_artist: str,
    result_title: str,
    result_artist: str,
    *,
    search_isrc: Optional[str] = None,
    result_isrc: Optional[str] = None,
    search_alternate_isrcs: Optional[Iterable[str]] = None,
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
    version_conflict = has_version_conflict(
        search_title, result_title, source_tags, result_tags
    )
    normalized_search_isrc = _normalize_isrc(search_isrc) if search_isrc else ""
    normalized_result_isrc = _normalize_isrc(result_isrc) if result_isrc else ""
    # A blank/whitespace-only ISRC is not identity evidence: it must neither
    # bypass the artist gate nor count as a matched ISRC in the weighted score.
    isrc_present = bool(normalized_search_isrc and normalized_result_isrc)
    known_isrcs = {normalized_search_isrc} if normalized_search_isrc else set()
    known_isrcs.update(
        _normalize_isrc(isrc) for isrc in (search_alternate_isrcs or ()) if isrc
    )
    isrc_equal = isrc_present and normalized_result_isrc in known_isrcs

    # Artist compatibility is a gate, not a weighted hint. Without it, close
    # titles can carry unrelated artists over the acceptance threshold. An
    # identical provider ISRC is strong identity evidence for transliterated
    # names, but it cannot override an explicit version conflict or a credit
    # that names a different lead artist.
    if not _credit_structure_compatible(
        search_artist, result_artist, search_title
    ) and not (isrc_equal and not version_conflict):
        return 0.0
    if not artists_are_compatible(search_artist, result_artist):
        if not (isrc_equal and not version_conflict):
            return 0.0

    norm_source_title = normalize_for_matching(source_core)
    norm_result_title = normalize_for_matching(result_core)
    norm_source_artist = _normalize_artist_alias(search_artist)
    norm_result_artist = _normalize_artist_alias(result_artist)

    title_sim = SequenceMatcher(None, norm_source_title, norm_result_title).ratio()
    if _artists_are_alias_equivalent(search_artist, result_artist):
        artist_sim = 1.0
    else:
        artist_sim = SequenceMatcher(
            None, norm_source_artist, norm_result_artist
        ).ratio()
    if isrc_equal and not version_conflict:
        # The same ISRC identifies the same recording even when providers use
        # different scripts or transliterations for the artist name.
        artist_sim = max(artist_sim, 0.75)

    weighted_score = 0.0
    weights_used = 0.0

    # Title: weight 0.35
    weighted_score += 0.35 * title_sim
    weights_used += 0.35

    # Artist: weight 0.35
    weighted_score += 0.35 * artist_sim
    weights_used += 0.35

    # ISRC: weight 0.20 (only if both provided and non-blank after normalization)
    if isrc_present:
        isrc_match = 1.0 if isrc_equal else 0.0
        weighted_score += 0.20 * isrc_match
        weights_used += 0.20

    # Duration: weight 0.10 (only if both provided)
    duration_diff: Optional[float] = None
    if search_duration_s is not None and result_duration_s is not None:
        diff = abs(search_duration_s - result_duration_s)
        duration_diff = diff
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

    # Missing featured credits are common (especially on YouTube), but a
    # result with none of them needs the extra penalty to stay below a
    # provider's acceptance threshold when another signal disagrees.
    score -= _missing_featured_penalty(search_artist, result_artist)

    # Two recordings can carry different ISRCs in different territories, so an
    # ISRC disagreement is not a rejection on its own. Only an independent
    # title/artist/version conflict compounds it; an in-gate duration difference
    # does not, or correct regional duplicates would be lost.
    if isrc_present and not isrc_equal:
        if version_conflict or artist_sim < 1.0:
            score -= _ISRC_CONFLICT_EXTRA_PENALTY
        if duration_diff is not None and search_duration_s:
            allowance_s = max(
                _DURATION_GATE_MIN_S, search_duration_s * _DURATION_GATE_FRACTION
            )
            if duration_diff > allowance_s:
                score = min(score, _ISRC_CONFLICT_CAP)

    # A version/language mismatch stays rejected regardless of how much the
    # title, artist, ISRC, and duration agree.
    if version_conflict:
        score = min(score, _VERSION_CONFLICT_CAP)

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
