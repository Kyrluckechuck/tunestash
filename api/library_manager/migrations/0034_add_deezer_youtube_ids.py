"""Add Deezer and YouTube Music ID fields, make Spotify GIDs nullable.

Part of the multi-provider migration: Deezer as primary metadata source,
YouTube Music as co-primary/fallback for audio downloads.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library_manager", "0033_alter_externallist_source"),
    ]

    operations = [
        # ── Artist: make gid nullable, add deezer_id + youtube_id ──
        migrations.AlterField(
            model_name="artist",
            name="gid",
            field=models.CharField(
                max_length=120,
                unique=True,
                null=True,
                blank=True,
                help_text="Spotify Artist ID (22-char base62, e.g., '4iV5W9uYEdYUVa79Axb7Rh')",
            ),
        ),
        migrations.AddField(
            model_name="artist",
            name="deezer_id",
            field=models.BigIntegerField(
                unique=True,
                null=True,
                blank=True,
                help_text="Deezer artist ID",
            ),
        ),
        migrations.AddField(
            model_name="artist",
            name="youtube_id",
            field=models.CharField(
                max_length=120,
                unique=True,
                null=True,
                blank=True,
                help_text="YouTube Music channel ID",
            ),
        ),
        # ── Song: make gid nullable, add deezer_id + youtube_id ──
        migrations.AlterField(
            model_name="song",
            name="gid",
            field=models.CharField(
                max_length=120,
                unique=True,
                null=True,
                blank=True,
                help_text="Spotify Track ID (22-char base62, e.g., '6rqhFgbbKwnb9MLmUQDhG6')",
            ),
        ),
        migrations.AddField(
            model_name="song",
            name="deezer_id",
            field=models.BigIntegerField(
                unique=True,
                null=True,
                blank=True,
                help_text="Deezer track ID",
            ),
        ),
        migrations.AddField(
            model_name="song",
            name="youtube_id",
            field=models.CharField(
                max_length=120,
                unique=True,
                null=True,
                blank=True,
                help_text="YouTube Music video ID",
            ),
        ),
        # ── Album: make spotify_gid nullable, add deezer_id + youtube_id ──
        migrations.AlterField(
            model_name="album",
            name="spotify_gid",
            field=models.CharField(
                max_length=2048,
                unique=True,
                null=True,
                blank=True,
                help_text="Spotify Album ID (22-char base62, e.g., '7K3BhSpAxZBzniskgIPUYj')",
            ),
        ),
        migrations.AddField(
            model_name="album",
            name="deezer_id",
            field=models.BigIntegerField(
                unique=True,
                null=True,
                blank=True,
                help_text="Deezer album ID",
            ),
        ),
        migrations.AddField(
            model_name="album",
            name="youtube_id",
            field=models.CharField(
                max_length=120,
                unique=True,
                null=True,
                blank=True,
                help_text="YouTube Music album/playlist ID",
            ),
        ),
        # ── CHECK constraints: at least one external ID must be present ──
        migrations.AddConstraint(
            model_name="artist",
            constraint=models.CheckConstraint(
                check=~(
                    models.Q(gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="artist_has_at_least_one_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="song",
            constraint=models.CheckConstraint(
                check=~(
                    models.Q(gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="song_has_at_least_one_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="album",
            constraint=models.CheckConstraint(
                check=~(
                    models.Q(spotify_gid__isnull=True)
                    & models.Q(deezer_id__isnull=True)
                    & models.Q(youtube_id__isnull=True)
                ),
                name="album_has_at_least_one_external_id",
            ),
        ),
        # ── Indexes for new ID fields ──
        migrations.AddIndex(
            model_name="artist",
            index=models.Index(fields=["deezer_id"], name="idx_artist_deezer_id"),
        ),
        migrations.AddIndex(
            model_name="artist",
            index=models.Index(fields=["youtube_id"], name="idx_artist_youtube_id"),
        ),
        migrations.AddIndex(
            model_name="song",
            index=models.Index(fields=["deezer_id"], name="idx_song_deezer_id"),
        ),
        migrations.AddIndex(
            model_name="song",
            index=models.Index(fields=["youtube_id"], name="idx_song_youtube_id"),
        ),
        migrations.AddIndex(
            model_name="album",
            index=models.Index(fields=["deezer_id"], name="idx_album_deezer_id"),
        ),
        migrations.AddIndex(
            model_name="album",
            index=models.Index(fields=["youtube_id"], name="idx_album_youtube_id"),
        ),
    ]
