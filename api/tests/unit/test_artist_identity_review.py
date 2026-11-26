"""Review and resolution of backfill-reported artist identity pairs.

All artists, tracks, ids and ISRCs below are synthetic test data.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from library_manager.artist_review import (
    ACTION_LINK,
    ACTION_MERGE,
    ACTION_NEEDS_REVIEW,
    DIFFERENT_SETTING_KEY,
    IdentityCase,
    build_review,
    recorded_different_pairs,
)
from library_manager.management.commands import resolve_artist_identity as resolver
from library_manager.models import (
    Album,
    AppSetting,
    Artist,
    ContributingArtist,
    Song,
    TrackingTier,
)


def _audit(
    path: Path,
    status: str,
    *,
    old_id: int,
    old_name: str,
    old_deezer_id: int | None,
    lead_name: str,
    lead_deezer_id: int | None,
    credits: list[dict[str, Any]],
    song_id: int,
    song_name: str = "Synthetic Track",
    ambiguous: list[str] | None = None,
    evidence: list[str] | None = None,
) -> None:
    record = {
        "record": "plan" if False else "song",
        "song_id": song_id,
        "name": song_name,
        "status": status,
        "old_primary_id": old_id,
        "old_primary_name": old_name,
        "old_primary_deezer_id": old_deezer_id,
        "lead_name": lead_name,
        "lead_deezer_id": lead_deezer_id,
        "credits": credits,
        "ambiguous_credits": ambiguous or [],
        "evidence_isrcs": evidence or [],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _artist(
    name: str,
    *,
    deezer_id: int | None = None,
    gid: str | None = None,
    tier: int = TrackingTier.UNTRACKED,
) -> Artist:
    return Artist.objects.create(
        name=name, deezer_id=deezer_id, gid=gid, tracking_tier=tier
    )


def _song(
    name: str, artist: Artist, *, isrc: str | None = None, deezer_id: int | None = None
) -> Song:
    return Song.objects.create(
        name=name,
        primary_artist=artist,
        isrc=isrc,
        deezer_id=deezer_id or 900000 + Song.objects.count(),
        downloaded=True,
    )


def _case(
    kind: str,
    existing_id: int,
    incoming_name: str,
    deezer_id: int | None,
    gid: str | None = None,
) -> IdentityCase:
    return IdentityCase(
        kind=kind,
        existing_artist_id=existing_id,
        incoming_name=incoming_name,
        incoming_deezer_id=deezer_id,
        incoming_gid=gid,
    )


def _csv(path: Path, decisions: list[tuple[IdentityCase, str]]) -> None:
    fields = [
        "case_key",
        "kind",
        "existing_artist_id",
        "existing_artist_name",
        "existing_gid",
        "existing_deezer_id",
        "existing_tier",
        "incoming_name",
        "incoming_deezer_id",
        "incoming_gid",
        "affected_songs",
        "isrc_overlap_songs",
        "isrc_overlap_example",
        "example_songs",
        "suggested_action",
        "reason",
        "decision",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case, decision in decisions:
            writer.writerow(
                {
                    "case_key": case.case_key,
                    "kind": case.kind,
                    "existing_artist_id": case.existing_artist_id,
                    "existing_artist_name": case.existing_name,
                    "existing_gid": case.existing_gid or "",
                    "existing_deezer_id": case.existing_deezer_id or "",
                    "existing_tier": case.existing_tier,
                    "incoming_name": case.incoming_name,
                    "incoming_deezer_id": case.incoming_deezer_id or "",
                    "incoming_gid": case.incoming_gid or "",
                    "affected_songs": case.affected_songs,
                    "suggested_action": case.suggested_action,
                    "reason": case.reason,
                    "decision": decision,
                }
            )


@pytest.mark.unit
class TestGroupingAndEvidence:
    def test_same_name_groups_by_existing_row_and_incoming_id(
        self, tmp_path: Path
    ) -> None:
        tracked = _artist("Alpha Name", deezer_id=101, tier=TrackingTier.TRACKED)
        audit = tmp_path / "audit.jsonl"
        _audit(
            audit,
            "skip_same_name_different_id",
            old_id=tracked.pk,
            old_name="Alpha Name",
            old_deezer_id=101,
            lead_name="Alpha Name",
            lead_deezer_id=202,
            credits=[{"name": "Alpha Name", "deezer_id": 202, "role": "main"}],
            song_id=1,
        )
        _audit(
            audit,
            "skip_same_name_different_id",
            old_id=tracked.pk,
            old_name="Alpha Name",
            old_deezer_id=101,
            lead_name="Alpha Name",
            lead_deezer_id=202,
            credits=[{"name": "Alpha Name", "deezer_id": 202, "role": "main"}],
            song_id=2,
        )
        cases = build_review(audit)
        assert len(cases) == 1
        assert cases[0].kind == "same_name_different_id"
        assert cases[0].affected_songs == 2
        assert cases[0].existing_artist_id == tracked.pk
        assert cases[0].incoming_deezer_id == 202
        assert cases[0].existing_tier == TrackingTier.TRACKED

    def test_ambiguous_groups_by_unlinked_same_name_row(self, tmp_path: Path) -> None:
        _artist("Gamma Name", gid="GAMMAGID000000000001", tier=TrackingTier.TRACKED)
        audit = tmp_path / "audit.jsonl"
        _audit(
            audit,
            "skip_ambiguous_artist",
            old_id=1,
            old_name="Lead Person",
            old_deezer_id=303,
            lead_name="Lead Person",
            lead_deezer_id=303,
            credits=[
                {"name": "Lead Person", "deezer_id": 303, "role": "main"},
                {"name": "Gamma Name", "deezer_id": 404, "role": "featured"},
            ],
            song_id=3,
            ambiguous=["Gamma Name"],
        )
        cases = build_review(audit)
        assert cases
        assert all(c.kind == "ambiguous" for c in cases)
        assert all(c.incoming_deezer_id == 404 for c in cases)
        assert sum(c.affected_songs for c in cases) == 1

    def test_isrc_overlap_uses_db_and_excludes_affected_songs(
        self, tmp_path: Path
    ) -> None:
        tracked = _artist("Delta Name", deezer_id=505, tier=TrackingTier.TRACKED)
        affected = _song("Affected", tracked, isrc="ZZISO0000001", deezer_id=9101)
        evidence = _song("Evidence", tracked, isrc="ZZISO0000001", deezer_id=9102)
        audit = tmp_path / "audit.jsonl"
        _audit(
            audit,
            "skip_same_name_different_id",
            old_id=tracked.pk,
            old_name="Delta Name",
            old_deezer_id=505,
            lead_name="Delta Name",
            lead_deezer_id=606,
            credits=[{"name": "Delta Name", "deezer_id": 606, "role": "main"}],
            song_id=affected.pk,
        )
        case = build_review(audit)[0]
        assert case.isrc_overlap_songs == 1
        assert case.isrc_overlap_example == ["Evidence"]
        assert case.suggested_action == ACTION_MERGE
        assert evidence.pk != affected.pk

    def test_no_evidence_defaults_to_needs_review(self, tmp_path: Path) -> None:
        tracked = _artist("Epsilon Name", deezer_id=707)
        affected = _song("Affected", tracked, isrc="ZZISO0000009", deezer_id=9103)
        audit = tmp_path / "audit.jsonl"
        _audit(
            audit,
            "skip_same_name_different_id",
            old_id=tracked.pk,
            old_name="Epsilon Name",
            old_deezer_id=707,
            lead_name="Epsilon Name",
            lead_deezer_id=808,
            credits=[{"name": "Epsilon Name", "deezer_id": 808, "role": "main"}],
            song_id=affected.pk,
        )
        case = build_review(audit)[0]
        assert case.isrc_overlap_songs == 0
        assert case.suggested_action == ACTION_NEEDS_REVIEW

    def test_tracked_sorted_before_untracked_and_then_by_song_count(
        self, tmp_path: Path
    ) -> None:
        tracked = _artist("Zeta Name", deezer_id=111, tier=TrackingTier.TRACKED)
        untracked = _artist("Eta Name", deezer_id=222)
        audit = tmp_path / "audit.jsonl"
        lines = []
        for artist, incoming, count in ((untracked, 333, 8), (tracked, 444, 1)):
            for i in range(count):
                lines.append(
                    json.dumps(
                        {
                            "song_id": 1000 + len(lines),
                            "name": "Synthetic",
                            "status": "skip_same_name_different_id",
                            "old_primary_id": artist.pk,
                            "old_primary_name": artist.name,
                            "old_primary_deezer_id": artist.deezer_id,
                            "lead_name": artist.name,
                            "lead_deezer_id": incoming,
                            "credits": [
                                {
                                    "name": artist.name,
                                    "deezer_id": incoming,
                                    "role": "main",
                                }
                            ],
                            "ambiguous_credits": [],
                            "evidence_isrcs": [],
                        }
                    )
                )
        audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cases = build_review(audit)
        assert cases[0].existing_artist_id == tracked.pk
        assert cases[0].affected_songs == 1
        assert cases[1].existing_artist_id == untracked.pk
        assert cases[1].affected_songs == 8


@pytest.mark.unit
class TestResolveDryRun:
    def test_dry_run_changes_nothing_and_writes_no_audit(self, tmp_path: Path) -> None:
        existing = _artist("Theta Name", deezer_id=1212)
        incoming = _artist("Theta Name", deezer_id=1313)
        _song("Existing song", existing, isrc="ZZISO0000021", deezer_id=9201)
        case = _case("same_name_different_id", existing.pk, "Theta Name", 1313)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])
        audit = tmp_path / "new-audit.jsonl"
        out = StringIO()

        call_command(
            "resolve_artist_identity",
            str(csv_path),
            stdout=out,
        )

        assert "DRY RUN" in out.getvalue()
        assert not audit.exists()
        assert Artist.objects.filter(pk__in=[existing.pk, incoming.pk]).count() == 2
        existing.refresh_from_db()
        assert existing.tracking_tier == TrackingTier.UNTRACKED
        assert recorded_different_pairs() == {}

    def test_audit_file_without_apply_is_refused(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [])
        with pytest.raises(CommandError, match="only applies with --apply"):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--audit-file",
                str(tmp_path / "a.jsonl"),
            )

    def test_apply_requires_audit_file(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [])
        with pytest.raises(CommandError, match="--audit-file"):
            call_command("resolve_artist_identity", str(csv_path), "--apply")


@pytest.mark.unit
class TestResolveApply:
    def _apply(self, csv_path: Path, audit: Path) -> StringIO:
        out = StringIO()
        with patch.object(resolver.os, "fsync"):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--apply",
                "--audit-file",
                str(audit),
                stdout=out,
            )
        return out

    def test_link_attaches_id_conditionally(self, tmp_path: Path) -> None:
        existing = _artist("Iota Name", deezer_id=None, gid="IOTAGID00000000001")
        case = _case("ambiguous", existing.pk, "Iota Name", 1414)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_LINK)])
        audit = tmp_path / "audit.jsonl"

        out = self._apply(csv_path, audit)

        assert "linked deezer_id=1414" in out.getvalue()
        existing.refresh_from_db()
        assert existing.deezer_id == 1414
        assert audit.stat().st_mode & 0o777 == 0o600

    def test_link_refuses_when_another_row_holds_id(self, tmp_path: Path) -> None:
        existing = _artist("Kappa Name", deezer_id=None, gid="KAPPAGID0000000001")
        holder = _artist("Other Name", deezer_id=1515)
        case = _case("ambiguous", existing.pk, "Kappa Name", 1515)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_LINK)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "refused" in out.getvalue()
        existing.refresh_from_db()
        assert existing.deezer_id is None
        assert holder.deezer_id == 1515

    def test_link_refuses_when_row_already_has_a_different_id(
        self, tmp_path: Path
    ) -> None:
        existing = _artist("Lambda Name", deezer_id=1616)
        case = _case("ambiguous", existing.pk, "Lambda Name", 1717)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_LINK)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "already set" in out.getvalue()
        existing.refresh_from_db()
        assert existing.deezer_id == 1616

    def test_merge_moves_content_and_keeps_higher_tier(self, tmp_path: Path) -> None:
        low = _artist("Mu Name", deezer_id=1818)
        high = _artist(
            "Mu Name",
            deezer_id=1919,
            gid="MUGID00000000000001",
            tier=TrackingTier.TRACKED,
        )
        song = _song("Movable", low, isrc="ZZISO0000031", deezer_id=9301)
        album = Album.objects.create(name="Movable Album", artist=low, deezer_id=77)
        song.album = album
        song.save(update_fields=["album"])
        ContributingArtist.objects.create(song=song, artist=low)
        case = _case("same_name_different_id", low.pk, "Mu Name", 1919)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "merged" in out.getvalue()
        assert not Artist.objects.filter(pk=low.pk).exists()
        high.refresh_from_db()
        song.refresh_from_db()
        album.refresh_from_db()
        assert high.tracking_tier == TrackingTier.TRACKED
        assert high.deezer_id == 1919
        assert song.primary_artist_id == high.pk
        assert album.artist_id == high.pk
        assert not ContributingArtist.objects.filter(artist_id=low.pk).exists()

    def test_merge_refuses_conflicting_deezer_ids_on_ambiguous_pair(
        self, tmp_path: Path
    ) -> None:
        left = _artist("Nu Name", deezer_id=2020)
        right = _artist("Nu Name", deezer_id=2121, tier=TrackingTier.TRACKED)
        case = _case("ambiguous", left.pk, "Nu Name", 2121)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "conflicting deezer_ids" in out.getvalue()
        assert Artist.objects.filter(pk__in=[left.pk, right.pk]).count() == 2

    def test_merge_refuses_conflicting_spotify_ids(self, tmp_path: Path) -> None:
        left = _artist("Omicron Two", deezer_id=3030, gid="OMIGID0000000000001")
        right = _artist(
            "Omicron Two",
            deezer_id=3131,
            gid="OMIGID0000000000002",
            tier=TrackingTier.TRACKED,
        )
        case = _case("same_name_different_id", left.pk, "Omicron Two", 3131)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "conflicting gids" in out.getvalue()
        assert Artist.objects.filter(pk__in=[left.pk, right.pk]).count() == 2

    def test_merge_refuses_missing_incoming_row(self, tmp_path: Path) -> None:
        left = _artist("Xi Name", deezer_id=2222)
        case = _case("same_name_different_id", left.pk, "Xi Name", 2323)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "artist row missing" in out.getvalue()
        assert Artist.objects.filter(pk=left.pk).exists()

    def test_different_records_pair_for_future_runs(self, tmp_path: Path) -> None:
        left = _artist("Omicron Name", deezer_id=2424)
        case = _case("same_name_different_id", left.pk, "Omicron Name", 2525)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, "different")])

        self._apply(csv_path, tmp_path / "audit.jsonl")

        pairs = recorded_different_pairs()
        assert case.case_key in pairs
        assert AppSetting.objects.filter(key=DIFFERENT_SETTING_KEY).exists()

    def test_unknown_decision_is_refused(self, tmp_path: Path) -> None:
        left = _artist("Pi Name", deezer_id=2626)
        case = _case("same_name_different_id", left.pk, "Pi Name", 2727)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, "teleport")])

        out = self._apply(csv_path, tmp_path / "audit.jsonl")

        assert "unknown decision" in out.getvalue()
        left.refresh_from_db()
        assert left.deezer_id == 2626

    def test_apply_audit_refuses_existing_file(self, tmp_path: Path) -> None:
        existing = _artist("Rho Name", deezer_id=2828)
        case = _case("ambiguous", existing.pk, "Rho Name", 2929)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_LINK)])
        audit = tmp_path / "audit.jsonl"
        audit.write_text("existing", encoding="utf-8")
        with pytest.raises(CommandError, match="already exists"):
            self._apply(csv_path, audit)


@pytest.mark.unit
class TestAuditPrecedesWrites:
    def _records(self, audit: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()
        ]

    @staticmethod
    def _apply(csv_path: Path, audit: Path) -> None:
        with patch.object(resolver.os, "fsync"):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--apply",
                "--audit-file",
                str(audit),
                stdout=StringIO(),
            )

    def test_planned_preimage_is_audited_before_apply(self, tmp_path: Path) -> None:
        low = _artist("Sigma Name", deezer_id=3434)
        high = _artist(
            "Sigma Name",
            deezer_id=3535,
            gid="SIGMAGID00000000001",
            tier=TrackingTier.TRACKED,
        )
        song = _song("Movable", low, isrc="ZZISO0000041", deezer_id=9401)
        album = Album.objects.create(name="Movable Album", artist=low, deezer_id=88)
        song.album = album
        song.save(update_fields=["album"])
        ContributingArtist.objects.create(song=song, artist=low)
        case = _case("same_name_different_id", low.pk, "Sigma Name", 3535)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])
        audit = tmp_path / "audit.jsonl"

        with patch.object(resolver.os, "fsync"):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--apply",
                "--audit-file",
                str(audit),
                stdout=StringIO(),
            )

        records = self._records(audit)
        assert [r["record"] for r in records] == ["header", "planned", "decision"]
        pre = records[1]["preimage"]
        assert {a["id"] for a in pre["artists"]} == {low.pk, high.pk}
        assert pre["keeper_id"] == high.pk and pre["other_id"] == low.pk
        assert [s["id"] for s in pre["songs"]] == [song.pk]
        assert [c["artist_id"] for c in pre["contributors"]] == [low.pk]
        assert [a["id"] for a in pre["albums"]] == [album.pk]
        assert pre["keeper_tier"] == TrackingTier.TRACKED
        assert records[2]["result"] == "applied"

    def test_audit_failure_mid_decision_leaves_no_db_writes(
        self, tmp_path: Path
    ) -> None:
        existing = _artist("Tau Name", deezer_id=None, gid="TAUGID0000000000001")
        case = _case("ambiguous", existing.pk, "Tau Name", 3636)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_LINK)])
        audit = tmp_path / "audit.jsonl"
        real = resolver.Command._write_and_sync

        def fail_after_planned(handle: Any, record: dict[str, Any]) -> None:
            real(handle, record)
            if record["record"] == "planned":
                raise OSError("simulated audit device failure")

        with (
            patch.object(resolver.os, "fsync"),
            patch.object(
                resolver.Command, "_write_and_sync", side_effect=fail_after_planned
            ),
            pytest.raises(OSError, match="simulated audit"),
        ):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--apply",
                "--audit-file",
                str(audit),
                stdout=StringIO(),
            )

        existing.refresh_from_db()
        assert existing.deezer_id is None
        records = self._records(audit)
        assert [r["record"] for r in records] == ["header", "planned"]
        assert records[1]["preimage"]["value"] == 3636

    def test_refused_merge_has_no_planned_record_and_no_writes(
        self, tmp_path: Path
    ) -> None:
        left = _artist("Upsilon Name", deezer_id=3737, gid="UPSGID0000000000001")
        right = _artist(
            "Upsilon Name",
            deezer_id=3838,
            gid="UPSGID0000000000002",
            tier=TrackingTier.TRACKED,
        )
        _song("Untouched", left, isrc="ZZISO0000051", deezer_id=9501)
        case = _case("same_name_different_id", left.pk, "Upsilon Name", 3838)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])
        audit = tmp_path / "audit.jsonl"

        self._apply(csv_path, audit)

        assert [r["record"] for r in self._records(audit)] == ["header", "decision"]
        assert Artist.objects.filter(pk__in=[left.pk, right.pk]).count() == 2

    def test_refused_after_partial_writes_rolls_back_everything(
        self, tmp_path: Path
    ) -> None:
        low = _artist("Phi Name", deezer_id=3939)
        high = _artist(
            "Phi Name",
            deezer_id=4040,
            gid="PHIGID0000000000001",
            tier=TrackingTier.TRACKED,
        )
        song = _song("Movable", low, isrc="ZZISO0000061", deezer_id=9601)
        album = Album.objects.create(name="Movable Album", artist=low, deezer_id=99)
        song.album = album
        song.save(update_fields=["album"])
        ContributingArtist.objects.create(song=song, artist=low)
        case = _case("same_name_different_id", low.pk, "Phi Name", 4040)
        csv_path = tmp_path / "review.csv"
        _csv(csv_path, [(case, ACTION_MERGE)])
        audit = tmp_path / "audit.jsonl"
        real_apply = resolver._apply_plan

        def racing_apply(plan: resolver.DecisionPlan) -> str:
            # A concurrent insert arrives after the pre-image was captured.
            Song.objects.create(
                name="Late Racer", primary_artist=plan.other, deezer_id=999999
            )
            return real_apply(plan)

        out = StringIO()
        with (
            patch.object(resolver.os, "fsync"),
            patch.object(resolver, "_apply_plan", side_effect=racing_apply),
        ):
            call_command(
                "resolve_artist_identity",
                str(csv_path),
                "--apply",
                "--audit-file",
                str(audit),
                stdout=out,
            )

        assert "refused: other row still referenced" in out.getvalue()
        assert Artist.objects.filter(pk__in=[low.pk, high.pk]).count() == 2
        song.refresh_from_db()
        album.refresh_from_db()
        assert song.primary_artist_id == low.pk
        assert album.artist_id == low.pk
        assert ContributingArtist.objects.filter(artist=low).count() == 1
        assert not Song.objects.filter(name="Late Racer").exists()
        assert [r["record"] for r in self._records(audit)] == [
            "header",
            "planned",
            "decision",
        ]
