"""Legacy flag repair must be explicit, narrow, and never schedule downloads."""

import json
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.models import Artist, Song


@pytest.mark.django_db
def test_legacy_repair_is_dry_run_then_idempotent(tmp_path):
    artist = Artist.objects.create(name="Repair test", deezer_id=990001)
    old = datetime(2026, 6, 1, tzinfo=timezone.utc)
    songs = [
        Song.objects.create(
            name=f"Test {i}",
            deezer_id=990002 + i,
            primary_artist=artist,
            unavailable=True,
            failure_reason=reason,
            downloaded=downloaded,
            last_failed_at=failed_at,
            failed_count=5,
        )
        for i, (reason, downloaded, failed_at) in enumerate(
            [
                ("temporary", False, old),
                ("temporary", True, old),
                ("ytm_no_match", False, old),
                ("temporary", False, datetime(2026, 7, 1, tzinfo=timezone.utc)),
                ("temporary", False, None),
                (
                    "temporary",
                    False,
                    datetime(2026, 6, 19, 20, 2, 34, tzinfo=timezone.utc),
                ),
            ]
        )
    ]
    output = StringIO()
    call_command("repair_legacy_availability", stdout=output)
    songs[0].refresh_from_db()
    assert songs[0].unavailable
    assert "would repair 1" in output.getvalue()

    with pytest.raises(CommandError, match="requires --audit-file"):
        call_command("repair_legacy_availability", apply=True)
    with patch("library_manager.tasks.retry_failed_songs.delay") as queue:
        call_command(
            "repair_legacy_availability",
            apply=True,
            audit_file=str(tmp_path / "audit.json"),
            stdout=StringIO(),
        )
        queue.assert_not_called()
    for song in songs:
        song.refresh_from_db()
    assert not songs[0].unavailable
    assert all(song.unavailable for song in songs[1:])
    assert songs[0].failed_count == 5
    assert songs[0].failure_reason == "temporary"
    assert songs[0].last_failed_at == old
    audit = json.loads((tmp_path / "audit.json").read_text())
    assert [row["id"] for row in audit] == [songs[0].id]
    assert audit[0]["unavailable"] is True
    output = StringIO()
    call_command(
        "repair_legacy_availability",
        apply=True,
        audit_file=str(tmp_path / "second-audit.json"),
        stdout=output,
    )
    assert "repaired 0" in output.getvalue()
