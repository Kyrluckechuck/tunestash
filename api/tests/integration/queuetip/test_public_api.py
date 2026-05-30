import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account
from src.queuetip.app import app
from src.queuetip.auth import (
    SESSION_COOKIE,
    make_magic_link_token,
    make_session_token,
)
from src.queuetip.auth_flows import create_login_code_challenge, set_account_password


@pytest.fixture
def async_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    async with async_client as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_me_is_null_when_anonymous(async_client):
    async with async_client as client:
        response = await client.post("/graphql", json={"query": "{ me { id } }"})
    assert response.status_code == 200
    assert response.json()["data"]["me"] is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_me_returns_account_with_session_cookie():
    from asgiref.sync import sync_to_async

    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    transport = httpx.ASGITransport(app=app)
    cookies = httpx.Cookies({SESSION_COOKIE: make_session_token(account.id)})
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", cookies=cookies
    ) as client:
        response = await client.post(
            "/graphql",
            json={"query": "{ me { id displayName } }"},
        )
    data = response.json()["data"]["me"]
    assert data["displayName"] == "Jo"
    assert data["id"] == str(account.id)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_verify_route_sets_session_cookie(async_client):
    from asgiref.sync import sync_to_async

    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    token = make_magic_link_token(account.id)
    async with async_client as client:
        response = await client.get("/auth/verify", params={"token": token})
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies
    assert "Open Queuetip" in response.text


@pytest.mark.asyncio
async def test_verify_route_rejects_bad_token(async_client):
    async with async_client as client:
        response = await client.get("/auth/verify", params={"token": "garbage"})
    assert response.status_code == 400
    assert "Back to sign-in" in response.text


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_code_login_sets_session_cookie(async_client):
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    email = "jo@example.com"
    from queuetip.models import AuthIdentity

    await sync_to_async(AuthIdentity.objects.create)(
        account=account, provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=email
    )
    code = await sync_to_async(create_login_code_challenge)(account, email)
    async with async_client as client:
        response = await client.post(
            "/auth/code-login", json={"email": email, "code": code}
        )
    assert response.status_code == 204
    assert SESSION_COOKIE in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_password_login_sets_session_cookie(async_client):
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    email = "jo@example.com"
    from queuetip.models import AuthIdentity

    await sync_to_async(AuthIdentity.objects.create)(
        account=account, provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=email
    )
    await sync_to_async(set_account_password)(account, "correct horse battery staple")
    async with async_client as client:
        response = await client.post(
            "/auth/password-login",
            json={"email": email, "password": "correct horse battery staple"},
        )
    assert response.status_code == 204
    assert SESSION_COOKIE in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_tunestash_admin_schema_is_not_mounted(async_client):
    # The TuneStash admin schema exposes an `artists` root query; Queuetip's
    # schema does not. A query for it must fail schema validation.
    async with async_client as client:
        response = await client.post("/graphql", json={"query": "{ artists { id } }"})
    assert response.json().get("errors")


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
    assert SESSION_COOKIE in set_cookie_header


@pytest.mark.asyncio
async def test_public_settings_allowlist_enforced_by_default(async_client):
    """publicSettings.signupAllowlistEnforced is true when env var is absent or 'true'."""
    import os

    # Ensure the env var is not set to false (default behavior)
    os.environ.pop("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", None)
    async with async_client as client:
        response = await client.post(
            "/graphql",
            json={"query": "{ publicSettings { signupAllowlistEnforced } }"},
        )
    data = response.json()
    assert "errors" not in data, data.get("errors")
    assert data["data"]["publicSettings"]["signupAllowlistEnforced"] is True


@pytest.mark.asyncio
async def test_public_settings_allowlist_disabled_via_env(async_client, monkeypatch):
    """publicSettings.signupAllowlistEnforced is false when env var set to 'false'."""
    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "false")
    async with async_client as client:
        response = await client.post(
            "/graphql",
            json={"query": "{ publicSettings { signupAllowlistEnforced } }"},
        )
    data = response.json()
    assert "errors" not in data, data.get("errors")
    assert data["data"]["publicSettings"]["signupAllowlistEnforced"] is False


def test_schema_has_depth_and_alias_extensions():
    """Verify QueryDepthLimiter and MaxAliasesLimiter are registered on the schema."""
    from strawberry.extensions import MaxAliasesLimiter, QueryDepthLimiter

    from src.queuetip.schema import schema

    # Both extensions are instantiated as instances of their respective classes.
    assert any(
        isinstance(ext, QueryDepthLimiter) for ext in schema.extensions
    ), "QueryDepthLimiter not found in schema extensions"
    assert any(
        isinstance(ext, MaxAliasesLimiter) for ext in schema.extensions
    ), "MaxAliasesLimiter not found in schema extensions"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_normal_depth_query_succeeds(async_client):
    """A well-formed shallow query must not be blocked by the depth limiter."""
    async with async_client as client:
        response = await client.post("/graphql", json={"query": "{ me { id } }"})
    assert response.status_code == 200
    data = response.json()
    assert "errors" not in data or data.get("data") is not None


@pytest.mark.asyncio
async def test_error_masking_hides_unexpected_exceptions(async_client):
    """Unhandled resolver exceptions must be replaced with a generic message."""
    from unittest.mock import AsyncMock, patch

    from src.queuetip.schema.query import Query

    with patch.object(Query, "me", new_callable=lambda: property(lambda self: None)):
        # Patch catalog_search to raise an unexpected error
        with patch(
            "src.queuetip.schema.query._catalog_search",
            new=AsyncMock(side_effect=ZeroDivisionError("boom")),
        ):
            async with async_client as client:
                response = await client.post(
                    "/graphql",
                    json={"query": '{ catalogSearch(query: "test") { title } }'},
                )
    body = response.json()
    assert "errors" in body
    # The original "boom" message must not appear
    error_messages = [e.get("message", "") for e in body["errors"]]
    assert all("boom" not in msg for msg in error_messages)
    assert any("internal server error" in msg.lower() for msg in error_messages)


@pytest.mark.asyncio
async def test_introspection_enabled_in_debug_mode(async_client):
    """Introspection must work when DEBUG=True (default in tests)."""
    introspection_query = "{ __schema { types { name } } }"
    async with async_client as client:
        response = await client.post("/graphql", json={"query": introspection_query})
    body = response.json()
    # In DEBUG mode (tests), introspection must succeed
    assert "data" in body
    assert body["data"] is not None


@pytest.mark.asyncio
async def test_security_headers_present_on_health(async_client):
    """The security-headers middleware must attach hardening headers to all responses."""
    async with async_client as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "same-origin"
    assert response.headers.get("permissions-policy") == "interest-cohort=()"
    # HSTS is only set outside DEBUG — test env runs with DEBUG=True, so absent here.


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_sign_out_everywhere_invalidates_old_session():
    """After signOutEverywhere, a follow-up request with the old session returns me=null."""
    from asgiref.sync import sync_to_async

    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    old_token = make_session_token(account.id, session_epoch=0)

    transport = httpx.ASGITransport(app=app)

    # Sign out everywhere using old session
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={SESSION_COOKIE: old_token},
    ) as client:
        resp = await client.post(
            "/graphql",
            json={
                "query": "mutation { signOutEverywhere { success } }",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "errors" not in body, body.get("errors")
    assert body["data"]["signOutEverywhere"]["success"] is True

    # Follow-up request with the OLD token: me must be null
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={SESSION_COOKIE: old_token},
    ) as client:
        resp2 = await client.post("/graphql", json={"query": "{ me { id } }"})
    assert resp2.json()["data"]["me"] is None
