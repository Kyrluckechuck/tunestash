# Queuetip Phase 1B — Playlists & Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add playlist CRUD, invite-link-based membership, and role-based permissions on top of the Phase 1A foundation — plus the small hardening items deferred from the 1A final review.

**Architecture:** A thin Strawberry resolver layer over a Django-ORM service layer (`api/src/queuetip/services/`), with permission checks centralized in `api/queuetip/permissions.py`. The async/sync boundary is wrapped at the service layer; resolvers stay simple. Plan 1C (contributions + voting + bulk import) builds on these models.

**Tech Stack:** Django 5.1+, Strawberry GraphQL, FastAPI, `django.core.signing`, pytest / pytest-django.

**Spec:** `docs/specs/2026-05-19-queuetip-phase-1-core-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/src/queuetip/app.py` *(modify, Task 1)* | Add `close_old_connections` middleware |
| `api/src/queuetip/routes.py` *(modify, Task 1)* | `delete_cookie` attribute match |
| `api/tests/integration/queuetip/test_public_api.py` *(modify, Task 1)* | Logout test |
| `api/queuetip/permissions.py` | Permission helpers + exceptions |
| `api/src/queuetip/errors.py` | Public-API errors (auth-required, permission-denied, not-found) — mapped to GraphQL errors |
| `api/src/queuetip/services/__init__.py` | Empty package marker |
| `api/src/queuetip/services/playlist.py` | Playlist create/get/update/delete/regenerate-invite |
| `api/src/queuetip/services/membership.py` | Join/leave/kick/promote |
| `api/src/queuetip/graphql_types.py` *(extend)* | `PlaylistType`, `MembershipType`, `EngineSettingsInput` |
| `api/src/queuetip/schema/query.py` *(extend)* | `myPlaylists`, `playlist` |
| `api/src/queuetip/schema/mutation.py` *(extend)* | 8 new mutations |
| `api/tests/unit/queuetip/test_permissions.py` | Permission helper tests |
| `api/tests/unit/queuetip/test_service_playlist.py` | Playlist service tests |
| `api/tests/unit/queuetip/test_service_membership.py` | Membership service tests |
| `api/tests/integration/queuetip/test_playlists_api.py` | GraphQL integration tests for playlist + membership ops |

**Conventions (carried forward from 1A — implementers must respect):**
- Do NOT add `__init__.py` to any test directory.
- Async tests touching DB use `@pytest.mark.django_db(transaction=True)` and `@pytest.mark.asyncio`. Wrap any bare ORM call in `await sync_to_async(...)`.
- Commit with `--no-gpg-sign`. Brief messages. Pre-commit hook runs automatically.
- Run `python3 -m isort` + `python3 -m black` on changed files before committing.
- Run tests in Docker: `docker compose exec -T web python -m pytest <args>`.

---

### Task 1: Hardening — 1A final-review follow-ups

**Files:**
- Modify: `api/src/queuetip/app.py`
- Modify: `api/src/queuetip/routes.py`
- Modify: `api/tests/integration/queuetip/test_public_api.py`

The Phase 1A final review left three deferred items. Address them in one focused task.

- [ ] **Step 1: Add a `close_old_connections` middleware to `app.py`**

The long-lived ASGI process has no Django request cycle to fire `CONN_HEALTH_CHECKS`. An idle-closed Postgres connection will surface as `InterfaceError` on the next ORM call. Mirror the `task_prerun` `close_old_connections` pattern from `api/celery_app.py`.

Add to `api/src/queuetip/app.py`, inside `create_queuetip_app()` after `app.add_middleware(CORSMiddleware, ...)` and before the inner imports:

```python
    from django.db import close_old_connections  # noqa: E402

    @app.middleware("http")
    async def _close_stale_db_connections(request, call_next):
        # The long-lived ASGI process has no Django request cycle, so
        # CONN_HEALTH_CHECKS never fires. Reap stale connections per request,
        # mirroring celery_app.py's task_prerun hook.
        close_old_connections()
        try:
            response = await call_next(request)
        finally:
            close_old_connections()
        return response
```

- [ ] **Step 2: Fix `delete_cookie` attribute mismatch in `routes.py`**

`set_cookie` and `delete_cookie` must agree on `samesite`/`secure`/`path` for browsers to honor the clear. Update the logout route:

```python
@router.post("/auth/logout")
def logout() -> Response:
    """Clear the session cookie."""
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        samesite="lax",
        secure=not settings.DEBUG,
    )
    return response
```

- [ ] **Step 3: Add a logout integration test**

Append to `api/tests/integration/queuetip/test_public_api.py`:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_logout_clears_session_cookie():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        client.cookies.set(SESSION_COOKIE, make_session_token(account.id))
        response = await client.post("/auth/logout")
    assert response.status_code == 204
    set_cookie_header = response.headers.get("set-cookie", "")
    # Clearing emits a Set-Cookie with the cookie name and a past/zero expiry.
    assert SESSION_COOKIE in set_cookie_header
