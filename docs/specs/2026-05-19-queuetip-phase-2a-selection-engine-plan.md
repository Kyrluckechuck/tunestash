# Queuetip Phase 2A — Selection Engine + m3u Export

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Queuetip's first end-to-end usable product — the deterministic, seeded selection engine plus m3u export. After Phase 2A, friends can create a playlist, contribute songs, vote, and download a tracklist that's playable in any local m3u-capable player.

**Architecture:** Pure-Python `SelectionEngine` (deterministic given inputs + seed), `ExportService` orchestrating filter→curve→roll→floor→ceiling→shuffle, `ExportSnapshot`/`ExportSnapshotTrack` models for immutable persisted results, a pure `render_m3u(snapshot)` function, and a session-authed `/exports/{id}.m3u` download endpoint.

**Tech Stack:** Django 5.1+, Strawberry GraphQL, FastAPI, pytest. No new external deps.

**Program spec:** `2026-05-19-queuetip-collaborative-playlist-design.md` (Selection Engine section is the canonical algorithm reference).

---

## Design Summary (this section is the spec; the rest is the plan)

### Curve

Piecewise-linear over `net = Σ vote values`, with per-playlist knobs (defaults in parentheses):

| Condition | Probability |
|---|---|
| `net ≥ t_high` (+3) | `1.0` — guaranteed |
| `net ≥ 0` | `base + (1 − base) × net / t_high` |
| `net ≥ −t_low` (−3) | `base + (p_floor − base) × (−net) / t_low` |
| `net < −t_low` | `p_floor` (0.15) |

`base = 0.85`. Piecewise-linear (not sigmoid) so `1.0` and `p_floor` are exact, hittable values. At `net = 0`, `p = base` exactly.

### Personal filters (v1)

One filter only in v1: `excludeMyDownvotes: bool = false`. Spec leaves room for more; the structure must be extensible (a TypedDict or `@strawberry.input` with future fields).

### Materialization

1. Apply personal filters → eligible set.
2. Compute `p` for each eligible song.
3. **Roll** with seeded `random.Random(seed)`: include each song with prob `p`. `p == 1.0` always in.
4. **Floor:** if `count < min_size`, top up from highest-`p` excluded songs (ties broken by ascending song id for determinism). Reason = `topped_up`.
5. **Ceiling:** if `max_size` set and `count > max_size`, drop lowest-`p` included songs (ties broken by descending song id), but NEVER drop `p == 1.0` (guaranteed).
6. **Edge:** if guaranteed alone exceed `max_size`, seeded weighted draw among guaranteed; flag `warning_message` on the snapshot.
7. **Shuffle** the final set with the same seeded RNG.
8. Persist snapshot + tracks (with `inclusion_reason` ∈ {`guaranteed`, `rolled_in`, `topped_up`} and `roll_probability`).

`rng_seed` is generated at materialization time (`secrets.randbits(63)`) and stored. Re-running export with the same seed reproduces the snapshot identically; "re-shuffle" creates a NEW snapshot with a fresh seed.

### m3u

Extended m3u (`#EXTM3U` header + `#EXTINF:duration,Artist - Title` per track) with the LOCAL file path on the line after `#EXTINF`. **Skip songs without a downloaded local file** (per program spec). Add a header comment with the playlist + snapshot id for traceability.

Example:
```
#EXTM3U
# Queuetip export — playlist "Friday Mix" — snapshot 42
#EXTINF:243,Daft Punk - Get Lucky
/mnt/music_spotify/Daft Punk/Random Access Memories/Get Lucky.mp3
#EXTINF:198,The Weeknd - Starboy
/mnt/music_spotify/The Weeknd/Starboy/Starboy.mp3
```

`Song` model exposes the on-disk path — Phase 1C confirmed the title attribute is `Song.name`; verify the path attribute is `file_path` (or whatever the model calls it) during Task 1. Duration may also need verification — could be `length`, `duration`, `duration_ms`. Skip per-song values that are missing rather than crashing.

