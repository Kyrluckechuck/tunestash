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
    status.cookies_expire_in_days = 30  # Plenty of time
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
    status.cookies_expire_in_days = None
    status.cookies_error_message = "Cookies expired 5 days ago"
    status.po_token_configured = False
    status.po_token_valid = False
    status.spotify_auth_mode = "public"
    status.spotify_token_valid = True
    return status


@pytest.fixture
def mock_auth_status_cookies_expiring_soon():
    """AuthenticationStatus with cookies expiring in 5 days."""
    status = MagicMock()
    status.cookies_valid = True
    status.cookies_expire_in_days = 5  # Within 7-day warning threshold
    status.cookies_error_message = None
    status.po_token_configured = False
    status.po_token_valid = False
    status.spotify_auth_mode = "public"
    status.spotify_token_valid = True
    return status


@pytest.fixture
def mock_auth_status_cookies_expiring_urgent():
    """AuthenticationStatus with cookies expiring in 1 day."""
    status = MagicMock()
    status.cookies_valid = True
    status.cookies_expire_in_days = 1  # Within 1-day urgent threshold
    status.cookies_error_message = None
    status.po_token_configured = False
    status.po_token_valid = False
    status.spotify_auth_mode = "public"
    status.spotify_token_valid = True
    return status


NOTIFICATION_DEFAULTS = {
    "notifications_enabled": True,
    "notifications_urls": ["json://stdout"],
    "notifications_cooldown_minutes": 60,
    "notifications_error_max_failure_pct": 50,
    "notifications_error_min_downloads": 20,
    "notifications_error_window_hours": 6,
    "notifications_cookie_warn_days": 7,
    "notifications_cookie_urgent_days": 1,
    "notifications_instance_name": "",
}


def _mock_get_setting(overrides=None):
    vals = {**NOTIFICATION_DEFAULTS, **(overrides or {})}
    return lambda key: vals.get(key, "")


@pytest.fixture
def notification_settings():
    """Patch get_setting for notifications."""
    with patch(
        "src.services.notification.get_setting",
        side_effect=_mock_get_setting(),
    ) as mock:
        yield mock


class TestNotificationServiceConfiguration:
    """Tests for configuration and early-exit behavior."""

    def test_returns_empty_when_disabled(self, service):
        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_enabled": False}),
        ):
            result = service.check_and_notify_all()
            assert result == {}

    def test_returns_empty_when_no_urls(self, service):
        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_urls": []}),
        ):
            result = service.check_and_notify_all()
            assert result == {}

    def test_returns_empty_when_enabled_not_set(self, service):
        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_enabled": False}),
        ):
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

    def test_sends_warning_when_cookies_expiring_soon(
        self, service, notification_settings, mock_auth_status_cookies_expiring_soon
    ):
        """Cookies with 5 days left should trigger the 7-day warning."""
        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expiring_soon,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_SOON] is True
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_URGENT] is False
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "Expiring" in call_kwargs["title"]
            assert "5 day(s)" in call_kwargs["body"]

    def test_sends_urgent_when_cookies_expiring_tomorrow(
        self, service, notification_settings, mock_auth_status_cookies_expiring_urgent
    ):
        """Cookies with 1 day left should trigger the urgent warning."""
        with (
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=mock_auth_status_cookies_expiring_urgent,
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_SOON] is False
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_URGENT] is True
            call_kwargs = mock_apprise.notify.call_args[1]
            assert "Soon!" in call_kwargs["title"]
            assert "1 day(s)" in call_kwargs["body"]

    def test_no_warning_when_cookies_have_plenty_of_time(
        self, service, notification_settings, mock_auth_status_healthy
    ):
        """Cookies with 30 days left should not trigger any warning."""
        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_healthy,
        ):
            result = service.check_and_notify_all()

            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_SOON] is False
            assert result[NotificationService.ALERT_COOKIES_EXPIRING_URGENT] is False


