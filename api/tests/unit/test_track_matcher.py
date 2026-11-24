"""Tests for the shared track matching module."""

from downloader.track_matcher import (
    album_type_score,
    compute_tag_penalty,
    extract_title_tags,
    has_version_conflict,
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

    def test_isrc_whitespace_normalization_is_consistent(self) -> None:
        padded = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
            search_isrc=" USRC12345678 ",
            result_isrc="usrc12345678",
        )
        exact = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
        )
        assert padded == exact

    def test_blank_isrcs_do_not_bypass_artist_gate(self) -> None:
        score = score_track_match(
            "Avoidant",
            "CHEZ",
            "Avoidance",
            "Detz",
            search_isrc="   ",
            result_isrc=" ",
        )
        assert score == 0.0

    def test_blank_isrcs_do_not_count_as_a_match(self) -> None:
        baseline = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
        )
        blank = score_track_match(
            "Bailando",
            "Enrique Iglesias",
            "Bailando",
            "Enrique Iglesias",
            search_isrc="   ",
            result_isrc=" ",
        )
        assert blank == baseline

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


class TestArtistCompatibility:
    """Artist credit must be an independent gate, not just a fuzzy score."""

    def test_rejects_unrelated_artists_with_similar_titles(self) -> None:
        # Production regression: CHEZ "Avoidant" was matched to Detz
        # "Avoidance" at 0.6618, above the 0.6 acceptance threshold.
        score = score_track_match("Avoidant", "CHEZ", "Avoidance", "Detz")
        assert score < 0.6

    def test_rejects_unrelated_artists_without_isrc_or_duration(self) -> None:
        # Production regression: Jon Pumper "Change (Piano Version)" was
        # matched to jame "Change" at 0.7143.
        score = score_track_match(
            "Change (Piano Version)",
            "Jon Pumper",
            "Change",
            "jame",
        )
        assert score < 0.6

    def test_accepts_comma_and_ampersand_collaboration_credit(self) -> None:
        comma = score_track_match(
            "Song",
            "Artist A, Artist B",
            "Song",
            "Artist A & Artist B",
        )
        assert comma >= 0.9

    def test_accepts_bullet_separated_youtube_credit(self) -> None:
        score = score_track_match(
            "Levitating",
            "Dua Lipa",
            "Levitating",
            "Dua Lipa • DaBaby",
        )
        assert score >= 0.7

    def test_accepts_featured_artist_credit(self) -> None:
        score = score_track_match(
            "Song",
            "Artist A feat. Artist B",
            "Song",
            "Artist A featuring Artist B",
        )
        assert score >= 0.9

    def test_many_collaborators_are_not_rejected_by_count(self) -> None:
        score = score_track_match(
            "All Stars",
            "Artist A, Artist B, Artist C, Artist D",
            "All Stars",
            "Artist A • Artist B • Artist C • Artist D",
        )
        assert score >= 0.8

    def test_same_primary_artist_with_extra_collaborator_is_retained(self) -> None:
        score = score_track_match(
            "Song",
            "Artist A",
            "Song",
            "Artist A • Artist B",
        )
        assert score >= 0.8

    def test_slash_and_compact_alias_ac_dc(self) -> None:
        score = score_track_match(
            "Thunderstruck",
            "AC/DC",
            "Thunderstruck",
            "ACDC",
        )
        assert score >= 0.9

    def test_punctuation_alias_pink(self) -> None:
        score = score_track_match(
            "So What",
            "P!nk",
            "So What",
            "Pink",
        )
        assert score >= 0.9

    def test_punctuation_alias_kesha(self) -> None:
        score = score_track_match(
            "Tik Tok",
            "Ke$ha",
            "Tik Tok",
            "Kesha",
        )
        assert score >= 0.9

    def test_band_short_credit_matches_full_member_credit(self) -> None:
        score = score_track_match(
            "Maneater",
            "Hall & Oates",
            "Maneater",
            "Daryl Hall & John Oates",
        )
        assert score >= 0.8

    def test_band_full_credit_matches_short_member_credit(self) -> None:
        score = score_track_match(
            "Maneater",
            "Daryl Hall & John Oates",
            "Maneater",
            "Hall & Oates",
        )
        assert score >= 0.8

    def test_single_word_is_not_a_substring_alias(self) -> None:
        score = score_track_match(
            "So What",
            "Pink",
            "So What",
            "Pink Floyd",
        )
        assert score < 0.6

    def test_short_artist_names_are_not_substring_aliases(self) -> None:
        air_score = score_track_match(
            "Song",
            "Air",
            "Song",
            "Air Supply",
        )
        prince_score = score_track_match(
            "Song",
            "Prince",
            "Song",
            "Prince Royce",
        )
        assert air_score < 0.6
        assert prince_score < 0.6

    def test_vevo_suffix_is_not_an_automatic_alias(self) -> None:
        score = score_track_match(
            "Song",
            "Artist",
            "Song",
            "ArtistVEVO",
        )
        assert score < 0.6

    def test_identical_isrc_allows_transliterated_artist_names(self) -> None:
        score = score_track_match(
            "Song",
            "Мельница",
            "Song",
            "Melnitsa",
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
            search_duration_s=240.0,
            result_duration_s=240.0,
        )
        assert score >= 0.8

    def test_isrc_does_not_override_version_conflict(self) -> None:
        score = score_track_match(
            "Song (Extended Mix)",
            "Artist",
            "Song (Acoustic Version)",
            "Artist",
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
            search_duration_s=240.0,
            result_duration_s=240.0,
        )
        assert score < 0.6


