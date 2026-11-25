"""Regression tests for track-match quality checks (title, artist, duration)."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from downloader.providers.base import (
    TrackMatch,
    TrackMetadata,
    calculate_match_confidence,
    is_duration_compatible,
)
from downloader.providers.fallback import DownloadChainResult
from downloader.providers.monochrome import MonochromeProvider
from downloader.providers.qobuz import QobuzProvider
from downloader.providers.tidal import TidalProvider
from downloader.providers.validation import (
    AudioFormat,
    AudioInfo,
    ValidationResult,
)
from downloader.providers.youtube import YouTubeMusicProvider
from downloader.track_matcher import score_track_match

GET_LOWER_DURATION_MS = 206_000
GET_LOWER_FILE_DURATION_MS = 191_000


def _audio_info(duration_ms: int) -> AudioInfo:
    return AudioInfo(
        format=AudioFormat.AAC,
        duration_ms=duration_ms,
        bitrate_kbps=256,
        sample_rate=44100,
        channels=2,
        bits_per_sample=None,
        file_size_bytes=1000,
    )


def _chain_result(duration_ms: int, match: TrackMatch) -> DownloadChainResult:
    validation = ValidationResult(
        is_valid=True,
        audio_info=_audio_info(duration_ms),
        errors=[],
        warnings=[],
    )
    return DownloadChainResult(
        success=True,
        file_path=None,
        provider_used=match.provider,
        error_message=None,
        track_match=match,
        validation_result=validation,
    )


class TestDurationCompatibility:
    """The audit's 8s/5% threshold is shared by search and post-download checks."""

    def test_get_lower_candidate_is_rejected(self):
        assert not is_duration_compatible(
            GET_LOWER_DURATION_MS, GET_LOWER_FILE_DURATION_MS
        )

    def test_small_difference_is_accepted(self):
        assert is_duration_compatible(200_000, 204_000)
        assert is_duration_compatible(240_000, 246_000)

    def test_five_percent_beyond_eight_seconds_is_rejected(self):
        assert not is_duration_compatible(300_000, 316_000)
        assert is_duration_compatible(300_000, 308_000)

    def test_unknown_duration_is_never_rejected(self):
        assert is_duration_compatible(0, 191_000)
        assert is_duration_compatible(206_000, 0)
        assert is_duration_compatible(None, 191_000)
        assert is_duration_compatible(206_000, None)


class TestProviderSearchDurationRejection:
    """A same-title recording by a different artist must not be matched."""

    def test_qobuz_rejects_get_lower(self):
        provider = QobuzProvider()
        album = {"title": "Album", "artist": {"name": "Test Artist E"}}
        tracks = [
            {
                "id": 1,
                "title": "Test Track Two",
                "duration": 191,
                "performer": {"name": "Test Artist E"},
                "isrc": "USDM32458801",
            }
        ]
        assert (
            provider._find_best_track_match(
                tracks,
                album,
                "Test Track Two",
                "Test Artist E",
                search_isrc="USDM32458801",
                search_duration_ms=GET_LOWER_DURATION_MS,
            )
            is None
        )

    def test_tidal_rejects_get_lower(self):
        provider = TidalProvider()
        results = [
            {
                "id": 1,
                "title": "Test Track Two",
                "duration": 191,
                "artists": [{"name": "Test Artist E"}],
                "isrc": "USDM32458801",
            }
        ]
        assert (
            provider._find_best_match(
                results,
                "Test Track Two",
                "Test Artist E",
                isrc="USDM32458801",
                duration_ms=GET_LOWER_DURATION_MS,
            )
            is None
        )

    def test_monochrome_rejects_get_lower(self):
        provider = MonochromeProvider()
        results = [
            {
                "id": 1,
                "title": "Test Track Two",
                "duration": 191,
                "artists": [{"name": "Test Artist E"}],
                "isrc": "USDM32458801",
            }
        ]
        assert (
            provider._find_best_match(
                results,
                "Test Track Two",
                "Test Artist E",
                isrc="USDM32458801",
                duration_ms=GET_LOWER_DURATION_MS,
            )
            is None
        )

    def test_youtube_rejects_get_lower(self):
        with patch("ytmusicapi.YTMusic") as mock_ytmusic:
            mock_ytmusic.return_value.search.return_value = [
                {
                    "videoId": "abc",
                    "title": "Test Track Two",
                    "artists": [{"name": "Test Artist E"}],
                    "duration_seconds": 191,
                }
            ]
            match = YouTubeMusicProvider()._search_track_sync(
                "Test Track Two",
                "Test Artist E",
                duration_ms=GET_LOWER_DURATION_MS,
            )
        assert match is None

    def test_duration_unknown_source_still_matches(self):
        provider = QobuzProvider()
        album = {"title": "Album", "artist": {"name": "Test Artist E"}}
        tracks = [
            {
                "id": 1,
                "title": "Test Track Two",
                "duration": 191,
                "performer": {"name": "Test Artist E"},
                "isrc": "USDM32458801",
            }
        ]
        result = provider._find_best_track_match(
            tracks,
            album,
            "Test Track Two",
            "Test Artist E",
            search_isrc="USDM32458801",
            search_duration_ms=0,
        )
        assert result is not None
        assert result.provider_track_id == "1"


