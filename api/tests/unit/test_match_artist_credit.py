"""Regression tests for lead-artist and featured-credit match decisions.

All names in this module are synthetic; no real catalog identities are used.
"""

from unittest.mock import patch

from downloader.providers.monochrome import MonochromeProvider
from downloader.providers.tidal import TidalProvider
from downloader.providers.youtube import YouTubeMusicProvider
from downloader.track_matcher import score_track_match

SOURCE_TITLE = "Test Title"
SOURCE_LEAD = "Lead Artist"
FEATURED_ONE = "Featured One"
FEATURED_TWO = "Featured Two"
UNEXPECTED_LEAD = "Other Lead"
UNEXPECTED_FEATURED = "Featured Three"

SOURCE_CREDIT = f"{SOURCE_LEAD}, {FEATURED_ONE}, {FEATURED_TWO}"


def _score(result_credit: str, **kwargs: object) -> float:
    return score_track_match(
        SOURCE_TITLE,
        SOURCE_CREDIT,
        SOURCE_TITLE,
        result_credit,
        search_duration_s=200.0,
        result_duration_s=200.4,
        **kwargs,  # type: ignore[arg-type]
    )


class TestLeadArtistGate:
    """The candidate lead must be the expected primary, not merely contain it."""

    def test_unexpected_lead_with_expected_primary_second_is_rejected(self) -> None:
        # Production pattern: the expected primary appears as the second
        # credit, but the lead and the other credits are different artists.
        score = _score(
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}, {UNEXPECTED_FEATURED}",
        )
        assert score < 0.6

    def test_unexpected_lead_added_to_non_remix_source_is_rejected(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            f"{SOURCE_LEAD}, {FEATURED_ONE}",
            SOURCE_TITLE,
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score < 0.6

    def test_matching_isrc_rescues_an_unexpected_lead(self) -> None:
        # An identical ISRC identifies the recording regardless of credit
        # order, provided there is no version conflict.
        score = score_track_match(
            SOURCE_TITLE,
            SOURCE_CREDIT,
            SOURCE_TITLE,
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}, {UNEXPECTED_FEATURED}",
            search_isrc="TEST00000001",
            result_isrc="TEST00000001",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.7

    def test_matching_alternate_isrc_rescues_an_unexpected_lead(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            SOURCE_CREDIT,
            SOURCE_TITLE,
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}, {UNEXPECTED_FEATURED}",
            search_isrc="TEST00000001",
            result_isrc="TEST00000002",
            search_alternate_isrcs=["TEST00000002"],
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.7

    def test_isrc_rescue_still_respects_version_conflict(self) -> None:
        score = score_track_match(
            f"{SOURCE_TITLE} (Acoustic)",
            SOURCE_CREDIT,
            SOURCE_TITLE,
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}, {UNEXPECTED_FEATURED}",
            search_isrc="TEST00000001",
            result_isrc="TEST00000001",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score < 0.6

    def test_single_artist_source_is_not_hard_rejected_for_an_extra_lead(self) -> None:
        # Normal source metadata carries only the primary; an unknown
        # collaborator in the result is not evidence of a different version.
        score = score_track_match(
            SOURCE_TITLE,
            SOURCE_LEAD,
            SOURCE_TITLE,
            f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.6

    def test_remixer_leading_credit_is_accepted_when_named_in_title(self) -> None:
        score = score_track_match(
            f"{SOURCE_TITLE} (Remixer One Remix)",
            f"{SOURCE_LEAD}, {FEATURED_ONE}",
            f"{SOURCE_TITLE} (Remixer One Remix)",
            f"Remixer One, {SOURCE_LEAD}, {FEATURED_ONE}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.7

    def test_plus_in_duo_name_is_not_a_strong_credit_separator(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            "Duo One + Duo Two",
            SOURCE_TITLE,
            "Remixer One • Duo One + Duo Two",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.6

    def test_standalone_x_credit_separator_is_recognized(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            f"{SOURCE_LEAD}, {FEATURED_ONE}",
            SOURCE_TITLE,
            f"{FEATURED_ONE} X {SOURCE_LEAD}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.6

    def test_lead_only_youtube_credit_is_accepted(self) -> None:
        assert _score(SOURCE_LEAD) >= 0.6

    def test_featured_artists_in_different_order_are_accepted(self) -> None:
        score = _score(f"{SOURCE_LEAD}, {FEATURED_TWO}, {FEATURED_ONE}")
        assert score >= 0.7

    def test_expected_primary_listed_after_featured_artist_is_accepted(self) -> None:
        # Every other candidate credit is an expected artist, so this is a
        # credit-order difference rather than a different version.
        score = _score(f"{FEATURED_ONE}, {SOURCE_LEAD}, {FEATURED_TWO}")
        assert score >= 0.6

    def test_alias_aware_lead_still_matches(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            f"P!nk, {FEATURED_ONE}",
            SOURCE_TITLE,
            f"Pink, {FEATURED_ONE}",
        )
        assert score >= 0.7

    def test_ac_dc_style_weak_tokens_are_not_split(self) -> None:
        assert (
            score_track_match(
                SOURCE_TITLE,
                "AC/DC",
                SOURCE_TITLE,
                "ACDC",
            )
            >= 0.9
        )
        assert (
            score_track_match(
                SOURCE_TITLE,
                "AC Slater",
                SOURCE_TITLE,
                "AC/DC",
            )
            < 0.6
        )


class TestFeaturedCreditPenalty:
    """Missing featured artists lower confidence without breaking lead-only hits."""

    def test_missing_all_featured_plus_isrc_conflict_is_rejected(self) -> None:
        score = _score(
            SOURCE_LEAD,
            search_isrc="TEST00000001",
            result_isrc="TEST00000002",
        )
        assert score < 0.6

    def test_missing_some_featured_only_lowers_confidence_slightly(self) -> None:
        full = _score(f"{SOURCE_LEAD}, {FEATURED_ONE}, {FEATURED_TWO}")
        partial = _score(f"{SOURCE_LEAD}, {FEATURED_ONE}")
        assert partial >= full - 0.15
        assert partial >= 0.9

    def test_single_artist_source_accepts_an_extra_collaborator(self) -> None:
        score = score_track_match(
            SOURCE_TITLE,
            SOURCE_LEAD,
            SOURCE_TITLE,
            f"{SOURCE_LEAD}, {UNEXPECTED_FEATURED}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.8


class TestRemixExtraArtist:
    """A remixer credited as an extra artist does not invalidate the match."""

    def test_remixer_added_to_remix_source_is_accepted(self) -> None:
        score = score_track_match(
            f"{SOURCE_TITLE} (Foo Remix)",
            f"{SOURCE_LEAD}, {FEATURED_ONE}",
            f"{SOURCE_TITLE} (Foo Remix)",
            f"{SOURCE_LEAD}, {FEATURED_ONE}, Remixer Extra",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.7

    def test_remixer_inserted_before_featured_artist_is_accepted(self) -> None:
        score = score_track_match(
            f"{SOURCE_TITLE} (Foo Remix)",
            f"{SOURCE_LEAD}, {FEATURED_ONE}",
            f"{SOURCE_TITLE} (Foo Remix)",
            f"{SOURCE_LEAD}, Remixer Extra, {FEATURED_ONE}",
            search_duration_s=200.0,
            result_duration_s=200.4,
        )
        assert score >= 0.7


class TestYouTubeSearchCredit:
    """The YouTube search path applies the same structural artist gate."""

    @staticmethod
    def _entry(credit: str) -> list[dict[str, object]]:
        return [
            {
                "videoId": "synthetic-id",
                "title": SOURCE_TITLE,
                "artists": [{"name": name} for name in credit.split(", ")],
                "duration_seconds": 200,
            }
        ]

    def test_unexpected_lead_result_is_not_returned(self) -> None:
        with patch("ytmusicapi.YTMusic") as mock_ytmusic:
            mock_ytmusic.return_value.search.return_value = self._entry(
                f"{UNEXPECTED_LEAD}, {SOURCE_LEAD}, {UNEXPECTED_FEATURED}"
            )
            match = YouTubeMusicProvider()._search_track_sync(
                SOURCE_TITLE,
                SOURCE_CREDIT,
                duration_ms=200_000,
            )
        assert match is None

    def test_lead_only_result_is_returned(self) -> None:
        with patch("ytmusicapi.YTMusic") as mock_ytmusic:
            mock_ytmusic.return_value.search.return_value = self._entry(SOURCE_LEAD)
            match = YouTubeMusicProvider()._search_track_sync(
                SOURCE_TITLE,
                SOURCE_CREDIT,
                duration_ms=200_000,
            )
        assert match is not None
        assert match.artist == SOURCE_LEAD


class TestProviderCreditParsing:
    """Providers with artist arrays keep the full credit for the matcher."""

    @staticmethod
    def _result() -> dict[str, object]:
        return {
            "id": 1,
            "title": SOURCE_TITLE,
            "duration": 200,
            "artists": [
                {"name": SOURCE_LEAD},
                {"name": FEATURED_ONE},
                {"name": FEATURED_TWO},
            ],
            "album": {},
        }

    def test_tidal_keeps_all_credited_artists(self) -> None:
        match = TidalProvider()._parse_track_result(self._result(), confidence=0.0)
        assert match is not None
        assert match.artist == f"{SOURCE_LEAD} • {FEATURED_ONE} • {FEATURED_TWO}"

    def test_monochrome_keeps_all_credited_artists(self) -> None:
        match = MonochromeProvider()._parse_track_result(self._result(), confidence=0.0)
        assert match is not None
        assert match.artist == f"{SOURCE_LEAD} • {FEATURED_ONE} • {FEATURED_TWO}"
