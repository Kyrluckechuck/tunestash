"""Regression tests for the independent review of the matcher improvements."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from downloader.providers.base import (
    DownloadProvider,
    DownloadResult,
    ProviderCapabilities,
    ProviderType,
    TrackMatch,
    TrackMetadata,
    calculate_match_confidence,
    is_duration_compatible,
    rejected_key,
)
from downloader.providers.fallback import (
    DownloadChainResult,
    DownloadProviderChain,
    ProviderOutcome,
)
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


def _audio_info(duration_ms):
    return AudioInfo(
        format=AudioFormat.AAC,
        duration_ms=duration_ms,
        bitrate_kbps=256,
        sample_rate=44100,
        channels=2,
        bits_per_sample=None,
        file_size_bytes=1000,
    )


def _success_result(file_path):
    return DownloadChainResult(
        success=True,
        file_path=Path(file_path),
        provider_used="youtube",
        error_message=None,
        track_match=_match("youtube", "abc", 206_000),
        validation_result=None,
    )


def _match(provider, track_id, duration_ms, title="Get Lower", artist="Steve Aoki"):
    return TrackMatch(
        provider=provider,
        provider_track_id=track_id,
        title=title,
        artist=artist,
        album="",
        duration_ms=duration_ms,
        isrc="USDM32458801",
        confidence=0.9,
    )


class TestAlternateIsrcs:
    def test_alternate_isrc_counts_as_a_match(self):
        score = score_track_match(
            "No Crime",
            "Asketa & Natan Chaim",
            "No Crime",
            "Asketa & Natan Chaim",
            search_isrc="NL1ZN2000188",
            search_alternate_isrcs=["NL1ZN2000025"],
            result_isrc="NL1ZN2000025",
            search_duration_s=200.0,
            result_duration_s=203.0,
        )
        assert score >= 0.9

    def test_confidence_helper_forwards_alternate_isrcs(self):
        score = calculate_match_confidence(
            "No Crime",
            "Asketa & Natan Chaim",
            "No Crime",
            "Asketa & Natan Chaim",
            search_duration_ms=200_000,
            result_duration_ms=203_000,
            search_isrc="NL1ZN2000188",
            result_isrc="NL1ZN2000025",
            search_alternate_isrcs=["  nl1zn2000025 "],
        )
        assert score >= 0.9

    @pytest.mark.parametrize(
        "result_duration_s",
        [203.0, 208.0, 315.0],
        ids=["three_seconds", "eight_seconds", "five_percent"],
    )
    def test_unknown_isrc_conflict_within_gate_still_passes(self, result_duration_s):
        source_s = 300.0 if result_duration_s == 315.0 else 200.0
        assert is_duration_compatible(
            int(source_s * 1000), int(result_duration_s * 1000)
        )
        score = score_track_match(
            "Song",
            "Artist",
            "Song",
            "Artist",
            search_isrc="USRC11111111",
            result_isrc="USRC22222222",
            search_duration_s=source_s,
            result_duration_s=result_duration_s,
        )
        assert score >= 0.7

    def test_unknown_isrc_conflict_beyond_gate_is_rejected(self):
        assert not is_duration_compatible(200_000, 216_000)
        score = score_track_match(
            "Song",
            "Artist",
            "Song",
            "Artist",
            search_isrc="USRC11111111",
            result_isrc="USRC22222222",
            search_duration_s=200.0,
            result_duration_s=216.0,
        )
        assert score < 0.6

    def test_unknown_isrc_conflict_with_partial_artist_still_rejected(self):
        score = score_track_match(
            "Shut Up And Dance",
            "Test Artist A",
            "Shut Up And Dance",
            "Test Artist B",
            search_isrc="TEST00000001",
            result_isrc="QMF123456789",
            search_duration_s=146.0,
            result_duration_s=147.0,
        )
        assert score < 0.6


class TestProviderExclusion:
    def test_qobuz_skips_rejected_track(self):
        album = {"title": "Album", "artist": {"name": "Steve Aoki"}}
        tracks = [
            {
                "id": 1,
                "title": "Get Lower",
                "duration": 206,
                "performer": {"name": "Steve Aoki"},
            },
            {
                "id": 2,
                "title": "Get Lower",
                "duration": 206,
                "performer": {"name": "Steve Aoki"},
            },
        ]
        result = QobuzProvider()._find_best_track_match(
            tracks,
            album,
            "Get Lower",
            "Steve Aoki",
            excluded_track_ids={"qobuz:1"},
        )
        assert result.provider_track_id == "2"

    def test_tidal_skips_rejected_track(self):
        results = [
            {
                "id": 1,
                "title": "Get Lower",
                "duration": 206,
                "artists": [{"name": "Steve Aoki"}],
            },
            {
                "id": 2,
                "title": "Get Lower",
                "duration": 206,
                "artists": [{"name": "Steve Aoki"}],
            },
        ]
        match = TidalProvider()._find_best_match(
            results,
            "Get Lower",
            "Steve Aoki",
            excluded_track_ids={"tidal:1"},
        )
        assert match.provider_track_id == "2"

    def test_monochrome_skips_rejected_track(self):
        results = [
            {
                "id": 1,
                "title": "Get Lower",
                "duration": 206,
                "artists": [{"name": "Steve Aoki"}],
            },
            {
                "id": 2,
                "title": "Get Lower",
                "duration": 206,
                "artists": [{"name": "Steve Aoki"}],
            },
        ]
        match = MonochromeProvider()._find_best_match(
            results,
            "Get Lower",
            "Steve Aoki",
            excluded_track_ids={"monochrome:1"},
        )
        assert match.provider_track_id == "2"

    def test_youtube_skips_rejected_track(self):
        with patch("ytmusicapi.YTMusic") as mock_ytmusic:
            mock_ytmusic.return_value.search.return_value = [
                {
                    "videoId": "bad",
                    "title": "Get Lower",
                    "artists": [{"name": "Steve Aoki"}],
                    "duration_seconds": 206,
                },
                {
                    "videoId": "good",
                    "title": "Get Lower",
                    "artists": [{"name": "Steve Aoki"}],
                    "duration_seconds": 206,
                },
            ]
            match = YouTubeMusicProvider()._search_track_sync(
                "Get Lower",
                "Steve Aoki",
                excluded_track_ids={"youtube:bad"},
            )
        assert match.provider_track_id == "good"

    def test_key_includes_provider(self):
        assert rejected_key("youtube", "abc") == "youtube:abc"
        assert rejected_key("tidal", "abc") != rejected_key("youtube", "abc")


class _FakeProvider(DownloadProvider):
    """Provider whose search honours exclusions, exposing the ranked catalog."""

    name = "fake"
    display_name = "Fake"

    def __init__(self, candidates, measured_duration):
        self.candidates = candidates
        self.measured_duration = measured_duration
        self.search_calls = []
        self.download_calls = []

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_type=ProviderType.REST_API,
            supports_search=True,
            supports_isrc_lookup=False,
            embeds_metadata=False,
            available_qualities=(),
            formats=(),
        )

    async def is_available(self):
        return True

    async def search_track(
        self,
        title,
        artist,
        album=None,
        isrc=None,
        duration_ms=None,
        excluded_track_ids=None,
    ):
        self.search_calls.append(set(excluded_track_ids or ()))
        for match in self.candidates:
            if rejected_key(self.name, match.provider_track_id) not in (
                excluded_track_ids or ()
            ):
                return match
        return None

    async def download_track(self, track_match, output_path, quality=None):
        self.download_calls.append(track_match.provider_track_id)
        return DownloadResult(success=True, provider=self.name, file_path=output_path)


def _chain_for(provider):
    chain = DownloadProviderChain()
    chain._providers["fake"] = provider
    chain._initialized.add("fake")
    chain._provider_order = ["fake"]
    chain._metadata_embedder = MagicMock()
    chain._metadata_embedder.embed_metadata.return_value = True
    chain._audio_validator = MagicMock()
    return chain


def _metadata():
    return TrackMetadata(
        spotify_id="abc",
        title="Get Lower",
        artist="Steve Aoki",
        album="",
        album_artist="Steve Aoki",
        duration_ms=206_000,
    )


class TestRejectedCandidateRetry:
    def test_retry_within_same_attempt_reaches_second_candidate(self, tmp_path):
        bad = _match("fake", "bad", 191_000)
        good = _match("fake", "good", 206_000)
        provider = _FakeProvider([bad, good], measured_duration=None)
        chain = _chain_for(provider)
        chain._output_dir = tmp_path
        chain._audio_validator.validate.side_effect = [
            ValidationResult(
                is_valid=True, audio_info=_audio_info(191_000), errors=[], warnings=[]
            ),
            ValidationResult(
                is_valid=True, audio_info=_audio_info(206_000), errors=[], warnings=[]
            ),
        ]

        result = asyncio.run(chain.download_track(_metadata()))

        assert result.success is True
        assert result.track_match.provider_track_id == "good"
        assert provider.download_calls == ["bad", "good"]
        assert any(
            entry["key"] == rejected_key("fake", "bad")
            for entry in result.rejected_matches
        )

    def test_no_other_candidate_fails_without_redownloading(self, tmp_path):
        bad = _match("fake", "bad", 191_000)
        provider = _FakeProvider([bad], measured_duration=None)
        chain = _chain_for(provider)
        chain._output_dir = tmp_path
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True, audio_info=_audio_info(191_000), errors=[], warnings=[]
        )

        result = asyncio.run(chain.download_track(_metadata()))

        assert result.success is False
        assert provider.download_calls == ["bad"]
        assert len(provider.search_calls) == 2
        assert rejected_key("fake", "bad") in provider.search_calls[1]
        assert result.rejected_matches

    def test_rejected_ids_from_previous_attempt_are_honoured(self, tmp_path):
        good = _match("fake", "good", 206_000)
        provider = _FakeProvider([_match("fake", "bad", 191_000), good], None)
        chain = _chain_for(provider)
        chain._output_dir = tmp_path
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True, audio_info=_audio_info(206_000), errors=[], warnings=[]
        )

        result = asyncio.run(
            chain.download_track(
                _metadata(),
                rejected_track_ids={rejected_key("fake", "bad")},
            )
        )

        assert result.success is True
        assert provider.download_calls == ["good"]


@pytest.mark.django_db
class TestRejectedMatchPersistence:
    def test_non_track_match_is_never_persisted(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.download import _record_successful_match

        artist = Artist.objects.create(name="Artist", gid="gid-nonmatch")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=13)
        result = MagicMock()
        result.track_match = MagicMock()
        result.provider_used = "youtube"
        result.validation_result = None

        _record_successful_match(song, result)

        song.refresh_from_db()
        assert song.matched_provider is None
        assert song.matched_provider_track_id is None

    def test_rejected_matches_are_persisted_and_bounded(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.download import _record_rejected_matches

        artist = Artist.objects.create(name="Artist", gid="gid-reject")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=9)
        result = DownloadChainResult(
            success=False,
            file_path=None,
            provider_used=None,
            error_message="Measured duration mismatch",
            track_match=None,
            validation_result=None,
            provider_outcomes=[],
            rejected_matches=[
                {
                    "provider": "youtube",
                    "provider_track_id": str(i),
                    "reason": "duration",
                }
                for i in range(25)
            ],
        )

        _record_rejected_matches(song, result)
        song.refresh_from_db()
        assert len(song.rejected_matches) == 20
        assert song.rejected_matches[-1]["provider_track_id"] == "24"
        assert "at" in song.rejected_matches[-1]

    def test_retry_passes_persisted_rejections_to_chain(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.maintenance import (
            _download_deezer_songs_via_fallback,
        )

        artist = Artist.objects.create(name="Artist", gid="gid-retry")
        song = Song.objects.create(
            name="Song",
            primary_artist=artist,
            deezer_id=10,
            rejected_matches=[
                {
                    "provider": "youtube",
                    "provider_track_id": "bad",
                    "reason": "duration",
                    "at": "2026-01-01T00:00:00+00:00",
                }
            ],
        )
        captured = {}

        async def _fake_download(self, metadata, rejected_track_ids=None, **kwargs):
            captured["rejected"] = set(rejected_track_ids or ())
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=None,
                error_message="failed",
                track_match=None,
                validation_result=None,
                provider_outcomes=[],
            )

        with (
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=_fake_download,
            ),
            patch("library_manager.tasks.maintenance._try_resolve_to_deezer"),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
        ):
            _download_deezer_songs_via_fallback([song])

        assert captured["rejected"] == {"youtube:bad"}


@pytest.mark.django_db
class TestMaintenanceFinalization:
    def test_success_persists_match_details(self):
        from library_manager.models import Artist, Song
        from library_manager.tasks.maintenance import (
            _download_deezer_songs_via_fallback,
        )

        artist = Artist.objects.create(name="Artist", gid="gid-maint-success")
        song = Song.objects.create(
            name="Get Lower", primary_artist=artist, deezer_id=11
        )
        match = _match("youtube", "abc", 206_000)
        result = DownloadChainResult(
            success=True,
            file_path=Path("/tmp/music/file.m4a"),
            provider_used="youtube",
            error_message=None,
            track_match=match,
            validation_result=ValidationResult(
                is_valid=True,
                audio_info=_audio_info(206_000),
                errors=[],
                warnings=[],
            ),
        )

        with (
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=AsyncMock(return_value=result),
            ),
            patch("library_manager.tasks.maintenance._try_resolve_to_deezer"),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
        ):
            downloaded, failed = _download_deezer_songs_via_fallback([song])

        assert (downloaded, failed) == (1, 0)
        song.refresh_from_db()
        assert song.matched_provider == "youtube"
        assert song.matched_provider_track_id == "abc"
        assert song.matched_duration_ms == 206_000

    def test_failure_emits_provider_outcomes(self):
        from tests.factories import TaskHistoryFactory

        from library_manager.models import Artist, Song
        from library_manager.tasks.maintenance import (
            _download_deezer_songs_via_fallback,
        )

        artist = Artist.objects.create(name="Artist", gid="gid-maint-failure")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=12)
        history = TaskHistoryFactory.create(log_messages=[])
        result = DownloadChainResult(
            success=False,
            file_path=None,
            provider_used=None,
            error_message="failed",
            track_match=None,
            validation_result=None,
            provider_outcomes=[
                ProviderOutcome("youtube", "validation", "error", "duration bad")
            ],
        )

        with (
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=AsyncMock(return_value=result),
            ),
            patch("library_manager.tasks.maintenance._try_resolve_to_deezer"),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
            patch("library_manager.tasks.download.logger") as mock_logger,
        ):
            _download_deezer_songs_via_fallback([song], task_history=history)

        text = " ".join(str(c.args) for c in mock_logger.warning.call_args_list)
        assert "stage=validation" in text
        assert "youtube" in text
        history.refresh_from_db()
        assert any("stage=validation" in str(m) for m in history.log_messages)


@pytest.mark.django_db
class TestForcedCancellationCheck:
    def test_cancel_just_before_provider_call_stops_download(self):
        from tests.factories import TaskHistoryFactory

        from library_manager.models import Artist, Song
        from library_manager.tasks import core as core_tasks
        from library_manager.tasks.download import download_deezer_track

        artist = Artist.objects.create(name="Artist", gid="gid-cancel")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=20)
        history = TaskHistoryFactory.create(task_id="cancel-before-provider")
        cancel_state = {"set": False}

        def _mark_cancelled_then_check(task_history, *, force_refresh=False):
            if not cancel_state["set"]:
                cancel_state["set"] = True
                history.status = "CANCELLED"
                history.save(update_fields=["status"])
            return core_tasks.raise_if_cancelled(
                task_history, force_refresh=force_refresh
            )

        provider_download = AsyncMock()

        with (
            patch(
                "library_manager.tasks.download.create_task_history",
                return_value=history,
            ),
            patch("library_manager.tasks.download.require_download_capability"),
            patch("library_manager.tasks.download.update_task_progress"),
            patch(
                "library_manager.tasks.download.raise_if_cancelled",
                side_effect=_mark_cancelled_then_check,
            ),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=provider_download,
            ),
        ):
            with pytest.raises(core_tasks.TaskCancelledException):
                download_deezer_track(song.id)

        provider_download.assert_not_called()
        song.refresh_from_db()
        assert song.downloaded is False


class TestAlternateIsrcSearchInterface:
    @pytest.mark.parametrize(
        "provider_cls",
        [YouTubeMusicProvider, QobuzProvider, TidalProvider, MonochromeProvider],
    )
    def test_search_accepts_alternate_isrcs(self, provider_cls):
        import inspect

        params = inspect.signature(provider_cls.search_track).parameters
        assert "search_alternate_isrcs" in params

    def test_youtube_search_runs_with_alternate_isrcs(self):
        with patch("ytmusicapi.YTMusic") as mock_ytmusic:
            mock_ytmusic.return_value.search.return_value = []
            result = asyncio.run(
                YouTubeMusicProvider().search_track(
                    "Song",
                    "Artist",
                    isrc="USRC11111111",
                    duration_ms=200_000,
                    search_alternate_isrcs=["USRC22222222"],
                )
            )
        assert result is None

    def test_qobuz_search_runs_with_alternate_isrcs(self):
        provider = QobuzProvider()
        with patch.object(provider, "_search_music", new=AsyncMock(return_value=None)):
            result = asyncio.run(
                provider.search_track(
                    "Song", "Artist", search_alternate_isrcs=["USRC22222222"]
                )
            )
        assert result is None

    def test_tidal_search_runs_with_alternate_isrcs(self):
        provider = TidalProvider()
        with patch.object(
            provider._endpoint_manager, "get_all_healthy_endpoints", return_value=[]
        ):
            result = asyncio.run(
                provider.search_track(
                    "Song", "Artist", search_alternate_isrcs=["USRC22222222"]
                )
            )
        assert result is None

    def test_monochrome_search_runs_with_alternate_isrcs(self):
        provider = MonochromeProvider()
        with patch.object(
            provider._endpoint_manager, "get_healthy_endpoints", return_value=[]
        ):
            result = asyncio.run(
                provider.search_track(
                    "Song", "Artist", search_alternate_isrcs=["USRC22222222"]
                )
            )
        assert result is None


class TestCancellationBetweenProviders:
    def test_guard_checked_before_each_provider_attempt(self, tmp_path):
        guard_calls = []

        async def _guard():
            guard_calls.append(True)

        first = _FakeProvider([], None)
        second = _FakeProvider([_match("fake", "good", 206_000)], None)
        chain = DownloadProviderChain()
        chain._providers = {"first": first, "second": second}
        chain._initialized = {"first", "second"}
        chain._provider_order = ["first", "second"]
        chain._output_dir = tmp_path
        chain._metadata_embedder = MagicMock()
        chain._metadata_embedder.embed_metadata.return_value = True
        chain._audio_validator = MagicMock()
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True, audio_info=_audio_info(206_000), errors=[], warnings=[]
        )

        result = asyncio.run(
            chain.download_track(_metadata(), cancellation_check=_guard)
        )

        assert result.success is True
        assert len(guard_calls) >= 2


@pytest.mark.django_db
class TestMaintenanceCancellation:
    def test_cancel_before_provider_call_skips_it(self):
        from tests.factories import TaskHistoryFactory

        from library_manager.models import Artist, Song
        from library_manager.tasks import core as core_tasks
        from library_manager.tasks import maintenance

        artist = Artist.objects.create(name="Artist", gid="gid-maint-cancel")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=30)
        history = TaskHistoryFactory.create(task_id="maint-cancel")
        history.status = "CANCELLED"
        history.save(update_fields=["status"])
        provider_download = AsyncMock()

        def _check(task_history, *, force_refresh=False):
            assert force_refresh is True
            return core_tasks.raise_if_cancelled(
                task_history, force_refresh=force_refresh
            )

        with (
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=provider_download,
            ),
            patch("library_manager.tasks.maintenance._try_resolve_to_deezer"),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
            patch(
                "library_manager.tasks.maintenance.raise_if_cancelled",
                side_effect=_check,
            ),
        ):
            with pytest.raises(core_tasks.TaskCancelledException):
                maintenance._download_deezer_songs_via_fallback([song], history)

        provider_download.assert_not_called()

    def test_late_cancel_removes_file_without_publishing(self, tmp_path):
        from tests.factories import TaskHistoryFactory

        from library_manager.models import Artist, Song
        from library_manager.tasks import core as core_tasks
        from library_manager.tasks import maintenance

        artist = Artist.objects.create(name="Artist", gid="gid-maint-late")
        song = Song.objects.create(name="Song", primary_artist=artist, deezer_id=31)
        history = TaskHistoryFactory.create(task_id="maint-late-cancel")
        target = tmp_path / "late.m4a"
        target.touch()
        calls = {"count": 0}

        def _check(task_history, *, force_refresh=False):
            calls["count"] += 1
            if calls["count"] >= 2:
                history.status = "CANCELLED"
                history.save(update_fields=["status"])
            return core_tasks.raise_if_cancelled(
                task_history, force_refresh=force_refresh
            )

        result = _success_result(str(target))
        with (
            patch(
                "downloader.providers.fallback.FallbackDownloader.download_track",
                new=AsyncMock(return_value=result),
            ),
            patch("library_manager.tasks.maintenance._try_resolve_to_deezer"),
            patch(
                "library_manager.tasks.maintenance._build_track_metadata",
                return_value=_metadata(),
            ),
            patch(
                "library_manager.tasks.maintenance.raise_if_cancelled",
                side_effect=_check,
            ),
        ):
            downloaded, failed = maintenance._download_deezer_songs_via_fallback(
                [song], history
            )

        assert (downloaded, failed) == (0, 0)
        assert not target.exists()
        song.refresh_from_db()
        assert song.downloaded is False


class TestCleanupWarning:
    def test_cleanup_failure_logs_path_only(self, tmp_path):
        bad_file = tmp_path / "bad.m4a"
        bad_file.touch()
        provider = _FakeProvider([_match("fake", "bad", 191_000)], None)
        chain = _chain_for(provider)
        chain._output_dir = tmp_path
        chain._audio_validator.validate.return_value = ValidationResult(
            is_valid=True, audio_info=_audio_info(191_000), errors=[], warnings=[]
        )

        def _fail_unlink(*args, **kwargs):
            raise OSError("token=SECRET")

        with (
            patch.object(Path, "unlink", side_effect=_fail_unlink),
            patch("downloader.providers.fallback.logger") as mock_logger,
        ):
            asyncio.run(chain.download_track(_metadata()))

        text = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "Failed to remove rejected file" in text
        assert str(tmp_path) in text
        assert "SECRET" not in text