### GraphQL surface (Phase 2A additions)

Queries:
- `export(id: ID!) → ExportSnapshotType` — member-only.
- `myPlaylistExports(playlistId: ID!) → list[ExportSnapshotType]` — member-only, newest first.

Mutations:
- `createExport(playlistId: ID!, options: ExportOptionsInput) → ExportSnapshotType` — member-only.

Input:
```graphql
input ExportOptionsInput {
  excludeMyDownvotes: Boolean = false
}
```

Types:
```graphql
type ExportSnapshotType {
  id: ID!
  playlist: PlaylistType!     # reuse 1B's type
  requestedBy: AccountType!
  createdAt: DateTime!
  parameters: String!          # JSON-stringified, opaque to clients
  rngSeed: String!             # int rendered as string for JSON safety
  warningMessage: String!
  tracks: [ExportSnapshotTrackType!]!
  m3uUrl: String!              # convenience — points at the REST download
}

type ExportSnapshotTrackType {
  id: ID!
  song: SongRef!               # reuse 1C's SongRef
  position: Int!
  inclusionReason: String!
  rollProbability: Float!
}
```

### Download route

`GET /exports/{snapshot_id}.m3u` on the public ASGI app — session cookie required, must be a member of the snapshot's playlist; returns `Content-Type: audio/x-mpegurl` with the rendered m3u as the body. 404 if missing, 403 if not a member.

### Models

`ExportSnapshot`:
- `playlist` FK Playlist CASCADE
- `requested_by` FK Account PROTECT (attribution survives leaving)
- `created_at`
- `parameters` JSONField — the export options
- `rng_seed` BigIntegerField
- `warning_message` TextField blank

`ExportSnapshotTrack`:
- `snapshot` FK ExportSnapshot CASCADE
- `song` FK `library_manager.Song` PROTECT
- `position` PositiveIntegerField
- `inclusion_reason` CharField choices
- `roll_probability` FloatField
- `Meta: ordering = ["position"], unique_together = (snapshot, position)`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/queuetip/models.py` *(extend)* | `ExportSnapshot`, `ExportSnapshotTrack` |
| `api/queuetip/migrations/0002_export_models.py` | Generated |
| `api/src/queuetip/selection.py` | Pure-Python `compute_probability`, `materialize` |
| `api/src/queuetip/services/export.py` | `ExportService.create`, `.get`, `.list_for_playlist` |
| `api/src/queuetip/m3u.py` | `render_m3u(snapshot) -> str` |
| `api/src/queuetip/graphql_types.py` *(extend)* | `ExportSnapshotType`, `ExportSnapshotTrackType`, `ExportOptionsInput` |
| `api/src/queuetip/schema/query.py` *(extend)* | `export`, `myPlaylistExports` |
| `api/src/queuetip/schema/mutation.py` *(extend)* | `createExport` |
| `api/src/queuetip/routes.py` *(extend)* | `GET /exports/{id}.m3u` |
| Tests | Per task |

Conventions: as 1A/1B/1C (no `__init__.py` in test dirs; async DB tests use `(transaction=True)` + `asyncio` marks + `sync_to_async`-wrapped ORM; commits with `--no-gpg-sign`, no Claude footer, pre-commit autorun).

---

### Task 1: Export models + migration

**Files:** `api/queuetip/models.py` (append), `api/queuetip/migrations/0002_*.py` (generated), `api/tests/unit/queuetip/test_models_export.py`

- [ ] **Step 1: Verify `Song` model has the file-path + duration attributes.**
Run `docker compose exec -T web python -c "import django; django.setup(); from library_manager.models import Song; print(sorted(f.name for f in Song._meta.get_fields() if not f.is_relation))"` and note the field that holds the on-disk path and the field that holds duration in seconds. Use the verified names in Task 6 (m3u rendering).

- [ ] **Step 2: Append to `api/queuetip/models.py`:**

```python
class ExportSnapshot(models.Model):
    """Immutable materialization of a playlist's contributions to a tracklist."""

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="export_snapshots"
    )
    requested_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="export_snapshots"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    parameters = models.JSONField(default=dict)
    rng_seed = models.BigIntegerField()
    warning_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ExportSnapshot {self.id} of {self.playlist}"


