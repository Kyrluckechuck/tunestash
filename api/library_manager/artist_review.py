"""Read-only review of artist identity cases reported by the credits backfill.

The backfill deliberately leaves two classes of songs untouched:
``skip_ambiguous_artist`` (an unlinked same-name Artist row could not be
verified from the database) and ``skip_same_name_different_id`` (the current
primary carries another Deezer id for the same name). This module streams the
backfill's JSONL audit, groups the reported pairs, and adds evidence gathered
**only from the database** — never from the provider and never from files.

Memory is bounded: the audit is read one line at a time, and each group keeps
only counters plus a small, fixed number of example song names and ISRCs.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, TextIO

from django.db.models import Q

from library_manager.artist_credits import normalize_artist_name
from library_manager.models import AppSetting, Artist, Song

KIND_AMBIGUOUS = "ambiguous"
KIND_SAME_NAME = "same_name_different_id"
KINDS = (KIND_AMBIGUOUS, KIND_SAME_NAME)

STATUS_AMBIGUOUS = "skip_ambiguous_artist"
STATUS_SAME_NAME = "skip_same_name_different_id"

ACTION_LINK = "link"
ACTION_MERGE = "merge"
ACTION_DIFFERENT = "different"
ACTION_NEEDS_REVIEW = "needs review"

MAX_EXAMPLES = 5
MAX_ISRCS = 25
MAX_SONG_IDS = 2000
MAX_AFFECTED_ISRCS = 50

CSV_COLUMNS = [
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

_LOG_AMBIGUOUS = re.compile(
    r"ambiguous_artist_identity:\s+(?P<name>.*?)\s+\((?P<field>\w+)=(?P<value>[^)]*)\)"
)
_LOG_SAME_NAME = re.compile(
    r"same_name_different_id:\s+(?P<name>.*?)\s+\(deezer_id=(?P<value>\d+)\)"
)


def _clean_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.strip("'\"")


def _isrcs(*values: Any) -> Iterator[str]:
    """Yield normalized ISRCs from a scalar or nested list of values."""
    for value in values:
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from _isrcs(item)
        elif isinstance(value, str) and value.strip():
            yield value.strip().upper()


@dataclass
class IdentityCase:
    """One (existing Artist row, provider artist) pair reported by the backfill."""

    kind: str
    existing_artist_id: int
    existing_name: str = ""
    existing_gid: Optional[str] = None
    existing_deezer_id: Optional[int] = None
    existing_tier: int = 0
    incoming_name: str = ""
    incoming_deezer_id: Optional[int] = None
    incoming_gid: Optional[str] = None
    provider_field: str = "deezer_id"
    affected_songs: int = 0
    song_ids: set[int] = field(default_factory=set)
    example_songs: list[str] = field(default_factory=list)
    isrcs: set[str] = field(default_factory=set)
    isrc_overlap_songs: int = 0
    isrc_overlap_example: list[str] = field(default_factory=list)
    suggested_action: str = ACTION_NEEDS_REVIEW
    reason: str = "no independent ISRC evidence"

    @property
    def case_key(self) -> str:
        incoming = (
            f"deezer:{self.incoming_deezer_id}"
            if self.incoming_deezer_id is not None
            else f"gid:{self.incoming_gid or ''}"
        )
        return (
            f"{self.kind}|{self.existing_artist_id}|{incoming}|"
            f"{normalize_artist_name(self.incoming_name)}"
        )

    @property
    def tracked(self) -> bool:
        return self.existing_tier >= 1

    def add_song(self, song_id: int, name: str, isrcs: Iterable[str]) -> None:
        self.affected_songs += 1
        if song_id and len(self.song_ids) < MAX_SONG_IDS:
            self.song_ids.add(song_id)
        if len(self.example_songs) < MAX_EXAMPLES and name:
            self.example_songs.append(name)
        for isrc in isrcs:
            if len(self.isrcs) < MAX_ISRCS:
                self.isrcs.add(isrc)


def _incoming_identity(
    plan: dict[str, Any], kind: str
) -> tuple[str, Optional[int], Optional[str], str]:
    """Return (name, deezer_id, gid, provider_field) for the other artist."""
    if kind == KIND_SAME_NAME:
        return (
            _clean_name(plan.get("lead_name")),
            plan.get("lead_deezer_id"),
            None,
            "deezer_id",
        )
    ambiguous = _clean_name(
        (plan.get("ambiguous_credits") or [None])[0]
        if plan.get("ambiguous_credits")
        else plan.get("lead_name")
    )
    for credit in plan.get("credits") or []:
        if _clean_name(credit.get("name")) == ambiguous:
            gid = credit.get("gid")
            deezer_id = credit.get("deezer_id")
            return (
                ambiguous,
                deezer_id if isinstance(deezer_id, int) else None,
                gid if isinstance(gid, str) and gid else None,
                "deezer_id" if deezer_id else "gid",
            )
    return ambiguous, None, None, "deezer_id"


def _candidate_existing_ids(
    name: str, provider_field: str, provider_value: Any
) -> list[int]:
    """Artist rows an ambiguous credit could have been attached to by name."""
    if not name:
        return []
    queryset = Artist.objects.filter(name__iexact=name)
    if provider_field == "deezer_id":
        queryset = queryset.filter(deezer_id__isnull=True)
        if provider_value is not None:
            queryset = queryset.exclude(deezer_id=provider_value)
    else:
        queryset = queryset.filter(gid__isnull=True)
        if provider_value:
            queryset = queryset.exclude(gid=provider_value)
    return list(queryset.order_by("pk").values_list("pk", flat=True)[:5])


def iter_audit_plans(path: Path) -> Iterator[dict[str, Any]]:
    """Stream every JSON object record (skip headers, cursors and tail records)."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _log_case(name: str, deezer_id: Optional[int], kind: str) -> IdentityCase:
    return IdentityCase(
        kind=kind,
        existing_artist_id=0,
        incoming_name=name,
        incoming_deezer_id=deezer_id,
        provider_field="deezer_id",
    )


