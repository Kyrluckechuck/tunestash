# Queuetip Phase 1A — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Queuetip Django app, its data model, magic-link authentication, and a separate public ASGI process exposing an authenticated (but otherwise empty) GraphQL API.

**Architecture:** A new Django app `queuetip` (at `api/queuetip/`) holds the models. A new FastAPI/Strawberry layer (at `api/src/queuetip/`, beside the Phase 0 `resolution/` package) holds the public GraphQL schema, magic-link auth, and the public ASGI app. Auth uses `django.core.signing` (not `django-sesame`, which is coupled to `AUTH_USER_MODEL`). A new `queuetip` Docker service runs the public app from the same image.

**Tech Stack:** Django 5.1+, Strawberry GraphQL, FastAPI, `django.core.signing`, pytest / pytest-django.

**Spec:** `docs/specs/2026-05-19-queuetip-phase-1-core-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/queuetip/__init__.py` | Empty package marker |
| `api/queuetip/apps.py` | `QueuetipConfig` app config |
| `api/queuetip/models.py` | All 7 Queuetip models |
| `api/queuetip/migrations/__init__.py` | Migrations package marker |
| `api/queuetip/migrations/0001_initial.py` | Generated initial migration |
| `api/settings.py` *(modify)* | Register app; email + Queuetip settings |
| `api/src/queuetip/auth.py` | Magic-link + session signed-token functions |
| `api/src/queuetip/email.py` | Magic-link email delivery |
| `api/src/queuetip/context.py` | GraphQL context getter (resolves `current_account`) |
| `api/src/queuetip/graphql_types.py` | `AccountType` Strawberry type |
| `api/src/queuetip/schema/__init__.py` | Strawberry schema object |
| `api/src/queuetip/schema/query.py` | `Query` type (`me`) |
| `api/src/queuetip/schema/mutation.py` | `Mutation` type (`requestMagicLink`) |
| `api/src/queuetip/routes.py` | FastAPI auth routes (`/auth/verify`, `/auth/logout`) |
| `api/src/queuetip/app.py` | Public ASGI FastAPI app |
| `docker-compose.yml` *(modify)* | Base `queuetip` service |
| `docker-compose.override.yml` *(modify)* | Dev `queuetip` service |
| `api/tests/unit/queuetip/test_models.py` | Model constraint tests |
| `api/tests/unit/queuetip/test_auth.py` | Token round-trip / expiry tests |
| `api/tests/unit/queuetip/test_email.py` | Email delivery test |
| `api/tests/integration/queuetip/__init__.py` | Package marker |
| `api/tests/integration/queuetip/test_public_api.py` | Public app integration tests |

**Naming note:** Two packages are both called `queuetip` — `queuetip` (Django app, project root) and `src.queuetip` (FastAPI layer). They never import circularly: `src.queuetip` imports `queuetip.models`; the Django app never imports `src.queuetip`.

---

### Task 1: Django app scaffold + settings registration

**Files:**
- Create: `api/queuetip/__init__.py`
- Create: `api/queuetip/apps.py`
- Create: `api/queuetip/migrations/__init__.py`
- Modify: `api/settings.py`

- [ ] **Step 1: Create the package markers and app config**

`api/queuetip/__init__.py` — empty file.

`api/queuetip/migrations/__init__.py` — empty file.

`api/queuetip/apps.py`:

```python
from django.apps import AppConfig


class QueuetipConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "queuetip"
```

- [ ] **Step 2: Register the app in INSTALLED_APPS**

In `api/settings.py`, in the `INSTALLED_APPS` list passed to `DjangoDynaconf` (currently ending `"library_manager",`), add `"queuetip"` immediately after:

```python
        "library_manager",
        "queuetip",
        # Dev-only apps are appended conditionally below
```

- [ ] **Step 3: Add Queuetip + email settings**

Append to the end of `api/settings.py`:

```python
# ── Queuetip ────────────────────────────────────────────────────────────────
# Public base URL of the Queuetip ASGI process — used to build magic-link URLs.
QUEUETIP_PUBLIC_URL = os.getenv("QUEUETIP_PUBLIC_URL", "http://localhost:5050")
# Origin of the Queuetip frontend — used for CORS on the public process.
QUEUETIP_FRONTEND_URL = os.getenv("QUEUETIP_FRONTEND_URL", "http://localhost:3001")

# Email — magic-link delivery. Console backend by default (links print to logs);
# set `email_host` in settings.yaml to switch to real SMTP delivery.
_email_host = settings.get("email_host", None)
if _email_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _email_host
    EMAIL_PORT = int(settings.get("email_port", 587))
    EMAIL_HOST_USER = settings.get("email_host_user", "")
    EMAIL_HOST_PASSWORD = settings.get("email_host_password", "")
    EMAIL_USE_TLS = bool(settings.get("email_use_tls", True))
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = settings.get(
    "default_from_email", "Queuetip <queuetip@localhost>"
)
```

