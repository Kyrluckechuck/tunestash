from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("library_manager", "0053_song_alternate_isrcs_song_idx_song_alt_isrcs"),
    ]

    operations = [
        TrigramExtension(),
    ]
