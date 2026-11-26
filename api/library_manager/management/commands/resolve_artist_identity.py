"""Apply operator decisions from a review_artist_identity CSV.

Dry run by default. ``--apply`` requires a fresh audit file (mode 0600). For
every decision that can write, the command gathers the full pre-image inside a
transaction with the artist rows locked in ascending id order, writes and
fsyncs a ``planned`` audit record **before the first DB write**, then applies
the decision in that same transaction. A refusal or any error rolls that
decision back completely; the outcome is recorded after commit.

Decisions:

* ``link`` — attach the provider id to the existing row, only while that field
  is still NULL and no other row holds the id.
* ``merge`` — move songs, contributor links, albums and tracking onto the
  higher-tier row; delete the other row only when nothing references it. Two
  different Deezer ids are allowed for reviewed ``same_name_different_id``
  pairs (duplicate Deezer pages); conflicting Spotify ids or any conflict on
  an ``ambiguous`` pair is refused.
* ``different`` — record the pair in an additive AppSetting so future review
  runs can stop reporting it.
* ``skip`` / blank — leave the pair alone.

No file outside the audit is ever written, and no provider API is called.
"""

from __future__ import annotations

import csv
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from library_manager.artist_review import (
    ACTION_DIFFERENT,
    ACTION_LINK,
    ACTION_MERGE,
    KIND_SAME_NAME,
    IdentityCase,
    record_different_pair,
)
from library_manager.models import Album, AppSetting, Artist, ContributingArtist, Song

DECISION_VALUES = (ACTION_LINK, ACTION_MERGE, ACTION_DIFFERENT, "skip")
REQUIRED_COLUMNS = {
    "case_key",
    "kind",
    "existing_artist_id",
    "incoming_name",
    "incoming_deezer_id",
    "incoming_gid",
    "suggested_action",
    "decision",
}
ID_FIELDS = ("deezer_id", "gid", "youtube_id")


class Refused(Exception):
    """A decision failed a pre-write or post-write safety check."""


@dataclass
class Outcome:
    decision: str
    result: str
    detail: str = ""


@dataclass
class DecisionPlan:
    """Everything needed to apply one decision after its audit is durable."""

    decision: str
    case: IdentityCase
    preimage: dict[str, Any]
    existing: Optional[Artist] = None
    incoming: Optional[Artist] = None
    keeper: Optional[Artist] = None
    other: Optional[Artist] = None
    field_name: Optional[str] = None
    value: Any = None
    song_ids: list[int] = field(default_factory=list)
    contributor_ids: list[int] = field(default_factory=list)
    albums: list[dict[str, Any]] = field(default_factory=list)
    clash_albums: dict[int, int] = field(default_factory=dict)


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _artist_snapshot(artist: Artist) -> dict[str, Any]:
    """Full reviewable pre-image of an artist row."""
    return {
        "id": artist.pk,
        "name": artist.name,
        "tracking_tier": artist.tracking_tier,
        **{name: getattr(artist, name) for name in ID_FIELDS},
        "last_synced_at": artist.last_synced_at,
        "last_downloaded_at": artist.last_downloaded_at,
        "deezer_migration_status": artist.deezer_migration_status,
    }


def _locked_artists(pks: set[int]) -> dict[int, Artist]:
    """Lock all involved artist rows in ascending id order (no deadlocks)."""
    if not pks:
        return {}
    return {
        a.pk: a
        for a in Artist.objects.select_for_update().filter(pk__in=pks).order_by("pk")
    }


def _find_incoming(case: IdentityCase) -> Optional[Artist]:
    if case.incoming_deezer_id is not None:
        return Artist.objects.filter(deezer_id=case.incoming_deezer_id).first()
    if case.incoming_gid:
        return Artist.objects.filter(gid=case.incoming_gid).first()
    return None


def _carry_metadata(source: Artist, keeper: Artist) -> None:
    """Carry non-conflicting provider ids and tracking onto the keeper."""
    updates: list[str] = []
    for name in ID_FIELDS:
        if getattr(keeper, name) is None and getattr(source, name) is not None:
            setattr(keeper, name, getattr(source, name))
            updates.append(name)
    if source.tracking_tier > keeper.tracking_tier:
        keeper.tracking_tier = source.tracking_tier
        updates.append("tracking_tier")
    for name in ("last_synced_at", "last_downloaded_at"):
        source_value, keeper_value = getattr(source, name), getattr(keeper, name)
        if source_value and (not keeper_value or source_value > keeper_value):
            setattr(keeper, name, source_value)
            updates.append(name)
    if updates:
        keeper.save(update_fields=updates)


