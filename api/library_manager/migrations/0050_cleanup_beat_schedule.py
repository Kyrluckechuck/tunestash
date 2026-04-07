from django.db import migrations


def cleanup_old_beat_entry(apps, schema_editor):
    """Delete the old sync-tracked-artists-metadata beat entry.

    It was split into two entries:
    - sync-tracked-artists-metadata-all (hourly at :00)
    - sync-tracked-artists-metadata-favourites (hourly at :30)
    """
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
        deleted, _ = PeriodicTask.objects.filter(
            name="sync-tracked-artists-metadata"
        ).delete()
        if deleted:
            print("  Deleted stale beat entry 'sync-tracked-artists-metadata'")
    except Exception:
        # django_celery_beat may not be installed in test environments
        pass


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("library_manager", "0049_three_tier_tracking"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(cleanup_old_beat_entry, noop),
    ]
