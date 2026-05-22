import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, AuthIdentity
from src.queuetip.schema.mutation import _check_magic_link_throttle, _request_magic_link


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_request_magic_link_creates_account_for_new_email(
    mailoutbox, monkeypatch
):
    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "false")
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
    # Message must not reveal whether the email is registered (enumeration hardening).
    assert "no account" not in result.message.lower()
    assert "sign up" in result.message.lower()
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_magic_link_throttled_after_per_email_limit(mailoutbox):
    """6th rapid request for the same email returns throttle message on the 6th call."""
    email = "throttle-test@example.com"
    ip = "10.0.0.1"

    # First 5 calls exhaust the per-email window budget
    for _ in range(5):
        await sync_to_async(_check_magic_link_throttle)(email, ip)

    # 6th call via _request_magic_link should be rejected by the throttle
    result = await _request_magic_link(email, "Throttled User", ip=ip)
    assert result.sent is False
    assert "too many" in result.message.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_magic_link_different_emails_not_throttled(mailoutbox):
    """Different emails are rate-limited independently — one full budget each."""
    for i in range(5):
        email = f"user{i}@example.com"
        result = await _request_magic_link(email, f"User {i}", ip="10.0.0.2")
        # Each unique email should succeed (or fail for unrelated reasons, not throttle)
        assert "too many" not in result.message.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_signup_blocked_when_email_not_in_allowlist(mailoutbox, monkeypatch):
    """With the allowlist enforced (default), an un-approved email cannot sign up."""
    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "true")
    result = await _request_magic_link(
        "uninvited@example.com", "New Person", ip="10.0.0.99"
    )
    assert result.sent is False
    assert (
        "approved" in result.message.lower() or "registered" in result.message.lower()
    )
    assert await sync_to_async(Account.objects.count)() == 0
    assert len(mailoutbox) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_signup_succeeds_when_email_is_allowlisted(mailoutbox, monkeypatch):
    """An allowlisted email can create a new account."""
    from queuetip.models import QueuetipSignupAllowlist

    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "true")
    await sync_to_async(QueuetipSignupAllowlist.objects.create)(
        email="invited@example.com"
    )
    result = await _request_magic_link(
        "invited@example.com", "Invited Person", ip="10.0.0.99"
    )
    assert result.sent is True
    assert await sync_to_async(Account.objects.count)() == 1
    assert len(mailoutbox) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_signup_works_when_allowlist_disabled(mailoutbox, monkeypatch):
    """When QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST=False, any email may sign up."""
    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "false")
    result = await _request_magic_link("anyone@example.com", "Anyone", ip="10.0.0.99")
    assert result.sent is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existing_account_signin_not_blocked_by_allowlist(
    mailoutbox, monkeypatch
):
    """An already-existing account can sign in even if not on the allowlist."""
    monkeypatch.setenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "true")
    account = await sync_to_async(Account.objects.create)(display_name="Existing")
    await sync_to_async(AuthIdentity.objects.create)(
        account=account,
        provider=AuthIdentity.PROVIDER_MAGIC_LINK,
        identifier="existing@example.com",
    )
    result = await _request_magic_link("existing@example.com", None, ip="10.0.0.99")
    assert result.sent is True
    assert len(mailoutbox) == 1
