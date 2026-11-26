"""End-to-end regressions: zero downloaded tracks must not be a catalog verdict."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from downloader.providers.fallback import DownloadChainResult, ProviderOutcome
from tests.factories import AlbumFactory, TaskHistoryFactory

from library_manager.models import AlbumFailureReason, TaskHistory
from library_manager.tasks.download import _download_deezer_album


def _chain_failure():
    return DownloadChainResult(
        success=False,
        file_path=None,
        provider_used=None,
        error_message="All providers failed",
        track_match=None,
        validation_result=None,
        provider_outcomes=[
            ProviderOutcome("tidal", "search", "error", "HTTP 500 token=SECRET")
        ],
    )


@pytest.mark.django_db
class TestZeroDownloadAlbumVerdict:
    def test_provider_failure_marks_temporary_and_logs_outcomes(self):
        task_history = TaskHistoryFactory.create(
            task_id="zero-download-regression", log_messages=[]
        )
        album = AlbumFactory.create(deezer_id=12345, downloaded=False, wanted=True)
        deezer_tracks = [
            SimpleNamespace(
                deezer_id=100,
                name="Song One",
                artist_name="Artist",
                artist_deezer_id=70100,
                credits=[],
                isrc="USRC10000001",
                duration_ms=180000,
                track_number=1,
                disc_number=1,
            )
        ]

        deezer_provider = MagicMock()
        deezer_provider.get_album_tracks.return_value = deezer_tracks
        deezer_provider.get_album.return_value = None
        fake_downloader = MagicMock()
        fake_downloader.download_track = AsyncMock(return_value=_chain_failure())
        fake_downloader.close = AsyncMock(return_value=None)

        with (
            patch(
                "src.providers.deezer.DeezerMetadataProvider",
                return_value=deezer_provider,
            ),
            patch(
                "downloader.providers.fallback.FallbackDownloader",
                return_value=fake_downloader,
            ),
        ):
            downloaded, failed = _download_deezer_album(album, task_history)

        assert (downloaded, failed) == (0, 1)
        album.refresh_from_db()
        assert album.failure_reason == AlbumFailureReason.TEMPORARY_ERROR
        assert album.unavailable is False

        refreshed = TaskHistory.objects.get(id=task_history.id)
        messages = " ".join(entry["message"] for entry in refreshed.log_messages)
        assert "tidal" in messages
        assert "search" in messages
        assert "SECRET" not in messages

    def test_search_none_chain_is_temporary_and_progress_logs_survive(self):
        task_history = TaskHistoryFactory.create(
            task_id="ambiguous-search-regression", log_messages=[]
        )
        album = AlbumFactory.create(deezer_id=2222, downloaded=False, wanted=True)
        deezer_tracks = [
            SimpleNamespace(
                deezer_id=200,
                name="Song Two",
                artist_name="Artist",
                artist_deezer_id=70200,
                credits=[],
                isrc="USRC20000001",
                duration_ms=180000,
                track_number=1,
                disc_number=1,
            )
        ]
        ambiguous = DownloadChainResult(
            success=False,
            file_path=None,
            provider_used=None,
            error_message="No result returned (no match or provider failure)",
            track_match=None,
            validation_result=None,
            provider_outcomes=[
                ProviderOutcome(
                    "tidal", "search", "no_result_unknown", "Search returned no result"
                )
            ],
        )
        deezer_provider = MagicMock()
        deezer_provider.get_album_tracks.return_value = deezer_tracks
        deezer_provider.get_album.return_value = None
        fake_downloader = MagicMock()
        fake_downloader.download_track = AsyncMock(return_value=ambiguous)
        fake_downloader.close = AsyncMock(return_value=None)

        with (
            patch(
                "src.providers.deezer.DeezerMetadataProvider",
                return_value=deezer_provider,
            ),
            patch(
                "downloader.providers.fallback.FallbackDownloader",
                return_value=fake_downloader,
            ),
        ):
            downloaded, failed = _download_deezer_album(album, task_history)

        assert (downloaded, failed) == (0, 1)
        album.refresh_from_db()
        assert album.failure_reason == AlbumFailureReason.TEMPORARY_ERROR
        assert album.unavailable is False

        refreshed = TaskHistory.objects.get(id=task_history.id)
        messages = " ".join(entry["message"] for entry in refreshed.log_messages)
        assert "no_result_unknown" in messages
        assert "95" in messages or "Completed" in messages

    def test_genuine_deezer_no_tracks_verdict_is_retained(self):
        task_history = TaskHistoryFactory.create(
            task_id="deezer-no-tracks-regression", log_messages=[]
        )
        album = AlbumFactory.create(deezer_id=54321, downloaded=False, wanted=True)

        deezer_provider = MagicMock()
        deezer_provider.get_album_tracks.return_value = []

        with (
            patch(
                "src.providers.deezer.DeezerMetadataProvider",
                return_value=deezer_provider,
            ),
            patch(
                "library_manager.tasks.download._resolve_album_to_deezer",
                return_value=None,
            ),
            pytest.raises(ValueError, match="No tracks found on Deezer"),
        ):
            _download_deezer_album(album, task_history)

        album.refresh_from_db()
        assert album.failure_reason == AlbumFailureReason.DEEZER_NO_TRACKS
        assert album.unavailable is True
