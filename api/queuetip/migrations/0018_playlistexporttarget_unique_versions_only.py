from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("queuetip", "0017_playlistexporttarget_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="playlistexporttarget",
            name="unique_versions_only",
            field=models.BooleanField(default=False),
        ),
    ]
