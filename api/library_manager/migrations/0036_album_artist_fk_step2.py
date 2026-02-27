"""Album FK migration step 2: Swap old gid-based FK with new integer FK.

Removes the old artist FK (to_field="gid", db_column="artist_gid"),
renames artist_new → artist, and makes it non-nullable.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library_manager", "0035_album_artist_fk_step1"),
    ]

    operations = [
        # Remove old gid-based FK
        migrations.RemoveField(
            model_name="album",
            name="artist",
        ),
        # Rename new integer FK
        migrations.RenameField(
            model_name="album",
            old_name="artist_new",
            new_name="artist",
        ),
        # Make non-nullable (all existing data was populated in step 1)
        migrations.AlterField(
            model_name="album",
            name="artist",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="library_manager.artist",
            ),
        ),
    ]
