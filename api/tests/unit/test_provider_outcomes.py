"""Tests for provider outcome diagnostics in the download chain (Task 2)."""

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest
from downloader.providers.base import DownloadResult, TrackMatch, TrackMetadata
from downloader.providers.fallback import (
    MAX_OUTCOMES,
    DownloadChainResult,
    FallbackDownloader,
    ProviderOutcome,
    sanitize_provider_detail,
)
from downloader.providers.validation import ValidationResult


@pytest.fixture
def metadata():
    return TrackMetadata(
        spotify_id="abc123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        album_artist="Test Artist",
        duration_ms=180000,
        isrc="USRC12345678",
    )


@pytest.fixture
def track_match():
    return TrackMatch(
        provider="qobuz",
        provider_track_id="qobuz_456",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration_ms=180000,
        confidence=0.95,
    )


class TestBackwardCompatibility:
    def test_old_six_field_constructor_still_valid(self):
        result = DownloadChainResult(
            success=False,
            file_path=None,
            provider_used="tidal",
            error_message="failed",
            track_match=None,
            validation_result=None,
        )
        assert result.provider_outcomes == []

    def test_new_fields_are_defaulted(self):
        names = {f.name for f in fields(DownloadChainResult)}
        assert {
            "success",
            "file_path",
            "provider_used",
            "error_message",
            "track_match",
            "validation_result",
            "provider_outcomes",
        } <= names


class TestSanitizeProviderDetail:
    def test_strips_standard_url_query_and_credentials(self):
        detail = (
            "GET https://api.example.com/tracks?id=1&token=SECRET123 failed; "
            "Authorization: Bearer SECRET456; api_key=SECRET789"
        )
        cleaned = sanitize_provider_detail(detail)
        for secret in ("SECRET123", "SECRET456", "SECRET789"):
            assert secret not in cleaned
        assert "api.example.com" in cleaned

    def test_json_access_and_refresh_tokens_are_removed(self):
        detail = '{"access_token":"abc123","refresh_token":"def456","ok":true}'
        cleaned = sanitize_provider_detail(detail)
        assert "abc123" not in cleaned
        assert "def456" not in cleaned
        assert "true" in cleaned

    def test_cookie_whole_header_is_removed(self):
        cleaned = sanitize_provider_detail("Cookie: a=1; sid=SECRET; token=ABC")
        assert "SECRET" not in cleaned
        assert "ABC" not in cleaned
        assert "a=1" not in cleaned

    def test_url_userinfo_is_removed(self):
        cleaned = sanitize_provider_detail(
            "connect https://user:pass@host.example/x failed"
        )
        assert "user" not in cleaned
        assert "pass" not in cleaned
        assert "host.example" in cleaned

    def test_signed_path_and_fragment_are_not_emitted(self):
        detail = (
            "download https://cdn.example/sig/ABC123/file.flac "
            "https://cdn.example/file.flac#token=XYZ failed"
        )
        cleaned = sanitize_provider_detail(detail)
        assert "ABC123" not in cleaned
        assert "XYZ" not in cleaned
        assert "cdn.example" in cleaned

    def test_ordinary_prose_keywords_are_preserved(self):
        cleaned = sanitize_provider_detail(
            "session expired and key not found for track"
        )
        assert cleaned == "session expired and key not found for track"

    def test_bounds_length(self):
        cleaned = sanitize_provider_detail("x" * 2000)
        assert len(cleaned) <= 300