class TestVersionProtection:
    """Version distinctions must survive even when the aggregate is high."""

    def test_plain_title_does_not_match_piano_version(self) -> None:
        score = score_track_match(
            "Change",
            "Jon Pumper",
            "Change (Piano Version)",
            "Jon Pumper",
        )
        assert score < 0.6

    def test_piano_version_does_not_match_plain_title(self) -> None:
        score = score_track_match(
            "Change (Piano Version)",
            "Jon Pumper",
            "Change",
            "Jon Pumper",
        )
        assert score < 0.6

    def test_mixed_is_not_identical_to_mix_cut(self) -> None:
        score = score_track_match("Mixed", "Fatum", "Mix Cut", "Fatum")
        assert score < 0.6

    def test_bracketed_mix_cut_is_not_identical_to_plain_title(self) -> None:
        score = score_track_match(
            "Mixed",
            "Fatum",
            "Mixed (Mix Cut)",
            "Fatum",
        )
        assert score < 0.6

    def test_same_version_still_matches_strongly(self) -> None:
        score = score_track_match(
            "Change (Piano Version)",
            "Jon Pumper",
            "Change (Piano Version)",
            "Jon Pumper",
        )
        assert score >= 0.9

    def test_remaster_remains_acceptable(self) -> None:
        score = score_track_match(
            "Bohemian Rhapsody",
            "Queen",
            "Bohemian Rhapsody (2011 Remaster)",
            "Queen",
        )
        assert score >= 0.7

    def test_extended_mix_and_extended_version_are_equivalent(self) -> None:
        assert (
            score_track_match(
                "Song (Extended Mix)",
                "Artist",
                "Song (Extended Version)",
                "Artist",
            )
            >= 0.9
        )
        assert (
            score_track_match(
                "Song (Extended Mix)",
                "Artist",
                "Song (Extended)",
                "Artist",
            )
            >= 0.9
        )

    def test_radio_edit_and_radio_version_are_equivalent(self) -> None:
        score = score_track_match(
            "Song (Radio Edit)",
            "Artist",
            "Song (Radio Version)",
            "Artist",
        )
        assert score >= 0.9

    def test_acoustic_and_acoustic_version_are_equivalent(self) -> None:
        score = score_track_match(
            "Song (Acoustic)",
            "Artist",
            "Song (Acoustic Version)",
            "Artist",
        )
        assert score >= 0.9

    def test_live_and_live_version_are_equivalent(self) -> None:
        score = score_track_match(
            "Song (Live)",
            "Artist",
            "Song (Live Version)",
            "Artist",
        )
        assert score >= 0.9

    def test_same_live_venue_still_matches(self) -> None:
        score = score_track_match(
            "Song (Live at Wembley)",
            "Artist",
            "Song (Live at Wembley)",
            "Artist",
        )
        assert score >= 0.9

    def test_different_live_venues_remain_distinct(self) -> None:
        score = score_track_match(
            "Song (Live at Wembley)",
            "Artist",
            "Song (Live at O2)",
            "Artist",
        )
        assert score < 0.6

    def test_piano_and_mixed_words_in_titles_are_not_variants(self) -> None:
        piano_penalty = compute_tag_penalty([], ["Piano Man"])
        mixed_penalty = compute_tag_penalty([], ["Mixed Emotions"])
        assert piano_penalty == 0.0
        assert mixed_penalty == 0.0

    def test_named_remixes_remain_distinct(self) -> None:
        foo = score_track_match(
            "Song (Foo Remix)",
            "Artist",
            "Song (Foo Remix)",
            "Artist",
        )
        bar = score_track_match(
            "Song (Foo Remix)",
            "Artist",
            "Song (Bar Remix)",
            "Artist",
        )
        assert foo >= 0.9
        assert bar < 0.6

    def test_remix_by_alias_matches_named_remix(self) -> None:
        score = score_track_match(
            "Song (Foo Remix)",
            "Artist",
            "Song (Remix by Foo)",
            "Artist",
        )
        assert score >= 0.9

    def test_named_demos_remain_distinct(self) -> None:
        same = score_track_match(
            "Song (Demo2019)",
            "Artist",
            "Song (Demo 2019)",
            "Artist",
        )
        different = score_track_match(
            "Song (Demo2019)",
            "Artist",
            "Song (Demo2020)",
            "Artist",
        )
        assert same >= 0.9
        assert different < 0.6

    def test_standalone_version_words_do_not_conflict(self) -> None:
        cases = (
            ("Song - Extended Version", "Song (Extended Mix)"),
            ("Song - Radio Mix", "Song (Radio Edit)"),
            ("Song - Live Version", "Song (Live)"),
        )
        for search_title, result_title in cases:
            _, search_tags = extract_title_tags(search_title)
            _, result_tags = extract_title_tags(result_title)
            assert not has_version_conflict(
                search_title,
                result_title,
                search_tags,
                result_tags,
            )

    def test_dash_suffix_versions_match_parenthetical_versions(self) -> None:
        cases = (
            ("Song - Foo Remix", "Song (Foo Remix)"),
            ("Song - Live", "Song (Live)"),
            ("Song - Acoustic", "Song (Acoustic)"),
            ("Song - Remastered 2011", "Song"),
        )
        for search_title, result_title in cases:
            score = score_track_match(
                search_title,
                "Artist",
                result_title,
                "Artist",
                search_isrc="USRC12345678",
                result_isrc="USRC12345678",
            )
            assert score >= 0.9, (search_title, result_title, score)

    def test_dash_suffix_named_remixer_difference_still_conflicts(self) -> None:
        score = score_track_match(
            "Song - Foo Remix",
            "Artist",
            "Song (Bar Remix)",
            "Artist",
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
        )
        assert score < 0.6

    def test_natural_dash_titles_are_preserved(self) -> None:
        core, tags = extract_title_tags("Part 2 - The Return")
        assert core == "Part 2 - The Return"
        assert tags == []
        core, tags = extract_title_tags("Song - Foo Remix")
        assert core == "Song"
        assert tags == ["foo remix"]

    def test_live_version_with_venue_matches_live_with_venue(self) -> None:
        score = score_track_match(
            "Song (Live Version at Wembley)",
            "Artist",
            "Song (Live at Wembley)",
            "Artist",
        )
        assert score >= 0.9

    def test_real_trailing_s_in_remixer_is_not_stripped(self) -> None:
        different = score_track_match(
            "Song (Mr S Remix)",
            "Artist",
            "Song (Mr Remix)",
            "Artist",
        )
        assert different < 0.6

    def test_possessive_remixer_still_matches_plain_remixer(self) -> None:
        score = score_track_match(
            "Song (Foo's Remix)",
            "Artist",
            "Song (Foo Remix)",
            "Artist",
        )
        assert score >= 0.9


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
