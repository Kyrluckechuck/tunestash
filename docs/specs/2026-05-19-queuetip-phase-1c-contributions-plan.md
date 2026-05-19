# Queuetip Phase 1C — Contributions, Voting, Bulk Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out Phase 1 by adding the song-contribution flow (search + paste-link), per-contribution voting, and async bulk playlist import — wiring the Phase 0 resolution layer into the public GraphQL API on top of the 1A/1B foundation.

**Architecture:** New `ContributionService`, `VoteService`, and `BulkImportService` mirror the 1B service/permission patterns. Bulk import runs as a Celery `@shared_task` in `api/queuetip/tasks.py` (Django app — Celery autodiscovers); it calls `resolve_playlist` + `ingest_track` (both sync) inside the worker. Resolvers wrap `sync_to_async` around all ORM/Phase-0 calls.

**Tech Stack:** Django 5.1+, Strawberry GraphQL, FastAPI, Celery (Valkey/Redis broker), pytest.

**Spec:** `docs/specs/2026-05-19-queuetip-phase-1-core-design.md`

**Phase 0 surface used:**
- `from src.queuetip.resolution.catalog import catalog_search` — async, `(query, limit) -> list[CatalogSearchTrack]`
- `from src.queuetip.resolution.links import resolve_link` — sync, `(url) -> TrackCandidate` (raises `UnsupportedURLError`, `TrackNotFoundError`)
- `from src.queuetip.resolution.playlists import resolve_playlist` — sync, `(url) -> list[TrackCandidate]` (raises `UnsupportedURLError`, `PlaylistNotFoundError`, `EditorialPlaylistError`)
- `from src.queuetip.resolution.ingest import ingest_track` — sync, `(candidate) -> Song` (queues download internally)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/src/queuetip/graphql_types.py` *(extend)* | `ContributionType`, `VoteType`, `ContributionInputResult`, `CatalogSearchResultType`, `BulkImportJobType` |
| `api/src/queuetip/services/contribution.py` | Contribute + remove; duplicate detection |
| `api/src/queuetip/services/vote.py` | Cast / clear vote |
| `api/src/queuetip/services/bulk_import.py` | Queue + status accessor |
| `api/queuetip/tasks.py` | `bulk_import_playlist` `@shared_task` |
| `api/src/queuetip/schema/query.py` *(extend)* | `catalogSearch`, `bulkImportJob` |
| `api/src/queuetip/schema/mutation.py` *(extend)* | 6 new mutations |
| `api/tests/unit/queuetip/test_service_contribution.py` | Contribution service tests |
| `api/tests/unit/queuetip/test_service_vote.py` | Vote service tests |
| `api/tests/unit/queuetip/test_bulk_import_task.py` | Bulk import Celery task tests |
| `api/tests/integration/queuetip/test_contributions_api.py` | E2E GraphQL for contribute/vote/import |

**Conventions (carried from 1A/1B):**
- No `__init__.py` in test dirs.
- Async DB tests: `@pytest.mark.django_db(transaction=True)` + `@pytest.mark.asyncio`; ORM wrapped in `sync_to_async`.
- `git commit --no-gpg-sign`; pre-commit autorun.
- isort + black before commit.
- Tests run in Docker: `docker compose exec -T web python -m pytest <args>`.

---

### Task 1: GraphQL types for contribution / vote / catalog / import

**Files:** `api/src/queuetip/graphql_types.py` (extend)

Append to `graphql_types.py` (top-level imports for `Contribution, Vote, BulkImportJob` from `queuetip.models`; for `CatalogSearchTrack` from `library_manager.services.catalog_search`):

```python
import dataclasses
from queuetip.models import BulkImportJob, Contribution, Vote


@strawberry.type
class VoteType:
    account: AccountType
    value: int
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, v: Vote) -> "VoteType":
        return cls(
            account=AccountType.from_model(v.account),
            value=v.value,
            created_at=v.created_at,
        )


@strawberry.type
class SongRef:
    """Minimal song identity exposed to the public API.

    Avoids leaking TuneStash's full Song shape. Phase 2 may expand this.
    """

    id: strawberry.ID
    title: str
    artist: str
    isrc: str | None