```

Adjust the imports at the top of the file to ensure `sync_to_async`, `Account`, and the local `httpx`/`SESSION_COOKIE` symbols are available (they already are from the 1A tests).

- [ ] **Step 4: Run the full queuetip suite**

`docker compose exec -T web python -m pytest tests/unit/queuetip/ tests/integration/queuetip/ -q`
Expected: all tests pass (one more than before).

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/app.py api/src/queuetip/routes.py tests/integration/queuetip/test_public_api.py
git commit --no-gpg-sign -m "fix(queuetip): 1A hardening — DB conn recycling, cookie attrs, logout test"
```

---

### Task 2: Permissions module

**Files:**
- Create: `api/queuetip/permissions.py`
- Create: `api/src/queuetip/errors.py`
- Test: `api/tests/unit/queuetip/test_permissions.py`

Permissions are pure-Python checks against `(account, playlist)` and a membership lookup. They live in the Django app (no FastAPI deps) so the service layer can use them. GraphQL errors come from `api/src/queuetip/errors.py` so the Django app stays import-light.

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_permissions.py`:

```python
import pytest

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import (
    PermissionDeniedError,
    get_membership,
    require_member,
    require_owner,
)


def _setup():
    owner = Account.objects.create(display_name="Owner")
    member = Account.objects.create(display_name="Member")
    outsider = Account.objects.create(display_name="Out")
    playlist = Playlist.objects.create(name="P", created_by=owner)
    PlaylistMembership.objects.create(
        playlist=playlist, account=owner, role=PlaylistMembership.ROLE_OWNER
    )
    PlaylistMembership.objects.create(
        playlist=playlist, account=member, role=PlaylistMembership.ROLE_MEMBER
    )
    return owner, member, outsider, playlist


@pytest.mark.django_db
def test_get_membership_returns_owner_membership():
    owner, _member, _out, playlist = _setup()
    m = get_membership(owner, playlist)
    assert m is not None
    assert m.role == PlaylistMembership.ROLE_OWNER


@pytest.mark.django_db
def test_get_membership_returns_none_for_outsider():
    _owner, _member, out, playlist = _setup()
    assert get_membership(out, playlist) is None


@pytest.mark.django_db
def test_require_member_passes_for_member():
    _o, member, _out, playlist = _setup()
    # No exception — returns the membership.
    m = require_member(member, playlist)
    assert m.role == PlaylistMembership.ROLE_MEMBER


@pytest.mark.django_db
def test_require_member_rejects_outsider():
    _o, _m, out, playlist = _setup()
    with pytest.raises(PermissionDeniedError):
        require_member(out, playlist)


@pytest.mark.django_db
def test_require_owner_passes_for_owner():
    owner, _m, _out, playlist = _setup()
    m = require_owner(owner, playlist)
    assert m.role == PlaylistMembership.ROLE_OWNER


@pytest.mark.django_db
def test_require_owner_rejects_member():
    _o, member, _out, playlist = _setup()
    with pytest.raises(PermissionDeniedError):
        require_owner(member, playlist)


def test_require_member_rejects_anonymous():
    with pytest.raises(PermissionDeniedError):
        require_member(None, None)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError`).
- [ ] **Step 3: Write `api/queuetip/permissions.py`:**

```python
"""Permission helpers for Queuetip operations.

Pure functions over (account, playlist) — no async, no GraphQL. Service-layer
callers wrap these in `sync_to_async` like any other ORM call.
"""

from __future__ import annotations

from .models import Account, Playlist, PlaylistMembership


class PermissionDeniedError(Exception):
    """Raised when an account lacks the required role for an action."""


def get_membership(
    account: Account | None, playlist: Playlist | None
) -> PlaylistMembership | None:
    """Return the account's membership in the playlist, or None."""
    if account is None or playlist is None:
        return None
    return PlaylistMembership.objects.filter(
        playlist=playlist, account=account
    ).first()


def require_member(account: Account | None, playlist: Playlist) -> PlaylistMembership:
    """Return the membership, or raise PermissionDeniedError."""
    membership = get_membership(account, playlist)
    if membership is None:
        raise PermissionDeniedError(
            "You must be a member of this playlist."
        )
    return membership


def require_owner(account: Account | None, playlist: Playlist) -> PlaylistMembership:
    """Return the membership iff role is owner, else raise PermissionDeniedError."""
    membership = require_member(account, playlist)
    if membership.role != PlaylistMembership.ROLE_OWNER:
        raise PermissionDeniedError(
            "Only the owner can perform this action."
        )
    return membership
```

- [ ] **Step 4: Write `api/src/queuetip/errors.py`** — used by services to signal auth/permission/not-found cases that resolvers translate to GraphQL errors:

```python
"""Service-layer error types for Queuetip's public API.

The Django app re-uses some of these (PermissionDeniedError) — see
`queuetip/permissions.py`. Resolvers translate these to GraphQL errors via
Strawberry's exception handling.
"""

from queuetip.permissions import PermissionDeniedError  # re-export


class AuthRequiredError(Exception):
    """Caller is anonymous; operation requires a signed-in account."""


class NotFoundError(Exception):
    """A referenced playlist / account / contribution does not exist."""


