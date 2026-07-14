from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("queuetip", "0019_account_password_and_auth_challenges"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthReplayGuard",
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
                ("kind", models.CharField(max_length=32)),
                ("token_digest", models.CharField(max_length=64)),
                ("consumed_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("kind", "token_digest"),
                        name="queuetip_auth_replay_kind_digest_unique",
                    )
                ],
            },
        ),
    ]
