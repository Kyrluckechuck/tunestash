"""Integration tests for the notification system.

Tests realistic flows with actual database state, minimal mocking.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from library_manager.models import NotificationState, TaskHistory
from src.services.notification import NotificationService


@pytest.mark.django_db
class TestNotificationCooldownFlow:
    """Test cooldown behavior with real database state."""

    def test_first_alert_always_sends(self):
        """First alert of a type should always send (no prior state)."""
        service = NotificationService()

        assert NotificationState.objects.count() == 0

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            sent = service._send(
                title="Test Alert",
                body="Something went wrong",
                alert_type="test_alert",
            )

        assert sent is True
        state = NotificationState.objects.get(alert_type="test_alert")
        assert "Something went wrong" in state.last_message

    def test_rapid_alerts_blocked_by_cooldown(self):
        """Sending the same alert type twice in quick succession should be blocked."""
        service = NotificationService()

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            first = service._send(
                title="Alert 1",
                body="First occurrence",
                alert_type="rapid_test",
            )
            second = service._send(
                title="Alert 2",
                body="Second occurrence",
                alert_type="rapid_test",
            )

        assert first is True
        assert second is False
        assert mock_apprise.notify.call_count == 1

    def test_different_alert_types_independent(self):
        """Different alert types should have independent cooldowns."""
        service = NotificationService()

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            cookies_sent = service._send(
                title="Cookies",
                body="Cookies expired",
                alert_type=NotificationService.ALERT_COOKIES_EXPIRED,
            )
            po_token_sent = service._send(
                title="PO Token",
                body="Token invalid",
                alert_type=NotificationService.ALERT_PO_TOKEN_INVALID,
            )

        assert cookies_sent is True
        assert po_token_sent is True
        assert mock_apprise.notify.call_count == 2
        assert NotificationState.objects.count() == 2

    def test_cooldown_respects_configured_duration(self):
        """Cooldown should respect the configured duration from settings."""
        NotificationState.objects.create(
            alert_type="configured_cooldown_test",
            last_sent_at=timezone.now() - timedelta(minutes=45),
            last_message="Earlier alert",
        )

        service = NotificationService()

        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 30

            # 45 minutes ago > 30 minute cooldown, should be allowed
            assert service._cooldown_elapsed("configured_cooldown_test") is True

            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60

            # 45 minutes ago < 60 minute cooldown, should be blocked
            assert service._cooldown_elapsed("configured_cooldown_test") is False


@pytest.mark.django_db
class TestErrorRateIntegration:
    """Test error rate detection with real TaskHistory records."""

    def test_counts_only_recent_failures(self):
        """Error rate should only count failures within the configured window."""
        now = timezone.now()

        # Create 5 recent failures (within window)
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"recent-fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=2),
            )

        # Create 10 old failures (outside default 6-hour window)
        for i in range(10):
            TaskHistory.objects.create(
                task_id=f"old-fail-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=12),
            )

        service = NotificationService()

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status"
            ) as mock_auth,
        ):
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 10
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6

            mock_auth.return_value = MagicMock(
                cookies_valid=True,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            )

            result = service._check_error_rate()

        # Only 5 recent failures, below threshold of 10
        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False

    def test_threshold_exactly_met_triggers_alert(self):
        """Alert should trigger when count equals threshold."""
        now = timezone.now()

        for i in range(10):  # Exactly threshold
            TaskHistory.objects.create(
                task_id=f"threshold-fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )

        service = NotificationService()

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 10
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6

            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service._check_error_rate()

        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is True

    def test_ignores_successful_tasks(self):
        """Only FAILED tasks should count toward error rate."""
        now = timezone.now()

        # Mix of statuses
        for i, status in enumerate(
            ["FAILED"] * 5 + ["SUCCESS"] * 20 + ["PENDING"] * 10
        ):
            TaskHistory.objects.create(
                task_id=f"mixed-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status=status,
                started_at=now - timedelta(hours=1),
            )

        service = NotificationService()

        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 10
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6

            result = service._check_error_rate()

        # Only 5 failures, below threshold
        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False


@pytest.mark.django_db
class TestFullNotificationCycle:
    """Test complete notification cycles with state persistence."""

    def test_alert_recovery_cycle(self):
        """Test alert → recovery → re-alert cycle with proper state tracking."""
        service = NotificationService()

        def make_auth_status(cookies_valid: bool):
            return MagicMock(
                cookies_valid=cookies_valid,
                cookies_error_message="Expired" if not cookies_valid else None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            )

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 100
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6

            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            # Phase 1: Cookies expire, alert sent
            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=False),
            ):
                result1 = service.check_and_notify_all()

            assert result1[NotificationService.ALERT_COOKIES_EXPIRED] is True
            assert mock_apprise.notify.call_count == 1

            # Phase 2: Cookies still expired, but cooldown blocks
            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=False),
            ):
                result2 = service.check_and_notify_all()

            assert result2[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert mock_apprise.notify.call_count == 1  # No new notification

            # Phase 3: Cookies fixed, no alert needed
            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=True),
            ):
                result3 = service.check_and_notify_all()

            assert result3[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert mock_apprise.notify.call_count == 1  # Still no new notification

            # Phase 4: Fast-forward past cooldown, cookies expire again
            state = NotificationState.objects.get(
                alert_type=NotificationService.ALERT_COOKIES_EXPIRED
            )
            state.last_sent_at = timezone.now() - timedelta(hours=2)
            state.save()

            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=False),
            ):
                result4 = service.check_and_notify_all()

            assert result4[NotificationService.ALERT_COOKIES_EXPIRED] is True
            assert mock_apprise.notify.call_count == 2  # New notification sent

    def test_multiple_simultaneous_failures(self):
        """Test handling of multiple auth failures at once."""
        service = NotificationService()

        all_broken_status = MagicMock(
            cookies_valid=False,
            cookies_error_message="Cookies expired",
            po_token_configured=True,
            po_token_valid=False,
            po_token_error_message="Token rejected",
            spotify_auth_mode="user-authenticated",
            spotify_token_valid=False,
            spotify_token_error_message="Refresh failed",
        )

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=all_broken_status,
            ),
        ):
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 100
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6

            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service.check_and_notify_all()

        # All three auth alerts should fire
        assert result[NotificationService.ALERT_COOKIES_EXPIRED] is True
        assert result[NotificationService.ALERT_PO_TOKEN_INVALID] is True
        assert result[NotificationService.ALERT_SPOTIFY_OAUTH_FAILED] is True
        assert mock_apprise.notify.call_count == 3

        # Each should have its own cooldown state
        assert NotificationState.objects.count() == 3


@pytest.mark.django_db
class TestNotificationStateModel:
    """Test NotificationState model behavior."""

    def test_update_or_create_updates_existing(self):
        """update_or_create should update existing records."""
        NotificationState.objects.create(
            alert_type="update_test",
            last_sent_at=timezone.now() - timedelta(days=1),
            last_message="Old message",
        )

        now = timezone.now()
        NotificationState.objects.update_or_create(
            alert_type="update_test",
            defaults={"last_sent_at": now, "last_message": "New message"},
        )

        assert NotificationState.objects.filter(alert_type="update_test").count() == 1
        state = NotificationState.objects.get(alert_type="update_test")
        assert state.last_message == "New message"
        assert (now - state.last_sent_at).total_seconds() < 1

    def test_str_representation(self):
        """Model __str__ should be informative."""
        state = NotificationState.objects.create(
            alert_type="str_test",
            last_sent_at=timezone.now(),
            last_message="Test message",
        )

        str_repr = str(state)
        assert "str_test" in str_repr


@pytest.mark.django_db
class TestInstanceNameConfiguration:
    """Test instance name configuration behavior."""

    def test_default_instance_name(self):
        """Default instance name should be 'TuneStash'."""
        service = NotificationService()

        with patch("src.services.notification.settings") as mock_settings:
            # Simulate attribute not existing
            del mock_settings.NOTIFICATIONS_INSTANCE_NAME

            name = service.get_instance_name()

        assert name == "TuneStash"

    def test_custom_instance_name(self):
        """Custom instance name from settings should be used."""
        service = NotificationService()

        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.NOTIFICATIONS_INSTANCE_NAME = "My Dev Server"

            name = service.get_instance_name()

        assert name == "My Dev Server"

    def test_instance_name_in_alert_titles(self):
        """Instance name should appear in notification titles."""
        service = NotificationService()

        with (
            patch("src.services.notification.settings") as mock_settings,
            patch("apprise.Apprise") as mock_apprise_cls,
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status"
            ) as mock_auth,
        ):
            mock_settings.NOTIFICATIONS_ENABLED = True
            mock_settings.NOTIFICATIONS_URLS = ["json://stdout"]
            mock_settings.NOTIFICATIONS_COOLDOWN_MINUTES = 60
            mock_settings.NOTIFICATIONS_ERROR_THRESHOLD = 100
            mock_settings.NOTIFICATIONS_ERROR_WINDOW_HOURS = 6
            mock_settings.NOTIFICATIONS_INSTANCE_NAME = "Production NAS"

            mock_auth.return_value = MagicMock(
                cookies_valid=False,
                cookies_error_message="Expired",
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            )

            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            service.check_and_notify_all()

            call_kwargs = mock_apprise.notify.call_args[1]
            assert "Production NAS:" in call_kwargs["title"]