class ExportSnapshotTrack(models.Model):
    """One track in an ExportSnapshot, with the reason it's included."""

    REASON_GUARANTEED = "guaranteed"
    REASON_ROLLED_IN = "rolled_in"
    REASON_TOPPED_UP = "topped_up"
    REASON_CHOICES = [
        (REASON_GUARANTEED, "Guaranteed (net ≥ t_high)"),
        (REASON_ROLLED_IN, "Rolled in"),
        (REASON_TOPPED_UP, "Topped up to min_size"),
    ]

    snapshot = models.ForeignKey(
        ExportSnapshot, on_delete=models.CASCADE, related_name="tracks"
    )
    song = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_export_tracks",
    )
    position = models.PositiveIntegerField()
    inclusion_reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    roll_probability = models.FloatField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "position"],
                name="queuetip_export_track_position_unique",
            )
        ]
```

- [ ] **Step 3: Write `api/tests/unit/queuetip/test_models_export.py`:**

```python
import pytest
from django.db import IntegrityError

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
)
from tests.factories import ArtistFactory, SongFactory


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
```

- [ ] **Step 4:** `docker compose exec -T web python manage.py makemigrations queuetip` → creates `0002_*.py`.
- [ ] **Step 5:** `docker compose exec -T web python manage.py migrate queuetip`
- [ ] **Step 6:** Run tests, all 2 pass.
- [ ] **Step 7:** Commit.

---

### Task 2: SelectionEngine — pure-Python materialization

**Files:** `api/src/queuetip/selection.py`, `api/tests/unit/queuetip/test_selection.py`

The engine is pure: given a list of `(song_id, net_score)` tuples + curve knobs + min/max + seed + a filter callable, it returns a deterministic list of `MaterializedTrack(song_id, position, inclusion_reason, roll_probability)`. No DB, no async, no Strawberry — easiest piece in the system to test exhaustively.

- [ ] **Step 1: Write the failing tests** (cover curve anchors at and between t_high/0/-t_low; min-size floor topping up by highest p; max-size ceiling dropping lowest p but preserving guaranteed; guaranteed-exceeds-max edge case sets warning + seeded draw; full determinism — same inputs + same seed → identical output).

Example test cases:
```python
import pytest
from src.queuetip.selection import (
    DEFAULT_KNOBS,
    CurveKnobs,
    MaterializationResult,
    Reason,
    SongInput,
    compute_probability,
    materialize,
)


KNOBS = DEFAULT_KNOBS  # base=0.85, p_floor=0.15, t_high=3, t_low=3


def test_curve_anchors():
    assert compute_probability(net=3, knobs=KNOBS) == 1.0
    assert compute_probability(net=4, knobs=KNOBS) == 1.0
    assert compute_probability(net=0, knobs=KNOBS) == pytest.approx(0.85)
    assert compute_probability(net=-3, knobs=KNOBS) == pytest.approx(0.15)
    assert compute_probability(net=-4, knobs=KNOBS) == 0.15


def test_curve_midpoints_are_linear():
    # at net=1.5 (halfway between 0 and t_high=3), p = base + (1 - base) * 0.5
    assert compute_probability(net=1, knobs=KNOBS) == pytest.approx(0.85 + (1 - 0.85) * (1 / 3))
    assert compute_probability(net=-1, knobs=KNOBS) == pytest.approx(0.85 + (0.15 - 0.85) * (1 / 3))


def test_materialize_is_deterministic_with_seed():
    songs = [SongInput(song_id=i, net=0) for i in range(10)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=42)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=42)
    assert [(t.song_id, t.position) for t in r1.tracks] == [(t.song_id, t.position) for t in r2.tracks]


