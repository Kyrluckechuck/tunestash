import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, AuthIdentity
from src.queuetip.schema.mutation import _request_magic_link


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_creates_account_for_new_email(mailoutbox):
    result = await _request_magic_link("New@Example.com", "Newbie")
    assert result.sent is True
    identity = await sync_to_async(
        lambda: AuthIdentity.objects.select_related("account").get(
            provider="magic_link", identifier="new@example.com"
        )
    )()
    assert identity.account.display_name == "Newbie"
    assert len(mailoutbox) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_unknown_email_without_name_does_not_send(mailoutbox):
    result = await _request_magic_link("ghost@example.com", None)
    assert result.sent is False
    assert await sync_to_async(Account.objects.count)() == 0
    assert len(mailoutbox) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_existing_account_reuses_it(mailoutbox):
    account = await sync_to_async(Account.objects.create)(display_name="Existing")
    await sync_to_async(AuthIdentity.objects.create)(
        account=account, provider="magic_link", identifier="known@example.com"
    )
    result = await _request_magic_link("known@example.com", None)
    assert result.sent is True
    assert await sync_to_async(Account.objects.count)() == 1
    assert len(mailoutbox) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_rejects_invalid_email(mailoutbox):
    result = await _request_magic_link("not-an-email", "Newbie")
    assert result.sent is False
    assert await sync_to_async(Account.objects.count)() == 0
    assert len(mailoutbox) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_rejects_overlong_display_name(mailoutbox):
    result = await _request_magic_link("new@example.com", "x" * 121)
    assert result.sent is False
    assert await sync_to_async(Account.objects.count)() == 0
    assert len(mailoutbox) == 0