__all__ = ["AuthRequiredError", "NotFoundError", "PermissionDeniedError"]
```

- [ ] **Step 5: Run tests, all 7 pass.**
- [ ] **Step 6: Commit**

```bash
git add api/queuetip/permissions.py api/src/queuetip/errors.py tests/unit/queuetip/test_permissions.py
git commit --no-gpg-sign -m "feat(queuetip): permissions module + service-layer errors"
```

---

### Task 3: Playlist GraphQL types

**Files:**
- Modify: `api/src/queuetip/graphql_types.py`

Adds the read types and the engine-settings input. Resolvers/services come in later tasks.

- [ ] **Step 1: Append to `api/src/queuetip/graphql_types.py`:**

```python
import strawberry

from queuetip.models import Playlist, PlaylistMembership


@strawberry.type
class MembershipType:
    """A member's role on a playlist."""

    account: AccountType
    role: str
    joined_at: datetime.datetime

    @classmethod
    def from_model(cls, m: PlaylistMembership) -> "MembershipType":
        return cls(
            account=AccountType.from_model(m.account),
            role=m.role,
            joined_at=m.joined_at,
        )


@strawberry.type
class EngineSettings:
    """The per-playlist selection-engine knobs. Read in 1B, used by Phase 2."""

    min_size: int
    max_size: int | None
    t_high: int
    t_low: int
    base: float
    p_floor: float


@strawberry.input
class EngineSettingsInput:
    """Updates to a playlist's engine knobs. All fields optional (partial update)."""

    min_size: int | None = None
    max_size: int | None = strawberry.UNSET  # noqa: PYI011 — distinguish "set null" vs "unchanged"
    t_high: int | None = None
    t_low: int | None = None
    base: float | None = None
    p_floor: float | None = None


@strawberry.type
class PlaylistType:
    """A Queuetip playlist with engine knobs and member list."""

    id: strawberry.ID
    name: str
    description: str
    invite_token: str
    created_by: AccountType
    created_at: datetime.datetime
    engine_settings: EngineSettings
    members: list[MembershipType]

    @classmethod
    def from_model(
        cls,
        playlist: Playlist,
        memberships: list[PlaylistMembership],
    ) -> "PlaylistType":
        return cls(
            id=strawberry.ID(str(playlist.id)),
            name=playlist.name,
            description=playlist.description,
            invite_token=playlist.invite_token,
            created_by=AccountType.from_model(playlist.created_by),
            created_at=playlist.created_at,
            engine_settings=EngineSettings(
                min_size=playlist.min_size,
                max_size=playlist.max_size,
                t_high=playlist.t_high,
                t_low=playlist.t_low,
                base=playlist.base,
                p_floor=playlist.p_floor,
            ),
            members=[MembershipType.from_model(m) for m in memberships],
        )
```

**Notable design points:**
- `max_size` uses `strawberry.UNSET` as the input default so the API distinguishes "leave alone" from "set to null." See the `update_settings` service in Task 4.
- `members` is a `list` not a `Connection` — Phase 1 doesn't paginate (a friend-group playlist is small). Phase 2 may revisit.
- `from_model(playlist, memberships)` accepts pre-fetched memberships rather than triggering a lazy load — protects against the async/sync trap.

- [ ] **Step 2: Sanity-import inside the container:**

`docker compose exec -T web python -c "import django; django.setup(); from src.queuetip.graphql_types import PlaylistType, MembershipType, EngineSettings, EngineSettingsInput; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add api/src/queuetip/graphql_types.py
git commit --no-gpg-sign -m "feat(queuetip): PlaylistType, MembershipType, EngineSettings types"
```

---

### Task 4: Playlist service

**Files:**
- Create: `api/src/queuetip/services/__init__.py` (empty)
- Create: `api/src/queuetip/services/playlist.py`
- Test: `api/tests/unit/queuetip/test_service_playlist.py`

The service exposes async methods. Each wraps a sync helper in `sync_to_async`. Resolvers call services and never touch the ORM directly.

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_service_playlist.py`:

```python
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import PermissionDeniedError
from src.queuetip.errors import NotFoundError
from src.queuetip.services.playlist import PlaylistService


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_playlist_makes_owner_membership():
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    playlist = await PlaylistService.create(owner, name="Friday", description="")
    memberships = await sync_to_async(
        lambda: list(playlist.memberships.all())
    )()
    assert len(memberships) == 1
    assert memberships[0].account_id == owner.id
    assert memberships[0].role == PlaylistMembership.ROLE_OWNER


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_by_invite_token_returns_playlist():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await PlaylistService.create(owner, name="P", description="")
    found = await PlaylistService.get_by_invite_token(p.invite_token)
    assert found.id == p.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_by_invite_token_unknown_raises_not_found():
    with pytest.raises(NotFoundError):
        await PlaylistService.get_by_invite_token("does-not-exist")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_settings_owner_can_change_knobs():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await PlaylistService.create(owner, name="P", description="")
    updated = await PlaylistService.update_settings(
        owner, p.id, name="Renamed", min_size=5, t_high=4
    )
    assert updated.name == "Renamed"
    assert updated.min_size == 5
    assert updated.t_high == 4


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_settings_non_owner_rejected():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    other = await sync_to_async(Account.objects.create)(display_name="X")
    p = await PlaylistService.create(owner, name="P", description="")
    with pytest.raises(PermissionDeniedError):
        await PlaylistService.update_settings(other, p.id, name="Hacked")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_regenerate_invite_token_changes_value_owner_only():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    other = await sync_to_async(Account.objects.create)(display_name="X")
    p = await PlaylistService.create(owner, name="P", description="")
    old = p.invite_token
    new_token = await PlaylistService.regenerate_invite_token(owner, p.id)
    assert new_token != old
    with pytest.raises(PermissionDeniedError):
        await PlaylistService.regenerate_invite_token(other, p.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delete_playlist_owner_only():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    other = await sync_to_async(Account.objects.create)(display_name="X")
    p = await PlaylistService.create(owner, name="P", description="")
    with pytest.raises(PermissionDeniedError):
        await PlaylistService.delete(other, p.id)
    await PlaylistService.delete(owner, p.id)
    exists = await sync_to_async(Playlist.objects.filter(id=p.id).exists)()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_account_returns_only_memberships():
    a = await sync_to_async(Account.objects.create)(display_name="A")
    b = await sync_to_async(Account.objects.create)(display_name="B")
    p1 = await PlaylistService.create(a, name="A1", description="")
    p2 = await PlaylistService.create(a, name="A2", description="")
    _ = await PlaylistService.create(b, name="B1", description="")
    listed = await PlaylistService.list_for_account(a)
    ids = sorted(pl.id for pl in listed)
    assert ids == sorted([p1.id, p2.id])
```