def _prepare_link(
    case: IdentityCase, decision: str
) -> tuple[Optional[DecisionPlan], Optional[Outcome]]:
    """Validate a link and capture its pre-image without writing anything."""
    field_name = "deezer_id" if case.incoming_deezer_id is not None else "gid"
    value = case.incoming_deezer_id if field_name == "deezer_id" else case.incoming_gid
    if value is None:
        return None, Outcome(decision, "refused", "refused: no provider id")
    holder = Artist.objects.filter(**{field_name: value}).first()
    rows = _locked_artists({case.existing_artist_id, *([holder.pk] if holder else [])})
    row = rows.get(case.existing_artist_id)
    if row is None:
        return None, Outcome(decision, "refused", "refused: artist row missing")
    current = getattr(row, field_name)
    if current is not None:
        detail = (
            "already linked"
            if current == value
            else f"refused: {field_name} already set to {current}"
        )
        return None, Outcome(
            decision,
            "refused" if detail.startswith("refused") else "already_linked",
            detail,
        )
    if holder is not None and holder.pk != row.pk:
        return None, Outcome(
            decision,
            "refused",
            f"refused: {field_name}={value} held by another row",
        )
    preimage = {
        "artists": [
            _artist_snapshot(row),
            *([_artist_snapshot(holder)] if holder else []),
        ],
        "field": field_name,
        "value": value,
    }
    return (
        DecisionPlan(
            decision=decision,
            case=case,
            preimage=preimage,
            existing=row,
            field_name=field_name,
            value=value,
        ),
        None,
    )


def _prepare_merge(
    case: IdentityCase, decision: str
) -> tuple[Optional[DecisionPlan], Optional[Outcome]]:
    """Validate every merge refusal condition and capture the entire pre-image."""
    incoming = _find_incoming(case)
    pks = {case.existing_artist_id}
    if incoming is not None:
        pks.add(incoming.pk)
    rows = _locked_artists(pks)
    existing = rows.get(case.existing_artist_id)
    if existing is None or incoming is None:
        return None, Outcome(decision, "refused", "refused: artist row missing")
    if existing.pk == incoming.pk:
        return None, Outcome(decision, "refused", "refused: same row")
    for name in ("deezer_id", "gid"):
        left, right = getattr(existing, name), getattr(incoming, name)
        if left is None or right is None or left == right:
            continue
        if name == "deezer_id" and case.kind == KIND_SAME_NAME:
            # Reviewed duplicate Deezer pages: the keeper keeps its own id.
            continue
        return None, Outcome(
            decision, "refused", f"refused: conflicting {name}s ({left} vs {right})"
        )

    keeper, other = (
        (existing, incoming)
        if existing.tracking_tier >= incoming.tracking_tier
        else (incoming, existing)
    )
    songs = list(
        Song.objects.filter(primary_artist=other).values(
            "id", "name", "primary_artist_id", "album_id", "isrc", "deezer_id"
        )
    )
    contributors = list(
        ContributingArtist.objects.filter(artist=other).values(
            "id", "song_id", "artist_id"
        )
    )
    albums = list(
        Album.objects.filter(artist=other).values(
            "id", "name", "artist_id", "deezer_id", "spotify_gid", "youtube_id"
        )
    )
    if (
        Song.objects.filter(primary_artist=other).count() != len(songs)
        or ContributingArtist.objects.filter(artist=other).count() != len(contributors)
        or Album.objects.filter(artist=other).count() != len(albums)
    ):
        return None, Outcome(
            decision, "refused", "refused: references changed concurrently"
        )
    clash_albums: dict[int, int] = {}
    for album in albums:
        for name in ("deezer_id", "spotify_gid", "youtube_id"):
            value = album[name]
            if value is None:
                continue
            clash = (
                Album.objects.filter(artist=keeper, **{name: value})
                .exclude(pk=album["id"])
                .values_list("pk", flat=True)
                .first()
            )
            if clash is not None:
                clash_albums[album["id"]] = clash
                break
    preimage = {
        "artists": [_artist_snapshot(existing), _artist_snapshot(incoming)],
        "keeper_id": keeper.pk,
        "other_id": other.pk,
        "keeper_tier": keeper.tracking_tier,
        "other_tier": other.tracking_tier,
        "songs": songs,
        "contributors": contributors,
        "albums": albums,
        "clash_albums": clash_albums,
    }
    return (
        DecisionPlan(
            decision=decision,
            case=case,
            preimage=preimage,
            existing=existing,
            incoming=incoming,
            keeper=keeper,
            other=other,
            song_ids=[s["id"] for s in songs],
            contributor_ids=[c["id"] for c in contributors],
            albums=albums,
            clash_albums=clash_albums,
        ),
        None,
    )