class TestIsrcConflictPenalty:
    """A differing ISRC is a strong hint, not a verdict on its own."""

    def test_alternate_isrc_with_exact_signals_passes(self):
        score = score_track_match(
            "No Crime",
            "Asketa & Natan Chaim",
            "No Crime",
            "Asketa & Natan Chaim",
            search_isrc="NL1ZN2000188",
            result_isrc="NL1ZN2000025",
            search_duration_s=200.0,
            result_duration_s=200.3,
        )
        assert score >= 0.7

    def test_isrc_conflict_with_in_gate_duration_still_passes(self):
        # The hard duration gate (max 8s, 5%) is the sole duration verdict;
        # a 4s difference must not become a second, stricter ISRC gate.
        score = score_track_match(
            "Cross Me",
            "Ed Sheeran",
            "Cross Me",
            "Ed Sheeran",
            search_isrc="GBAHS1900715",
            result_isrc="GBAHS1900798",
            search_duration_s=204.0,
            result_duration_s=208.0,
        )
        assert score >= 0.7

    def test_isrc_conflict_plus_version_mismatch_fails(self):
        score = score_track_match(
            "Hey Baby (feat. Gia Koka)",
            "Imanbek",
            "Hey Baby (Radio Edit)",
            "Imanbek",
            search_isrc="USRC12345678",
            result_isrc="USRC87654321",
            search_duration_s=177.0,
            result_duration_s=177.0,
        )
        assert score < 0.6

    def test_isrc_conflict_plus_partial_artist_fails(self):
        score = score_track_match(
            "Test Track One",
            "Test Artist A",
            "Test Track One",
            "Unrelated Performer",
            search_isrc="TEST00000001",
            result_isrc="QMF123456789",
            search_duration_s=146.0,
            result_duration_s=147.0,
        )
        assert score < 0.6

    def test_matching_isrc_still_passes_with_duration_off_by_four_seconds(self):
        score = calculate_match_confidence(
            "Song",
            "Artist",
            "Song",
            "Artist",
            search_duration_ms=200_000,
            result_duration_ms=204_000,
            search_isrc="USRC12345678",
            result_isrc="USRC12345678",
        )
        assert score >= 0.7


