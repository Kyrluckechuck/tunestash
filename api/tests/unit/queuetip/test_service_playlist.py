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
    memberships = await sync_to_async(lambda: list(playlist.memberships.all()))()
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
