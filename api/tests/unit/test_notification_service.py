"""Unit tests for NotificationService."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from library_manager.models import NotificationState, TaskHistory
from src.services.notification import NotificationService


@pytest.fixture
def service():
    return NotificationService()


@pytest.fixture
def mock_auth_status_healthy():
    """AuthenticationStatus where everything is healthy."""
    status = MagicMock()
    status.cookies_valid = True
    status.po_token_configured = True
    status.po_token_valid = True
    status.po_token_error_message = None
    status.spotify_auth_mode = "public"
    status.spotify_token_valid = True
    status.spotify_token_error_message = None
    status.cookies_error_message = None
    return status


@pytest.fixture
def mock_auth_status_cookies_expired():
    """AuthenticationStatus with expired cookies."""
    status = MagicMock()
    status.cookies_valid = False
    status.cookies_error_message = "Cookies expired 5 days ago"
    status.po_token_configured = False
    status.po_token_valid = False
    status.spotify_auth_mode = "public"
    status.spotify_token_valid = True
    return status


@pytest.fixture
def notification_settings():
    """Patch Django settings for notifications."""
    with patch("src.services.notification.settings") as mock_settings:
        mock_settings.NOTIFICATIONS_ENABLED = True
        mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
        mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
        mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 10
        mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6
        yield mock_settings


class TestNotificationServiceConfiguration:
    """Tests for configuration and early-exit behavior."""

    def test_returns_empty_when_disabled(self, service):
        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.NOTIFICATIONS_ENABLED = False
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            result = service.check_and_notify_all()
            assert result == {}

    def test_returns_empty_when_no_urls(self, service):
        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = []
            result = service.check_and_notify_all()
            assert result == {}

    def test_returns_empty_when_enabled_not_set(self, service):
        with patch("src.services.notification.settings", spec=[]) as mock_settings:
            # getattr on a spec=[] mock returns MagicMock for missing attrs,
            # but we explicitly make it falsy
            mock_settings.NOTIFICATIONS_ENABLED = False
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            result = service.check_and_notify_all()
            assert result == {}


class TestCookiesAlert:
    """Tests for YouTube cookies expiration alerts."""

    def test_sends_alert_when_cookies_expired(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expired,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is True
            mock_apprise.notify.assert_called()
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "Cookies Expired" in call_kwargs["title"]
            assert "expired 5 days ago" in call_kwargs["body"]

    def test_no_alert_when_cookies_valid(
        self, service, notification_settings, mock_auth_status_healthy
    ):
        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_healthy,
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False


class TestPoTokenAlert:
    """Tests for PO token validity alerts."""

    def test_sends_alert_when_po_token_invalid(self, service, notification_settings):
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_error_message = None
        status.po_token_configured = True
        status.po_token_valid = False
        status.po_token_error_message = "Token rejected by YouTube"
        status.spotify_auth_mode = "public"
        status.spotify_token_valid = True

        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=status,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_PO_TOKEN_INVALID] is True
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "PO Token" in call_kwargs["title"]

    def test_no_alert_when_po_token_not_configured(
        self, service, notification_settings
    ):
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_error_message = None
        status.po_token_configured = False
        status.po_token_valid = False
        status.spotify_auth_mode = "public"
        status.spotify_token_valid = True

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=status,
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_PO_TOKEN_INVALID] is False


class TestSpotifyOAuthAlert:
    """Tests for Spotify OAuth failure alerts."""

    def test_sends_alert_when_oauth_failed(self, service, notification_settings):
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_error_message = None
        status.po_token_configured = False
        status.po_token_valid = False
        status.spotify_auth_mode = "user-authenticated"
        status.spotify_token_valid = False
        status.spotify_token_error_message = "Refresh token revoked"

        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=status,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_SPOTIFY_OAUTH_FAILED] is True
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "Spotify OAuth" in call_kwargs["title"]

    def test_no_alert_in_public_mode(self, service, notification_settings):
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_error_message = None
        status.po_token_configured = False
        status.po_token_valid = False
        status.spotify_auth_mode = "public"
        status.spotify_token_valid = False

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=status,
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_SPOTIFY_OAUTH_FAILED] is False


class TestErrorRateAlert:
    """Tests for high error rate alerts."""

    def test_sends_alert_when_threshold_exceeded(
        self, service, notification_settings, sample_artist
    ):
        now = timezone.now()
        for i in range(12):
            TaskHistory.objects.create(
                task_id=f"fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )

        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=MagicMock(
                    cookies_valid=True,
                    cookies_error_message=None,
                    po_token_configured=False,
                    po_token_valid=False,
                    spotify_auth_mode="public",
                    spotify_token_valid=True,
                ),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is True
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "12 tasks" in call_kwargs["body"]

    def test_no_alert_below_threshold(self, service, notification_settings):
        now = timezone.now()
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"fail-below-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=MagicMock(
                cookies_valid=True,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            ),
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False

    def test_ignores_old_failures(self, service, notification_settings):
        now = timezone.now()
        for i in range(15):
            TaskHistory.objects.create(
                task_id=f"fail-old-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=10),  # Outside 6-hour window
            )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=MagicMock(
                cookies_valid=True,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            ),
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False


class TestCooldown:
    """Tests for notification cooldown behavior."""

    def test_respects_cooldown(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        # Record a recent notification
        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_COOKIES_EXPIRED,
            last_sent_at=timezone.now() - timedelta(minutes=30),
            last_message="Previous alert",
        )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_cookies_expired,
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False

    def test_sends_after_cooldown_expired(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        # Record an old notification (beyond 60-minute cooldown)
        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_COOKIES_EXPIRED,
            last_sent_at=timezone.now() - timedelta(minutes=90),
            last_message="Old alert",
        )

        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expired,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is True

    def test_records_sent_state(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expired,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            service.check_and_notify_all()

            state = NotificationState.objects.get(
                alert_type=NotificationService.ALERT_COOKIES_EXPIRED
            )
            assert state.last_message != ""
            assert (timezone.now() - state.last_sent_at).total_seconds() < 5


class TestAppriseFailures:
    """Tests for Apprise error handling."""

    def test_handles_apprise_send_failure(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expired,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = False
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            # Should return False and NOT record cooldown
            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert not NotificationState.objects.filter(
                alert_type=NotificationService.ALERT_COOKIES_EXPIRED
            ).exists()

    def test_auth_check_exception_doesnt_crash(self, service, notification_settings):
        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            side_effect=Exception("Unexpected error"),
        ):
            result = service.check_and_notify_all()
            # Should still try error rate check
            assert NotificationService.ALERT_HIGH_ERROR_RATE in result


class TestMultipleAlerts:
    """Tests for multiple simultaneous alert conditions."""

    def test_sends_multiple_alerts_same_cycle(self, service, notification_settings):
        status = MagicMock()
        status.cookies_valid = False
        status.cookies_error_message = "Expired"
        status.po_token_configured = True
        status.po_token_valid = False
        status.po_token_error_message = "Invalid"
        status.spotify_auth_mode = "user-authenticated"
        status.spotify_token_valid = False
        status.spotify_token_error_message = "Revoked"

        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=status,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is True
            assert result[NotificationService.ALERT_PO_TOKEN_INVALID] is True
            assert result[NotificationService.ALERT_SPOTIFY_OAUTH_FAILED] is True
            assert mock_apprise.notify.call_count == 3
