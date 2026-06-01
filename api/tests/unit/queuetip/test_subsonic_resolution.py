"""Unit tests for the queuetip-song → Subsonic-id resolution ladder.

The resolver does several search3 calls (ISRC, "title artist", bare title),
dedupes the candidates, then applies precedence rungs:
  1. file path (same-file on a shared mount)
  2. ISRC exact
  3. title + artist-list exact (version-suffix stripped)
  4. fuzzy title + artist-list

Tests mock the client so search_tracks returns a fixed candidate pool
regardless of query — that's the realistic shape (the real server returns
overlapping results across the queries, which we dedupe).
"""

from unittest.mock import MagicMock

from src.queuetip.subsonic.client import SubsonicError, SubsonicTrack
from src.queuetip.subsonic.resolution import (
    _fuzzy_title_score,
    _normalize,
    _paths_match,
    resolve_song_to_subsonic_id,
)


def _track(
    id_: str,
    title: str,
    artist: str,
    isrc: str | None = None,
    artists: list[str] | None = None,
    path: str = "",
) -> SubsonicTrack:
    return SubsonicTrack(
        id=id_,
        title=title,
        artist=artist,
        isrc=isrc,
        artists=artists or [],
        path=path,
    )


def _client(candidates: list[SubsonicTrack]) -> MagicMock:
    """Mock client whose search_tracks returns the same candidate pool for
    every query (mirrors the real server returning overlapping results that
    the resolver dedupes by id)."""
    client = MagicMock()
    client.search_tracks.return_value = candidates
    return client


# ── _normalize ─────────────────────────────────────────────────────────────


def test_normalize_lowercases_and_strips_punctuation():
    assert _normalize("Hello, World!") == "hello world"


def test_normalize_collapses_whitespace():
    assert _normalize("  a   b    c ") == "a b c"


def test_normalize_deletes_apostrophes_not_substitutes():
    assert _normalize("Don't — Stop!") == "dont stop"
    assert _normalize("Dont — Stop!") == "dont stop"


def test_normalize_keeps_trailing_parentheticals():
    assert (
        _normalize("Bohemian Rhapsody (Remastered)") == "bohemian rhapsody remastered"
    )
    assert _normalize("Wonderwall [Acoustic Version]") == "wonderwall acoustic version"


def test_normalize_keeps_legitimate_dash_titles():
    """A dash NOT followed by a version keyword must survive — don't truncate
    real titles like 'Crystal - Stylo'."""
    assert _normalize("Crystal - Stylo") == "crystal stylo"


def test_normalize_keeps_leading_parenthetical():
    """A LEADING parenthetical is part of the title — must not be deleted.
    Stripping all parens would turn this into just 'the reaper'."""
    assert _normalize("(Don't Fear) The Reaper") == "dont fear the reaper"


def test_normalize_keeps_meaningful_trailing_parenthetical():
    """A trailing parenthetical WITHOUT a version keyword carries meaning and
    must survive — otherwise 'Jump (For My Love)' collapses to 'jump' and
    false-matches Van Halen's 'Jump'."""
    assert _normalize("Jump (For My Love)") == "jump for my love"


def test_normalize_keeps_version_paren_keyword_not_first():
    assert _normalize("Some Song (2011 Remaster)") == "some song 2011 remaster"


# ── _fuzzy_title_score ─────────────────────────────────────────────────────


def test_fuzzy_score_exact_match_is_one():
    assert _fuzzy_title_score("hello", "hello") == 1.0


def test_fuzzy_score_returns_zero_for_disjoint_strings():
    assert _fuzzy_title_score("abc", "xyz") == 0.0


# ── _paths_match ───────────────────────────────────────────────────────────


def test_paths_match_relative_suffix_of_absolute():
    """Shared mount: TuneStash absolute path ends with Navidrome's relative."""
    assert _paths_match(
        "/mnt/music/Vanilla Ice/Album/01 - Ice Ice Baby.m4a",
        "Vanilla Ice/Album/01 - Ice Ice Baby.m4a",
    )


def test_paths_match_rejects_basename_only():
    """Same filename in DIFFERENT directories must NOT match — a basename
    collision (compilation vs original) would otherwise route the wrong track."""
    assert not _paths_match(
        "/mnt/music/The Beatles/Help!/01 - Help!.m4a",
        "Various Artists/60s Hits/01 - Help!.m4a",
    )


def test_paths_match_rejects_different_files():
    assert not _paths_match(
        "/mnt/music/A/01 - Song One.m4a",
        "B/02 - Song Two.m4a",
    )


