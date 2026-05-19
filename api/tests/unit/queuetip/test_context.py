import pytest
from asgiref.sync import sync_to_async
from queuetip.models import Account
from starlette.requests import Request

from src.queuetip import auth
from src.queuetip.context import get_context


def _request_with_cookies(cookies: dict) -> Request:
    header = "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()
    scope = {
        "type": "http",
        "headers": [(b"cookie", header)] if cookies else [],
    }
    return Request(scope)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_get_context_anonymous_without_cookie():
    ctx = await get_context(_request_with_cookies({}))
    assert ctx.account is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_get_context_resolves_account_from_session_cookie():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    token = auth.make_session_token(account.id)
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: token}))
    assert ctx.account is not None
    assert ctx.account.id == account.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_get_context_ignores_invalid_session_cookie():
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: "garbage"}))
    assert ctx.account is None