def collect_cases(
    audit_path: Path, log_path: Optional[Path] = None
) -> dict[str, IdentityCase]:
    """Group audit (and optionally log) reports into bounded identity cases."""
    cases: dict[str, IdentityCase] = {}

    def add(
        kind: str,
        existing_id: int,
        incoming_name: str,
        incoming_deezer_id: Optional[int],
        incoming_gid: Optional[str],
        provider_field: str,
        song_id: int,
        song_name: str,
        isrcs: Iterable[str],
    ) -> None:
        incoming_name = _clean_name(incoming_name)
        provisional = IdentityCase(
            kind=kind,
            existing_artist_id=existing_id,
            incoming_name=incoming_name,
            incoming_deezer_id=incoming_deezer_id,
            incoming_gid=incoming_gid,
            provider_field=provider_field,
        )
        case = cases.setdefault(provisional.case_key, provisional)
        case.add_song(song_id, song_name, isrcs)

    for record in iter_audit_plans(audit_path):
        status = record.get("status")
        if status == STATUS_SAME_NAME:
            kind = KIND_SAME_NAME
        elif status == STATUS_AMBIGUOUS:
            kind = KIND_AMBIGUOUS
        else:
            continue
        existing_id = record.get("old_primary_id")
        if not isinstance(existing_id, int) or not existing_id:
            continue
        incoming_name, deezer_id, gid, field_name = _incoming_identity(record, kind)
        song_id = record.get("song_id") or 0
        isrcs = list(_isrcs(record.get("evidence_isrcs")))
        if kind == KIND_SAME_NAME:
            add(
                kind,
                existing_id,
                incoming_name,
                deezer_id,
                gid,
                field_name,
                song_id,
                _clean_name(record.get("name")),
                isrcs,
            )
        else:
            candidates = _candidate_existing_ids(incoming_name, field_name, deezer_id)
            for candidate_id in candidates or [existing_id]:
                add(
                    kind,
                    candidate_id,
                    incoming_name,
                    deezer_id,
                    gid,
                    field_name,
                    song_id,
                    _clean_name(record.get("name")),
                    isrcs,
                )

    if log_path is not None and log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "ambiguous_artist_identity:" in line:
                    match = _LOG_AMBIGUOUS.search(line)
                    if not match:
                        continue
                    name = _clean_name(match.group("name"))
                    value = match.group("value").strip()
                    deezer_id = int(value) if value.isdigit() else None
                    for candidate in _candidate_existing_ids(
                        name, "deezer_id", deezer_id
                    ):
                        seed = _log_case(name, deezer_id, KIND_AMBIGUOUS)
                        seed.existing_artist_id = candidate
                        cases.setdefault(seed.case_key, seed)
                elif "same_name_different_id:" in line:
                    match = _LOG_SAME_NAME.search(line)
                    if not match:
                        continue
                    name = _clean_name(match.group("name"))
                    deezer_id = int(match.group("value"))
                    rows = (
                        Artist.objects.filter(name__iexact=name)
                        .exclude(deezer_id=deezer_id)
                        .values_list("pk", flat=True)[:5]
                    )
                    for candidate in rows:
                        seed = _log_case(name, deezer_id, KIND_SAME_NAME)
                        seed.existing_artist_id = candidate
                        cases.setdefault(seed.case_key, seed)
    return cases


def _overlap_query(case: IdentityCase):
    """Songs on the existing row, excluding the affected ones, sharing an ISRC."""
    base = Song.objects.filter(
        Q(primary_artist_id=case.existing_artist_id)
        | Q(contributingartist__artist_id=case.existing_artist_id)
    ).exclude(pk__in=case.song_ids)
    if not case.isrcs:
        return base.none()
    isrc_list = sorted(case.isrcs)
    return base.filter(
        Q(isrc__in=isrc_list) | Q(alternate_isrcs__overlap=isrc_list)
    ).distinct()