# ── Rung 1: file path (highest confidence) ─────────────────────────────────


def test_path_match_beats_content_and_wrong_version():
    """The path rung wins even when a different-version candidate would also
    pass content matching — the same file is definitively correct."""
    client = _client(
        [
            # A cover that would content-match if path didn't win.
            _track("COVER", "My Song", "Cover Artist"),
            # The real file, on the shared mount.
            _track(
                "REAL",
                "My Song",
                "Real Artist",
                path="Real Artist/Album/01 - My Song.m4a",
            ),
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="My Song",
        artist="Real Artist",
        isrc=None,
        client=client,
        file_path="/mnt/music/Real Artist/Album/01 - My Song.m4a",
    )
    assert out == "REAL"


# ── Rung 2: ISRC ───────────────────────────────────────────────────────────


def test_isrc_exact_match_returns_id():
    client = _client([_track("S1", "Get Lucky", "Daft Punk", isrc="USQX91300108")])
    out = resolve_song_to_subsonic_id(
        title="Get Lucky", artist="Daft Punk", isrc="USQX91300108", client=client
    )
    assert out == "S1"


# ── Rung 3: title + artist-list ────────────────────────────────────────────


def test_exact_match_against_featured_artist_list():
    """queuetip primary artist 'Maejor' matches a Navidrome track credited
    'Maejor • Juicy J • Justin Bieber' (same recording, featured artists)."""
    client = _client(
        [
            _track(
                "S1",
                "Lolly",
                "Maejor • Juicy J • Justin Bieber",
                artists=["Maejor", "Juicy J", "Justin Bieber"],
            )
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="Lolly", artist="Maejor", isrc=None, client=client
    )
    assert out == "S1"


def test_does_not_match_different_version_by_other_artist():
    """The wrong-version concern: queuetip 'Reel 2 Real' must NOT match a
    'will.i.am' cover with the same title. Artist-list membership prevents it."""
    client = _client(
        [
            _track("WILL", "I Like To Move It", "will.i.am", artists=["will.i.am"]),
            _track("ILYAA", "I Like To Move It", "ILYAA", artists=["ILYAA"]),
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="I Like To Move It", artist="Reel 2 Real", isrc=None, client=client
    )
    assert out is None


def test_plain_title_does_not_match_remix_variant_without_isrc():
    client = _client(
        [_track("S1", "Bluey Theme Tune (Extended Mix)", "Bluey", artists=["Bluey"])]
    )
    out = resolve_song_to_subsonic_id(
        title="Bluey Theme Tune", artist="Bluey", isrc=None, client=client
    )
    assert out is None


def test_exact_normalized_match_picks_correct_artist():
    client = _client(
        [
            _track("WRONG", "Yesterday", "Different Artist"),
            _track("RIGHT", "Yesterday", "The Beatles"),
        ]
    )
    out = resolve_song_to_subsonic_id(
        title="Yesterday", artist="The Beatles", isrc=None, client=client
    )
    assert out == "RIGHT"


# ── Rung 4: fuzzy ──────────────────────────────────────────────────────────


def test_fuzzy_does_not_cross_plain_to_versioned_variant():
    client = _client(
        [_track("S1", "Bohemian Rhapsody (Remastered)", "Queen", artists=["Queen"])]
    )
    out = resolve_song_to_subsonic_id(
        title="Bohemian Rhapsody", artist="Queen", isrc=None, client=client
    )
    assert out is None


def test_fuzzy_skipped_when_artist_blank():
    client = _client([_track("S1", "Some Cover Of A Song", "Cover Artist")])
    out = resolve_song_to_subsonic_id(
        title="A Song", artist="", isrc=None, client=client
    )
    assert out is None


# ── Misc / robustness ──────────────────────────────────────────────────────


def test_returns_none_when_no_search_results():
    client = _client([])
    out = resolve_song_to_subsonic_id(
        title="Nothing", artist="Mystery", isrc=None, client=client
    )
    assert out is None


def test_returns_none_when_both_title_and_artist_blank():
    client = _client([])
    out = resolve_song_to_subsonic_id(title="", artist="", isrc=None, client=client)
    assert out is None
    client.search_tracks.assert_not_called()


def test_search_error_does_not_crash_resolution():
    """A failing search is logged and skipped, not raised — a transient error
    on one query shouldn't abort the whole resolution."""
    client = MagicMock()
    client.search_tracks.side_effect = SubsonicError("boom")
    out = resolve_song_to_subsonic_id(
        title="Anything", artist="Someone", isrc=None, client=client
    )
    assert out is None