@strawberry.type
class ContributionType:
    id: strawberry.ID
    song: SongRef
    contributed_by: AccountType
    created_at: datetime.datetime
    votes: list[VoteType]
    net_score: int

    @classmethod
    def from_model(
        cls, contribution: Contribution, votes: list[Vote]
    ) -> "ContributionType":
        song = contribution.song
        return cls(
            id=strawberry.ID(str(contribution.id)),
            song=SongRef(
                id=strawberry.ID(str(song.id)),
                title=song.song_name,
                artist=song.primary_artist.name,
                isrc=song.isrc or None,
            ),
            contributed_by=AccountType.from_model(contribution.contributed_by),
            created_at=contribution.created_at,
            votes=[VoteType.from_model(v) for v in votes],
            net_score=sum(v.value for v in votes),
        )


@strawberry.type
class ContributionResult:
    """Outcome of a contribute mutation.

    `already_present=True` means the song was already in the playlist — the
    client can show "upvote existing?" UX. The returned `contribution` is the
    existing row in that case.
    """

    contribution: ContributionType
    already_present: bool


@strawberry.type
class CatalogSearchResultType:
    """One catalog search hit, with library-presence flag."""

    deezer_id: str
    title: str
    artist: str
    isrc: str | None
    in_library: bool


@strawberry.type
class BulkImportJobType:
    id: strawberry.ID
    source_url: str
    status: str
    added_count: int
    skipped_count: int
    unresolved_count: int
    unresolved_titles: list[str]
    error: str
    created_at: datetime.datetime
    finished_at: datetime.datetime | None

    @classmethod
    def from_model(cls, job: BulkImportJob) -> "BulkImportJobType":
        return cls(
            id=strawberry.ID(str(job.id)),
            source_url=job.source_url,
            status=job.status,
            added_count=job.added_count,
            skipped_count=job.skipped_count,
            unresolved_count=job.unresolved_count,
            unresolved_titles=list(job.unresolved_titles or []),
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )
```

Notes:
- `SongRef` deliberately exposes a minimal subset of `library_manager.Song` (title/artist/isrc) — TuneStash's full Song has admin-only fields like `downloaded`, `file_path`, etc. that the public API must NOT leak.
- `song.song_name` is the `Song` model's title field — verify with `Song._meta.get_fields()` before writing the test; if it's `title` adjust accordingly.

- [ ] **Step 1: Confirm `Song` field names.** Run `docker compose exec -T web python -c "import django; django.setup(); from library_manager.models import Song; print([f.name for f in Song._meta.get_fields() if not f.is_relation])"` and note the correct title field.

- [ ] **Step 2: Apply the type extension above**, replacing `song.song_name` with the real field name if different.

- [ ] **Step 3: Schema sanity check.** `docker compose exec -T web python -c "import django; django.setup(); from src.queuetip.graphql_types import ContributionType, VoteType, ContributionResult, CatalogSearchResultType, BulkImportJobType; from src.queuetip.schema import schema; print('ok')"`. Expected: `ok`.

- [ ] **Step 4: Run full queuetip suite — no regressions.**

- [ ] **Step 5: Commit:** `feat(queuetip): ContributionType, VoteType, BulkImportJobType`

---

### Task 2: `catalogSearch` query

**Files:** `api/src/queuetip/schema/query.py` (extend)

The Phase 0 `catalog_search` is async and returns `CatalogSearchTrack` objects. Translate to the public `CatalogSearchResultType`. Anonymous callers MAY use this — no auth required (returns Deezer catalog metadata, not private data).

- [ ] **Step 1: Add a resolver to `Query`:**

```python
    @strawberry.field
    async def catalog_search(
        self, query: str, limit: int = 10
    ) -> list[CatalogSearchResultType]:
        """Deezer-backed track search, with in_library flagging."""
        from src.queuetip.resolution.catalog import catalog_search as _catalog_search

        if not query.strip():
            return []
        limit = max(1, min(50, limit))
        hits = await _catalog_search(query, limit=limit)
        return [
            CatalogSearchResultType(
                deezer_id=str(h.deezer_id),
                title=h.title,
                artist=h.artist_name,
                isrc=h.isrc or None,
                in_library=bool(h.in_library),
            )
            for h in hits
        ]
