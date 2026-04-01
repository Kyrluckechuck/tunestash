"""Celery Beat schedule configuration for periodic tasks."""

from celery.schedules import crontab

from library_manager.task_priorities import TaskPriority

CELERY_BEAT_SCHEDULE = {
    "sync-all-playlists": {
        "task": "library_manager.tasks.sync_tracked_playlists",
        "schedule": crontab(minute=0, hour="*/8"),  # Every 8 hours
        "options": {"priority": TaskPriority.PLAYLIST_DOWNLOAD},
    },
    "validate-undownloaded-songs": {
        "task": "library_manager.tasks.validate_undownloaded_songs",
        "schedule": crontab(minute=0, hour="*/12"),  # Every 12 hours
        "options": {"priority": TaskPriority.ALBUM_DOWNLOAD},
    },
    "retry-failed-songs": {
        "task": "library_manager.tasks.retry_failed_songs",
        "schedule": crontab(
            minute=0, hour=4, day_of_week="1,3,5"
        ),  # Mon/Wed/Fri at 4 AM
        "options": {"priority": TaskPriority.TRACK_DOWNLOAD},
    },
    "queue-missing-albums-for-tracked-artists": {
        "task": "library_manager.tasks.queue_missing_albums_for_tracked_artists",
        "schedule": crontab(minute="0,30"),  # Every 30 minutes
        "options": {"priority": TaskPriority.ARTIST_DOWNLOAD},
    },
    "sync-tracked-artists-metadata": {
        "task": "library_manager.tasks.sync_tracked_artists_metadata",
        "schedule": crontab(minute=30),  # Every hour at :30
        "options": {"priority": TaskPriority.ARTIST_SYNC},
    },
    "scan-new-releases-for-tracked-artists": {
        "task": "library_manager.tasks.scan_new_releases_for_tracked_artists",
        "schedule": crontab(minute=0, hour="*/6"),  # Every 6 hours
        "options": {"priority": TaskPriority.ARTIST_SYNC},
    },
    "cleanup-celery-history": {
        "task": "library_manager.tasks.cleanup_celery_history",
        "schedule": crontab(minute=0, hour=6),  # Daily at 6 AM
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "cleanup-stale-tasks": {
        "task": "library_manager.tasks.cleanup_stuck_tasks_periodic",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "memory-health-check": {
        "task": "library_manager.tasks.periodic_memory_health_check",
        "schedule": crontab(minute="*/10"),  # Every 10 minutes
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "cleanup-app-metrics": {
        "task": "library_manager.tasks.cleanup_app_metrics",
        "schedule": crontab(minute=0, hour=6),  # Daily at 6 AM
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "check-notifications": {
        "task": "library_manager.tasks.check_notifications",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
        "options": {"priority": 0},
    },
    "sync-all-external-lists": {
        "task": "library_manager.tasks.sync_all_external_lists",
        "schedule": crontab(minute=0, hour="*/8"),  # Every 8 hours
        "options": {"priority": TaskPriority.PLAYLIST_DOWNLOAD},
    },
    "cleanup-mapping-cache": {
        "task": "library_manager.tasks.cleanup_mapping_cache",
        "schedule": crontab(minute=0, hour=6),  # Daily at 6 AM
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "retry-missing-lyrics": {
        "task": "library_manager.tasks.retry_missing_lyrics",
        "schedule": crontab(minute=15),  # Every hour at :15
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "trigger-navidrome-rescan": {
        "task": "library_manager.tasks.trigger_navidrome_rescan",
        "schedule": crontab(minute=45),  # Every hour at :45
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
    "refresh-cached-stats": {
        "task": "library_manager.tasks.refresh_cached_stats",
        "schedule": crontab(minute="*/15"),
        "options": {"priority": TaskPriority.MAINTENANCE},
    },
}
