"""Notification service using Apprise for credential expiry and error rate alerts."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from library_manager.models import NotificationState, TaskHistory

logger = logging.getLogger(__name__)


class NotificationService:
    """Sends notifications via Apprise when credentials expire or error rates spike.

    Configuration is read from Django settings (Dynaconf-backed):
        NOTIFICATIONS_ENABLED: bool - master toggle
        NOTIFICATIONS_URLS: list[str] - Apprise notification URLs
        NOTIFICATIONS_COOLDOWN_MINUTES: int - minimum minutes between repeated alerts
        NOTIFICATIONS_ERROR_THRESHOLD: int - number of failures to trigger alert
        NOTIFICATIONS_ERROR_WINDOW_HOURS: int - time window for error counting
        NOTIFICATIONS_COOKIE_WARN_DAYS: int - days before expiry for first warning (default 7)
        NOTIFICATIONS_COOKIE_URGENT_DAYS: int - days before expiry for urgent warning (default 1)
    """

    ALERT_COOKIES_EXPIRED = "cookies_expired"
    ALERT_COOKIES_EXPIRING_SOON = "cookies_expiring_soon"
    ALERT_COOKIES_EXPIRING_URGENT = "cookies_expiring_urgent"
    ALERT_PO_TOKEN_INVALID = "po_token_invalid"
    ALERT_SPOTIFY_OAUTH_FAILED = "spotify_oauth_failed"
    ALERT_HIGH_ERROR_RATE = "high_error_rate"

    COOKIE_ALERT_TYPES = [
        ALERT_COOKIES_EXPIRED,
        ALERT_COOKIES_EXPIRING_SOON,
        ALERT_COOKIES_EXPIRING_URGENT,
    ]

    def check_and_notify_all(self) -> dict[str, bool]:
        """Run all notification checks and send alerts as needed.

        Returns:
            dict mapping alert_type to whether a notification was sent.
        """
        results: dict[str, bool] = {}

        if not self._is_configured():
            logger.info("[NOTIFY] Notifications not configured, skipping")
            return results

        try:
            results.update(self._check_auth_alerts())
        except Exception as e:
            logger.warning(f"[NOTIFY] Auth check failed: {e}")

        try:
            results.update(self._check_error_rate())
        except Exception as e:
            logger.warning(f"[NOTIFY] Error rate check failed: {e}")

        return results

    def _is_configured(self) -> bool:
        enabled = getattr(settings, "NOTIFICATIONS_ENABLED", False)
        urls = getattr(settings, "NOTIFICATIONS_URLS", [])
        return bool(enabled and urls)

    def get_instance_name(self) -> str:
        """Get the instance name for notification titles."""
        name = getattr(settings, "NOTIFICATIONS_INSTANCE_NAME", "")
        if name:
            return str(name)
        return "TuneStash"

    def _get_cooldown_minutes(self) -> int:
        return int(getattr(settings, "NOTIFICATIONS_COOLDOWN_MINUTES", 60))

    def _check_auth_alerts(self) -> dict[str, bool]:
        """Check all authentication conditions and send alerts."""
        from src.services.system_health import SystemHealthService

        results: dict[str, bool] = {}
        name = self.get_instance_name()

        auth_status = SystemHealthService.check_authentication_status()

        # Get configurable warning thresholds
        warn_days = int(getattr(settings, "NOTIFICATIONS_COOKIE_WARN_DAYS", 7))
        urgent_days = int(getattr(settings, "NOTIFICATIONS_COOKIE_URGENT_DAYS", 1))

        # YouTube cookies - check expiration state with tiered warnings
        # Auth alerts use fire-once: send once per condition, reset when resolved
        if not auth_status.cookies_valid:
            error_msg = auth_status.cookies_error_message or "Unknown error"
            results[self.ALERT_COOKIES_EXPIRED] = self._send(
                title=f"{name}: YouTube Cookies Expired",
                body=f"YouTube Music cookies are invalid: {error_msg}. "
                "Downloads will fail until cookies are refreshed.",
                alert_type=self.ALERT_COOKIES_EXPIRED,
                send_once=True,
            )
            results[self.ALERT_COOKIES_EXPIRING_SOON] = False
            results[self.ALERT_COOKIES_EXPIRING_URGENT] = False
        else:
            results[self.ALERT_COOKIES_EXPIRED] = False
            days_left = auth_status.cookies_expire_in_days

            if days_left is not None and days_left <= urgent_days:
                results[self.ALERT_COOKIES_EXPIRING_URGENT] = self._send(
                    title=f"{name}: YouTube Cookies Expiring Soon!",
                    body=f"YouTube Music cookies expire in {days_left} day(s). "
                    "Please refresh your cookies to avoid download failures.",
                    alert_type=self.ALERT_COOKIES_EXPIRING_URGENT,
                    send_once=True,
                )
                results[self.ALERT_COOKIES_EXPIRING_SOON] = False
            elif days_left is not None and days_left <= warn_days:
                results[self.ALERT_COOKIES_EXPIRING_SOON] = self._send(
                    title=f"{name}: YouTube Cookies Expiring",
                    body=f"YouTube Music cookies expire in {days_left} day(s). "
                    "Consider refreshing your cookies soon.",
                    alert_type=self.ALERT_COOKIES_EXPIRING_SOON,
                    send_once=True,
                )
                results[self.ALERT_COOKIES_EXPIRING_URGENT] = False
            else:
                # Cookies are healthy - clear cookie alert states so they
                # fire again when cookies next enter a warning tier
                self._clear_alert_states(self.COOKIE_ALERT_TYPES)
                results[self.ALERT_COOKIES_EXPIRING_SOON] = False
                results[self.ALERT_COOKIES_EXPIRING_URGENT] = False

        # PO token (only alert if configured but invalid)
        if auth_status.po_token_configured and not auth_status.po_token_valid:
            error_msg = auth_status.po_token_error_message or "Validation failed"
            results[self.ALERT_PO_TOKEN_INVALID] = self._send(
                title=f"{name}: PO Token Invalid",
                body=f"PO token validation failed: {error_msg}. "
                "Premium audio quality may be unavailable.",
                alert_type=self.ALERT_PO_TOKEN_INVALID,
                send_once=True,
            )
        else:
            self._clear_alert_states([self.ALERT_PO_TOKEN_INVALID])
            results[self.ALERT_PO_TOKEN_INVALID] = False

        # Spotify OAuth (only alert in user-authenticated mode)
        if (
            auth_status.spotify_auth_mode == "user-authenticated"
            and not auth_status.spotify_token_valid
        ):
            error_msg = (
                auth_status.spotify_token_error_message or "Token refresh failed"
            )
            results[self.ALERT_SPOTIFY_OAUTH_FAILED] = self._send(
                title=f"{name}: Spotify OAuth Failed",
                body=f"Spotify OAuth token is invalid: {error_msg}. "
                "Private playlist syncing will fail until re-authenticated.",
                alert_type=self.ALERT_SPOTIFY_OAUTH_FAILED,
                send_once=True,
            )
        else:
            self._clear_alert_states([self.ALERT_SPOTIFY_OAUTH_FAILED])
            results[self.ALERT_SPOTIFY_OAUTH_FAILED] = False

        return results

    def _check_error_rate(self) -> dict[str, bool]:
        """Check if task failure rate exceeds threshold."""
        threshold = int(getattr(settings, "NOTIFICATIONS_ERROR_THRESHOLD", 10))
        window_hours = int(getattr(settings, "NOTIFICATIONS_ERROR_WINDOW_HOURS", 6))
        name = self.get_instance_name()

        window_start = timezone.now() - timedelta(hours=window_hours)
        failed_count = TaskHistory.objects.filter(
            status="FAILED", started_at__gte=window_start
        ).count()

        if failed_count >= threshold:
            sent = self._send(
                title=f"{name}: High Error Rate",
                body=f"{failed_count} tasks have failed in the last {window_hours} hours "
                f"(threshold: {threshold}). Check worker logs for details.",
                alert_type=self.ALERT_HIGH_ERROR_RATE,
            )
            return {self.ALERT_HIGH_ERROR_RATE: sent}

        return {self.ALERT_HIGH_ERROR_RATE: False}

    def _send(
        self, title: str, body: str, alert_type: str, send_once: bool = False
    ) -> bool:
        """Send a notification if allowed by cooldown or send-once logic.

        Args:
            send_once: If True, only send if we haven't already notified for this
                alert type. State must be cleared externally when the condition
                resolves. If False, use the standard time-based cooldown.

        Returns True if notification was actually sent, False if skipped or failed.
        """
        if send_once:
            if self._already_notified(alert_type):
                logger.debug(f"[NOTIFY] Already notified for {alert_type}, skipping")
                return False
        elif not self._cooldown_elapsed(alert_type):
            logger.debug(f"[NOTIFY] Cooldown active for {alert_type}, skipping")
            return False

        import apprise

        urls = getattr(settings, "NOTIFICATIONS_URLS", [])
        if not urls:
            return False

        apobj = apprise.Apprise()
        for url in urls:
            apobj.add(url)

        success = apobj.notify(title=title, body=body)

        if success:
            logger.info(f"[NOTIFY] Sent '{alert_type}' notification")
            self._record_sent(alert_type, body)
        else:
            logger.warning(
                f"[NOTIFY] Failed to send '{alert_type}' notification via Apprise"
            )

        return bool(success)

    def _cooldown_elapsed(self, alert_type: str) -> bool:
        """Check if enough time has passed since the last notification of this type."""
        cooldown_minutes = self._get_cooldown_minutes()
        try:
            state = NotificationState.objects.get(alert_type=alert_type)
            elapsed = timezone.now() - state.last_sent_at
            return bool(elapsed >= timedelta(minutes=cooldown_minutes))
        except NotificationState.DoesNotExist:
            return True

    def _already_notified(self, alert_type: str) -> bool:
        """Check if we've already sent a notification for this alert type."""
        return NotificationState.objects.filter(alert_type=alert_type).exists()

    def _clear_alert_states(self, alert_types: list[str]) -> None:
        """Clear notification states so alerts can fire again.

        Called when a condition resolves (e.g., cookies refreshed).
        """
        deleted, _ = NotificationState.objects.filter(
            alert_type__in=alert_types
        ).delete()
        if deleted:
            logger.debug(
                f"[NOTIFY] Cleared {deleted} notification state(s) "
                f"for resolved conditions"
            )

    def _record_sent(self, alert_type: str, message: str) -> None:
        """Record that a notification was sent for cooldown tracking."""
        NotificationState.objects.update_or_create(
            alert_type=alert_type,
            defaults={"last_sent_at": timezone.now(), "last_message": message},
        )