- [ ] **Step 4: Verify the app loads**

Run: `docker compose exec -T web python manage.py check queuetip`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add api/queuetip/__init__.py api/queuetip/apps.py api/queuetip/migrations/__init__.py api/settings.py
git commit -m "feat(queuetip): scaffold queuetip Django app + settings"
```

---

### Task 2: Models + initial migration

**Files:**
- Create: `api/queuetip/models.py`
- Create: `api/queuetip/migrations/0001_initial.py` (generated)
- Test: `api/tests/unit/queuetip/test_models.py`

Note: `pytest.ini` runs with `--nomigrations`, so tests build tables directly from the models — but the migration must still be generated and committed for real deployments.

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_models.py`:

```python
import pytest
from django.db import IntegrityError
from django.db.utils import DataError

from queuetip.models import (
    Account,
    AuthIdentity,
    Contribution,
    Playlist,
    PlaylistMembership,
    Vote,
)
from tests.factories import ArtistFactory, SongFactory


@pytest.mark.django_db
def test_invite_token_autogenerated_and_unique():
    a = Account.objects.create(display_name="Owner")
    p1 = Playlist.objects.create(name="One", created_by=a)
    p2 = Playlist.objects.create(name="Two", created_by=a)
    assert p1.invite_token
    assert p1.invite_token != p2.invite_token


@pytest.mark.django_db
def test_auth_identity_provider_identifier_unique():
    a = Account.objects.create(display_name="Owner")
    AuthIdentity.objects.create(account=a, provider="magic_link", identifier="x@y.z")
    with pytest.raises(IntegrityError):
        AuthIdentity.objects.create(
            account=a, provider="magic_link", identifier="x@y.z"
        )


@pytest.mark.django_db
def test_contribution_unique_per_playlist_song():
    a = Account.objects.create(display_name="Owner")
    p = Playlist.objects.create(name="P", created_by=a)
    song = SongFactory(primary_artist=ArtistFactory())
    Contribution.objects.create(playlist=p, song=song, contributed_by=a)
    with pytest.raises(IntegrityError):
        Contribution.objects.create(playlist=p, song=song, contributed_by=a)


@pytest.mark.django_db
def test_vote_value_check_constraint_rejects_zero():
    a = Account.objects.create(display_name="Owner")
    p = Playlist.objects.create(name="P", created_by=a)
    song = SongFactory(primary_artist=ArtistFactory())
    c = Contribution.objects.create(playlist=p, song=song, contributed_by=a)
    with pytest.raises(IntegrityError):
        Vote.objects.create(contribution=c, account=a, value=0)


@pytest.mark.django_db
def test_membership_unique_per_playlist_account():
    a = Account.objects.create(display_name="Owner")
    p = Playlist.objects.create(name="P", created_by=a)
    PlaylistMembership.objects.create(playlist=p, account=a, role="owner")
    with pytest.raises(IntegrityError):
        PlaylistMembership.objects.create(playlist=p, account=a, role="member")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'queuetip.models'` (or import error).

- [ ] **Step 3: Write the models**

`api/queuetip/models.py`:

```python
"""Queuetip core models — accounts, playlists, contributions, voting.

This Django app backs the Queuetip collaborative-playlist feature. It shares
TuneStash's database; `Contribution.song` is a real FK into `library_manager`.
"""

import secrets

from django.db import models


def generate_invite_token() -> str:
    """Return a URL-safe random token for a playlist invite link."""
    return secrets.token_urlsafe(16)


class Account(models.Model):
    """A Queuetip user. Unrelated to TuneStash's operator; not AUTH_USER_MODEL."""

    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.display_name


class AuthIdentity(models.Model):
    """A login identity for an Account — one row per auth provider."""

    PROVIDER_MAGIC_LINK = "magic_link"
    PROVIDER_CHOICES = [(PROVIDER_MAGIC_LINK, "Magic link")]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="identities"
    )
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    identifier = models.CharField(max_length=254)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "identifier"],
                name="queuetip_authidentity_provider_identifier_unique",
            )
        ]


class Playlist(models.Model):
    """A collaborative playlist. Engine knobs are stored now, used in Phase 2."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="created_playlists"
    )
    invite_token = models.CharField(
        max_length=64, unique=True, default=generate_invite_token
    )
    created_at = models.DateTimeField(auto_now_add=True)
    min_size = models.PositiveSmallIntegerField(default=0)
    max_size = models.PositiveSmallIntegerField(null=True, blank=True)
    t_high = models.PositiveSmallIntegerField(default=3)
    t_low = models.PositiveSmallIntegerField(default=3)
    base = models.FloatField(default=0.85)
    p_floor = models.FloatField(default=0.15)

    def __str__(self) -> str:
        return self.name


class PlaylistMembership(models.Model):
    """Links an Account to a Playlist with a role."""

    ROLE_OWNER = "owner"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_OWNER, "Owner"), (ROLE_MEMBER, "Member")]

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="memberships"
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "account"], name="queuetip_membership_unique"
            )
        ]


class Contribution(models.Model):
    """One song contributed to a playlist."""

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="contributions"
    )
    song = models.ForeignKey(
        "library_manager.Song",
        on_delete=models.PROTECT,
        related_name="queuetip_contributions",
    )
    contributed_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="contributions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "song"], name="queuetip_contribution_unique"
            )
        ]


class Vote(models.Model):
    """A +1/-1 vote by an Account on a Contribution. No row = no vote."""

    contribution = models.ForeignKey(
        Contribution, on_delete=models.CASCADE, related_name="votes"
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="votes"
    )
    value = models.SmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["contribution", "account"], name="queuetip_vote_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(value__in=[-1, 1]),
                name="queuetip_vote_value_valid",
            ),
        ]


class BulkImportJob(models.Model):
    """Tracks one async bulk-import run so the importer can poll for results."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="import_jobs"
    )
    requested_by = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="import_jobs"
    )
    source_url = models.URLField(max_length=500)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    added_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    unresolved_count = models.PositiveIntegerField(default=0)
    unresolved_titles = models.JSONField(default=list)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
```

Note: `CheckConstraint(condition=...)` requires Django 5.1+. The repo emits the `RemovedInDjango60Warning` for `check=`, confirming it is on 5.1+.

- [ ] **Step 4: Generate the migration**

Run: `docker compose exec -T web python manage.py makemigrations queuetip`
Expected: creates `api/queuetip/migrations/0001_initial.py` listing all 7 models.

- [ ] **Step 5: Apply the migration**

Run: `docker compose exec -T web python manage.py migrate queuetip`
Expected: `Applying queuetip.0001_initial... OK`

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_models.py -q`
Expected: PASS — 5 tests.

- [ ] **Step 7: Commit**

```bash
git add api/queuetip/models.py api/queuetip/migrations/0001_initial.py tests/unit/queuetip/test_models.py
git commit -m "feat(queuetip): core models — accounts, playlists, contributions, voting"
```

---

### Task 3: Auth token module

**Files:**
- Create: `api/src/queuetip/auth.py`
- Test: `api/tests/unit/queuetip/test_auth.py`

`django.core.signing.dumps/loads` produce/verify signed, timestamped tokens. `loads` raises `SignatureExpired` past `max_age` and `BadSignature` for tampering — both subclasses of `BadSignature`.

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_auth.py`:

```python
import time
from unittest.mock import patch

import pytest

from src.queuetip import auth


def test_magic_link_token_round_trip():
    token = auth.make_magic_link_token(42)
    assert auth.read_magic_link_token(token) == 42


def test_session_token_round_trip():
    token = auth.make_session_token(7)
    assert auth.read_session_token(token) == 7


def test_magic_and_session_tokens_are_not_interchangeable():
    magic = auth.make_magic_link_token(1)
    with pytest.raises(auth.InvalidTokenError):
        auth.read_session_token(magic)


def test_tampered_token_rejected():
    token = auth.make_magic_link_token(1)
    with pytest.raises(auth.InvalidTokenError):
        auth.read_magic_link_token(token + "x")


def test_expired_magic_link_token_rejected():
    token = auth.make_magic_link_token(1)
    with patch.object(auth, "MAGIC_LINK_MAX_AGE", -1):
        with pytest.raises(auth.InvalidTokenError):
            auth.read_magic_link_token(token)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.auth'`.

- [ ] **Step 3: Write the auth module**

`api/src/queuetip/auth.py`:

```python
"""Magic-link and session tokens for Queuetip, built on django.core.signing.

Using Django's own signing framework (vetted, maintained) instead of
django-sesame, which is coupled to AUTH_USER_MODEL — Queuetip's Account is a
standalone model, not the project user model.
"""

from django.core import signing

# Cookie carrying the session token on the public process.
SESSION_COOKIE = "queuetip_session"

_MAGIC_SALT = "queuetip.magic-link"
_SESSION_SALT = "queuetip.session"

MAGIC_LINK_MAX_AGE = 15 * 60  # 15 minutes
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


class InvalidTokenError(Exception):
    """Raised when a token is malformed, tampered with, or expired."""


def make_magic_link_token(account_id: int) -> str:
    """Sign a short-lived token identifying an account for magic-link login."""
    return signing.dumps({"aid": account_id}, salt=_MAGIC_SALT)


def read_magic_link_token(token: str) -> int:
    """Return the account id from a magic-link token, or raise InvalidTokenError."""
    try:
        data = signing.loads(token, salt=_MAGIC_SALT, max_age=MAGIC_LINK_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidTokenError(str(exc)) from exc
    return int(data["aid"])


def make_session_token(account_id: int) -> str:
    """Sign a long-lived session token identifying an account."""
    return signing.dumps({"aid": account_id}, salt=_SESSION_SALT)


def read_session_token(token: str) -> int:
    """Return the account id from a session token, or raise InvalidTokenError."""
    try:
        data = signing.loads(token, salt=_SESSION_SALT, max_age=SESSION_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidTokenError(str(exc)) from exc
    return int(data["aid"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_auth.py -q`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/auth.py tests/unit/queuetip/test_auth.py
git commit -m "feat(queuetip): magic-link + session signed-token module"
```

---

### Task 4: Magic-link email delivery

**Files:**
- Create: `api/src/queuetip/email.py`
- Test: `api/tests/unit/queuetip/test_email.py`

- [ ] **Step 1: Write the failing test**

`api/tests/unit/queuetip/test_email.py`:

```python
import pytest

from src.queuetip.email import magic_link_url, send_magic_link_email


def test_magic_link_url_includes_token():
    url = magic_link_url("abc123")
    assert url.endswith("/auth/verify?token=abc123")
    assert "://" in url


@pytest.mark.django_db
def test_send_magic_link_email_delivers_with_link(mailoutbox):
    send_magic_link_email("friend@example.com", "tok456")
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["friend@example.com"]
    assert "/auth/verify?token=tok456" in message.body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_email.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.email'`.

- [ ] **Step 3: Write the email module**

`api/src/queuetip/email.py`:

```python
"""Magic-link email delivery for Queuetip."""

from django.conf import settings
from django.core.mail import send_mail


def magic_link_url(token: str) -> str:
    """Build the public magic-link verification URL for a token."""
    base = getattr(
        settings, "QUEUETIP_PUBLIC_URL", "http://localhost:5050"
    ).rstrip("/")
    return f"{base}/auth/verify?token={token}"


def send_magic_link_email(email: str, token: str) -> None:
    """Email a one-time sign-in link to the given address."""
    url = magic_link_url(token)
    send_mail(
        subject="Your Queuetip sign-in link",
        message=(
            f"Click the link below to sign in to Queuetip:\n\n{url}\n\n"
            "This link expires in 15 minutes. If you did not request it, "
            "you can ignore this email."
        ),
        from_email=getattr(
            settings, "DEFAULT_FROM_EMAIL", "queuetip@localhost"
        ),
        recipient_list=[email],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_email.py -q`
Expected: PASS — 2 tests.

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/email.py tests/unit/queuetip/test_email.py
git commit -m "feat(queuetip): magic-link email delivery"
```

---

### Task 5: GraphQL context, AccountType, and `me` query

**Files:**
- Create: `api/src/queuetip/context.py`
- Create: `api/src/queuetip/graphql_types.py`
- Create: `api/src/queuetip/schema/__init__.py`
- Create: `api/src/queuetip/schema/query.py`
- Test: covered by Task 8's integration tests (the schema is not independently runnable without the app); add a focused unit test here for the context getter.
- Test: `api/tests/unit/queuetip/test_context.py`

- [ ] **Step 1: Write the failing test**

`api/tests/unit/queuetip/test_context.py`:

```python
import pytest
from starlette.requests import Request

from src.queuetip import auth
from src.queuetip.context import get_context
from queuetip.models import Account