- [ ] **Step 2: Run to verify failure** (ModuleNotFoundError).
- [ ] **Step 3: Write `api/src/queuetip/services/__init__.py` empty.**
- [ ] **Step 4: Write `api/src/queuetip/services/playlist.py`:**

```python
"""Async service for playlist CRUD + invite-token regeneration."""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import transaction

from queuetip.models import Account, Playlist, PlaylistMembership, generate_invite_token
from queuetip.permissions import require_owner

from ..errors import NotFoundError

_UNSET = object()


class PlaylistService:
    """Stateless namespace for playlist operations. All methods are async."""

    @staticmethod
    async def create(owner: Account, name: str, description: str) -> Playlist:
        """Create a playlist and the owner membership in one transaction."""

        def _create() -> Playlist:
            with transaction.atomic():
                playlist = Playlist.objects.create(
                    name=name.strip(), description=description, created_by=owner
                )
                PlaylistMembership.objects.create(
                    playlist=playlist,
                    account=owner,
                    role=PlaylistMembership.ROLE_OWNER,
                )
            return playlist

        return await sync_to_async(_create)()

    @staticmethod
    async def get_by_id(playlist_id: int) -> Playlist:
        playlist = await sync_to_async(
            lambda: Playlist.objects.select_related("created_by")
            .filter(id=playlist_id)
            .first()
        )()
        if playlist is None:
            raise NotFoundError(f"No playlist with id={playlist_id}")
        return playlist

    @staticmethod
    async def get_by_invite_token(token: str) -> Playlist:
        playlist = await sync_to_async(
            lambda: Playlist.objects.select_related("created_by")
            .filter(invite_token=token)
            .first()
        )()
        if playlist is None:
            raise NotFoundError("No playlist for that invite token.")
        return playlist

    @staticmethod
    async def list_for_account(account: Account) -> list[Playlist]:
        return await sync_to_async(
            lambda: list(
                Playlist.objects.filter(memberships__account=account)
                .select_related("created_by")
                .order_by("-created_at")
                .distinct()
            )
        )()

    @staticmethod
    async def list_memberships(playlist: Playlist) -> list[PlaylistMembership]:
        return await sync_to_async(
            lambda: list(
                playlist.memberships.select_related("account").order_by("joined_at")
            )
        )()

    @staticmethod
    async def update_settings(
        account: Account,
        playlist_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        min_size: int | None = None,
        max_size: object = _UNSET,
        t_high: int | None = None,
        t_low: int | None = None,
        base: float | None = None,
        p_floor: float | None = None,
    ) -> Playlist:
        """Owner-only partial update. `max_size` uses sentinel to allow set-null."""

        def _update() -> Playlist:
            playlist = (
                Playlist.objects.select_related("created_by")
                .filter(id=playlist_id)
                .first()
            )
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            if name is not None:
                playlist.name = name.strip()
            if description is not None:
                playlist.description = description
            if min_size is not None:
                playlist.min_size = min_size
            if max_size is not _UNSET:
                playlist.max_size = max_size  # may be None
            if t_high is not None:
                playlist.t_high = t_high
            if t_low is not None:
                playlist.t_low = t_low
            if base is not None:
                playlist.base = base
            if p_floor is not None:
                playlist.p_floor = p_floor
            playlist.save()
            return playlist

        return await sync_to_async(_update)()

    @staticmethod
    async def regenerate_invite_token(account: Account, playlist_id: int) -> str:
        """Owner-only. Generates a new token and returns it."""

        def _regen() -> str:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            playlist.invite_token = generate_invite_token()
            playlist.save(update_fields=["invite_token"])
            return playlist.invite_token

        return await sync_to_async(_regen)()

    @staticmethod
    async def delete(account: Account, playlist_id: int) -> None:
        """Owner-only. Cascades memberships/contributions/votes via FK CASCADE."""

        def _delete() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(account, playlist)
            playlist.delete()

        await sync_to_async(_delete)()
```