```

Import `CatalogSearchResultType` from `..graphql_types`. The fields used on `h` (`deezer_id`, `title`, `artist_name`, `isrc`, `in_library`) need to match the actual `CatalogSearchTrack` dataclass — verify in Phase 0's catalog module before implementing; adjust attribute names if they differ. If `in_library` is not a field on the result, drop it from the type or compute it via a `Song.objects.filter(deezer_id=h.deezer_id).exists()` lookup wrapped in `sync_to_async`.

- [ ] **Step 2: Schema sanity check + run full suite.**
- [ ] **Step 3: Commit:** `feat(queuetip): catalogSearch query`

---

### Task 3: ContributionService

**Files:**
- Create: `api/src/queuetip/services/contribution.py`
- Test: `api/tests/unit/queuetip/test_service_contribution.py`

The service:
- `contribute_from_link(account, playlist_id, url)` → `(Contribution, already_present: bool)`
- `contribute_from_search(account, playlist_id, deezer_id)` → same shape (constructs Deezer URL and uses `resolve_link`)
- `remove_contribution(account, contribution_id)` → owner may remove any; member removes own only

Duplicate handling: if a Contribution already exists for `(playlist, song)`, return the EXISTING contribution with `already_present=True`. The mutation surfaces this for the "upvote existing?" UX.

- [ ] **Step 1: Write the failing tests** at `api/tests/unit/queuetip/test_service_contribution.py`. Tests should cover:
1. `contribute_from_link` happy path — creates Contribution, `already_present=False`.
2. Second `contribute_from_link` for same URL/same playlist returns existing, `already_present=True`, no duplicate.
3. Non-member contributor → `PermissionDeniedError`.
4. `contribute_from_search` builds Deezer URL and resolves it (mock `resolve_link`).
5. `remove_contribution` by the contributor — succeeds.
6. `remove_contribution` by a non-owner non-contributor — `PermissionDeniedError`.
7. `remove_contribution` by the owner of someone else's contribution — succeeds.
8. `UnsupportedURLError` from `resolve_link` propagates.

Use `@patch("src.queuetip.services.contribution.resolve_link")` and `@patch("src.queuetip.services.contribution.ingest_track")` — return a fake `Song` (use `SongFactory(primary_artist=ArtistFactory())` from `tests.factories`). Wrap test factory calls in `sync_to_async`.

- [ ] **Step 2: Implement `api/src/queuetip/services/contribution.py`:**

```python
"""Async service for song contributions: add via search or link, remove."""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from queuetip.models import Account, Contribution, Playlist, PlaylistMembership
from queuetip.permissions import (
    PermissionDeniedError,
    get_membership,
    require_member,
)
from library_manager.models import Song
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.links import resolve_link

from ..errors import NotFoundError


def _deezer_track_url(deezer_id: str) -> str:
    return f"https://www.deezer.com/track/{deezer_id}"


class ContributionService:
    """Stateless namespace for contribution operations."""

    @staticmethod
    async def contribute_from_link(
        account: Account, playlist_id: int, url: str
    ) -> tuple[Contribution, bool]:
        """Resolve a track URL, ingest a Song, create a Contribution.

        Returns (contribution, already_present). If the song is already
        contributed to this playlist, returns the existing contribution with
        already_present=True (no duplicate insert).
        """

        def _contribute() -> tuple[Contribution, bool]:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            candidate = resolve_link(url)
            song: Song = ingest_track(candidate)
            # Duplicate detection — same playlist+song already contributed.
            existing = Contribution.objects.filter(
                playlist=playlist, song=song
            ).select_related("contributed_by", "song").first()
            if existing is not None:
                return existing, True
            try:
                with transaction.atomic():
                    contribution = Contribution.objects.create(
                        playlist=playlist, song=song, contributed_by=account
                    )
            except IntegrityError:
                # Lost a race — fetch what's there.
                contribution = Contribution.objects.get(
                    playlist=playlist, song=song
                )
                return contribution, True
            return contribution, False

        return await sync_to_async(_contribute)()

    @staticmethod
    async def contribute_from_search(
        account: Account, playlist_id: int, deezer_id: str
    ) -> tuple[Contribution, bool]:
        """Contribute by Deezer track id (e.g. picked from catalog_search)."""
        return await ContributionService.contribute_from_link(
            account, playlist_id, _deezer_track_url(deezer_id)
        )

    @staticmethod
    async def remove_contribution(
        account: Account, contribution_id: int
    ) -> None:
        """Owner may remove any; member may remove their own only."""

        def _remove() -> None:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(f"No contribution with id={contribution_id}")
            membership = get_membership(account, contribution.playlist)
            if membership is None:
                raise PermissionDeniedError(
                    "You must be a member of this playlist."
                )
            is_owner = membership.role == PlaylistMembership.ROLE_OWNER
            is_self = contribution.contributed_by_id == account.id
            if not (is_owner or is_self):
                raise PermissionDeniedError(
                    "Only the contributor or a playlist owner may remove this."
                )
            contribution.delete()

        await sync_to_async(_remove)()