def _request_with_cookies(cookies: dict) -> Request:
    header = "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()
    scope = {
        "type": "http",
        "headers": [(b"cookie", header)] if cookies else [],
    }
    return Request(scope)


@pytest.mark.django_db
async def test_get_context_anonymous_without_cookie():
    ctx = await get_context(_request_with_cookies({}))
    assert ctx.account is None


@pytest.mark.django_db
async def test_get_context_resolves_account_from_session_cookie():
    account = Account.objects.create(display_name="Jo")
    token = auth.make_session_token(account.id)
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: token}))
    assert ctx.account is not None
    assert ctx.account.id == account.id


@pytest.mark.django_db
async def test_get_context_ignores_invalid_session_cookie():
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: "garbage"}))
    assert ctx.account is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_context.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.context'`.

- [ ] **Step 3: Write the context module**

`api/src/queuetip/context.py`:

```python
"""GraphQL request context for the Queuetip public process.

Resolves the current Account from the signed session cookie. Resolvers read
`info.context.account`; it is None for anonymous requests.
"""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from starlette.requests import Request

from queuetip.models import Account

from .auth import SESSION_COOKIE, InvalidTokenError, read_session_token


@dataclass
class QueuetipContext:
    """Per-request GraphQL context."""

    request: Request
    account: Account | None


async def get_context(request: Request) -> QueuetipContext:
    """Build the GraphQL context, resolving the session cookie to an Account."""
    account: Account | None = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            account_id = read_session_token(token)
        except InvalidTokenError:
            account_id = None
        if account_id is not None:
            account = await sync_to_async(
                Account.objects.filter(id=account_id).first
            )()
    return QueuetipContext(request=request, account=account)
```

- [ ] **Step 4: Write the AccountType**

`api/src/queuetip/graphql_types.py`:

```python
"""Strawberry GraphQL types for Queuetip."""

import datetime

import strawberry

from queuetip.models import Account


@strawberry.type
class AccountType:
    """A Queuetip user account."""

    id: strawberry.ID
    display_name: str
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, account: Account) -> "AccountType":
        """Build an AccountType from a Django Account row."""
        return cls(
            id=strawberry.ID(str(account.id)),
            display_name=account.display_name,
            created_at=account.created_at,
        )
```

- [ ] **Step 5: Write the Query type**

`api/src/queuetip/schema/query.py`:

```python
"""Queuetip GraphQL Query type."""

import strawberry
from strawberry.types import Info

from ..context import QueuetipContext
from ..graphql_types import AccountType


@strawberry.type
class Query:
    """Root query for the Queuetip public API."""

    @strawberry.field
    def me(self, info: Info) -> AccountType | None:
        """Return the currently signed-in account, or null if anonymous."""
        ctx: QueuetipContext = info.context
        if ctx.account is None:
            return None
        return AccountType.from_model(ctx.account)
```

- [ ] **Step 6: Write the schema object**

`api/src/queuetip/schema/__init__.py`:

```python
"""Queuetip public GraphQL schema."""

import strawberry

from .query import Query

schema = strawberry.Schema(query=Query)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_context.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 8: Commit**

```bash
git add api/src/queuetip/context.py api/src/queuetip/graphql_types.py api/src/queuetip/schema/ tests/unit/queuetip/test_context.py
git commit -m "feat(queuetip): GraphQL context, AccountType, me query"
```

---

### Task 6: `requestMagicLink` mutation

**Files:**
- Create: `api/src/queuetip/schema/mutation.py`
- Modify: `api/src/queuetip/schema/__init__.py`
- Test: `api/tests/unit/queuetip/test_mutation_auth.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/unit/queuetip/test_mutation_auth.py`:

```python
import pytest

from queuetip.models import Account, AuthIdentity
from src.queuetip.schema.mutation import _request_magic_link


@pytest.mark.django_db
async def test_request_magic_link_creates_account_for_new_email(mailoutbox):
    result = await _request_magic_link("New@Example.com", "Newbie")
    assert result.sent is True
    identity = AuthIdentity.objects.get(provider="magic_link", identifier="new@example.com")
    assert identity.account.display_name == "Newbie"
    assert len(mailoutbox) == 1


@pytest.mark.django_db
async def test_request_magic_link_unknown_email_without_name_does_not_send(mailoutbox):
    result = await _request_magic_link("ghost@example.com", None)
    assert result.sent is False
    assert Account.objects.count() == 0
    assert len(mailoutbox) == 0


