"""Album FK migration step 1: Add integer FK alongside old gid-based FK.

The Album model currently uses ForeignKey(Artist, to_field="gid", db_column="artist_gid")
which stores Spotify GID strings. Since Artist.gid is becoming nullable (for non-Spotify
providers), we need to migrate to a standard integer PK FK.

Step 1: Add new integer FK column and populate via raw SQL join.
"""

import django.db.models.deletion
from django.db import migrations, models


def populate_artist_id(apps, schema_editor):
    """Populate artist_new_id from the existing artist_gid column using raw SQL."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE albums
            SET artist_new_id = artists.id
            FROM artists
            WHERE albums.artist_gid = artists.gid
            """
        )


def reverse_populate(apps, schema_editor):
    """Reverse: populate artist_gid from artist_new_id using raw SQL."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE albums
            SET artist_gid = artists.gid
            FROM artists
            WHERE albums.artist_new_id = artists.id
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("library_manager", "0034_add_deezer_youtube_ids"),
    ]

    operations = [
        # Add new integer FK column (nullable initially for data migration)
        migrations.AddField(
            model_name="album",
            name="artist_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="library_manager.artist",
            ),
        ),
        # Populate from existing gid mapping
        migrations.RunPython(populate_artist_id, reverse_populate),
    ]