class TestPoTokenAlert:
    """Tests for PO token validity alerts."""

    def test_sends_alert_when_po_token_invalid(self, service, notification_settings):
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_expire_in_days = 30
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
        status.cookies_expire_in_days = 30
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
        status.cookies_expire_in_days = 30
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
        status.cookies_expire_in_days = 30
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
        # 18 failures + 2 successes = 90% failure rate (above 50% threshold)
        for i in range(18):
            TaskHistory.objects.create(
                task_id=f"fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )
        for i in range(2):
            TaskHistory.objects.create(
                task_id=f"ok-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="COMPLETED",
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
            assert "90%" in call_kwargs["body"]
            assert "18/20" in call_kwargs["body"]

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
                cookies_expire_in_days=30,
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
                cookies_expire_in_days=30,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            ),
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False

    def test_excludes_auth_failures_from_error_rate(
        self, service, notification_settings
    ):
        """Auth failures (expired POT, cookies) have their own alerts and
        should not inflate the error rate metric."""
        now = timezone.now()
        # 15 auth failures — these should be excluded
        for i in range(15):
            TaskHistory.objects.create(
                task_id=f"auth-fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
                error_message="Cannot download: PO Token invalid",
            )
        # 5 real provider failures + 15 successes = 25% real failure rate
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"real-fail-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )
        for i in range(15):
            TaskHistory.objects.create(
                task_id=f"ok-auth-{i}",
                type="DOWNLOAD",
                entity_id="789",
                entity_type="ALBUM",
                status="COMPLETED",
                started_at=now - timedelta(hours=1),
            )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=MagicMock(
                cookies_valid=True,
                cookies_expire_in_days=30,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            ),
        ):
            result = service.check_and_notify_all()
            # Without exclusion: 20/35 = 57% → would alert
            # With exclusion: 5/20 = 25% → no alert
            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False


class TestSendOnce:
    """Tests for fire-once notification behavior (auth alerts)."""

    def test_auth_alert_fires_once_then_blocks(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        """Same auth condition checked twice should only send once."""
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

            result1 = service.check_and_notify_all()
            result2 = service.check_and_notify_all()

            assert result1[NotificationService.ALERT_COOKIES_EXPIRED] is True
            assert result2[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert mock_apprise.notify.call_count == 1

    def test_auth_alert_blocked_even_after_cooldown(
        self, service, notification_settings, mock_auth_status_cookies_expired
    ):
        """Auth alerts use send-once, not cooldown. Old state still blocks."""
        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_COOKIES_EXPIRED,
            last_sent_at=timezone.now() - timedelta(hours=24),
            last_message="Old alert",
        )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_cookies_expired,
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_COOKIES_EXPIRED] is False

    def test_cookie_states_cleared_when_healthy(
        self, service, notification_settings, mock_auth_status_healthy
    ):
        """When cookies are healthy, clear all cookie alert states."""
        for alert_type in NotificationService.COOKIE_ALERT_TYPES:
            NotificationState.objects.create(
                alert_type=alert_type,
                last_sent_at=timezone.now(),
                last_message="Previous alert",
            )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_healthy,
        ):
            service.check_and_notify_all()

        assert (
            NotificationState.objects.filter(
                alert_type__in=NotificationService.COOKIE_ALERT_TYPES
            ).count()
            == 0
        )

    def test_alert_fires_again_after_state_cleared(
        self,
        service,
        notification_settings,
        mock_auth_status_cookies_expiring_soon,
        mock_auth_status_healthy,
    ):
        """Full lifecycle: alert → resolve → re-alert."""
        with (patch("apprise.Apprise") as mock_apprise_cls,):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            # Phase 1: Cookies expiring → sends alert
            with patch(
                "src.services.system_health.SystemHealthService"
                ".check_authentication_status",
                return_value=mock_auth_status_cookies_expiring_soon,
            ):
                result1 = service.check_and_notify_all()
            assert result1[NotificationService.ALERT_COOKIES_EXPIRING_SOON] is True

            # Phase 2: Cookies refreshed → clears state
            with patch(
                "src.services.system_health.SystemHealthService"
                ".check_authentication_status",
                return_value=mock_auth_status_healthy,
            ):
                service.check_and_notify_all()
            assert not NotificationState.objects.filter(
                alert_type=NotificationService.ALERT_COOKIES_EXPIRING_SOON
            ).exists()

            # Phase 3: Cookies expiring again → sends again
            with patch(
                "src.services.system_health.SystemHealthService"
                ".check_authentication_status",
                return_value=mock_auth_status_cookies_expiring_soon,
            ):
                result3 = service.check_and_notify_all()
            assert result3[NotificationService.ALERT_COOKIES_EXPIRING_SOON] is True
            assert mock_apprise.notify.call_count == 2

    def test_po_token_state_cleared_when_valid(
        self, service, notification_settings, mock_auth_status_healthy
    ):
        """PO token state should clear when token becomes valid."""
        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_PO_TOKEN_INVALID,
            last_sent_at=timezone.now(),
            last_message="Previous alert",
        )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=mock_auth_status_healthy,
        ):
            service.check_and_notify_all()

        assert not NotificationState.objects.filter(
            alert_type=NotificationService.ALERT_PO_TOKEN_INVALID
        ).exists()

    def test_spotify_oauth_state_cleared_when_valid(
        self, service, notification_settings
    ):
        """Spotify OAuth state should clear when token is valid."""
        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_SPOTIFY_OAUTH_FAILED,
            last_sent_at=timezone.now(),
            last_message="Previous alert",
        )
        status = MagicMock()
        status.cookies_valid = True
        status.cookies_expire_in_days = 30
        status.cookies_error_message = None
        status.po_token_configured = False
        status.po_token_valid = False
        status.spotify_auth_mode = "user-authenticated"
        status.spotify_token_valid = True

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=status,
        ):
            service.check_and_notify_all()

        assert not NotificationState.objects.filter(
            alert_type=NotificationService.ALERT_SPOTIFY_OAUTH_FAILED
        ).exists()


