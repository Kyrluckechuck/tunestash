"""revert_artist_credit_changes: dry-run first, CAS-guarded, audited.

All names and ids in this module are synthetic.
"""

import json
import os
import stat
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.management.commands import revert_artist_credit_changes as rev
from library_manager.models import Album, Artist, Song


def _credit(name: str, deezer_id: int, role: str) -> dict[str, Any]:
    return {"name": name, "deezer_id": deezer_id, "role": role, "gid": None}


def _write_audit(path: Path, entries: list[tuple[dict[str, Any], str]]) -> None:
    """entries: (plan, outcome) pairs, written like the backfill does."""
    lines: list[dict[str, Any]] = [{"record": "header"}]
    for plan, outcome in entries:
        lines.append({"status": "fix", **plan})
        lines.append(
            {"record": "complete", "song_id": plan["song_id"], "outcome": outcome}
        )
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


@pytest.fixture
def world() -> dict[str, Any]:
    old = Artist.objects.create(name="Old Primary", deezer_id=1)
    lead = Artist.objects.create(name="Credited Lead", deezer_id=2)
    owner = Artist.objects.create(name="Album Owner", deezer_id=3)
    return {"old": old, "lead": lead, "owner": owner}


def _song(
    world: dict[str, Any],
    n: int,
    album_artist: Artist | None = None,
    album_type: str = "album",
    album_name: str = "Some Album",
) -> Song:
    album = Album.objects.create(
        name=album_name,
        artist=album_artist or world["owner"],
        deezer_id=8000 + n,
        album_type=album_type,
    )
    # the backfill already moved the primary to the lead
    return Song.objects.create(
        name=f"Song {n}", deezer_id=9000 + n, primary_artist=world["lead"], album=album
    )


def _plan(
    world: dict[str, Any], song: Song, category: str, old_role: str | None
) -> dict[str, Any]:
    credits = [_credit("Credited Lead", 2, "main")]
    if old_role:
        credits.append(_credit("Old Primary", 1, old_role))
    return {
        "song_id": song.pk,
        "category": category,
        "old_primary_id": world["old"].pk,
        "old_primary_name": "Old Primary",
        "old_primary_deezer_id": 1,
        "lead_name": "Credited Lead",
        "lead_deezer_id": 2,
        "credits": credits,
    }


def _run(*args: str) -> str:
    out = StringIO()
    with patch.object(rev.os, "fsync"):
        call_command("revert_artist_credit_changes", *args, stdout=out)
    return out.getvalue()