- [ ] **Step 5: Run tests, all 8 pass.**
- [ ] **Step 6: Commit**

```bash
git add api/src/queuetip/services/ tests/unit/queuetip/test_service_playlist.py
git commit --no-gpg-sign -m "feat(queuetip): PlaylistService (CRUD + invite regeneration)"
```

---

### Task 5: Membership service

**Files:**
- Create: `api/src/queuetip/services/membership.py`
- Test: `api/tests/unit/queuetip/test_service_membership.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_service_membership.py`:

```python
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import PermissionDeniedError
from src.queuetip.errors import NotFoundError
from src.queuetip.services.membership import MembershipService
from src.queuetip.services.playlist import PlaylistService


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_join_with_valid_token_adds_member():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    m = await MembershipService.join(joiner, p.invite_token)
    assert m.account_id == joiner.id
    assert m.role == PlaylistMembership.ROLE_MEMBER


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_join_unknown_token_raises_not_found():
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    with pytest.raises(NotFoundError):
        await MembershipService.join(joiner, "nope")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_join_twice_returns_existing_membership_no_duplicate():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    m1 = await MembershipService.join(joiner, p.invite_token)
    m2 = await MembershipService.join(joiner, p.invite_token)
    assert m1.id == m2.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_leave_removes_membership():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(joiner, p.invite_token)
    await MembershipService.leave(joiner, p.id)
    exists = await sync_to_async(
        PlaylistMembership.objects.filter(playlist=p, account=joiner).exists
    )()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_leave_owner_with_others_still_present_is_rejected():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(joiner, p.invite_token)
    with pytest.raises(PermissionDeniedError):
        await MembershipService.leave(owner, p.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_kick_owner_removes_member_not_self():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(joiner, p.invite_token)
    await MembershipService.kick(owner, p.id, joiner.id)
    exists = await sync_to_async(
        PlaylistMembership.objects.filter(playlist=p, account=joiner).exists
    )()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_kick_self_rejected():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await PlaylistService.create(owner, name="P", description="")
    with pytest.raises(PermissionDeniedError):
        await MembershipService.kick(owner, p.id, owner.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_kick_non_owner_rejected():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    a = await sync_to_async(Account.objects.create)(display_name="A")
    b = await sync_to_async(Account.objects.create)(display_name="B")
    p = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(a, p.invite_token)
    await MembershipService.join(b, p.invite_token)
    with pytest.raises(PermissionDeniedError):
        await MembershipService.kick(a, p.id, b.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_promote_member_to_owner():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    p = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(joiner, p.invite_token)
    await MembershipService.promote(owner, p.id, joiner.id)
    m = await sync_to_async(
        lambda: PlaylistMembership.objects.get(playlist=p, account=joiner)
    )()
    assert m.role == PlaylistMembership.ROLE_OWNER
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Write `api/src/queuetip/services/membership.py`:**

```python
"""Async service for playlist membership: join, leave, kick, promote."""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from queuetip.models import Account, Playlist, PlaylistMembership
from queuetip.permissions import PermissionDeniedError, require_member, require_owner

from ..errors import NotFoundError


class MembershipService:
    """Stateless namespace for membership operations."""

    @staticmethod
    async def join(account: Account, invite_token: str) -> PlaylistMembership:
        """Add `account` to the playlist named by `invite_token` as a member.

        Idempotent — joining a playlist you're already in returns the existing
        membership.
        """

        def _join() -> PlaylistMembership:
            playlist = Playlist.objects.filter(invite_token=invite_token).first()
            if playlist is None:
                raise NotFoundError("No playlist for that invite token.")
            try:
                with transaction.atomic():
                    return PlaylistMembership.objects.create(
                        playlist=playlist,
                        account=account,
                        role=PlaylistMembership.ROLE_MEMBER,
                    )
            except IntegrityError:
                # Already a member — return the existing row.
                return PlaylistMembership.objects.get(
                    playlist=playlist, account=account
                )

        return await sync_to_async(_join)()

    @staticmethod
    async def leave(account: Account, playlist_id: int) -> None:
        """Remove the caller's own membership.

        An owner cannot leave a playlist that has other members — they must
        kick everyone else or promote another owner first. (Sole-owner self-
        leave is allowed and falls through to cascade-delete via Playlist
        deletion in the design; for v1 we simply require the owner to
        delete the playlist instead.)
        """

        def _leave() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            membership = require_member(account, playlist)
            if membership.role == PlaylistMembership.ROLE_OWNER:
                others = (
                    PlaylistMembership.objects.filter(playlist=playlist)
                    .exclude(account=account)
                    .exists()
                )
                if others:
                    raise PermissionDeniedError(
                        "Owners cannot leave a playlist with other members. "
                        "Promote another owner or delete the playlist."
                    )
            membership.delete()

        await sync_to_async(_leave)()

    @staticmethod
    async def kick(
        actor: Account, playlist_id: int, target_account_id: int
    ) -> None:
        """Owner-only. Removes the target's membership. Cannot kick yourself."""

        def _kick() -> None:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(actor, playlist)
            if target_account_id == actor.id:
                raise PermissionDeniedError(
                    "Use 'leave' to remove yourself; you cannot kick yourself."
                )
            target_membership = PlaylistMembership.objects.filter(
                playlist=playlist, account_id=target_account_id
            ).first()
            if target_membership is None:
                raise NotFoundError("That account is not a member.")
            target_membership.delete()

        await sync_to_async(_kick)()

    @staticmethod
    async def promote(
        actor: Account, playlist_id: int, target_account_id: int
    ) -> PlaylistMembership:
        """Owner-only. Promotes a member to owner role (co-owner)."""

        def _promote() -> PlaylistMembership:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_owner(actor, playlist)
            target_membership = PlaylistMembership.objects.filter(
                playlist=playlist, account_id=target_account_id
            ).first()
            if target_membership is None:
                raise NotFoundError("That account is not a member.")
            target_membership.role = PlaylistMembership.ROLE_OWNER
            target_membership.save(update_fields=["role"])
            return target_membership

        return await sync_to_async(_promote)()
