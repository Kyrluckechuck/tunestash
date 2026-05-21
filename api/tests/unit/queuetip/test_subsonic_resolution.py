"""Unit tests for the queuetip-song → Subsonic-id resolution ladder.

Mocks SubsonicClient.search_tracks; no network. Each test pins one rung of
the ladder so a regression on any single step is caught locally instead of
manifesting as "tracks just don't match" in integration.
"""

from unittest.mock import MagicMock

from src.queuetip.subsonic.client import SubsonicError, SubsonicTrack
from src.queuetip.subsonic.resolution import (
    _fuzzy_title_score,
    _normalize,
    resolve_song_to_subsonic_id,
)


def _track(id_: str, title: str, artist: str, isrc: str | None = None) -> SubsonicTrack:
    return SubsonicTrack(id=id_, title=title, artist=artist, isrc=isrc)


def _client_with_responses(*responses: list[SubsonicTrack]) -> MagicMock:
    """Build a stub client whose search_tracks returns each provided response
    in turn (one per ladder step the resolver might invoke)."""
    client = MagicMock()
    client.search_tracks.side_effect = list(responses)
    return client


# ── _normalize ─────────────────────────────────────────────────────────────


def test_normalize_lowercases_and_strips_punctuation():
    assert _normalize("Hello, World!") == "hello world"


def test_normalize_collapses_whitespace():
    assert _normalize("  a   b    c ") == "a b c"


def test_normalize_deletes_apostrophes_not_substitutes():
    """Apostrophes must be deleted (not replaced with space) so 'Don't' and
    'Dont' normalize identically — the most common punctuation drift."""
    assert _normalize("Don't — Stop!") == "dont stop"
    assert _normalize("Dont — Stop!") == "dont stop"


def test_normalize_strips_trailing_parentheticals():
    """'(Remastered)', '(Live)', '[Deluxe]' etc. are variation noise — the
    canonical title comes through."""
    assert _normalize("Bohemian Rhapsody (Remastered)") == "bohemian rhapsody"
    assert _normalize("Wonderwall [Acoustic Version]") == "wonderwall"


# ── _fuzzy_title_score ─────────────────────────────────────────────────────


def test_fuzzy_score_exact_match_is_one():
    assert _fuzzy_title_score("hello", "hello") == 1.0


def test_fuzzy_score_substring_returns_length_ratio():
    """'Title' inside 'Title (Remastered)' — exactly the variation we want
    to score high. Ratio = len(shorter) / len(longer)."""
    score = _fuzzy_title_score("hello", "hello remastered")
    assert 0.3 < score < 0.5  # 5 / 16 ≈ 0.3125


def test_fuzzy_score_returns_zero_for_disjoint_strings():
    assert _fuzzy_title_score("abc", "xyz") == 0.0


# ── ISRC step ──────────────────────────────────────────────────────────────


def test_isrc_exact_match_returns_id():
    """Highest-precision step: when both sides have ISRC, that's THE match."""
    client = _client_with_responses(
        [_track("S1", "Get Lucky", "Daft Punk", isrc="USQX91300108")]
    )
    out = resolve_song_to_subsonic_id(
        title="Get Lucky",
        artist="Daft Punk",
        isrc="USQX91300108",
        client=client,
    )
    assert out == "S1"


def test_isrc_case_insensitive_match():
    """Some servers return ISRC in lowercase, others uppercase. Match must
    be case-insensitive so we don't miss obvious hits."""
    client = _client_with_responses([_track("S1", "X", "Y", isrc="usqx91300108")])
    out = resolve_song_to_subsonic_id(
        title="X", artist="Y", isrc="USQX91300108", client=client
    )
    assert out == "S1"


def test_isrc_search_error_falls_through_to_title():
    """A failed ISRC search must not abort the run — fall through to the
    text-match ladder so we still have a shot at finding the track."""
    client = MagicMock()
    client.search_tracks.side_effect = [
        SubsonicError("transient"),  # ISRC search fails
        [_track("T2", "Same Song", "Same Artist")],  # title search succeeds
    ]
    out = resolve_song_to_subsonic_id(
        title="Same Song",
        artist="Same Artist",
        isrc="USQX91300108",
        client=client,
    )
    assert out == "T2"


# ── Title + artist step ────────────────────────────────────────────────────


def test_exact_normalized_match_picks_correct_artist():
    """Two tracks share a title; the artist constraint picks the right one."""
    client = _client_with_responses(
        [
            _track("WRONG", "Yesterday", "Different Artist"),
            _track("RIGHT", "Yesterday", "The Beatles"),
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="Yesterday", artist="The Beatles", isrc=None, client=client
    )
    assert out == "RIGHT"


def test_normalization_handles_punctuation_drift():
    """'Don't Stop' vs 'Dont Stop' shouldn't lose us the match — both
    normalize identically."""
    client = _client_with_responses([_track("S1", "Dont Stop", "Fleetwood Mac")])
    out = resolve_song_to_subsonic_id(
        title="Don't Stop", artist="Fleetwood Mac", isrc=None, client=client
    )
    assert out == "S1"


# ── Fuzzy step ─────────────────────────────────────────────────────────────


def test_fuzzy_match_picks_remastered_variant_with_matching_artist():
    """The server has 'Bohemian Rhapsody (Remastered)' but queuetip has just
    'Bohemian Rhapsody'. Fuzzy + strict artist match catches it."""
    client = _client_with_responses(
        [_track("S1", "Bohemian Rhapsody (Remastered)", "Queen")]
    )
    out = resolve_song_to_subsonic_id(
        title="Bohemian Rhapsody", artist="Queen", isrc=None, client=client
    )
    assert out == "S1"


def test_fuzzy_skipped_when_artist_blank():
    """No artist constraint = no fuzzy match. Too risky on title alone."""
    client = _client_with_responses(
        [_track("S1", "Some Cover Version Of A Song", "Cover Artist")]
    )
    out = resolve_song_to_subsonic_id(
        title="A Song", artist="", isrc=None, client=client
    )
    assert out is None


def test_fuzzy_rejects_match_with_different_artist():
    """A title-fuzzy candidate with the wrong artist is NOT a match —
    otherwise covers and samples would get returned."""
    client = _client_with_responses(
        [
            _track("WRONG", "Bohemian Rhapsody (Cover)", "Some Cover Band"),
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="Bohemian Rhapsody", artist="Queen", isrc=None, client=client
    )
    assert out is None


def test_returns_none_when_no_search_results():
    client = _client_with_responses([])
    out = resolve_song_to_subsonic_id(
        title="Nothing Matches", artist="Mystery", isrc=None, client=client
    )
    assert out is None


def test_returns_none_when_both_title_and_artist_blank():
    client = _client_with_responses()
    out = resolve_song_to_subsonic_id(title="", artist="", isrc=None, client=client)
    assert out is None
    # Should NOT have made any search calls.
    client.search_tracks.assert_not_called()