@pytest.mark.django_db
async def test_request_magic_link_existing_account_reuses_it(mailoutbox):
    account = Account.objects.create(display_name="Existing")
    AuthIdentity.objects.create(
        account=account, provider="magic_link", identifier="known@example.com"
    )
    result = await _request_magic_link("known@example.com", None)
    assert result.sent is True
    assert Account.objects.count() == 1
    assert len(mailoutbox) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_mutation_auth.py -q`
Expected: FAIL — import error on `src.queuetip.schema.mutation`.

- [ ] **Step 3: Write the Mutation type**

`api/src/queuetip/schema/mutation.py`:

```python
"""Queuetip GraphQL Mutation type."""

import strawberry
from asgiref.sync import sync_to_async

from queuetip.models import Account, AuthIdentity

from ..auth import make_magic_link_token
from ..email import send_magic_link_email


@strawberry.type
class RequestMagicLinkResult:
    """Outcome of a magic-link request."""

    sent: bool
    message: str


async def _request_magic_link(
    email: str, display_name: str | None
) -> RequestMagicLinkResult:
    """Find or create an account for `email` and email it a sign-in link.

    An unknown email with no display name cannot sign up — it gets a result
    with `sent=False` asking for a name. Known emails ignore `display_name`.
    """
    email = email.strip().lower()

    def find_identity() -> AuthIdentity | None:
        return (
            AuthIdentity.objects.filter(
                provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=email
            )
            .select_related("account")
            .first()
        )

    identity = await sync_to_async(find_identity)()

    if identity is None:
        if not display_name or not display_name.strip():
            return RequestMagicLinkResult(
                sent=False,
                message="No account exists for that email. "
                "Provide a display name to sign up.",
            )

        def create_account() -> Account:
            account = Account.objects.create(display_name=display_name.strip())
            AuthIdentity.objects.create(
                account=account,
                provider=AuthIdentity.PROVIDER_MAGIC_LINK,
                identifier=email,
            )
            return account

        account = await sync_to_async(create_account)()
    else:
        account = identity.account

    token = make_magic_link_token(account.id)
    await sync_to_async(send_magic_link_email)(email, token)
    return RequestMagicLinkResult(
        sent=True, message="Check your email for a sign-in link."
    )


@strawberry.type
class Mutation:
    """Root mutation for the Queuetip public API."""

    @strawberry.mutation
    async def request_magic_link(
        self, email: str, display_name: str | None = None
    ) -> RequestMagicLinkResult:
        """Request a magic-link sign-in email. Creates an account if needed."""
        return await _request_magic_link(email, display_name)
```

- [ ] **Step 4: Wire the Mutation into the schema**

Replace `api/src/queuetip/schema/__init__.py` with:

```python
"""Queuetip public GraphQL schema."""

import strawberry

from .mutation import Mutation
from .query import Query

schema = strawberry.Schema(query=Query, mutation=Mutation)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec -T web python -m pytest tests/unit/queuetip/test_mutation_auth.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 6: Commit**

```bash
git add api/src/queuetip/schema/ tests/unit/queuetip/test_mutation_auth.py
git commit -m "feat(queuetip): requestMagicLink mutation"
```

---

### Task 7: Auth routes (`/auth/verify`, `/auth/logout`)

**Files:**
- Create: `api/src/queuetip/routes.py`
- Test: covered by Task 8's integration tests (routes need the mounted app).

- [ ] **Step 1: Write the routes**

`api/src/queuetip/routes.py`:

```python
"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

from django.conf import settings
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    InvalidTokenError,
    make_session_token,
    read_magic_link_token,
)

router = APIRouter()


@router.get("/auth/verify")
def verify(token: str) -> Response:
    """Verify a magic-link token, set the session cookie, confirm sign-in."""
    try:
        account_id = read_magic_link_token(token)
    except InvalidTokenError:
        return HTMLResponse(
            "<h1>This sign-in link is invalid or has expired.</h1>"
            "<p>Request a new one to sign in.</p>",
            status_code=400,
        )

    response = HTMLResponse(
        "<h1>You're signed in to Queuetip.</h1>"
        "<p>You can close this tab and return to the app.</p>"
    )
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(account_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
    )
    return response


@router.post("/auth/logout")
def logout() -> Response:
    """Clear the session cookie."""
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE)
    return response
```

- [ ] **Step 2: Commit**

```bash
git add api/src/queuetip/routes.py
git commit -m "feat(queuetip): magic-link verify + logout routes"
```

(Routes are exercised by the Task 8 integration tests once the app mounts them.)

---