def _prepare_different(case: IdentityCase, decision: str) -> DecisionPlan:
    """Capture both artist rows and the current settings value before writing."""
    incoming = _find_incoming(case)
    pks = {case.existing_artist_id}
    if incoming is not None:
        pks.add(incoming.pk)
    rows = _locked_artists(pks)
    existing = rows.get(case.existing_artist_id)
    setting = AppSetting.objects.filter(key="artist_identity_different_pairs").first()
    preimage = {
        "artists": [
            *([_artist_snapshot(existing)] if existing else []),
            *([_artist_snapshot(incoming)] if incoming else []),
        ],
        "setting_value": setting.value if setting else None,
    }
    return DecisionPlan(
        decision=decision,
        case=case,
        preimage=preimage,
        existing=existing,
        incoming=incoming,
    )


def _apply_plan(plan: DecisionPlan) -> str:
    """Perform writes for a previously audited plan; raise Refused on a guard."""
    if plan.decision == ACTION_DIFFERENT:
        record_different_pair(plan.case)
        return "recorded as different"

    if plan.decision == ACTION_LINK:
        row, name, value = plan.existing, plan.field_name, plan.value
        if row is None or name is None:
            raise Refused("refused: invalid link plan")
        try:
            updated = Artist.objects.filter(
                pk=row.pk, **{f"{name}__isnull": True}
            ).update(**{name: value})
        except IntegrityError as exc:
            raise Refused(f"refused: {name}={value} changed concurrently") from exc
        if not updated:
            raise Refused(f"refused: {name}={value} changed concurrently")
        return f"linked {name}={value}"

    keeper, other = plan.keeper, plan.other
    if keeper is None or other is None:
        raise Refused("refused: invalid merge plan")
    Song.objects.filter(pk__in=plan.song_ids).update(primary_artist=keeper)
    for contributor_id in plan.contributor_ids:
        link = ContributingArtist.objects.filter(pk=contributor_id).first()
        if link is None:
            continue
        if ContributingArtist.objects.filter(
            song_id=link.song_id, artist=keeper
        ).exists():
            link.delete()
        else:
            ContributingArtist.objects.filter(pk=contributor_id).update(artist=keeper)
    for album in plan.albums:
        clash_id = plan.clash_albums.get(album["id"])
        if clash_id is not None:
            Song.objects.filter(album_id=album["id"]).update(album_id=clash_id)
            Album.objects.filter(pk=album["id"]).delete()
        else:
            Album.objects.filter(pk=album["id"]).update(artist=keeper)

    # A concurrent writer may have added a reference after the pre-image was
    # captured; refuse rather than cascade-delete that data.
    remaining = (
        Song.objects.filter(primary_artist=other).exists()
        or ContributingArtist.objects.filter(artist=other).exists()
        or Album.objects.filter(artist=other).exists()
    )
    if remaining:
        raise Refused("refused: other row still referenced")
    _carry_metadata(other, keeper)
    other_pk = other.pk
    keeper_pk = keeper.pk
    other.delete()
    return f"merged {other_pk} into {keeper_pk}"


def _case_from_row(row: dict[str, Any]) -> IdentityCase:
    return IdentityCase(
        kind=str(row.get("kind") or ""),
        existing_artist_id=_int(row.get("existing_artist_id")) or 0,
        existing_name=str(row.get("existing_artist_name") or ""),
        incoming_name=str(row.get("incoming_name") or ""),
        incoming_deezer_id=_int(row.get("incoming_deezer_id")),
        incoming_gid=str(row.get("incoming_gid") or "") or None,
    )