class TestOutcomeRecording:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_none_is_ambiguous_not_confirmed_no_match(
        self, tmp_path, metadata
    ):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(return_value=None)
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        result = await chain.download_track(metadata)

        assert not result.success
        assert len(result.provider_outcomes) == 1
        outcome = result.provider_outcomes[0]
        assert outcome.provider == "tidal"
        assert outcome.stage == "search"
        assert outcome.outcome == "no_result_unknown"
        assert "no matching track found" not in (result.error_message or "").lower()
        assert "or provider failure" in outcome.detail.lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_api_error_recorded_with_bounded_sanitized_detail(
        self, tmp_path, metadata
    ):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(
            side_effect=Exception(
                "HTTP 403 https://api.tidal.com/search?q=x&token=SECRETKEY"
            )
        )
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        result = await chain.download_track(metadata)

        assert len(result.provider_outcomes) == 1
        outcome = result.provider_outcomes[0]
        assert outcome.stage == "search"
        assert outcome.outcome == "error"
        assert "SECRETKEY" not in outcome.detail

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_exception_file_log_is_sanitized(
        self, tmp_path, metadata, caplog
    ):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(
            side_effect=Exception("Cookie: sid=LOGINSECRET failed")
        )
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        with caplog.at_level("ERROR", logger="downloader.providers.fallback"):
            await chain.download_track(metadata)

        assert "LOGINSECRET" not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_exception_file_log_is_sanitized(
        self, tmp_path, metadata, track_match, caplog
    ):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(return_value=track_match)
        provider.download_track = AsyncMock(
            side_effect=Exception("access_token=DOWNLOADSECRET")
        )
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        with caplog.at_level("ERROR", logger="downloader.providers.fallback"):
            await chain.download_track(metadata)

        assert "DOWNLOADSECRET" not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_unavailable_provider_recorded(self, tmp_path, metadata):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                chain,
                "_ensure_provider_initialized",
                AsyncMock(return_value=False),
            )
            result = await chain.download_track(metadata)

        assert len(result.provider_outcomes) == 1
        assert result.provider_outcomes[0].provider == "tidal"
        assert result.provider_outcomes[0].outcome == "unavailable"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_download_failure_recorded(self, tmp_path, metadata, track_match):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(return_value=track_match)
        provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=False, provider="tidal", error="HTTP 429 rate limited"
            )
        )
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        result = await chain.download_track(metadata)

        assert len(result.provider_outcomes) == 1
        assert result.provider_outcomes[0].stage == "download"
        assert result.provider_outcomes[0].outcome == "error"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_final_result_retains_all_attempts(self, tmp_path, metadata):
        chain = FallbackDownloader(
            output_dir=tmp_path, provider_order=["tidal", "qobuz"]
        )
        tidal = AsyncMock()
        tidal.name = "tidal"
        tidal.search_track = AsyncMock(side_effect=Exception("API down"))
        qobuz = AsyncMock()
        qobuz.name = "qobuz"
        qobuz.search_track = AsyncMock(return_value=None)
        chain._providers["tidal"] = tidal
        chain._providers["qobuz"] = qobuz
        chain._initialized.update(["tidal", "qobuz"])

        result = await chain.download_track(metadata)

        assert [o.provider for o in result.provider_outcomes] == ["tidal", "qobuz"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_success_retains_earlier_failure_outcomes(
        self, tmp_path, metadata, track_match
    ):
        chain = FallbackDownloader(
            output_dir=tmp_path, provider_order=["tidal", "qobuz"]
        )
        tidal = AsyncMock()
        tidal.name = "tidal"
        tidal.search_track = AsyncMock(side_effect=Exception("API down"))
        qobuz = AsyncMock()
        qobuz.name = "qobuz"
        qobuz.search_track = AsyncMock(return_value=track_match)
        output = tmp_path / "Test Artist - Test Song.m4a"
        output.touch()
        qobuz.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="qobuz",
                file_path=output,
                format="m4a",
                bitrate_kbps=256,
            )
        )
        chain._providers["tidal"] = tidal
        chain._providers["qobuz"] = qobuz
        chain._initialized.update(["tidal", "qobuz"])
        chain._audio_validator = MagicMock()
        chain._audio_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=True, audio_info=None, errors=[], warnings=[]
            )
        )

        result = await chain.download_track(metadata)

        assert result.success
        assert len(result.provider_outcomes) >= 2
        assert result.provider_outcomes[0].outcome == "error"
        assert any(
            o.stage == "download" and o.outcome == "success"
            for o in result.provider_outcomes
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_nonfatal_warnings_are_recorded_without_failing(
        self, tmp_path, metadata, track_match
    ):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(return_value=track_match)
        output = tmp_path / "Test Artist - Test Song.m4a"
        output.touch()
        provider.download_track = AsyncMock(
            return_value=DownloadResult(
                success=True,
                provider="tidal",
                file_path=output,
                format="m4a",
                bitrate_kbps=256,
            )
        )
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")
        chain._metadata_embedder = MagicMock()
        chain._metadata_embedder.embed_metadata = MagicMock(return_value=False)
        chain._audio_validator = MagicMock()
        chain._audio_validator.validate = MagicMock(
            return_value=ValidationResult(
                is_valid=False,
                audio_info=None,
                errors=["Duration mismatch"],
                warnings=[],
            )
        )

        result = await chain.download_track(metadata)

        assert result.success
        stages = {o.stage for o in result.provider_outcomes}
        assert {"metadata", "validation"} <= stages

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_chain_truncation_has_explicit_marker(self, tmp_path, metadata):
        chain = FallbackDownloader(output_dir=tmp_path, provider_order=["tidal"])
        provider = AsyncMock()
        provider.name = "tidal"
        provider.search_track = AsyncMock(side_effect=Exception("API down"))
        chain._providers["tidal"] = provider
        chain._initialized.add("tidal")

        # Force more than MAX_OUTCOMES records from a single provider attempt.
        chain._outcome = lambda *a, **kw: ProviderOutcome("tidal", "search", "error")
        chain._try_provider = AsyncMock(
            return_value=DownloadChainResult(
                success=False,
                file_path=None,
                provider_used="tidal",
                error_message="failed",
                track_match=None,
                validation_result=None,
                provider_outcomes=[
                    ProviderOutcome("tidal", "search", "error", str(i))
                    for i in range(MAX_OUTCOMES + 3)
                ],
            )
        )

        result = await chain.download_track(metadata)

        markers = [o for o in result.provider_outcomes if o.stage == "summary"]
        assert markers
        assert "omitted" in markers[0].detail
        assert "3" in markers[0].detail