class TestPostDownloadDurationFailure:
    """A measured file duration beyond the threshold fails the download."""

    def test_bad_measured_duration_fails_with_provider_outcome(self):
        from downloader.providers.fallback import DownloadProviderChain

        chain = DownloadProviderChain()
        match = TrackMatch(
            provider="youtube",
            provider_track_id="abc",
            title="Test Track Two",
            artist="Test Artist E",
            album="",
            duration_ms=GET_LOWER_FILE_DURATION_MS,
            confidence=0.9,
        )
        metadata = TrackMetadata(
            spotify_id="abc",
            title="Test Track Two",
            artist="Test Artist E",
            album="",
            album_artist="Test Artist E",
            duration_ms=GET_LOWER_DURATION_MS,
        )
        provider = MagicMock()
        provider.name = "youtube"
        provider.search_track = MagicMock()
        provider.download_track = MagicMock()

        async def _fake_search(**kwargs):
            return match

        async def _fake_download(**kwargs):
            from downloader.providers.base import DownloadResult

            return DownloadResult(
                success=True,
                provider="youtube",
                file_path=kwargs["output_path"],
            )

        provider.search_track = _fake_search
        provider.download_track = _fake_download
        chain._providers["youtube"] = provider
        chain._initialized.add("youtube")
        chain._provider_order = ["youtube"]
        chain._metadata_embedder = MagicMock()
        chain._metadata_embedder.embed_metadata.return_value = True
        chain._audio_validator = MagicMock()
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True,
            audio_info=_audio_info(GET_LOWER_FILE_DURATION_MS),
            errors=[],
            warnings=[],
        )
        chain._output_dir = Path("/tmp")

        with patch("downloader.providers.fallback.convert_flac_to_m4a"):
            result = asyncio.run(chain.download_track(metadata))

        assert result.success is False
        assert any(
            o.provider == "youtube" and o.stage == "validation" and o.outcome == "error"
            for o in result.provider_outcomes
        )
        assert "191000" in result.error_message

    def test_unknown_source_duration_does_not_fail(self):
        from downloader.providers.fallback import DownloadProviderChain

        chain = DownloadProviderChain()
        match = TrackMatch(
            provider="youtube",
            provider_track_id="abc",
            title="Test Track Two",
            artist="Test Artist E",
            album="",
            duration_ms=GET_LOWER_FILE_DURATION_MS,
            confidence=0.9,
        )
        metadata = TrackMetadata(
            spotify_id="abc",
            title="Test Track Two",
            artist="Test Artist E",
            album="",
            album_artist="Test Artist E",
            duration_ms=0,
        )
        provider = MagicMock()
        provider.name = "youtube"

        async def _fake_search(**kwargs):
            return match

        async def _fake_download(**kwargs):
            from downloader.providers.base import DownloadResult

            return DownloadResult(
                success=True,
                provider="youtube",
                file_path=kwargs["output_path"],
            )

        provider.search_track = _fake_search
        provider.download_track = _fake_download
        chain._providers["youtube"] = provider
        chain._initialized.add("youtube")
        chain._provider_order = ["youtube"]
        chain._metadata_embedder = MagicMock()
        chain._metadata_embedder.embed_metadata.return_value = True
        chain._audio_validator = MagicMock()
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True,
            audio_info=_audio_info(GET_LOWER_FILE_DURATION_MS),
            errors=[],
            warnings=[],
        )
        chain._output_dir = Path("/tmp")

        result = asyncio.run(chain.download_track(metadata))
        assert result.success is True


@pytest.mark.django_db
class TestMatchDetailsPersistence:
    """Successful matches write provider evidence to the Song row."""

    def test_records_match_details_from_provider_result(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.download import _record_successful_match

        artist = Artist.objects.create(name="Test Artist E", gid="gid-aoki")
        song = Song.objects.create(
            name="Test Track Two",
            primary_artist=artist,
            deezer_id=123,
        )
        match = TrackMatch(
            provider="youtube",
            provider_track_id="abc123",
            title="Test Track Two (Original Mix)",
            artist="Test Artist E",
            album="Album",
            duration_ms=206_000,
            isrc="USDM32458801",
            confidence=0.92,
        )
        result = _chain_result(204_500, match)

        with patch("library_manager.tasks.download.logger") as mock_logger:
            _record_successful_match(song, result)

        song.refresh_from_db()
        assert song.matched_provider == "youtube"
        assert song.matched_provider_track_id == "abc123"
        assert song.matched_title == "Test Track Two (Original Mix)"
        assert song.matched_artist == "Test Artist E"
        assert song.matched_duration_ms == 204_500
        assert song.matched_isrc == "USDM32458801"
        assert song.match_confidence == pytest.approx(0.92)
        assert song.matched_at is not None
        log_text = " ".join(str(c.args) for c in mock_logger.info.call_args_list)
        assert "song_id=%s" in log_text
        assert "abc123" in log_text

    def test_unknown_match_leaves_fields_null(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.download import _record_successful_match

        artist = Artist.objects.create(name="Artist", gid="gid-artist")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=2)
        result = DownloadChainResult(
            success=True,
            file_path=None,
            provider_used="youtube",
            error_message=None,
            track_match=None,
            validation_result=None,
        )
        _record_successful_match(song, result)
        song.refresh_from_db()
        assert song.matched_provider is None
        assert song.matched_at is None
