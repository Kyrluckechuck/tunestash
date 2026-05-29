from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("queuetip", "0016_account_last_signed_in_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="playlistexporttarget",
            name="exclude_my_downvotes",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="playlistexporttarget",
            name="min_score_threshold",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="playlistexporttarget",
            name="target_size_override",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