class Command(BaseCommand):
    help = "Apply reviewed artist identity decisions from a CSV (dry run by default)"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("review_csv", help="CSV produced by review_artist_identity")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--audit-file", help="New JSONL audit file, required with --apply"
        )

    @staticmethod
    def _write_and_sync(handle: Any, record: dict[str, Any]) -> None:
        handle.write(json.dumps(record, cls=DjangoJSONEncoder) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    def handle(self, *args: Any, **options: Any) -> None:
        apply = bool(options["apply"])
        audit_file = options["audit_file"]
        if apply and not audit_file:
            raise CommandError("--apply requires --audit-file")
        if not apply and audit_file:
            raise CommandError("--audit-file only applies with --apply")

        path = Path(options["review_csv"])
        if not path.exists():
            raise CommandError(f"review CSV not found: {path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"review CSV missing columns: {sorted(missing)}")
            rows = list(reader)

        audit_handle = None
        if apply:
            audit_path = Path(audit_file)
            if audit_path.exists():
                raise CommandError(f"audit file already exists: {audit_path}")
            fd = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            audit_handle = os.fdopen(fd, "w", encoding="utf-8")
            os.chmod(audit_path, stat.S_IRUSR | stat.S_IWUSR)

        self.stdout.write(
            "APPLY" if apply else "DRY RUN — no changes made, no audit file written"
        )
        counts: dict[str, int] = {}
        try:
            if audit_handle is not None:
                self._write_and_sync(
                    audit_handle,
                    {
                        "record": "header",
                        "command": "resolve_artist_identity",
                        "review_csv": str(path),
                    },
                )
            for row in rows:
                decision = str(row.get("decision") or "").strip().lower()
                case = _case_from_row(row)
                if not decision or decision == "skip":
                    outcome = Outcome("skip", "skipped")
                elif decision not in DECISION_VALUES:
                    outcome = Outcome(
                        decision, f"refused: unknown decision {decision!r}"
                    )
                elif not case.existing_artist_id:
                    outcome = Outcome(decision, "refused", "refused: missing artist id")
                elif not apply:
                    outcome = Outcome(decision, "would apply")
                else:
                    outcome = self._apply_with_audit(audit_handle, case, decision)
                counts[outcome.result] = counts.get(outcome.result, 0) + 1
                self.stdout.write(
                    f"  {case.case_key or case.existing_artist_id}: "
                    f"{outcome.decision or '(blank)'} -> {outcome.result}"
                    + (f" ({outcome.detail})" if outcome.detail else "")
                )
                if audit_handle is not None:
                    self._write_and_sync(
                        audit_handle,
                        {
                            "record": "decision",
                            "case_key": case.case_key,
                            "decision": decision,
                            "result": outcome.result,
                            "detail": outcome.detail,
                        },
                    )
        finally:
            if audit_handle is not None:
                audit_handle.close()

        self.stdout.write("summary:")
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")

    @staticmethod
    def _apply_with_audit(
        audit_handle: Any, case: IdentityCase, decision: str
    ) -> Outcome:
        """Plan, audit, and apply one decision atomically.

        The audit write is deliberately outside the guarded apply block: a
        failure there must propagate (and roll back the transaction) rather
        than be reported as a normal refusal.
        """
        with transaction.atomic():
            if decision == ACTION_LINK:
                plan, refusal = _prepare_link(case, decision)
            elif decision == ACTION_MERGE:
                plan, refusal = _prepare_merge(case, decision)
            else:
                plan = _prepare_different(case, decision)
                refusal = None
            if refusal is not None:
                return refusal
            if plan is None or audit_handle is None:
                raise CommandError("internal error: missing plan or audit handle")
            # Durability gate: the full pre-image is on disk before any write.
            Command._write_and_sync(
                audit_handle,
                {
                    "record": "planned",
                    "case_key": case.case_key,
                    "decision": decision,
                    "preimage": plan.preimage,
                },
            )
            try:
                detail = _apply_plan(plan)
            except Refused as exc:
                transaction.set_rollback(True)
                return Outcome(decision, "refused", str(exc))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                transaction.set_rollback(True)
                return Outcome(
                    decision, "refused", f"refused: error {type(exc).__name__}: {exc}"
                )
        return Outcome(decision, "applied", detail)
