from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import Account, Contribution
from queuetip.permissions import PermissionDeniedError
from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.services.contribution import ContributionService
from src.queuetip.services.membership import MembershipService
from src.queuetip.services.playlist import PlaylistService


async def _make_song(name: str = "Title") -> object:
    return await sync_to_async(SongFactory)(
        primary_artist=await sync_to_async(ArtistFactory)(name="Some Artist"),
        name=name,
    )


_DEEZER_URL = "https://www.deezer.com/track/1"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_happy_path():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        contribution, already_present = await ContributionService.contribute_from_link(
            owner, playlist.id, _DEEZER_URL
        )
    assert already_present is False
    assert contribution.song_id == song.id
    assert contribution.contributed_by_id == owner.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_duplicate_returns_existing():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        c1, already1 = await ContributionService.contribute_from_link(
            owner, playlist.id, _DEEZER_URL
        )
        c2, already2 = await ContributionService.contribute_from_link(
            owner, playlist.id, _DEEZER_URL
        )
    assert already1 is False
    assert already2 is True
    assert c1.id == c2.id
    count = await sync_to_async(
        Contribution.objects.filter(playlist=playlist, song=song).count
    )()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_non_member_raises():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    outsider = await sync_to_async(Account.objects.create)(display_name="X")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        with pytest.raises(PermissionDeniedError):
            await ContributionService.contribute_from_link(
                outsider, playlist.id, _DEEZER_URL
            )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_search_builds_deezer_url():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        await ContributionService.contribute_from_search(owner, playlist.id, "42")
    resolve.assert_called_once_with("https://www.deezer.com/track/42")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_contribution_by_contributor_succeeds():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    member = await sync_to_async(Account.objects.create)(display_name="M")
    playlist = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(member, playlist.invite_token)
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        contribution, _ = await ContributionService.contribute_from_link(
            member, playlist.id, _DEEZER_URL
        )
    await ContributionService.remove_contribution(member, contribution.id)
    exists = await sync_to_async(
        Contribution.objects.filter(id=contribution.id).exists
    )()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_contribution_by_non_contributor_member_raises():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    contributor = await sync_to_async(Account.objects.create)(display_name="C")
    other_member = await sync_to_async(Account.objects.create)(display_name="M")
    playlist = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(contributor, playlist.invite_token)
    await MembershipService.join(other_member, playlist.invite_token)
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        contribution, _ = await ContributionService.contribute_from_link(
            contributor, playlist.id, _DEEZER_URL
        )
    with pytest.raises(PermissionDeniedError):
        await ContributionService.remove_contribution(other_member, contribution.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_contribution_by_owner_succeeds():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    contributor = await sync_to_async(Account.objects.create)(display_name="C")
    playlist = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(contributor, playlist.invite_token)
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        contribution, _ = await ContributionService.contribute_from_link(
            contributor, playlist.id, _DEEZER_URL
        )
    await ContributionService.remove_contribution(owner, contribution.id)
    exists = await sync_to_async(
        Contribution.objects.filter(id=contribution.id).exists
    )()
    assert exists is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_resolution_failure_propagates():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await PlaylistService.create(owner, name="P", description="")
    with (
        patch(
            "src.queuetip.services.contribution.resolve_link",
            side_effect=UnsupportedURLError("bad url"),
        ),
        patch("src.queuetip.services.contribution.ingest_track"),
    ):
        with pytest.raises(UnsupportedURLError):
            await ContributionService.contribute_from_link(
                owner, playlist.id, "https://example.com/not-a-track"
            )
    count = await sync_to_async(Contribution.objects.filter(playlist=playlist).count)()
    assert count == 0
