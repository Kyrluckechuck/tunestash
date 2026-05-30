from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("queuetip", "0018_playlistexporttarget_unique_versions_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="password_hash",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="account",
            name="password_set_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="AuthAttemptLog",
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
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("code", "Code"),
                            ("password", "Password"),
                            ("password_reset_request", "Password reset request"),
                            ("password_reset_submit", "Password reset submit"),
                        ],
                        max_length=32,
                    ),
                ),
                ("identifier", models.EmailField(max_length=254)),
                ("ip_address", models.CharField(max_length=64)),
                ("was_successful", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="LoginCodeChallenge",
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
                ("identifier", models.EmailField(max_length=254)),
                ("code_hash", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="login_code_challenges",
                        to="queuetip.account",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PasswordResetChallenge",
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
                ("identifier", models.EmailField(max_length=254)),
                ("token_hash", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="password_reset_challenges",
                        to="queuetip.account",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="authattemptlog",
            index=models.Index(
                fields=["method", "identifier", "created_at"],
                name="qt_auth_meth_ident_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="authattemptlog",
            index=models.Index(
                fields=["method", "ip_address", "created_at"],
                name="qt_auth_meth_ip_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="logincodechallenge",
            index=models.Index(
                fields=["identifier", "created_at"],
                name="qt_lc_ident_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="logincodechallenge",
            index=models.Index(
                fields=["account", "created_at"],
                name="qt_lc_acct_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="passwordresetchallenge",
            index=models.Index(
                fields=["identifier", "created_at"],
                name="qt_pr_ident_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="passwordresetchallenge",
            index=models.Index(
                fields=["account", "created_at"],
                name="qt_pwreset_account_created_idx",
            ),
        ),
    ]