```

- [ ] **Step 3: Run tests, all 8 pass.**
- [ ] **Step 4: Commit:** `feat(queuetip): ContributionService (contribute + remove + dedup)`

---

### Task 4: VoteService

**Files:**
- Create: `api/src/queuetip/services/vote.py`
- Test: `api/tests/unit/queuetip/test_service_vote.py`

The service:
- `cast_vote(account, contribution_id, value)` — `value ∈ {-1, +1}`. Upsert. Member-only. Self-voting allowed.
- `clear_vote(account, contribution_id)` — delete the row if present. Idempotent.

- [ ] **Step 1: Write the failing tests.** Cover: cast new vote (member can), recast changes value, self-vote on own contribution succeeds, non-member rejected, clear-existing removes row, clear-nonexistent is a no-op, invalid value (0 or 2) raises `ValidationError`.

- [ ] **Step 2: Implement** `api/src/queuetip/services/vote.py`:

```python
"""Async service for casting / clearing votes on contributions."""

from __future__ import annotations

from asgiref.sync import sync_to_async

from queuetip.models import Account, Contribution, Vote
from queuetip.permissions import require_member

from ..errors import NotFoundError, ValidationError


class VoteService:
    """Stateless namespace for vote operations."""

    @staticmethod
    async def cast_vote(
        account: Account, contribution_id: int, value: int
    ) -> Vote:
        if value not in (-1, 1):
            raise ValidationError("Vote value must be +1 or -1.")

        def _cast() -> Vote:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(
                    f"No contribution with id={contribution_id}"
                )
            require_member(account, contribution.playlist)
            vote, _ = Vote.objects.update_or_create(
                contribution=contribution,
                account=account,
                defaults={"value": value},
            )
            return vote

        return await sync_to_async(_cast)()

    @staticmethod
    async def clear_vote(account: Account, contribution_id: int) -> None:
        def _clear() -> None:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(
                    f"No contribution with id={contribution_id}"
                )
            require_member(account, contribution.playlist)
            Vote.objects.filter(
                contribution=contribution, account=account
            ).delete()

        await sync_to_async(_clear)()
