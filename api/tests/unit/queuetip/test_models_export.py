from django.db import IntegrityError

import pytest
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
)


@pytest.mark.django_db
def test_export_snapshot_persists():
    owner = Account.objects.create(display_name="O")
    p = Playlist.objects.create(name="P", created_by=owner)
    snap = ExportSnapshot.objects.create(
        playlist=p, requested_by=owner, rng_seed=42, parameters={"x": 1}
    )
    assert snap.id is not None
    assert snap.parameters == {"x": 1}


@pytest.mark.django_db
def test_export_track_position_unique_per_snapshot():
    owner = Account.objects.create(display_name="O")
    p = Playlist.objects.create(name="P", created_by=owner)
    snap = ExportSnapshot.objects.create(playlist=p, requested_by=owner, rng_seed=1)
    song1 = SongFactory(primary_artist=ArtistFactory())
    song2 = SongFactory(primary_artist=ArtistFactory())
    ExportSnapshotTrack.objects.create(
        snapshot=snap,
        song=song1,
        position=0,
        inclusion_reason="rolled_in",
        roll_probability=0.85,
    )
    with pytest.raises(IntegrityError):
        ExportSnapshotTrack.objects.create(
            snapshot=snap,
            song=song2,
            position=0,
            inclusion_reason="rolled_in",
            roll_probability=0.85,
        )
