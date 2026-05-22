import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, PlaylistMembership
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
async def test_leave_sole_owner_must_delete_instead():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await PlaylistService.create(owner, name="P", description="")
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