```

- [ ] **Step 3: Run tests, all 7 pass.**
- [ ] **Step 4: Commit:** `feat(queuetip): VoteService (cast + clear, self-vote allowed)`

---

### Task 5: Bulk import — Celery task + service

**Files:**
- Create: `api/queuetip/tasks.py`
- Create: `api/src/queuetip/services/bulk_import.py`
- Test: `api/tests/unit/queuetip/test_bulk_import_task.py`

The Celery task lives in the Django app (`queuetip.tasks`) so Celery autodiscovers it. It is **sync** — it calls Phase 0's sync `resolve_playlist` and sync `ingest_track`. It uses the existing `BulkImportJob` model (created in 1A).

- [ ] **Step 1: Write `api/queuetip/tasks.py`:**

```python
"""Celery tasks for Queuetip — bulk playlist import."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from queuetip.models import Account, BulkImportJob, Contribution, Playlist
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    ResolutionError,
    UnsupportedURLError,
)
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.playlists import resolve_playlist

logger = logging.getLogger(__name__)


@shared_task(name="queuetip.tasks.bulk_import_playlist")
def bulk_import_playlist(job_id: int) -> dict[str, Any]:
    """Resolve a playlist URL and create Contributions for each track.

    - Idempotent skip on tracks already contributed to the playlist.
    - Unresolvable tracks are recorded by title in `unresolved_titles`.
    - A bad/non-public URL fails the whole job with `status=failed`.
    - Per-track failures do NOT abort the run.
    """
    try:
        job = BulkImportJob.objects.select_related("playlist", "requested_by").get(
            id=job_id
        )
    except BulkImportJob.DoesNotExist:
        logger.error("[bulk_import] job %s missing", job_id)
        return {"status": "missing"}

    if job.status not in (BulkImportJob.STATUS_PENDING, BulkImportJob.STATUS_RUNNING):
        logger.info("[bulk_import] job %s already in terminal state %s", job_id, job.status)
        return {"status": job.status}

    job.status = BulkImportJob.STATUS_RUNNING
    job.save(update_fields=["status"])

    try:
        candidates = resolve_playlist(job.source_url)
    except (UnsupportedURLError, PlaylistNotFoundError, EditorialPlaylistError) as exc:
        job.status = BulkImportJob.STATUS_FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return {"status": "failed", "error": str(exc)}
    except ResolutionError as exc:
        job.status = BulkImportJob.STATUS_FAILED
        job.error = f"Resolution error: {exc}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return {"status": "failed", "error": str(exc)}

    added = skipped = unresolved = 0
    unresolved_titles: list[str] = []
    playlist: Playlist = job.playlist
    requester: Account = job.requested_by

    for candidate in candidates:
        try:
            song = ingest_track(candidate)
        except Exception as exc:  # noqa: BLE001  — per-track failures must not abort
            logger.warning(
                "[bulk_import] ingest failed for %s: %s", candidate.track_name, exc
            )
            unresolved += 1
            unresolved_titles.append(
                f"{candidate.track_name} — {candidate.artist_name}"
            )
            continue
        # Skip if already contributed.
        existing = Contribution.objects.filter(playlist=playlist, song=song).exists()
        if existing:
            skipped += 1
            continue
        Contribution.objects.create(
            playlist=playlist, song=song, contributed_by=requester
        )
        added += 1

    job.added_count = added
    job.skipped_count = skipped
    job.unresolved_count = unresolved
    job.unresolved_titles = unresolved_titles
    job.status = BulkImportJob.STATUS_SUCCEEDED
    job.finished_at = timezone.now()
    job.save(
        update_fields=[
            "added_count",
            "skipped_count",
            "unresolved_count",
            "unresolved_titles",
            "status",
            "finished_at",
        ]
    )
    return {
        "status": "succeeded",
        "added": added,
        "skipped": skipped,
        "unresolved": unresolved,
    }
```

- [ ] **Step 2: Write `api/src/queuetip/services/bulk_import.py`:**

```python
"""Async service for queueing + checking bulk-import jobs."""

from __future__ import annotations

from asgiref.sync import sync_to_async

from queuetip.models import Account, BulkImportJob, Playlist
from queuetip.permissions import require_member

from ..errors import NotFoundError


class BulkImportService:
    """Stateless namespace for bulk-import operations."""

    @staticmethod
    async def start(
        account: Account, playlist_id: int, source_url: str
    ) -> BulkImportJob:
        """Create a BulkImportJob row and queue the Celery task."""

        def _create() -> BulkImportJob:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            return BulkImportJob.objects.create(
                playlist=playlist,
                requested_by=account,
                source_url=source_url,
            )

        job = await sync_to_async(_create)()

        # Lazy import — keeps test collection cheap and avoids pulling Celery
        # into the import-time graph of the public ASGI process.
        def _queue() -> None:
            from queuetip.tasks import bulk_import_playlist

            bulk_import_playlist.delay(job.id)

        await sync_to_async(_queue)()
        return job

    @staticmethod
    async def get(account: Account, job_id: int) -> BulkImportJob:
        """Fetch a job; requires the caller be a member of its playlist."""

        def _get() -> BulkImportJob:
            job = (
                BulkImportJob.objects.select_related("playlist", "requested_by")
                .filter(id=job_id)
                .first()
            )
            if job is None:
                raise NotFoundError(f"No bulk-import job with id={job_id}")
            require_member(account, job.playlist)
            return job

        return await sync_to_async(_get)()
```

- [ ] **Step 3: Write Celery task tests** at `api/tests/unit/queuetip/test_bulk_import_task.py`. Tests must:
1. Mock `resolve_playlist` to return a 3-track list of `TrackCandidate`s; mock `ingest_track` to return distinct `Song` instances (use `SongFactory`); assert the job ends `succeeded`, `added_count=3`, no skipped/unresolved, and 3 `Contribution` rows exist.
2. Mock `resolve_playlist` to raise `UnsupportedURLError`; assert job ends `failed`, `error` set.
3. Mock the second `ingest_track` call to raise `Exception("network")`; assert job ends `succeeded` with `added=2, unresolved=1`, and the failed candidate's title appears in `unresolved_titles`.
4. Pre-create a Contribution for one track; assert that track is `skipped` (not double-added).
5. Re-running `bulk_import_playlist` for a `succeeded` job is a no-op (returns `{"status": "succeeded"}` without re-resolving).

Run with `@pytest.mark.django_db(transaction=True)` (no `asyncio` — Celery tasks are sync). Use `@patch("queuetip.tasks.resolve_playlist")` and `@patch("queuetip.tasks.ingest_track")`. To call the task: `bulk_import_playlist(job.id)` — direct synchronous call, NOT `.delay()`.

- [ ] **Step 4: Run task tests, all 5 pass.**
- [ ] **Step 5: Commit:** `feat(queuetip): bulk-import Celery task + service`

---

### Task 6: Contribution + voting mutations + integration tests

**Files:**
- Modify: `api/src/queuetip/schema/mutation.py`
- Modify: `api/src/queuetip/schema/query.py` (add `bulkImportJob` query — see Task 7; but you may add it here if cleaner)
- Create: `api/tests/integration/queuetip/test_contributions_api.py`

Add mutations on `Mutation`:

```python
    @strawberry.mutation
    async def contribute_from_search(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        deezer_track_id: str,
    ) -> ContributionResult:
        account = _require_account(info)
        contribution, already_present = await ContributionService.contribute_from_search(
            account, int(playlist_id), deezer_track_id
        )
        votes = await _list_votes(contribution)
        return ContributionResult(
            contribution=ContributionType.from_model(contribution, votes),
            already_present=already_present,
        )

    @strawberry.mutation
    async def contribute_from_link(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        url: str,
    ) -> ContributionResult:
        account = _require_account(info)
        contribution, already_present = await ContributionService.contribute_from_link(
            account, int(playlist_id), url
        )
        votes = await _list_votes(contribution)
        return ContributionResult(
            contribution=ContributionType.from_model(contribution, votes),
            already_present=already_present,
        )

    @strawberry.mutation
    async def remove_contribution(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        account = _require_account(info)
        await ContributionService.remove_contribution(account, int(id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def cast_vote(
        self,
        info: Info[QueuetipContext, None],
        contribution_id: strawberry.ID,
        value: int,
    ) -> ContributionType:
        account = _require_account(info)
        await VoteService.cast_vote(account, int(contribution_id), value)
        contribution = await _get_contribution_with_votes(int(contribution_id))
        return contribution

    @strawberry.mutation
    async def clear_vote(
        self, info: Info[QueuetipContext, None], contribution_id: strawberry.ID
    ) -> ContributionType:
        account = _require_account(info)
        await VoteService.clear_vote(account, int(contribution_id))
        contribution = await _get_contribution_with_votes(int(contribution_id))
        return contribution
```

Add helpers (module-level) — and import `Contribution, Vote` from `queuetip.models`, `ContributionResult, ContributionType`, `ContributionService`, `VoteService`:

```python
async def _list_votes(contribution) -> list:
    from queuetip.models import Vote

    return await sync_to_async(
        lambda: list(
            Vote.objects.filter(contribution=contribution).select_related("account")
        )
    )()


async def _get_contribution_with_votes(contribution_id: int) -> "ContributionType":
    from queuetip.models import Contribution

    def _load():
        c = (
            Contribution.objects.select_related(
                "song", "song__primary_artist", "contributed_by"
            )
            .filter(id=contribution_id)
            .first()
        )
        if c is None:
            raise NotFoundError(f"No contribution with id={contribution_id}")
        votes = list(
            Vote.objects.filter(contribution=c).select_related("account")
        )
        return c, votes

    contribution, votes = await sync_to_async(_load)()
    return ContributionType.from_model(contribution, votes)
```

Add integration tests in `test_contributions_api.py`:
1. `contributeFromLink` happy path with `httpx.AsyncClient` + mocks of `resolve_link` and `ingest_track`. Assert `alreadyPresent=false`.
2. Second `contributeFromLink` for the same URL returns `alreadyPresent=true` with the same contribution id.
3. `castVote(+1)` raises `netScore` to 1; `castVote(-1)` flips to -1.
4. `clearVote` removes the vote (netScore back to 0).
5. `removeContribution` by the contributor succeeds; by a non-member fails.

- [ ] **Step 1: Verify the existing `mutation.py` imports** and add the new top-level imports (`Vote`, `ContributionType`, `ContributionResult`, `ContributionService`, `VoteService`) — run isort to group properly.

- [ ] **Step 2: Add the 5 mutations + helpers.**

- [ ] **Step 3: Write the integration tests.** Use `@patch("src.queuetip.services.contribution.resolve_link")` and `@patch("src.queuetip.services.contribution.ingest_track")` to keep tests hermetic.

- [ ] **Step 4: Run all tests — full queuetip suite green.**

- [ ] **Step 5: Commit:** `feat(queuetip): contribute + vote mutations + integration tests`

---

### Task 7: Bulk-import mutation + status query + integration tests

**Files:**
- Modify: `api/src/queuetip/schema/mutation.py` (add `bulkImportPlaylist`)
- Modify: `api/src/queuetip/schema/query.py` (add `bulkImportJob`)
- Modify: `api/tests/integration/queuetip/test_contributions_api.py` (add a bulk-import test)

Mutation:
```python
    @strawberry.mutation
    async def bulk_import_playlist(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        url: str,
    ) -> BulkImportJobType:
        """Queue a bulk import. Returns the job; poll bulkImportJob(id) for progress."""
        account = _require_account(info)
        job = await BulkImportService.start(account, int(playlist_id), url)
        return BulkImportJobType.from_model(job)
```

Query:
```python
    @strawberry.field
    async def bulk_import_job(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> BulkImportJobType:
        account = _require_account(info)
        job = await BulkImportService.get(account, int(id))
        return BulkImportJobType.from_model(job)
```

Integration test (in `test_contributions_api.py`): mock the Celery `.delay()` call (patch `queuetip.tasks.bulk_import_playlist.delay`) so the GraphQL mutation creates the job row + queues without running the task. Assert: mutation returns `status: "pending"`; `bulkImportJob(id)` returns the same row.

- [ ] **Step 1: Add the mutation + query + test.**
- [ ] **Step 2: Run full queuetip suite — green.**
- [ ] **Step 3: Commit:** `feat(queuetip): bulkImportPlaylist mutation + bulkImportJob query + tests`

---

## Self-Review

**Spec coverage** (against `2026-05-19-queuetip-phase-1-core-design.md`):
- `catalogSearch` query: Task 2 ✅
- Contribution types + duplicate detection: Tasks 1, 3, 6 ✅
- `contributeFromSearch` / `contributeFromLink` / `removeContribution`: Task 6 ✅
- Self-voting allowed: Task 4 + 6 ✅
- `castVote` / `clearVote`: Tasks 4, 6 ✅
- Bulk import (async Celery, per-track resilience, summary): Tasks 5, 7 ✅
- `BulkImportJob` polling: Task 7 ✅

**Type consistency:**
- `ContributionType.from_model(contribution, votes)` consumes pre-fetched votes — no lazy load.
- `ContributionResult.contribution` + `already_present` round-trips correctly through GraphQL.
- `BulkImportJob` model fields (added/skipped/unresolved counts, unresolved_titles JSON) all carried into `BulkImportJobType`.

**Open notes for Phase 2:**
- Engine_settings still exposed on the anonymous-preview path (final-review minor #3 from 1B) — Phase 2 should split `PlaylistType` if it matters.
- Cascade test for `deletePlaylist` once contributions + votes exist — add to Task 6 integration tests if straightforward (deletePlaylist with N contributions, assert all Vote rows cascade).
- Rate limit / dedicated Celery queue for Queuetip downloads — flagged in the design and Plan 1A; still deferred. A burst of bulk imports will queue many TuneStash downloads.
