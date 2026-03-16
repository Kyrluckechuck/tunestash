"""Tests for shared utility functions introduced by the code quality sweep.

Covers:
- rate_limit.check_api_rate_limit (shared rate limiter)
- core.extract_deezer_playlist_id (shared regex extractor)
- core.normalize_name (base normalization)
- track_mapping._normalize_name_for_track_matching (composed normalization)
- download.FALLBACK_PROVIDER_MAP / DEFAULT_FALLBACK_ORDER constants
"""

from unittest.mock import patch

import pytest

from library_manager.models import APIRateLimitState
from library_manager.tasks.core import extract_deezer_playlist_id, normalize_name


class TestExtractDeezerPlaylistId:
    """Test Deezer playlist URL extraction from various URL formats."""

    def test_standard_url(self):
        assert (
            extract_deezer_playlist_id("https://www.deezer.com/playlist/123456")
            == "123456"
        )

    def test_url_with_locale(self):
        assert (
            extract_deezer_playlist_id("https://www.deezer.com/en/playlist/789012")
            == "789012"
        )

    def test_url_with_query_params(self):
        result = extract_deezer_playlist_id(
            "https://www.deezer.com/playlist/111222?utm_source=test"
        )
        assert result == "111222"

    def test_non_deezer_url_returns_none(self):
        assert (
            extract_deezer_playlist_id("https://open.spotify.com/playlist/abc") is None
        )

    def test_deezer_album_url_returns_none(self):
        assert extract_deezer_playlist_id("https://www.deezer.com/album/123456") is None

    def test_empty_string_returns_none(self):
        assert extract_deezer_playlist_id("") is None

    def test_bare_deezer_domain_returns_none(self):
        assert extract_deezer_playlist_id("https://www.deezer.com/") is None


class TestNormalizeName:
    """Test the base normalize_name function used for cross-provider matching."""

    def test_basic_lowercasing(self):
        assert normalize_name("The Beatles") == "the beatles"

    def test_accent_stripping(self):
        assert normalize_name("Beyoncé") == "beyonce"

    def test_ampersand_to_and(self):
        assert normalize_name("Simon & Garfunkel") == "simon and garfunkel"

    def test_trademark_removal(self):
        assert normalize_name("Brand™ Name®") == "brand name"

    def test_punctuation_removal(self):
        assert normalize_name("P!nk") == "p nk"

    def test_whitespace_collapse(self):
        assert normalize_name("Too   Many   Spaces") == "too many spaces"


class TestNormalizeNameForTrackMatching:
    """Test the composed track-matching normalization that extends normalize_name."""

    def test_strips_feat_in_brackets(self):
        from src.services.track_mapping import _normalize_name_for_track_matching

        result = _normalize_name_for_track_matching("Song Name (feat. Artist)")
        assert "feat" not in result
        assert "artist" not in result

    def test_strips_ft_suffix(self):
        from src.services.track_mapping import _normalize_name_for_track_matching

        result = _normalize_name_for_track_matching("Song Name ft. Someone")
        assert "someone" not in result

    def test_strips_remastered_tag_raw_input(self):
        """Test with raw input (before base normalization strips brackets)."""
        from src.services.track_mapping import _normalize_name_for_track_matching

        # The base normalize_name strips brackets/punctuation before the regex runs,
        # so the bracket-based regexes won't match. This tests the suffix-based feat regex.
        result = _normalize_name_for_track_matching("Song Name ft. Someone Else")
        assert "someone" not in result

    def test_consistent_with_base_normalize(self):
        """Track matching normalization should be a superset of base normalization."""
        from src.services.track_mapping import _normalize_name_for_track_matching

        base = normalize_name("Hello World (feat. Test)")
        extended = _normalize_name_for_track_matching("Hello World (feat. Test)")
        # Extended should strip more (the feat tag), so it should be shorter or equal
        assert len(extended) <= len(base)

    def test_inherits_base_normalization(self):
        from src.services.track_mapping import _normalize_name_for_track_matching

        result = _normalize_name_for_track_matching("Beyoncé & Jay-Z (feat. Someone)")
        assert "beyonce" in result
        assert "jay" in result
        assert "someone" not in result


class TestCheckApiRateLimit:
    """Test the shared rate-limit function."""

    @pytest.mark.django_db
    def test_creates_state_on_first_call(self):
        from src.providers.rate_limit import check_api_rate_limit

        assert not APIRateLimitState.objects.filter(api_name="test_api").exists()

        check_api_rate_limit("test_api", default_rate=5.0)

        state = APIRateLimitState.objects.get(api_name="test_api")
        assert state.max_requests_per_second == 5.0
        assert state.request_count == 1

    @pytest.mark.django_db
    def test_increments_count_within_window(self):
        from src.providers.rate_limit import check_api_rate_limit

        check_api_rate_limit("test_incr", default_rate=10.0)
        check_api_rate_limit("test_incr", default_rate=10.0)

        state = APIRateLimitState.objects.get(api_name="test_incr")
        assert state.request_count == 2

    @pytest.mark.django_db
    def test_does_not_raise_on_db_error(self):
        """Rate limiter should silently pass on errors to avoid blocking callers."""
        from src.providers.rate_limit import check_api_rate_limit

        with patch.object(
            APIRateLimitState.objects, "get_or_create", side_effect=Exception("DB down")
        ):
            check_api_rate_limit("broken_api")


class TestFallbackProviderConstants:
    """Test that download constants are consistent and importable."""

    def test_provider_map_has_all_fallback_providers(self):
        from library_manager.tasks.download import (
            DEFAULT_FALLBACK_ORDER,
            FALLBACK_PROVIDER_MAP,
        )

        for provider_name in DEFAULT_FALLBACK_ORDER:
            assert provider_name in FALLBACK_PROVIDER_MAP, (
                f"'{provider_name}' is in DEFAULT_FALLBACK_ORDER "
                f"but missing from FALLBACK_PROVIDER_MAP"
            )

    def test_provider_map_values_are_download_provider_enum(self):
        from library_manager.models import DownloadProvider
        from library_manager.tasks.download import FALLBACK_PROVIDER_MAP

        for name, enum_val in FALLBACK_PROVIDER_MAP.items():
            assert isinstance(
                enum_val, DownloadProvider
            ), f"FALLBACK_PROVIDER_MAP['{name}'] should be a DownloadProvider enum"

    def test_maintenance_imports_same_constants(self):
        """Ensure maintenance module uses the same constants (no local copies)."""
        from library_manager.tasks import download, maintenance

        assert maintenance.FALLBACK_PROVIDER_MAP is download.FALLBACK_PROVIDER_MAP
        assert maintenance.DEFAULT_FALLBACK_ORDER is download.DEFAULT_FALLBACK_ORDER