### Task 8: Public ASGI app

**Files:**
- Create: `api/src/queuetip/app.py`
- Create: `api/tests/integration/queuetip/__init__.py` (empty)
- Test: `api/tests/integration/queuetip/test_public_api.py`

- [ ] **Step 1: Write the failing integration tests**

Create empty `api/tests/integration/queuetip/__init__.py`.

`api/tests/integration/queuetip/test_public_api.py`:

```python
import pytest
from starlette.testclient import TestClient

from queuetip.models import Account
from src.queuetip.app import app
from src.queuetip.auth import (
    SESSION_COOKIE,
    make_magic_link_token,
    make_session_token,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.django_db
def test_me_is_null_when_anonymous(client):
    response = client.post("/graphql", json={"query": "{ me { id } }"})
    assert response.status_code == 200
    assert response.json()["data"]["me"] is None


@pytest.mark.django_db
def test_me_returns_account_with_session_cookie(client):
    account = Account.objects.create(display_name="Jo")
    client.cookies.set(SESSION_COOKIE, make_session_token(account.id))
    response = client.post(
        "/graphql", json={"query": "{ me { id displayName } }"}
    )
    data = response.json()["data"]["me"]
    assert data["displayName"] == "Jo"
    assert data["id"] == str(account.id)


@pytest.mark.django_db
def test_verify_route_sets_session_cookie(client):
    account = Account.objects.create(display_name="Jo")
    token = make_magic_link_token(account.id)
    response = client.get("/auth/verify", params={"token": token})
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies


def test_verify_route_rejects_bad_token(client):
    response = client.get("/auth/verify", params={"token": "garbage"})
    assert response.status_code == 400


def test_tunestash_admin_schema_is_not_mounted(client):
    # The TuneStash admin schema exposes an `artists` root query; Queuetip's
    # schema does not. A query for it must fail schema validation.
    response = client.post("/graphql", json={"query": "{ artists { id } }"})
    assert response.json().get("errors")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T web python -m pytest tests/integration/queuetip/test_public_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.queuetip.app'`.

- [ ] **Step 3: Write the public ASGI app**

`api/src/queuetip/app.py`:

```python
"""Public-facing Queuetip ASGI application.

Mounts ONLY Queuetip's GraphQL schema and magic-link auth routes. It never
imports TuneStash's admin schema (`src.schema`) — the admin surface is
unreachable from this process by construction (fail-safe).
"""

# pylint: disable=wrong-import-position

import os
import sys
from pathlib import Path

import django

# api/ is three parents up from api/src/queuetip/app.py.
API_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(API_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from django.conf import settings as dj_settings  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from strawberry.fastapi import GraphQLRouter  # noqa: E402


def create_queuetip_app() -> FastAPI:
    """Build the public Queuetip FastAPI app."""
    app = FastAPI(title="Queuetip API", version="1.0.0")

    frontend_origin = getattr(
        dj_settings, "QUEUETIP_FRONTEND_URL", "http://localhost:3001"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .context import get_context
    from .routes import router as auth_router
    from .schema import schema

    app.include_router(
        GraphQLRouter(schema, context_getter=get_context), prefix="/graphql"
    )
    app.include_router(auth_router)

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


app = create_queuetip_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T web python -m pytest tests/integration/queuetip/test_public_api.py -q`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add api/src/queuetip/app.py tests/integration/queuetip/
git commit -m "feat(queuetip): public ASGI app mounting only the Queuetip schema"
```

---

### Task 9: Docker `queuetip` service

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.override.yml`

- [ ] **Step 1: Add the base service**

In `docker-compose.yml`, after the `web` service block (before `frontend`), add:

```yaml
  queuetip:
    image: ${BACKEND_IMAGE:-ghcr.io/kyrluckechuck/tunestash:latest}
    environment:
      - CI=${CI:-false}
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-django-insecure-development-only-key}
      - DJANGO_DEBUG=${DJANGO_DEBUG:-False}
      - POSTGRES_DB=${POSTGRES_DB:-tunestash}
      - POSTGRES_USER=${POSTGRES_USER:-slm_user}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-slm_dev_password}
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - CELERY_BROKER_URL=${CELERY_BROKER_URL:-redis://valkey:6379/0}
      - HOME=/config
      - TUNESTASH_SERVICE=queuetip
      - QUEUETIP_PUBLIC_URL=${QUEUETIP_PUBLIC_URL:-http://localhost:5050}
      - QUEUETIP_FRONTEND_URL=${QUEUETIP_FRONTEND_URL:-http://localhost:3001}
    command: uvicorn src.queuetip.app:app --host 0.0.0.0 --port 5000
    depends_on:
      postgres:
        condition: service_healthy
      web:
        condition: service_healthy
    ports:
      - "${QUEUETIP_PORT:-5050}:5000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health')"]
      interval: 15s
      timeout: 10s
      retries: 6
      start_period: 30s
    restart: unless-stopped
    networks:
      - slm_net
    volumes:
      - config_storage:/config
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 256M
```

