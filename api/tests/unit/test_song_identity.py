"""Identifier backfill must never attach a different recording's Deezer id or ISRC."""

from unittest.mock import patch

import pytest

from library_manager.models import Artist, Song
from library_manager.tasks.song_identity import (
    apply_identifier_updates,
    identifier_updates,
)


@pytest.fixture
def artist():
    return Artist.objects.create(name="Identity helper artist", deezer_id=8801001)


def _song(artist, **kwargs):
    defaults = {"name": "Track", "gid": "gid-helper", "primary_artist": artist}
    defaults.update(kwargs)
    return Song.objects.create(**defaults)


@pytest.mark.django_db
def test_conflicting_isrc_blocks_deezer_id_backfill(artist):
    song = _song(artist, isrc="TEST00000001")
    with patch("library_manager.tasks.song_identity.logger") as log:
        updates = identifier_updates(song, 9000000002, "TEST00000002")

    assert "deezer_id" not in updates
    assert "isrc conflict" in " ".join(str(c) for c in log.info.call_args_list).lower()


@pytest.mark.django_db
def test_alternate_isrc_allows_deezer_id_backfill(artist):
    song = _song(artist, isrc="TEST00000001", alternate_isrcs=["TEST00000002"])

    updates = identifier_updates(song, 9000000002, "TEST00000002")

    assert updates == {"deezer_id": 9000000002}


@pytest.mark.django_db
def test_matching_isrc_allows_deezer_id_backfill(artist):
    song = _song(artist, isrc="TEST00000001")

    updates = identifier_updates(song, 9000000001, "TEST00000001")

    assert updates == {"deezer_id": 9000000001}


@pytest.mark.django_db
def test_existing_deezer_id_is_never_replaced(artist):
    song = _song(artist, deezer_id=9000000001, isrc="TEST00000001")

    updates = identifier_updates(song, 9000000002, "TEST00000001")

    assert "deezer_id" not in updates


@pytest.mark.django_db
def test_missing_isrc_is_not_filled_when_deezer_ids_disagree(artist):
    song = _song(artist, deezer_id=9000000001)

    updates = identifier_updates(song, 9000000002, "TEST00000002")

    assert "isrc" not in updates


@pytest.mark.django_db
def test_missing_isrc_is_filled_when_deezer_ids_agree(artist):
    song = _song(artist, deezer_id=9000000001)

    updates = identifier_updates(song, 9000000001, "TEST00000001")

    assert updates == {"isrc": "TEST00000001"}


@pytest.mark.django_db
def test_apply_identifier_updates_persists_only_listed_fields(artist):
    song = _song(artist, isrc="TEST00000001", name="Original")

    apply_identifier_updates(
        song, {"deezer_id": 9000000001, "name": "Updated"}, extra_fields=["album_id"]
    )

    song.refresh_from_db()
    assert song.deezer_id == 9000000001
    assert song.name == "Updated"
