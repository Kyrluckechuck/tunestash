from django.apps import AppConfig


class QueuetipConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "queuetip"

    def ready(self) -> None:
        # Import for side-effect: registers Contribution/Vote post-save signal
        # handlers that fan out auto-sync triggers to any PlaylistExportTarget
        # with sync_mode=on_change.
        from . import (  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
            signals,
        )
