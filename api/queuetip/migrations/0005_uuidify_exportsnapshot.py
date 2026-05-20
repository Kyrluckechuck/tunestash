# Manually crafted — AlterField cannot cast bigint→uuid in PostgreSQL.
# Strategy: drop ExportSnapshotTrack rows (FK), drop ExportSnapshot rows,
# then recreate both tables with UUID PK via SeparateDatabaseAndState so
# Django's state sees the AlterField while the DB gets explicit SQL.

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("queuetip", "0004_magiclinkrequestlog"),
    ]

    operations = [
        # 1. Remove the FK constraint from ExportSnapshotTrack so we can alter
        #    ExportSnapshot's PK freely. Accomplished by dropping and recreating
        #    the FK column using SeparateDatabaseAndState.
        migrations.SeparateDatabaseAndState(
            # Database side: raw SQL to drop + recreate the PK and FK
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    -- Drop all existing snapshot data (dev environment;
                    -- no production rows exist yet).
                    DELETE FROM queuetip_exportsnapshottrack;
                    DELETE FROM queuetip_exportsnapshot;

                    -- Drop FK constraint on ExportSnapshotTrack.snapshot_id
                    ALTER TABLE queuetip_exportsnapshottrack
                        DROP COLUMN snapshot_id;

                    -- Drop old bigserial PK and replace with uuid
                    ALTER TABLE queuetip_exportsnapshot
                        DROP CONSTRAINT queuetip_exportsnapshot_pkey;
                    ALTER TABLE queuetip_exportsnapshot
                        DROP COLUMN id;
                    ALTER TABLE queuetip_exportsnapshot
                        ADD COLUMN id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY;

                    -- Recreate snapshot_id FK column on ExportSnapshotTrack
                    ALTER TABLE queuetip_exportsnapshottrack
                        ADD COLUMN snapshot_id uuid NOT NULL
                        REFERENCES queuetip_exportsnapshot(id) DEFERRABLE INITIALLY DEFERRED;

                    -- Restore unique constraint on (snapshot, position)
                    ALTER TABLE queuetip_exportsnapshottrack
                        ADD CONSTRAINT queuetip_export_track_position_unique
                        UNIQUE (snapshot_id, position);

                    -- Restore index on snapshot_id for FK lookups
                    CREATE INDEX queuetip_exportsnapshottrack_snapshot_id_idx
                        ON queuetip_exportsnapshottrack (snapshot_id);
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                )
            ],
            # State side: tell Django's migration framework the new field shape
            state_operations=[
                migrations.AlterField(
                    model_name="exportsnapshot",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
            ],
        ),
    ]