class TestCooldown:
    """Tests for time-based cooldown behavior (error rate alerts)."""

    def test_error_rate_respects_cooldown(self, service, notification_settings):
        """Error rate alerts still use time-based cooldown."""
        now = timezone.now()
        # 18 failures + 2 successes = 90% failure rate (above threshold)
        for i in range(18):
            TaskHistory.objects.create(
                task_id=f"fail-cd-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )
        for i in range(2):
            TaskHistory.objects.create(
                task_id=f"ok-cd-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="COMPLETED",
                started_at=now - timedelta(hours=1),
            )

        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_HIGH_ERROR_RATE,
            last_sent_at=timezone.now() - timedelta(minutes=30),
            last_message="Previous alert",
        )

        with patch(
            "src.services.system_health.SystemHealthService.check_authentication_status",
            return_value=MagicMock(
                cookies_valid=True,
                cookies_expire_in_days=30,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            ),
        ):
            result = service.check_and_notify_all()
            assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False

    def test_error_rate_sends_after_cooldown(self, service, notification_settings):
        """Error rate alert sends again after cooldown expires."""
        now = timezone.now()
        # 18 failures + 2 successes = 90% failure rate
        for i in range(18):
            TaskHistory.objects.create(
                task_id=f"fail-cd2-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )
        for i in range(2):
            TaskHistory.objects.create(
                task_id=f"ok-cd2-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="COMPLETED",
                started_at=now - timedelta(hours=1),
            )

        NotificationState.objects.create(
            alert_type=NotificationService.ALERT_HIGH_ERROR_RATE,
            last_sent_at=timezone.now() - timedelta(minutes=90),
            last_message="Old alert",
        )

        with (
            patch(
                "src.services.system_health.SystemHealthService"
                ".check_authentication_status",
                return_value=MagicMock(
                    cookies_valid=True,
                    cookies_expire_in_days=30,
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