```

- [ ] **Step 4: Run tests, all 9 pass.**
- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/services/membership.py tests/unit/queuetip/test_service_membership.py
git commit --no-gpg-sign -m "feat(queuetip): MembershipService (join/leave/kick/promote)"
```

---

### Task 6: Queries — `myPlaylists` and `playlist`

**Files:**
- Modify: `api/src/queuetip/schema/query.py`
- Test: covered by Task 8 integration tests.

The resolvers call services and translate `errors.py` exceptions into Strawberry errors.

- [ ] **Step 1: Replace `api/src/queuetip/schema/query.py`** with:

```python
"""Queuetip GraphQL Query type."""

import strawberry
from strawberry.types import Info

from ..context import QueuetipContext
from ..errors import AuthRequiredError, NotFoundError
from ..graphql_types import AccountType, PlaylistType
from ..services.playlist import PlaylistService


@strawberry.type
class Query:
    """Root query for the Queuetip public API."""

    @strawberry.field
    def me(self, info: Info[QueuetipContext, None]) -> AccountType | None:
        """Return the currently signed-in account, or null if anonymous."""
        ctx = info.context
        if ctx.account is None:
            return None
        return AccountType.from_model(ctx.account)

    @strawberry.field
    async def my_playlists(
        self, info: Info[QueuetipContext, None]
    ) -> list[PlaylistType]:
        """Playlists the current account is a member of."""
        ctx = info.context
        if ctx.account is None:
            raise AuthRequiredError("Sign in to see your playlists.")
        playlists = await PlaylistService.list_for_account(ctx.account)
        # Pre-fetch each playlist's memberships to avoid lazy loads.
        result: list[PlaylistType] = []
        for p in playlists:
            members = await PlaylistService.list_memberships(p)
            result.append(PlaylistType.from_model(p, members))
        return result

    @strawberry.field
    async def playlist(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID | None = None,
        invite_token: str | None = None,
    ) -> PlaylistType:
        """Look up a playlist by id (auth required) or invite token (anonymous OK).

        The invite-token path is the unauthenticated "preview before joining"
        experience: anyone with the link can read playlist metadata + members.
        The id path requires membership.
        """
        ctx = info.context
        if invite_token is not None:
            playlist = await PlaylistService.get_by_invite_token(invite_token)
        elif id is not None:
            if ctx.account is None:
                raise AuthRequiredError("Sign in to look up a playlist by id.")
            playlist = await PlaylistService.get_by_id(int(id))
            # Authorization: must be a member.
            from queuetip.permissions import require_member
            from asgiref.sync import sync_to_async

            await sync_to_async(require_member)(ctx.account, playlist)
        else:
            raise NotFoundError("Provide either id or inviteToken.")
        members = await PlaylistService.list_memberships(playlist)
        return PlaylistType.from_model(playlist, members)
```

- [ ] **Step 2: Commit** (tests come in Task 8):

```bash
git add api/src/queuetip/schema/query.py
git commit --no-gpg-sign -m "feat(queuetip): myPlaylists + playlist queries"
```

---

### Task 7: Mutations — playlist CRUD

**Files:**
- Modify: `api/src/queuetip/schema/mutation.py`
- Test: covered by Task 8 integration tests.

Adds: `createPlaylist`, `updatePlaylistSettings`, `regenerateInviteToken`, `deletePlaylist`. Each resolver:
1. Reads `info.context.account` — raises `AuthRequiredError` if None.
2. Calls the appropriate `PlaylistService` method.
3. Returns `PlaylistType` (or a result type for delete/regenerate).

- [ ] **Step 1: Append to `api/src/queuetip/schema/mutation.py`** (after the existing `Mutation` class — you will need to **add** the new fields to the existing `Mutation` class, not create a second one). Here is the full new content for the bottom of the file — keep the existing `RequestMagicLinkResult`, `_request_magic_link`, and `Mutation.request_magic_link` and add the rest:

```python
# Add these imports at the top of mutation.py (alongside existing ones):
from asgiref.sync import sync_to_async
from strawberry.types import Info

from queuetip.permissions import PermissionDeniedError

from ..context import QueuetipContext
from ..errors import AuthRequiredError, NotFoundError
from ..graphql_types import EngineSettingsInput, PlaylistType
from ..services.playlist import PlaylistService


@strawberry.type
class DeletePlaylistResult:
    deleted: bool


@strawberry.type
class RegenerateInviteResult:
    invite_token: str


def _require_account(info: Info[QueuetipContext, None]):
    ctx = info.context
    if ctx.account is None:
        raise AuthRequiredError("Sign in to perform this action.")
    return ctx.account


async def _build_playlist_type(playlist) -> PlaylistType:
    members = await PlaylistService.list_memberships(playlist)
    return PlaylistType.from_model(playlist, members)


# ── Add these methods to the existing `Mutation` class ─────────────────────────

    @strawberry.mutation
    async def create_playlist(
        self, info: Info[QueuetipContext, None], name: str, description: str = ""
    ) -> PlaylistType:
        account = _require_account(info)
        if not name.strip():
            raise NotFoundError("Playlist name cannot be empty.")
        playlist = await PlaylistService.create(account, name=name, description=description)
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def update_playlist_settings(
        self,
        info: Info[QueuetipContext, None],
        id: strawberry.ID,
        name: str | None = None,
        description: str | None = None,
        engine: EngineSettingsInput | None = None,
    ) -> PlaylistType:
        account = _require_account(info)
        max_size: object
        if engine is None:
            min_size = t_high = t_low = base = p_floor = None
            max_size = PlaylistService._UNSET if hasattr(PlaylistService, "_UNSET") else None
        else:
            min_size = engine.min_size
            max_size = engine.max_size  # may be strawberry.UNSET
            t_high = engine.t_high
            t_low = engine.t_low
            base = engine.base
            p_floor = engine.p_floor
        # PlaylistService.update_settings expects a sentinel for max_size.
        from src.queuetip.services.playlist import _UNSET as MAX_SIZE_UNSET
        if max_size is strawberry.UNSET:
            max_size = MAX_SIZE_UNSET
        playlist = await PlaylistService.update_settings(
            account,
            int(id),
            name=name,
            description=description,
            min_size=min_size,
            max_size=max_size,
            t_high=t_high,
            t_low=t_low,
            base=base,
            p_floor=p_floor,
        )
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def regenerate_invite_token(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> RegenerateInviteResult:
        account = _require_account(info)
        token = await PlaylistService.regenerate_invite_token(account, int(id))
        return RegenerateInviteResult(invite_token=token)

    @strawberry.mutation
    async def delete_playlist(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        account = _require_account(info)
        await PlaylistService.delete(account, int(id))
        return DeletePlaylistResult(deleted=True)
```

Place the new top-level types (`DeletePlaylistResult`, `RegenerateInviteResult`, helpers) above the `Mutation` class. Add the four `@strawberry.mutation` methods inside the existing `Mutation` class.

- [ ] **Step 2: Schema sanity check** — `docker compose exec -T web python -c "import django; django.setup(); from src.queuetip.schema import schema; print('ok')"`. Expected: `ok`.
- [ ] **Step 3: Commit**

```bash
git add api/src/queuetip/schema/mutation.py
git commit --no-gpg-sign -m "feat(queuetip): playlist CRUD mutations"
```

---

### Task 8: Mutations — membership + integration tests

**Files:**
- Modify: `api/src/queuetip/schema/mutation.py` (add membership mutations)
- Create: `api/tests/integration/queuetip/test_playlists_api.py`

Adds `joinPlaylist`, `leavePlaylist`, `kickMember`, `promoteMember`. End-to-end integration tests cover Tasks 6–8 in one go.

- [ ] **Step 1: Add membership mutations** to `Mutation` class in `mutation.py`. Also add the necessary import: `from ..services.membership import MembershipService`. Then inside `Mutation`:

```python
    @strawberry.mutation
    async def join_playlist(
        self, info: Info[QueuetipContext, None], invite_token: str
    ) -> PlaylistType:
        account = _require_account(info)
        await MembershipService.join(account, invite_token)
        playlist = await PlaylistService.get_by_invite_token(invite_token)
        return await _build_playlist_type(playlist)

    @strawberry.mutation
    async def leave_playlist(
        self, info: Info[QueuetipContext, None], id: strawberry.ID
    ) -> DeletePlaylistResult:
        account = _require_account(info)
        await MembershipService.leave(account, int(id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def kick_member(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        account_id: strawberry.ID,
    ) -> DeletePlaylistResult:
        actor = _require_account(info)
        await MembershipService.kick(actor, int(playlist_id), int(account_id))
        return DeletePlaylistResult(deleted=True)

    @strawberry.mutation
    async def promote_member(
        self,
        info: Info[QueuetipContext, None],
        playlist_id: strawberry.ID,
        account_id: strawberry.ID,
    ) -> PlaylistType:
        actor = _require_account(info)
        await MembershipService.promote(actor, int(playlist_id), int(account_id))
        playlist = await PlaylistService.get_by_id(int(playlist_id))
        return await _build_playlist_type(playlist)
```

- [ ] **Step 2: Write integration tests** at `api/tests/integration/queuetip/test_playlists_api.py`:

