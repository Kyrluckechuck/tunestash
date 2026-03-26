"""Settings migration tasks."""

from typing import Any

from celery.utils.log import get_task_logger
from celery_app import app as celery_app

logger = get_task_logger(__name__)


@celery_app.task(bind=True, name="library_manager.tasks.migrate_settings_from_yaml")
def migrate_settings_from_yaml(self: Any) -> dict[str, Any]:
    """One-off task: migrate settings from /config/settings.yaml to the database.

    Backs up the YAML to settings.yaml.bak, imports non-default values,
    then deletes the original. Idempotent — safe to re-run.
    """
    from src.services.settings import SettingsService

    service = SettingsService()
    result = service.migrate_from_yaml_sync("/config/settings.yaml")

    if result["success"]:
        logger.info(
            "[SETTINGS] YAML migration: %d migrated, %d skipped",
            result["migrated"],
            result["skipped"],
        )
    else:
        logger.error("[SETTINGS] YAML migration failed: %s", result.get("error"))

    return result
