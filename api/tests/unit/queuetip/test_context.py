import pytest
from asgiref.sync import sync_to_async
from starlette.requests import Request

from queuetip.models import Account
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
@pytest.mark.django_db(transaction=True)
async def test_get_context_anonymous_without_cookie():
    ctx = await get_context(_request_with_cookies({}))
    assert ctx.account is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_context_resolves_account_from_session_cookie():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    token = auth.make_session_token(account.id, session_epoch=0)
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: token}))
    assert ctx.account is not None
    assert ctx.account.id == account.id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_context_ignores_invalid_session_cookie():
    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: "garbage"}))
    assert ctx.account is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_context_rejects_token_with_stale_epoch():
    """A session token with ep=0 is rejected if account.session_epoch has been bumped."""
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    # Issue a token with epoch 0
    token = auth.make_session_token(account.id, session_epoch=0)
    # Bump the account's epoch to 1 (simulates signOutEverywhere)
    await sync_to_async(Account.objects.filter(id=account.id).update)(session_epoch=1)

    ctx = await get_context(_request_with_cookies({auth.SESSION_COOKIE: token}))
    assert ctx.account is None
