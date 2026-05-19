import httpx
import pytest

from queuetip.models import Account
from src.queuetip.app import app
from src.queuetip.auth import (
    SESSION_COOKIE,
    make_magic_link_token,
    make_session_token,
)


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


@pytest.mark.asyncio
async def test_verify_route_rejects_bad_token(async_client):
    async with async_client as client:
        response = await client.get("/auth/verify", params={"token": "garbage"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_tunestash_admin_schema_is_not_mounted(async_client):
    # The TuneStash admin schema exposes an `artists` root query; Queuetip's
    # schema does not. A query for it must fail schema validation.
    async with async_client as client:
        response = await client.post("/graphql", json={"query": "{ artists { id } }"})
    assert response.json().get("errors")
