"""Tests for the shared track matching module."""

from downloader.track_matcher import (
    album_type_score,
    compute_tag_penalty,
    extract_title_tags,
    normalize_for_matching,
    score_track_match,
)


class TestExtractTitleTags:
    def test_no_tags(self) -> None:
        core, tags = extract_title_tags("Bailando")
        assert core == "Bailando"
        assert tags == []

    def test_single_paren_tag(self) -> None:
        core, tags = extract_title_tags("Bailando (Spanish Version)")
        assert core == "Bailando"
        assert tags == ["spanish version"]

    def test_bracket_tag(self) -> None:
        core, tags = extract_title_tags("Bailando [Live]")
        assert core == "Bailando"
        assert tags == ["live"]

    def test_multiple_tags(self) -> None:
        core, tags = extract_title_tags("Bailando (Spanish Version) [Remastered]")
        assert core == "Bailando"
        assert "spanish version" in tags
        assert "remastered" in tags
        assert len(tags) == 2

    def test_remaster_tag(self) -> None:
        core, tags = extract_title_tags("Bohemian Rhapsody (2011 Remaster)")
        assert core == "Bohemian Rhapsody"
        assert tags == ["2011 remaster"]

    def test_preserves_core_punctuation(self) -> None:
        core, tags = extract_title_tags("Rock & Roll (Live)")
        assert core == "Rock & Roll"
        assert tags == ["live"]

    def test_nested_parens(self) -> None:
        core, tags = extract_title_tags("Song Title (feat. Artist) (Remix)")
        assert core == "Song Title"
        assert len(tags) == 2


class TestNormalizeForMatching:
    def test_lowercase(self) -> None:
        assert normalize_for_matching("HELLO") == "hello"

    def test_strip_accents(self) -> None:
        result = normalize_for_matching("café résumé")
        assert result == "cafe resume"

    def test_ampersand(self) -> None:
        result = normalize_for_matching("Rock & Roll")
        assert "and" in result
        assert "&" not in result

    def test_strip_punctuation(self) -> None:
        result = normalize_for_matching("don't stop!")
        assert "don" in result
        assert "stop" in result
        assert "'" not in result
        assert "!" not in result


class TestComputeTagPenalty:
    def test_no_tags_no_penalty(self) -> None:
        assert compute_tag_penalty([], []) == 0.0

    def test_matching_tags_no_penalty(self) -> None:
        assert compute_tag_penalty(["Live"], ["Live"]) == 0.0

    def test_source_clean_result_has_language(self) -> None:
        penalty = compute_tag_penalty([], ["Spanish Version"])
        assert penalty >= 0.3

    def test_result_has_remix(self) -> None:
        penalty = compute_tag_penalty([], ["Remix"])
        assert penalty >= 0.2

    def test_result_has_acoustic(self) -> None:
        penalty = compute_tag_penalty([], ["Acoustic"])
        assert penalty >= 0.2

    def test_result_has_live(self) -> None:
        penalty = compute_tag_penalty([], ["Live"])
        assert penalty >= 0.15

    def test_mismatched_variants(self) -> None:
        penalty = compute_tag_penalty(["Remix"], ["Acoustic"])
        assert penalty >= 0.2

    def test_source_has_tag_result_missing(self) -> None:
        penalty = compute_tag_penalty(["Live"], [])
        assert penalty >= 0.1

    def test_feat_tags_not_penalized(self) -> None:
        penalty = compute_tag_penalty([], ["feat. Drake"])
        assert penalty == 0.0

    def test_language_heavier_than_variant(self) -> None:
        lang_penalty = compute_tag_penalty([], ["Spanish Version"])
        variant_penalty = compute_tag_penalty([], ["Remix"])
        assert lang_penalty > variant_penalty


