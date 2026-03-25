"""Tests for the download queue pause/resume circuit breaker.

When authentication fails (expired POT token, invalid cookies, etc.),
the worker should stop consuming from the downloads queue so tasks stay
preserved in the broker rather than draining as immediate failures.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

import library_manager.tasks.core as core_module
from library_manager.tasks.core import (
    _pause_downloads_queue,
    require_download_capability,
    resume_downloads_queue,
)


@pytest.fixture(autouse=True)
def _reset_pause_state():
    """Ensure every test starts (and ends) with a clean circuit breaker."""
    core_module._downloads_paused = False
    core_module._downloads_paused_at = 0.0
    yield
    core_module._downloads_paused = False
    core_module._downloads_paused_at = 0.0


class TestPauseDownloadsQueue:
    """Test the low-level pause helper."""

    @patch("library_manager.tasks.core.celery_app")
    def test_sets_flag_and_cancels_consumer(self, mock_app):
        _pause_downloads_queue("PO Token expired")

        assert core_module._downloads_paused is True
        assert core_module._downloads_paused_at > 0
        mock_app.control.cancel_consumer.assert_called_once_with("downloads")

    @patch("library_manager.tasks.core.celery_app")
    def test_idempotent_when_already_paused(self, mock_app):
        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()

        _pause_downloads_queue("PO Token expired")

        mock_app.control.cancel_consumer.assert_not_called()

    @patch("library_manager.tasks.core.celery_app")
    def test_handles_control_exception(self, mock_app):
        mock_app.control.cancel_consumer.side_effect = Exception("broker down")

        _pause_downloads_queue("PO Token expired")

        assert core_module._downloads_paused is True


class TestResumeDownloadsQueue:
    """Test the low-level resume helper."""

    @patch("library_manager.tasks.core.celery_app")
    def test_clears_flag_and_adds_consumer(self, mock_app):
        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()

        resume_downloads_queue()

        assert core_module._downloads_paused is False
        assert core_module._downloads_paused_at == 0.0
        mock_app.control.add_consumer.assert_called_once_with("downloads")

    @patch("library_manager.tasks.core.celery_app")
    def test_noop_when_not_paused(self, mock_app):
        resume_downloads_queue()

        mock_app.control.add_consumer.assert_not_called()

    @patch("library_manager.tasks.core.celery_app")
    def test_handles_control_exception(self, mock_app):
        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()
        mock_app.control.add_consumer.side_effect = Exception("broker down")

        resume_downloads_queue()

        assert core_module._downloads_paused is False


class TestRequireDownloadCapability:
    """Test the auth gate that download tasks call."""

    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_passes_when_auth_valid(self, mock_capable):
        mock_capable.return_value = (True, None)

        require_download_capability()

    @patch("library_manager.tasks.core.celery_app")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_auth_failure_pauses_queue(self, mock_capable, mock_app, settings):
        settings.PAUSE_DOWNLOADS_ON_AUTH_FAILURE = True
        mock_capable.return_value = (False, "PO Token expired")

        with pytest.raises(RuntimeError, match="Cannot download"):
            require_download_capability()

        assert core_module._downloads_paused is True
        mock_app.control.cancel_consumer.assert_called_once_with("downloads")

    @patch("library_manager.tasks.core.celery_app")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_auth_failure_no_pause_when_disabled(
        self, mock_capable, mock_app, settings
    ):
        settings.PAUSE_DOWNLOADS_ON_AUTH_FAILURE = False
        mock_capable.return_value = (False, "PO Token expired")

        with pytest.raises(RuntimeError, match="Cannot download"):
            require_download_capability()

        assert core_module._downloads_paused is False
        mock_app.control.cancel_consumer.assert_not_called()

    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_fast_path_rejects_during_pause_window(self, mock_capable):
        """While paused and within the recheck window, reject without calling the API."""
        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()

        with pytest.raises(RuntimeError, match="waiting for renewal"):
            require_download_capability()

        mock_capable.assert_not_called()

    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_fast_path_updates_task_history(self, mock_capable):
        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()

        mock_history = MagicMock()
        with pytest.raises(RuntimeError):
            require_download_capability(task_history=mock_history)

        assert mock_history.status == "FAILED"
        mock_history.add_log_message.assert_called_once()
        mock_history.save.assert_called_once()

    @patch("library_manager.tasks.core.celery_app")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_rechecks_after_pause_window_expires(self, mock_capable, mock_app):
        """After the recheck interval, re-validate instead of fast-rejecting."""
        core_module._downloads_paused = True
        core_module._downloads_paused_at = (
            time.monotonic() - core_module._PAUSE_RECHECK_SECONDS - 1
        )
        mock_capable.return_value = (False, "Still invalid")

        with pytest.raises(RuntimeError, match="Cannot download"):
            require_download_capability()

        mock_capable.assert_called_once()

    @patch("library_manager.tasks.core.celery_app")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_resumes_when_auth_restored(self, mock_capable, mock_app):
        """If auth check passes while we were paused, resume downloads."""
        core_module._downloads_paused = True
        core_module._downloads_paused_at = (
            time.monotonic() - core_module._PAUSE_RECHECK_SECONDS - 1
        )
        mock_capable.return_value = (True, None)

        require_download_capability()

        assert core_module._downloads_paused is False
        mock_app.control.add_consumer.assert_called_once_with("downloads")

    @patch("library_manager.tasks.core.celery_app")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    def test_auth_failure_updates_task_history(self, mock_capable, mock_app, settings):
        settings.PAUSE_DOWNLOADS_ON_AUTH_FAILURE = True
        mock_capable.return_value = (False, "Cookies expired")

        mock_history = MagicMock()
        with pytest.raises(RuntimeError):
            require_download_capability(task_history=mock_history)

        assert mock_history.status == "FAILED"
        mock_history.add_log_message.assert_called_once()
        mock_history.save.assert_called_once()


class TestCheckNotificationsResume:
    """Test that the periodic notification task resumes downloads when auth is restored."""

    @patch("src.services.notification.NotificationService")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    @patch("library_manager.tasks.core.celery_app")
    def test_resumes_paused_downloads_on_auth_restored(
        self, mock_app, mock_capable, mock_notify_cls
    ):
        from library_manager.tasks.notification import check_notifications

        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()
        mock_capable.return_value = (True, None)
        mock_notify_cls.return_value.check_and_notify_all.return_value = {}

        check_notifications()

        assert core_module._downloads_paused is False
        mock_app.control.add_consumer.assert_called_once_with("downloads")

    @patch("src.services.notification.NotificationService")
    @patch("src.services.system_health.SystemHealthService.is_download_capable")
    @patch("library_manager.tasks.core.celery_app")
    def test_stays_paused_when_auth_still_invalid(
        self, mock_app, mock_capable, mock_notify_cls
    ):
        from library_manager.tasks.notification import check_notifications

        core_module._downloads_paused = True
        core_module._downloads_paused_at = time.monotonic()
        mock_capable.return_value = (False, "Still expired")
        mock_notify_cls.return_value.check_and_notify_all.return_value = {}

        check_notifications()

        assert core_module._downloads_paused is True
        mock_app.control.add_consumer.assert_not_called()

    @patch("src.services.notification.NotificationService")
    @patch("library_manager.tasks.core.celery_app")
    def test_skips_resume_check_when_not_paused(self, mock_app, mock_notify_cls):
        from library_manager.tasks.notification import check_notifications

        mock_notify_cls.return_value.check_and_notify_all.return_value = {}

        check_notifications()

        mock_app.control.add_consumer.assert_not_called()
