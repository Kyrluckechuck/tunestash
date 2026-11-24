"""Tests for honest failure diagnostics in download tasks (Task 2 fix round)."""

from unittest.mock import patch

from downloader.providers.fallback import DownloadChainResult, ProviderOutcome
from tests.factories import TaskHistoryFactory

from library_manager.models import TaskHistory
from library_manager.tasks.download import (
    _build_provider_failure_summary,
    _persist_provider_history,
    _provider_outcome_log_messages,
)


def _result(outcomes, message="All providers failed"):
    return DownloadChainResult(
        success=False,
        file_path=None,
        provider_used=None,
        error_message=message,
        track_match=None,
        validation_result=None,
        provider_outcomes=outcomes,
    )


class TestProviderOutcomeLogMessages:
    def test_includes_song_id_and_provider_stage_without_secrets(self):
        result = _result(
            [ProviderOutcome("tidal", "search", "error", "HTTP 500 token=ABCD")]
        )
        messages = _provider_outcome_log_messages(42, result)
        assert len(messages) == 1
        assert "song_id=42" in messages[0]
        assert "tidal" in messages[0]
        assert "search" in messages[0]
        assert "ABCD" not in messages[0]

    def test_bare_exception_result_produces_useful_summary(self):
        messages = _provider_outcome_log_messages(
            7, RuntimeError("boom with token=SECRET")
        )
        assert len(messages) == 1
        assert "song_id=7" in messages[0]
        assert "SECRET" not in messages[0]


class TestBuildProviderFailureSummary:
    def test_summary_contains_each_provider_and_no_secrets(self):
        results = [
            (
                1,
                _result([ProviderOutcome("tidal", "search", "error", "token=S1")]),
            ),
            (
                2,
                _result([ProviderOutcome("qobuz", "download", "error", "api_key=S2")]),
            ),
        ]
        summary = _build_provider_failure_summary(results)
        assert "tidal" in summary
        assert "qobuz" in summary
        assert "S1" not in summary
        assert "S2" not in summary

    def test_empty_results(self):
        assert _build_provider_failure_summary([]) == ""


class TestPersistProviderHistory:
    @patch("library_manager.tasks.download.logger")
    def test_batch_saves_once_and_preserves_existing_progress(self, mock_logger):
        history = TaskHistoryFactory.create(
            task_id="provider-history-batch", log_messages=[]
        )
        history.add_log_message("progress: 30%")
        with patch.object(history, "save", wraps=history.save) as save_mock:
            _persist_provider_history(
                history,
                [
                    (
                        1,
                        _result([ProviderOutcome("tidal", "search", "error", "boom")]),
                    )
                ],
            )
        assert save_mock.call_count == 1

        refreshed = TaskHistory.objects.get(id=history.id)
        messages = [entry["message"] for entry in refreshed.log_messages]
        assert any("progress: 30%" in m for m in messages)
        assert any("song_id=1" in m for m in messages)

    @patch("library_manager.tasks.download.logger")
    def test_omitted_count_is_explicit_and_capacity_is_reserved(self, mock_logger):
        history = TaskHistoryFactory.create(
            task_id="provider-history-bounded", log_messages=[]
        )
        failed = [
            (
                song_id,
                _result([ProviderOutcome("tidal", "search", "error", "boom")]),
            )
            for song_id in range(60)
        ]

        _persist_provider_history(history, failed)

        refreshed = TaskHistory.objects.get(id=history.id)
        entries = refreshed.log_messages
        assert len(entries) <= 50
        messages = [entry["message"] for entry in entries]
        assert any("omitted" in m for m in messages)
        # Some progress capacity remains for the 95% completion message.
        assert len(entries) < 50