def test_guaranteed_always_in():
    songs = [
        SongInput(song_id=1, net=5),  # guaranteed
        SongInput(song_id=2, net=-10),  # floor
    ]
    # Use a seed that would normally drop song 2 (p=0.15).
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    ids = {t.song_id for t in r.tracks}
    assert 1 in ids


def test_min_size_topup_picks_highest_p_excluded():
    # 3 songs all with net=-10 (p=0.15) → high chance none included; min_size=2 forces topup.
    songs = [SongInput(song_id=i, net=-10) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=2, max_size=None, seed=0)
    assert len(r.tracks) >= 2


def test_max_size_drops_lowest_p_first_preserving_guaranteed():
    songs = [
        SongInput(song_id=1, net=5),   # guaranteed
        SongInput(song_id=2, net=5),   # guaranteed
        SongInput(song_id=3, net=0),   # p=0.85
        SongInput(song_id=4, net=-5),  # p=0.15
    ]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=2, seed=1)
    ids = {t.song_id for t in r.tracks}
    # Both guaranteed must be present; the lowest-p ones get dropped to fit.
    assert {1, 2}.issubset(ids)


def test_guaranteed_exceeds_max_emits_warning_and_seeded_draw():
    songs = [SongInput(song_id=i, net=5) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=7)
    assert len(r.tracks) == 3
    assert r.warning_message != ""