Note: `depends_on: web` is for **startup ordering only** (the `web` service runs DB migrations); it is not a runtime dependency. `queuetip` is the only publicly exposed backend service.

- [ ] **Step 2: Add the dev override**

In `docker-compose.override.yml`, after the `web` service block, add:

```yaml
  queuetip:
    build:
      context: .
      target: backend-dev
    command: bash -c "
      echo '🎯 Starting Queuetip public API (DEV MODE)...';
      pip install -r /requirements/requirements.txt -r /requirements/requirements-dev.txt &&
      uvicorn src.queuetip.app:app --host 0.0.0.0 --port 5000 --reload --log-level info
      "
    environment:
      - DJANGO_DEBUG=True
      - INSTALL_DEV_DEPS=true
      - POSTGRES_DB=${POSTGRES_DB:-tunestash}
      - POSTGRES_USER=${POSTGRES_USER:-slm_user}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-slm_dev_password}
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - QUEUETIP_PUBLIC_URL=${QUEUETIP_PUBLIC_URL:-http://localhost:5050}
      - QUEUETIP_FRONTEND_URL=${QUEUETIP_FRONTEND_URL:-http://localhost:3001}
    volumes:
      - ./api:/app
      - ./requirements.txt:/requirements/requirements.txt:ro
      - ./requirements-dev.txt:/requirements/requirements-dev.txt:ro
      - python_packages:/app/.venv
      - pip_cache:/root/.cache/pip
```

- [ ] **Step 3: Validate the compose files**

Run: `docker compose config --quiet`
Expected: no output, exit 0 (the merged compose config is valid).

- [ ] **Step 4: Verify the service builds and serves**

Run: `docker compose up -d queuetip` then `curl -s http://localhost:5050/health`
Expected: `ok`. (If the dev stack is already running, `docker compose up -d queuetip` just adds the new service.)

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.override.yml
git commit -m "feat(queuetip): add public queuetip Docker service"
```

---

## Self-Review

**Spec coverage** (against `2026-05-19-queuetip-phase-1-core-design.md`):
- Package layout (`api/queuetip/` + `api/src/queuetip/`) — Tasks 1–8. ✅
- 7 data models — Task 2. ✅
- `django.core.signing` magic-link + session (not django-sesame) — Task 3. ✅
- Email backend config (console default, SMTP when configured) — Task 1; delivery Task 4. ✅
- Stateless signed session cookie, `HttpOnly`/`SameSite=Lax`/`Secure`-in-prod — Tasks 3, 7. ✅
- GraphQL context resolving `current_account` — Task 5. ✅
- `me` query, `requestMagicLink` mutation — Tasks 5, 6. ✅
- Public ASGI app mounting only Queuetip's schema — Task 8 (incl. a test that the admin schema is absent). ✅
- `queuetip` Docker service, only publicly exposed backend — Task 9. ✅
- Deferred to Plan 1B: playlists/membership/contribution/voting/bulk-import operations, permissions, services. (Models for them exist after Task 2.)

**Placeholder scan:** none — every step contains complete code or an exact command.

**Type consistency:** `QueuetipContext.account` (Task 5) is read by `Query.me` (Task 5) and produced by `get_context` (Task 5). `SESSION_COOKIE`, `make_session_token`, `read_session_token`, `make_magic_link_token`, `read_magic_link_token`, `InvalidTokenError`, `MAGIC_LINK_MAX_AGE`, `SESSION_MAX_AGE` (Task 3) are consumed consistently in Tasks 4, 5, 7, 8. `AccountType.from_model` (Task 5) is called by `Query.me`. `_request_magic_link` / `RequestMagicLinkResult` (Task 6) match their tests. `create_queuetip_app` imports `schema`, `get_context`, `router` — all defined in Tasks 5–7.

This plan produces working, testable software: after Task 9 the Queuetip public API is deployable and serves authenticated `me` / `requestMagicLink` over a separate container. Plan 1B builds the playlist/contribution/voting features on top.