@pytest.mark.unit
class TestRevertDryRun:
    def test_reports_counts_and_examples_and_writes_nothing(
        self, world: dict[str, Any], tmp_path: Path
    ) -> None:
        co_lead = _song(world, 1)
        genuine = _song(world, 2)
        absent = _song(world, 3)
        audit = tmp_path / "audit.jsonl"
        _write_audit(
            audit,
            [
                (
                    _plan(world, co_lead, "featured_as_primary", "main"),
                    "featured_as_primary",
                ),
                (
                    _plan(world, genuine, "featured_as_primary", "featured"),
                    "featured_as_primary",
                ),
                (
                    _plan(world, absent, "primary_not_credited", None),
                    "primary_not_credited",
                ),
            ],
        )

        output = _run("--audit-in", str(audit))

        assert "DRY RUN" in output
        assert "featured_as_primary:old_primary_credited_main:revertable: 1" in output
        assert "keep_change_genuine_fix_old_not_main_credited: 2" in output
        assert "revertable now: 1" in output
        assert "[featured_as_primary/old_primary_credited_main]" in output
        for song in (co_lead, genuine, absent):
            song.refresh_from_db()
            assert song.primary_artist == world["lead"]

    def test_own_album_remix_is_revertable_even_when_featured_only(
        self, world: dict[str, Any], tmp_path: Path
    ) -> None:
        remix = _song(world, 4, album_artist=world["old"])
        audit = tmp_path / "audit.jsonl"
        _write_audit(
            audit,
            [
                (
                    _plan(world, remix, "featured_as_primary", "featured"),
                    "featured_as_primary",
                )
            ],
        )

        output = _run("--audit-in", str(audit))

        assert "old_primary_credited_on_own_album:revertable: 1" in output

    def test_primary_not_credited_breakdown(
        self, world: dict[str, Any], tmp_path: Path
    ) -> None:
        dj = _song(world, 5, album_artist=world["old"], album_type="compilation")
        mixname = _song(
            world, 6, album_artist=world["old"], album_name="Club Mix Vol. 3"
        )
        other_owner = _song(world, 7, album_type="compilation")
        plain = _song(world, 8, album_artist=world["old"])
        unrelated = _song(world, 9)
        audit = tmp_path / "audit.jsonl"
        _write_audit(
            audit,
            [
                (_plan(world, s, "primary_not_credited", None), "primary_not_credited")
                for s in (dj, mixname, other_owner, plain, unrelated)
            ],
        )

        output = _run("--audit-in", str(audit))

        assert "dj_mix_compilation: 2" in output
        assert "compilation_other_owner: 1" in output
        assert "other_album_by_old_primary: 1" in output
        assert "  other: 1" in output

    def test_changed_since_backfill_is_not_revertable(
        self, world: dict[str, Any], tmp_path: Path
    ) -> None:
        song = _song(world, 10)
        newer = Artist.objects.create(name="Newer Fix", deezer_id=99)
        Song.objects.filter(pk=song.pk).update(primary_artist=newer)
        audit = tmp_path / "audit.jsonl"
        _write_audit(
            audit,
            [
                (
                    _plan(world, song, "featured_as_primary", "main"),
                    "featured_as_primary",
                )
            ],
        )

        output = _run("--audit-in", str(audit))

        assert "skip_primary_changed_since_backfill: 1" in output
        assert "revertable now: 0" in output

    def test_apply_requires_a_new_audit_out(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit.jsonl"
        _write_audit(audit, [])
        with pytest.raises(CommandError, match="--audit-out"):
            call_command(
                "revert_artist_credit_changes", "--audit-in", str(audit), "--apply"
            )
        out = tmp_path / "out.jsonl"
        out.write_text("x")
        with pytest.raises(CommandError, match="already exists"):
            _run("--audit-in", str(audit), "--apply", "--audit-out", str(out))


@pytest.mark.unit
class TestRevertApply:
    def test_restores_only_co_leads_under_cas_with_a_private_pre_written_audit(
        self, world: dict[str, Any], tmp_path: Path
    ) -> None:
        co_lead = _song(world, 11)
        genuine = _song(world, 12)
        raced = _song(world, 13)
        audit = tmp_path / "audit.jsonl"
        _write_audit(
            audit,
            [
                (
                    _plan(world, co_lead, "featured_as_primary", "main"),
                    "featured_as_primary",
                ),
                (
                    _plan(world, genuine, "featured_as_primary", "featured"),
                    "featured_as_primary",
                ),
                (
                    _plan(world, raced, "primary_not_credited", "main"),
                    "primary_not_credited",
                ),
            ],
        )
        out = tmp_path / "revert.jsonl"
        seen: dict[str, Any] = {}
        original = rev.Command._revert_one
        newer = Artist.objects.create(name="Newer Fix", deezer_id=99)

        def spy(item: dict[str, Any]) -> str:
            if "lines" not in seen:
                seen["mode"] = stat.S_IMODE(os.stat(out).st_mode)
                seen["lines"] = out.read_text().splitlines()
                # a concurrent correction lands before the second song is reached
                Song.objects.filter(pk=raced.pk).update(primary_artist=newer)
            return original(item)

        with patch.object(rev.Command, "_revert_one", staticmethod(spy)):
            output = _run("--audit-in", str(audit), "--apply", "--audit-out", str(out))

        co_lead.refresh_from_db()
        genuine.refresh_from_db()
        raced.refresh_from_db()
        assert co_lead.primary_artist == world["old"]
        assert genuine.primary_artist == world["lead"]  # genuine fix left alone
        assert raced.primary_artist == newer  # CAS: newer value never overwritten
        assert "reverted: 1; skipped (changed meanwhile): 1" in output
        assert seen["mode"] == 0o600
        plans = [json.loads(x) for x in seen["lines"] if '"plan"' in x]
        assert {p["song_id"] for p in plans} == {co_lead.pk, raced.pk}  # before writes
