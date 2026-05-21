import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import Account, Contribution, Playlist, PlaylistMembership, Vote
from queuetip.permissions import PermissionDeniedError
from src.queuetip.errors import ValidationError
from src.queuetip.services.vote import VoteService


async def _setup():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    member = await sync_to_async(Account.objects.create)(display_name="M")
    outsider = await sync_to_async(Account.objects.create)(display_name="X")
    playlist = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=member, role="member"
    )
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    contribution = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )
    return owner, member, outsider, contribution


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_creates_row():
    owner, member, _, contribution = await _setup()
    vote = await VoteService.cast_vote(member, contribution.id, 1)
    assert vote.value == 1
    assert vote.account_id == member.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_upserts_existing_vote():
    owner, member, _, contribution = await _setup()
    await VoteService.cast_vote(member, contribution.id, 1)
    vote = await VoteService.cast_vote(member, contribution.id, -1)
    assert vote.value == -1
    count = await sync_to_async(
        Vote.objects.filter(contribution=contribution, account=member).count
    )()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_value_zero_raises_validation_error():
    owner, member, _, contribution = await _setup()
    with pytest.raises(ValidationError):
        await VoteService.cast_vote(member, contribution.id, 0)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_value_two_raises_validation_error():
    owner, member, _, contribution = await _setup()
    with pytest.raises(ValidationError):
        await VoteService.cast_vote(member, contribution.id, 2)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_self_vote_allowed():
    owner, _, _, contribution = await _setup()
    vote = await VoteService.cast_vote(owner, contribution.id, 1)
    assert vote.value == 1
    assert vote.account_id == owner.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_non_member_raises_permission_denied():
    _, _, outsider, contribution = await _setup()
    with pytest.raises(PermissionDeniedError):
        await VoteService.cast_vote(outsider, contribution.id, 1)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_clear_vote_removes_existing_row():
    owner, member, _, contribution = await _setup()
    await VoteService.cast_vote(member, contribution.id, 1)
    await VoteService.clear_vote(member, contribution.id)
    exists = await sync_to_async(
        Vote.objects.filter(contribution=contribution, account=member).exists
    )()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_clear_vote_no_existing_vote_is_noop():
    owner, member, _, contribution = await _setup()
    # Should not raise even when no vote exists
    await VoteService.clear_vote(member, contribution.id)
    exists = await sync_to_async(
        Vote.objects.filter(contribution=contribution, account=member).exists
    )()
    assert exists is False