```

- [ ] **Step 2: Implement** `api/src/queuetip/selection.py`:

```python
"""Pure-Python selection engine for Queuetip exports.

Deterministic given (inputs, knobs, seed). No DB, no async, no GraphQL —
fully unit-tested independently of the rest of the system.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Reason(str, Enum):
    GUARANTEED = "guaranteed"
    ROLLED_IN = "rolled_in"
    TOPPED_UP = "topped_up"


@dataclass(frozen=True)
class CurveKnobs:
    base: float = 0.85
    p_floor: float = 0.15
    t_high: int = 3
    t_low: int = 3


DEFAULT_KNOBS = CurveKnobs()


@dataclass(frozen=True)
class SongInput:
    song_id: int
    net: int


@dataclass(frozen=True)
class MaterializedTrack:
    song_id: int
    position: int
    inclusion_reason: Reason
    roll_probability: float


@dataclass(frozen=True)
class MaterializationResult:
    tracks: list[MaterializedTrack]
    warning_message: str


def compute_probability(*, net: int, knobs: CurveKnobs) -> float:
    """Piecewise-linear net → probability per the program spec."""
    if net >= knobs.t_high:
        return 1.0
    if net >= 0:
        # Linear from (0, base) to (t_high, 1.0).
        return knobs.base + (1.0 - knobs.base) * (net / knobs.t_high)
    if net > -knobs.t_low:
        # Linear from (0, base) to (-t_low, p_floor).
        return knobs.base + (knobs.p_floor - knobs.base) * ((-net) / knobs.t_low)
    return knobs.p_floor


def materialize(
    songs: list[SongInput],
    *,
    knobs: CurveKnobs,
    min_size: int,
    max_size: int | None,
    seed: int,
) -> MaterializationResult:
    """Roll → floor → ceiling → shuffle. See program spec for the algorithm."""
    rng = random.Random(seed)
    warning = ""

    # Compute probabilities once. Sort by song_id for stable order.
    annotated = sorted(
        (
            (s.song_id, compute_probability(net=s.net, knobs=knobs), s)
            for s in songs
        ),
        key=lambda t: t[0],
    )

    guaranteed: list[tuple[int, float]] = [
        (sid, p) for sid, p, _ in annotated if p == 1.0
    ]
    non_guaranteed: list[tuple[int, float]] = [
        (sid, p) for sid, p, _ in annotated if p < 1.0
    ]

    # Edge: guaranteed alone exceed max_size — seeded weighted draw among them.
    if max_size is not None and len(guaranteed) > max_size:
        warning = (
            f"Guaranteed songs ({len(guaranteed)}) exceed max_size ({max_size}); "
            "a seeded weighted draw was made among the guaranteed set."
        )
        # All-equal weights since all are p=1.0 — uniform seeded sample.
        chosen = rng.sample(guaranteed, max_size)
        included = [(sid, 1.0, Reason.GUARANTEED) for sid, _ in chosen]
    else:
        # Step 3 — roll non-guaranteed independently.
        included: list[tuple[int, float, Reason]] = [
            (sid, p, Reason.GUARANTEED) for sid, p in guaranteed
        ]
        for sid, p in non_guaranteed:
            if rng.random() < p:
                included.append((sid, p, Reason.ROLLED_IN))

        included_ids = {sid for sid, _, _ in included}

        # Step 4 — floor: top up with highest-p excluded.
        if len(included) < min_size:
            excluded = sorted(
                [
                    (sid, p)
                    for sid, p in non_guaranteed
                    if sid not in included_ids
                ],
                key=lambda t: (-t[1], t[0]),  # highest p first, then song_id
            )
            needed = min_size - len(included)
            for sid, p in excluded[:needed]:
                included.append((sid, p, Reason.TOPPED_UP))

        # Step 5 — ceiling: drop lowest-p non-guaranteed until ≤ max_size.
        if max_size is not None and len(included) > max_size:
            non_g = sorted(
                [t for t in included if t[2] != Reason.GUARANTEED],
                key=lambda t: (t[1], -t[0]),  # lowest p first, then song_id desc
            )
            g = [t for t in included if t[2] == Reason.GUARANTEED]
            keep_non_g = non_g[len(non_g) - (max_size - len(g)) :] if max_size > len(g) else []
            included = g + keep_non_g

    # Step 6 — shuffle.
    rng.shuffle(included)

    tracks = [
        MaterializedTrack(
            song_id=sid, position=pos, inclusion_reason=reason, roll_probability=p
        )
        for pos, (sid, p, reason) in enumerate(included)
    ]
    return MaterializationResult(tracks=tracks, warning_message=warning)
```

- [ ] **Step 3:** Run tests, all pass.
- [ ] **Step 4:** Commit.

---

### Task 3: ExportService

**Files:** `api/src/queuetip/services/export.py`, `api/tests/unit/queuetip/test_service_export.py`

Orchestrates: validate caller is member, fetch contributions + votes, apply personal filters (`excludeMyDownvotes`), call `materialize`, persist `ExportSnapshot` + `ExportSnapshotTrack` rows in one transaction, return the snapshot.

Use `secrets.randbits(63)` for the seed (positive int that fits BigIntegerField). Store parameters as the dict directly.

Provide also: `ExportService.get(account, snapshot_id) -> ExportSnapshot` (member-only) and `ExportService.list_for_playlist(account, playlist_id) -> list[ExportSnapshot]` (member-only, newest first via the model's default ordering).

Tests (paraphrasing — write them in 1B/1C style):
1. `create` with no votes → all songs have net=0 → all rolled-in (or floor topup) → returns snapshot with N tracks.
2. `create(excludeMyDownvotes=True)` excludes songs the caller voted -1 on; assert their ids absent.
3. `create` on a playlist with min_size=0 max_size=0 (degenerate) → 0 tracks, no crash.
4. `create` with `min_size > total contributions` tops up everything (still capped at total).
5. `get` member-only — outsider raises `PermissionDeniedError`.
6. `list_for_playlist` returns snapshots newest-first.
7. Determinism: two `create` calls (different seeds, persisted) yield different snapshots; but `materialize` invoked with the stored seed reproduces.

Implementation sketch (write the full version):
```python
import secrets
from asgiref.sync import sync_to_async
from django.db import transaction

from queuetip.models import (
    Account, Contribution, ExportSnapshot, ExportSnapshotTrack, Playlist, Vote,
)
from queuetip.permissions import require_member
from src.queuetip.errors import NotFoundError
from src.queuetip.selection import (
    CurveKnobs, SongInput, materialize,
)


class ExportService:
    @staticmethod
    async def create(
        account: Account, playlist_id: int, *, exclude_my_downvotes: bool = False
    ) -> ExportSnapshot:
        def _create() -> ExportSnapshot:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)

            # Pull contributions + votes in one go.
            contributions = list(
                Contribution.objects.filter(playlist=playlist)
                .select_related("song")
                .prefetch_related("votes")
            )

            # Apply personal filter.
            if exclude_my_downvotes:
                contributions = [
                    c for c in contributions
                    if not any(
                        v.account_id == account.id and v.value == -1
                        for v in c.votes.all()
                    )
                ]

            song_inputs = [
                SongInput(
                    song_id=c.song_id,
                    net=sum(v.value for v in c.votes.all()),
                )
                for c in contributions
            ]

            knobs = CurveKnobs(
                base=playlist.base,
                p_floor=playlist.p_floor,
                t_high=playlist.t_high,
                t_low=playlist.t_low,
            )
            seed = secrets.randbits(63)
            result = materialize(
                song_inputs,
                knobs=knobs,
                min_size=playlist.min_size,
                max_size=playlist.max_size,
                seed=seed,
            )

            params = {"exclude_my_downvotes": exclude_my_downvotes}

            with transaction.atomic():
                snapshot = ExportSnapshot.objects.create(
                    playlist=playlist,
                    requested_by=account,
                    rng_seed=seed,
                    parameters=params,
                    warning_message=result.warning_message,
                )
                ExportSnapshotTrack.objects.bulk_create([
                    ExportSnapshotTrack(
                        snapshot=snapshot,
                        song_id=t.song_id,
                        position=t.position,
                        inclusion_reason=t.inclusion_reason.value,
                        roll_probability=t.roll_probability,
                    )
                    for t in result.tracks
                ])
            return snapshot

        return await sync_to_async(_create)()

    @staticmethod
    async def get(account: Account, snapshot_id: int) -> ExportSnapshot:
        def _get() -> ExportSnapshot:
            snap = (
                ExportSnapshot.objects.select_related("playlist", "requested_by")
                .filter(id=snapshot_id)
                .first()
            )
            if snap is None:
                raise NotFoundError(f"No snapshot with id={snapshot_id}")
            require_member(account, snap.playlist)
            return snap

        return await sync_to_async(_get)()

    @staticmethod
    async def list_for_playlist(
        account: Account, playlist_id: int
    ) -> list[ExportSnapshot]:
        def _list() -> list[ExportSnapshot]:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            return list(
                ExportSnapshot.objects.filter(playlist=playlist)
                .select_related("requested_by")
            )

        return await sync_to_async(_list)()
```

Commit when tests pass.

---

### Task 4: ExportSnapshot GraphQL types

**Files:** `api/src/queuetip/graphql_types.py` (extend)

Append `ExportSnapshotType`, `ExportSnapshotTrackType`, `ExportOptionsInput`. Reuse `PlaylistType` (with a fresh memberships fetch — pass in pre-fetched), `AccountType`, `SongRef`. Render `rng_seed` as `str(seed)` (avoid JS number-precision issues with BigInt), `parameters` as a JSON string. Add a computed `m3u_url` field that returns `f"{settings.QUEUETIP_PUBLIC_URL.rstrip('/')}/exports/{snapshot.id}.m3u"`.

The `from_model` classmethod takes pre-fetched tracks + memberships to avoid lazy loads. Mirror Task 1 of 1C's PlaylistType handling.

Commit when schema sanity check passes.

---

### Task 5: createExport + export + myPlaylistExports GraphQL

**Files:** `api/src/queuetip/schema/{query.py, mutation.py}` (extend)

Add `createExport(playlistId, options) → ExportSnapshotType` mutation, `export(id) → ExportSnapshotType` query, `myPlaylistExports(playlistId) → list[ExportSnapshotType]` query. All call `ExportService` and translate to types. Use the existing `_require_account` helpers.

Integration test (new `test_exports_api.py` in integration tests): create playlist + contribute 5 songs + vote on some + call `createExport`, assert snapshot id, parameters, tracks. Then `export(id)` returns it.

Commit when integration tests pass.

---

### Task 6: m3u rendering

**Files:** `api/src/queuetip/m3u.py`, `api/tests/unit/queuetip/test_m3u.py`

Pure function `render_m3u(snapshot: ExportSnapshot) -> str` that:
- Pre-fetches `snapshot.tracks.select_related("song", "song__primary_artist")`.
- Emits `#EXTM3U`, a header comment, and per-track `#EXTINF:duration,Artist - Title\n<file_path>\n` blocks.
- Skips tracks whose Song has no downloaded file (per spec). Detect via the file-path attribute verified in Task 1; "no downloaded file" = empty path OR a `downloaded`/`is_downloaded` boolean field if present.

Unit tests: small fixture-built snapshot, assert the rendered output contains the expected lines in order, missing-audio tracks are skipped, header line has the playlist name + snapshot id.

This is a sync function — callers wrap in `sync_to_async` (the REST route will).

Commit when tests pass.

---

### Task 7: m3u download REST route + integration test

**Files:** `api/src/queuetip/routes.py` (extend), `api/tests/integration/queuetip/test_exports_api.py` (extend)

Add to `routes.py`:
```python
@router.get("/exports/{snapshot_id}.m3u")
async def export_m3u(snapshot_id: int, request: Request) -> Response:
    """Stream the m3u for a snapshot. Member-only, session-cookie auth."""
    from .auth import SESSION_COOKIE, InvalidTokenError, read_session_token
    from queuetip.models import Account, ExportSnapshot
    from queuetip.permissions import require_member, PermissionDeniedError

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return Response(status_code=401)
    try:
        account_id = read_session_token(token)
    except InvalidTokenError:
        return Response(status_code=401)

    def _load_and_render() -> str | None:
        account = Account.objects.filter(id=account_id).first()
        if account is None:
            return None
        snap = (
            ExportSnapshot.objects.select_related("playlist")
            .filter(id=snapshot_id)
            .first()
        )
        if snap is None:
            return None
        try:
            require_member(account, snap.playlist)
        except PermissionDeniedError:
            return "FORBIDDEN"
        from .m3u import render_m3u
        return render_m3u(snap)

    body = await sync_to_async(_load_and_render)()
    if body is None:
        return Response(status_code=404)
    if body == "FORBIDDEN":
        return Response(status_code=403)
    return Response(
        content=body,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="snapshot-{snapshot_id}.m3u"'
        },
    )
```

Add `from asgiref.sync import sync_to_async` and `from starlette.requests import Request` to `routes.py` imports.

Integration tests: full happy path (create snapshot → GET /exports/{id}.m3u with session cookie → 200 with audio/x-mpegurl content-type); 401 without cookie; 403 for non-member; 404 for nonexistent id.

Commit when all 1A+1B+1C+2A tests pass.

---

## Self-Review

**Spec coverage** (against program spec's Selection Engine + Phase 2 section):
- Curve (anchors + linearity): Task 2 ✅
- Materialization (roll/floor/ceiling/shuffle): Task 2 ✅
- Guaranteed-exceeds-max edge: Task 2 + warning_message field ✅
- Personal filter (excludeMyDownvotes): Tasks 3, 5 ✅
- Seeded snapshot persistence: Tasks 1, 3 ✅
- m3u export with skipped missing audio: Task 6 ✅
- REST download with auth: Task 7 ✅

**Deferred to later phases:**
- More personal filters than just `excludeMyDownvotes` (Phase 2+ as program spec specifies).
- m3u flavor for non-local consumers — current design assumes consumer can reach the host's `/mnt/music_spotify/...` paths. A future "extended-only" m3u for off-host playback can come with Phase 3/4 export to streaming services.
- Frontend (Phase 2B).
