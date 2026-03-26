"""Integration tests for the notification system.

Tests realistic flows with actual database state, minimal mocking.
"""

import sys
from datetime import timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

# Pre-inject stubs so that ``from src.services.notification import ...``
# does not trigger ``src/services/__init__.py`` (which imports ``deezer``,
# a Docker-only dependency).
if "src.services" not in sys.modules:
    import importlib.util
    from pathlib import Path as _Path

    _stub_pkg = ModuleType("src.services")
    _stub_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["src.services"] = _stub_pkg

    _services_dir = _Path(__file__).resolve().parents[2] / "src" / "services"

    for _name in ("system_health", "notification"):
        _fqn = f"src.services.{_name}"
        if _fqn not in sys.modules:
            _spec = importlib.util.spec_from_file_location(
                _fqn, _services_dir / f"{_name}.py"
            )
            assert _spec and _spec.loader
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules[_fqn] = _mod
            setattr(_stub_pkg, _name, _mod)
            _spec.loader.exec_module(_mod)

from library_manager.models import NotificationState, TaskHistory
from src.services.notification import NotificationService

# Default notification settings for get_setting mock
_NOTIFICATION_DEFAULTS = {
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
    """Return a side_effect function for get_setting with optional overrides."""
    defaults = {**_NOTIFICATION_DEFAULTS, **(overrides or {})}

    def _side_effect(key):
        if key in defaults:
            return defaults[key]
        raise KeyError(f"Unknown setting: {key!r}")

    return _side_effect


@pytest.mark.django_db
class TestNotificationCooldownFlow:
    """Test cooldown behavior with real database state."""

    def test_first_alert_always_sends(self):
        """First alert of a type should always send (no prior state)."""
        service = NotificationService()

        assert NotificationState.objects.count() == 0

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
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
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
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
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
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

        # 45 minutes ago > 30 minute cooldown, should be allowed
        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_cooldown_minutes": 30}),
        ):
            assert service._cooldown_elapsed("configured_cooldown_test") is True

        # 45 minutes ago < 60 minute cooldown, should be blocked
        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_cooldown_minutes": 60}),
        ):
            assert service._cooldown_elapsed("configured_cooldown_test") is False


@pytest.mark.django_db
class TestErrorRateIntegration:
    """Test error rate detection with real TaskHistory records."""

    def test_counts_only_recent_failures(self):
        """Error rate should only count failures within the configured window."""
        now = timezone.now()

        # Create 5 recent failures and 20 successes (25% failure rate, below 50%)
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"recent-fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=2),
            )
        for i in range(20):
            TaskHistory.objects.create(
                task_id=f"recent-ok-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="COMPLETED",
                started_at=now - timedelta(hours=2),
            )

        service = NotificationService()

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status"
            ) as mock_auth,
        ):
            mock_auth.return_value = MagicMock(
                cookies_valid=True,
                cookies_expire_in_days=30,
                cookies_error_message=None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            )

            result = service._check_error_rate()

        # 25% failure rate, below 50% threshold
        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False

    def test_threshold_exactly_met_triggers_alert(self):
        """Alert should trigger when failure rate hits threshold."""
        now = timezone.now()

        # 15 failures + 5 successes = 75% failure rate (above 50%)
        for i in range(15):
            TaskHistory.objects.create(
                task_id=f"threshold-fail-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"threshold-ok-{i}",
                type="DOWNLOAD",
                entity_id="456",
                entity_type="ALBUM",
                status="COMPLETED",
                started_at=now - timedelta(hours=1),
            )

        service = NotificationService()

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
            mock_apprise = MagicMock()
            mock_apprise.notify.return_value = True
            mock_apprise_cls.return_value = mock_apprise

            result = service._check_error_rate()

        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is True

    def test_ignores_low_volume(self):
        """Should not alert when too few downloads to be meaningful."""
        now = timezone.now()

        # 5 failures, 0 successes -- 100% failure rate but only 5 downloads
        for i in range(5):
            TaskHistory.objects.create(
                task_id=f"low-vol-{i}",
                type="DOWNLOAD",
                entity_id="123",
                entity_type="ALBUM",
                status="FAILED",
                started_at=now - timedelta(hours=1),
            )

        service = NotificationService()

        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting(),
        ):
            result = service._check_error_rate()

        # Below min_downloads threshold, should not alert
        assert result[NotificationService.ALERT_HIGH_ERROR_RATE] is False


@pytest.mark.django_db
class TestFullNotificationCycle:
    """Test complete notification cycles with state persistence."""

    def test_alert_recovery_cycle(self):
        """Test alert -> recovery -> re-alert cycle with proper state tracking."""
        service = NotificationService()

        def make_auth_status(cookies_valid: bool):
            return MagicMock(
                cookies_valid=cookies_valid,
                cookies_expire_in_days=None if not cookies_valid else 30,
                cookies_error_message="Expired" if not cookies_valid else None,
                po_token_configured=False,
                po_token_valid=False,
                spotify_auth_mode="public",
                spotify_token_valid=True,
            )

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
        ):
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

            # Phase 2: Cookies still expired, send-once blocks repeat
            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=False),
            ):
                result2 = service.check_and_notify_all()

            assert result2[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert mock_apprise.notify.call_count == 1  # No new notification

            # Phase 3: Cookies fixed -> state is cleared automatically
            with patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=make_auth_status(cookies_valid=True),
            ):
                result3 = service.check_and_notify_all()

            assert result3[NotificationService.ALERT_COOKIES_EXPIRED] is False
            assert mock_apprise.notify.call_count == 1
            # State should be cleared since cookies are healthy
            assert not NotificationState.objects.filter(
                alert_type=NotificationService.ALERT_COOKIES_EXPIRED
            ).exists()

            # Phase 4: Cookies expire again -> fires immediately (no cooldown needed)
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
            cookies_expire_in_days=None,
            cookies_error_message="Cookies expired",
            po_token_configured=True,
            po_token_valid=False,
            po_token_error_message="Token rejected",
            spotify_auth_mode="user-authenticated",
            spotify_token_valid=False,
            spotify_token_error_message="Refresh failed",
        )

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status",
                return_value=all_broken_status,
            ),
        ):
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

        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting({"notifications_instance_name": ""}),
        ):
            name = service.get_instance_name()

        assert name == "TuneStash"

    def test_custom_instance_name(self):
        """Custom instance name from settings should be used."""
        service = NotificationService()

        with patch(
            "src.services.notification.get_setting",
            side_effect=_mock_get_setting(
                {"notifications_instance_name": "My Dev Server"}
            ),
        ):
            name = service.get_instance_name()

        assert name == "My Dev Server"

    def test_instance_name_in_alert_titles(self):
        """Instance name should appear in notification titles."""
        service = NotificationService()

        with (
            patch(
                "src.services.notification.get_setting",
                side_effect=_mock_get_setting(
                    {"notifications_instance_name": "Production NAS"}
                ),
            ),
            patch("apprise.Apprise") as mock_apprise_cls,
            patch(
                "src.services.system_health.SystemHealthService.check_authentication_status"
            ) as mock_auth,
        ):
            mock_auth.return_value = MagicMock(
                cookies_valid=False,
                cookies_expire_in_days=None,
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
