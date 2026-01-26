"""Notification tasks for credential expiry and error rate alerts."""

from typing import Any

from celery_app import app as celery_app

from .core import logger


@celery_app.task(
    bind=True,
    name="library_manager.tasks.check_notifications",
    ignore_result=True,
)
def check_notifications(self: Any) -> dict[str, bool]:
    """Periodic task to check system health and send notifications via Apprise."""
    from src.services.notification import NotificationService

    service = NotificationService()
    results = service.check_and_notify_all()

    if not results:
        logger.info("[NOTIFY] Notifications not configured, skipping")
    elif any(results.values()):
        sent = [k for k, v in results.items() if v]
        logger.info(f"[NOTIFY] Notifications sent: {sent}")
    else:
        logger.info("[NOTIFY] All checks passed, no notifications needed")

    return results


@celery_app.task(
    bind=True,
    name="library_manager.tasks.send_test_notification",
)
def send_test_notification(self: Any) -> bool:
    """Send a test notification to all configured Apprise URLs."""
    from django.conf import settings

    from src.services.notification import NotificationService

    urls = getattr(settings, "NOTIFICATIONS_URLS", [])
    enabled = getattr(settings, "NOTIFICATIONS_ENABLED", False)

    if not enabled or not urls:
        logger.info(
            "[NOTIFY] Test failed: NOTIFICATIONS_ENABLED is not true "
            "or NOTIFICATIONS_URLS is empty in settings.yaml"
        )
        return False

    try:
        import apprise
    except ImportError:
        logger.error("[NOTIFY] Test failed: apprise package not installed")
        return False

    service = NotificationService()
    name = service.get_instance_name()

    apobj = apprise.Apprise()
    for url in urls:
        apobj.add(url)

    success = apobj.notify(
        title=f"{name}: Test Notification",
        body=f"This is a test notification from {name}. "
        "If you're seeing this, notifications are working correctly!",
    )

    if success:
        logger.info(f"[NOTIFY] Test notification sent to {len(urls)} URL(s)")
    else:
        logger.warning("[NOTIFY] Test notification failed to send")

    return bool(success)