```python
"""End-to-end GraphQL integration tests for Phase 1B playlist + membership ops."""

import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership
from src.queuetip.app import app
from src.queuetip.auth import SESSION_COOKIE, make_session_token


def _authed_client(account_id: int) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(SESSION_COOKIE, make_session_token(account_id))
    return client


async def _gql(client: httpx.AsyncClient, query: str, variables: dict | None = None):
    payload: dict = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    response = await client.post("/graphql", json=payload)
    return response.json()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_playlist_returns_playlist_with_owner_member():
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            """
            mutation($name: String!) {
              createPlaylist(name: $name) {
                id name inviteToken members { account { displayName } role }
              }
            }
            """,
            {"name": "Friday Mix"},
        )
    data = result["data"]["createPlaylist"]
    assert data["name"] == "Friday Mix"
    assert len(data["members"]) == 1
    assert data["members"][0]["role"] == "owner"
    assert data["members"][0]["account"]["displayName"] == "Owner"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_join_via_invite_token_adds_member():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    async with _authed_client(joiner.id) as client:
        result = await _gql(
            client,
            """
            mutation($t: String!) {
              joinPlaylist(inviteToken: $t) {
                members { account { displayName } role }
              }
            }
            """,
            {"t": p.invite_token},
        )
    roles = {m["account"]["displayName"]: m["role"] for m in result["data"]["joinPlaylist"]["members"]}
    assert roles == {"O": "owner", "J": "member"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_anonymous_playlist_by_invite_token_returns_metadata():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(name="Public Mix", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        result = await _gql(
            client,
            """
            query($t: String!) {
              playlist(inviteToken: $t) { name members { account { displayName } } }
            }
            """,
            {"t": p.invite_token},
        )
    assert result["data"]["playlist"]["name"] == "Public Mix"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_owner_cannot_update_settings():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    intruder = await sync_to_async(Account.objects.create)(display_name="X")
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=intruder, role="member"
    )
    async with _authed_client(intruder.id) as client:
        result = await _gql(
            client,
            """
            mutation($id: ID!) {
              updatePlaylistSettings(id: $id, name: "Hacked") { name }
            }
            """,
            {"id": str(p.id)},
        )
    assert "errors" in result
    assert any("owner" in e["message"].lower() for e in result["errors"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_owner_can_kick_and_promote():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    member = await sync_to_async(Account.objects.create)(display_name="M")
    other = await sync_to_async(Account.objects.create)(display_name="X")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    for acct, role in [(owner, "owner"), (member, "member"), (other, "member")]:
        await sync_to_async(PlaylistMembership.objects.create)(
            playlist=p, account=acct, role=role
        )
    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            "mutation($p: ID!, $a: ID!) { promoteMember(playlistId: $p, accountId: $a) { name } }",
            {"p": str(p.id), "a": str(member.id)},
        )
        assert "errors" not in result
        result = await _gql(
            client,
            "mutation($p: ID!, $a: ID!) { kickMember(playlistId: $p, accountId: $a) { deleted } }",
            {"p": str(p.id), "a": str(other.id)},
        )
        assert result["data"]["kickMember"]["deleted"] is True
    # Member should now be owner, other should be gone
    m = await sync_to_async(
        lambda: PlaylistMembership.objects.get(playlist=p, account=member)
    )()
    assert m.role == "owner"
    exists = await sync_to_async(
        PlaylistMembership.objects.filter(playlist=p, account=other).exists
    )()
    assert exists is False
```

- [ ] **Step 3: Run all integration + unit tests:**
`docker compose exec -T web python -m pytest tests/unit/queuetip/ tests/integration/queuetip/ -q`
Expected: ALL pass (Phase 0 + 1A + 1B).

- [ ] **Step 4: Commit**

```bash
git add api/src/queuetip/schema/mutation.py tests/integration/queuetip/test_playlists_api.py
git commit --no-gpg-sign -m "feat(queuetip): membership mutations + 1B integration tests"
```

---

## Self-Review

**Spec coverage** (against `2026-05-19-queuetip-phase-1-core-design.md`):
- Hardening (1A deferred): Task 1 ✅
- Permissions module: Task 2 ✅
- PlaylistType / EngineSettings: Task 3 ✅
- Playlist CRUD service + tests: Task 4 ✅
- Membership service + tests: Task 5 ✅
- `myPlaylists`, `playlist(id|inviteToken)` queries: Task 6 ✅
- `createPlaylist`, `updatePlaylistSettings`, `regenerateInviteToken`, `deletePlaylist`: Task 7 ✅
- `joinPlaylist`, `leavePlaylist`, `kickMember`, `promoteMember` + integration tests: Task 8 ✅
- Deferred to Plan 1C: `catalogSearch` query, `contributeFrom*` mutations, voting mutations, `bulkImportPlaylist` mutation + Celery task.

**Type consistency:**
- `EngineSettingsInput.max_size = strawberry.UNSET` paired with `PlaylistService._UNSET` sentinel (Tasks 3, 4, 7) — distinct sentinels for "unchanged" vs "set to None" preserved across the boundary.
- `PlaylistService.list_memberships` returns `list[PlaylistMembership]` consumed by `PlaylistType.from_model(playlist, memberships)` (Tasks 3, 4) — no lazy-load trap.
- Service exceptions (`PermissionDeniedError`, `NotFoundError`, `AuthRequiredError`) surface to GraphQL via Strawberry's default exception handling.

**Placeholder scan:** none.