class TestScoreTrackMatch:
    def test_identical_tracks(self) -> None:
        score = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        assert score >= 0.95

    def test_isrc_boosts_score(self) -> None:
        base = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        boosted = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
        )
        assert boosted >= base

    def test_spanish_version_penalized(self) -> None:
        clean = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        spanish = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
        )
        assert spanish < 0.8
        assert spanish < clean

    def test_explicit_spanish_search_matches_spanish(self) -> None:
        score = score_track_match(
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
        )
        assert score >= 0.95

    def test_remix_vs_original(self) -> None:
        original = score_track_match(
            "Blinding Lights",
            "The Weeknd",
            "Blinding Lights",
            "The Weeknd",
        )
        remix = score_track_match(
            "Blinding Lights",
            "The Weeknd",
            "Blinding Lights (Remix)",
            "The Weeknd",
        )
        assert remix < original

    def test_live_vs_studio(self) -> None:
        studio = score_track_match(
            "Bohemian Rhapsody",
            "Queen",
            "Bohemian Rhapsody",
            "Queen",
        )
        live = score_track_match(
            "Bohemian Rhapsody",
            "Queen",
            "Bohemian Rhapsody (Live)",
            "Queen",
        )
        assert live < studio

    def test_remaster_acceptable(self) -> None:
        score = score_track_match(
            "Bohemian Rhapsody",
            "Queen",
            "Bohemian Rhapsody (2011 Remaster)",
            "Queen",
        )
        assert score >= 0.7

    def test_completely_different(self) -> None:
        score = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Stairway to Heaven",
            "Led Zeppelin",
        )
        assert score < 0.3

    def test_duration_helps(self) -> None:
        without_dur = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        with_dur = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
            search_duration_s=240.0,
            result_duration_s=240.0,
        )
        assert with_dur >= without_dur

    def test_always_bounded_0_to_1(self) -> None:
        score = score_track_match(
            "A",
            "B",
            "Completely Different (Spanish Version) (Remix) (Live)",
            "Z",
        )
        assert 0.0 <= score <= 1.0


class TestMultiResultSelection:
    """Test picking the best match from multiple candidates."""

    def test_picks_original_over_remix(self) -> None:
        original_score = score_track_match(
            "Blinding Lights",
            "The Weeknd",
            "Blinding Lights",
            "The Weeknd",
        )
        remix_score = score_track_match(
            "Blinding Lights",
            "The Weeknd",
            "Blinding Lights (Remix)",
            "The Weeknd",
        )
        assert original_score > remix_score

    def test_picks_correct_language(self) -> None:
        spanish_score = score_track_match(
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
        )
        english_score = score_track_match(
            "Bailando (Spanish Version)",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        assert spanish_score > english_score


class TestPlaylistSyncMatching:
    def test_exact_name_match_scores_highest(self) -> None:
        exact = score_track_match(
            "Shape of You",
            "Ed Sheeran",
            "Shape of You",
            "Ed Sheeran",
        )
        close = score_track_match(
            "Shape of You",
            "Ed Sheeran",
            "Shape of You (Acoustic)",
            "Ed Sheeran",
        )
        assert exact > close

    def test_searching_for_variant_prefers_variant(self) -> None:
        variant = score_track_match(
            "Shape of You (Acoustic)",
            "Ed Sheeran",
            "Shape of You (Acoustic)",
            "Ed Sheeran",
        )
        original = score_track_match(
            "Shape of You (Acoustic)",
            "Ed Sheeran",
            "Shape of You",
            "Ed Sheeran",
        )
        assert variant > original


class TestM3UResolutionRanking:
    def test_original_preferred_over_live(self) -> None:
        original = score_track_match(
            "Hotel California",
            "Eagles",
            "Hotel California",
            "Eagles",
        )
        live = score_track_match(
            "Hotel California",
            "Eagles",
            "Hotel California (Live)",
            "Eagles",
        )
        assert original > live

    def test_remaster_acceptable_for_m3u(self) -> None:
        score = score_track_match(
            "Hotel California",
            "Eagles",
            "Hotel California (2013 Remaster)",
            "Eagles",
        )
        assert score >= 0.7


class TestAlbumTypeScore:
    def test_single_ranks_highest(self) -> None:
        assert album_type_score("single") > album_type_score("album")

    def test_album_ranks_above_compilation(self) -> None:
        assert album_type_score("album") > album_type_score("compilation")

    def test_preference_order(self) -> None:
        order = ["single", "album", "ep", "compilation"]
        scores = [album_type_score(t) for t in order]
        assert scores == sorted(scores, reverse=True)

    def test_none_ranks_lowest(self) -> None:
        assert album_type_score(None) < album_type_score("compilation")

    def test_unknown_type_ranks_lowest(self) -> None:
        assert album_type_score("something_weird") < album_type_score("compilation")