def enrich_cases(cases: dict[str, IdentityCase]) -> list[IdentityCase]:
    """Add DB-only ISRC evidence, artist metadata and a suggestion; sort."""
    rows: list[IdentityCase] = []
    artist_ids = {c.existing_artist_id for c in cases.values() if c.existing_artist_id}
    artists = {
        a["pk"]: a
        for a in Artist.objects.filter(pk__in=artist_ids).values(
            "pk", "name", "gid", "deezer_id", "tracking_tier"
        )
    }
    for case in cases.values():
        artist = artists.get(case.existing_artist_id)
        if artist is None:
            continue
        case.existing_name = artist["name"]
        case.existing_gid = artist["gid"]
        case.existing_deezer_id = artist["deezer_id"]
        case.existing_tier = artist["tracking_tier"] or 0

        # The same_name audit records do not carry evidence_isrcs (the backfill
        # sets them after that check), so read the affected tracks' ISRCs from
        # the database. The provider is never consulted here.
        if case.song_ids:
            for isrc, alternate in Song.objects.filter(
                pk__in=list(case.song_ids)[:MAX_AFFECTED_ISRCS]
            ).values_list("isrc", "alternate_isrcs"):
                for value in _isrcs(isrc, alternate):
                    if len(case.isrcs) < MAX_ISRCS:
                        case.isrcs.add(value)

        overlap = _overlap_query(case)
        case.isrc_overlap_songs = overlap.count()
        for name in overlap.values_list("name", flat=True)[:MAX_EXAMPLES]:
            case.isrc_overlap_example.append(name)

        if case.isrc_overlap_songs:
            sample = ", ".join(case.isrc_overlap_example[:2])
            if case.kind == KIND_SAME_NAME:
                case.suggested_action = ACTION_MERGE
                case.reason = (
                    f"{case.isrc_overlap_songs} other song(s) on this artist row "
                    f"share an ISRC with the affected tracks (e.g. {sample}); "
                    "likely two Deezer pages for one artist"
                )
            else:
                case.suggested_action = ACTION_LINK
                case.reason = (
                    f"{case.isrc_overlap_songs} other song(s) on this row share an "
                    f"ISRC with the affected tracks (e.g. {sample}); independent "
                    "evidence the provider id belongs here"
                )
        else:
            case.suggested_action = ACTION_NEEDS_REVIEW
            case.reason = (
                "no independent song on this row shares an ISRC with the "
                "affected tracks; cannot safely link or merge"
            )
        if case.tracked:
            case.reason += "; existing row is tracked"
        rows.append(case)

    rows.sort(
        key=lambda c: (
            not c.tracked,
            -c.affected_songs,
            c.kind,
            c.case_key,
        )
    )
    return rows


def to_csv_rows(cases: Iterable[IdentityCase]) -> Iterator[dict[str, Any]]:
    for case in cases:
        yield {
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
            "isrc_overlap_songs": case.isrc_overlap_songs,
            "isrc_overlap_example": " | ".join(case.isrc_overlap_example),
            "example_songs": " | ".join(case.example_songs),
            "suggested_action": case.suggested_action,
            "reason": case.reason,
            "decision": "",
        }


def write_review_csv(
    cases: Iterable[IdentityCase], target: TextIO, *, with_decision: bool = True
) -> None:
    columns = (
        CSV_COLUMNS if with_decision else [c for c in CSV_COLUMNS if c != "decision"]
    )
    writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in to_csv_rows(cases):
        writer.writerow({k: v for k, v in row.items() if k in columns})


def build_review(
    audit_path: Path, log_path: Optional[Path] = None
) -> list[IdentityCase]:
    """Full read-only pipeline: parse, group, enrich, sort."""
    return enrich_cases(collect_cases(audit_path, log_path))


# Operator-confirmed "different artist" pairs live in one AppSetting row. A
# JSON object keyed by case key keeps this additive: no schema change and no
# backfill code needs to be touched to record a reviewed decision.
DIFFERENT_SETTING_KEY = "artist_identity_different_pairs"


def recorded_different_pairs() -> dict[str, dict[str, Any]]:
    """Pairs already confirmed as two different artists."""
    row = AppSetting.objects.filter(key=DIFFERENT_SETTING_KEY).first()
    if row is None or not isinstance(row.value, dict):
        return {}
    return {str(k): v for k, v in row.value.items() if isinstance(v, dict)}


def record_different_pair(case: IdentityCase) -> None:
    """Remember a reviewed pair so it can be excluded from future reports."""
    row, _ = AppSetting.objects.get_or_create(
        key=DIFFERENT_SETTING_KEY,
        defaults={"category": "artist_identity", "value": {}},
    )
    value = dict(row.value) if isinstance(row.value, dict) else {}
    value[case.case_key] = {
        "kind": case.kind,
        "existing_artist_id": case.existing_artist_id,
        "incoming_name": case.incoming_name,
        "incoming_deezer_id": case.incoming_deezer_id,
        "incoming_gid": case.incoming_gid,
    }
    AppSetting.objects.filter(pk=row.pk).update(value=value)
