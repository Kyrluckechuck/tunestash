from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import Account, Contribution
from queuetip.permissions import PermissionDeniedError
from src.queuetip.errors import NotFoundError
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_playlist_returns_contributions():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    member = await sync_to_async(Account.objects.create)(display_name="M")
    playlist = await PlaylistService.create(owner, name="P", description="")
    await MembershipService.join(member, playlist.invite_token)
    song1 = await _make_song("Song A")
    song2 = await _make_song("Song B")
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track") as ingest,
    ):
        resolve.return_value = object()
        ingest.return_value = song1
        await ContributionService.contribute_from_link(owner, playlist.id, _DEEZER_URL)
        ingest.return_value = song2
        await ContributionService.contribute_from_link(member, playlist.id, _DEEZER_URL)

    contributions = await ContributionService.list_for_playlist(owner, playlist.id)
    assert len(contributions) == 2
    titles = {c.song.name for c in contributions}
    assert titles == {"Song A", "Song B"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_playlist_non_member_raises():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    outsider = await sync_to_async(Account.objects.create)(display_name="X")
    playlist = await PlaylistService.create(owner, name="P", description="")

    with pytest.raises(PermissionDeniedError):
        await ContributionService.list_for_playlist(outsider, playlist.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_playlist_unknown_playlist_raises():
    owner = await sync_to_async(Account.objects.create)(display_name="O")

    with pytest.raises(NotFoundError):
        await ContributionService.list_for_playlist(owner, 99999)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_returned_contribution_has_prefetched_relations():
    """Regression: the returned Contribution must have song, song.primary_artist,
    and contributed_by relations pre-loaded so async resolvers can traverse
    them without triggering a SynchronousOnlyOperation lazy load."""
    owner = await sync_to_async(Account.objects.create)(display_name="Regress User")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link"),
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        contribution, _ = await ContributionService.contribute_from_link(
            owner, playlist.id, _DEEZER_URL
        )

    # Accessing these from async context without sync_to_async wrapping is the
    # exact pattern that raised SynchronousOnlyOperation before the fix.
    name = contribution.song.name
    artist_name = contribution.song.primary_artist.name
    contributor_name = contribution.contributed_by.display_name

    assert name == song.name
    assert artist_name == song.primary_artist.name
    assert contributor_name == owner.display_name


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_duplicate_returned_contribution_has_prefetched_relations():
    """Same regression for the alreadyPresent=True (dedup) path."""
    owner = await sync_to_async(Account.objects.create)(display_name="Regress User 2")
    playlist = await PlaylistService.create(owner, name="P", description="")
    song = await _make_song()
    with (
        patch("src.queuetip.services.contribution.resolve_link"),
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        await ContributionService.contribute_from_link(owner, playlist.id, _DEEZER_URL)
        contribution, already_present = await ContributionService.contribute_from_link(
            owner, playlist.id, _DEEZER_URL
        )

    assert already_present is True
    # Relation access from async context — must not raise.
    assert contribution.song.primary_artist.name == song.primary_artist.name
    assert contribution.contributed_by.display_name == owner.display_name
