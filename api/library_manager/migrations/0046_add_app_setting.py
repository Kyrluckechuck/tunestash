from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library_manager", "0045_add_lyrics_pending_retry_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=100, unique=True)),
                ("value", models.JSONField()),
                ("category", models.CharField(max_length=50)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "app_setting",
            },
        ),
    ]
