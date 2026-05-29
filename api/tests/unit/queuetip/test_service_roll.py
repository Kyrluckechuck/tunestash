import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    Contribution,
    Playlist,
    PlaylistMembership,
    Vote,
)
from src.queuetip.services.roll import roll_playlist


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_roll_playlist_applies_exclude_downvotes_and_min_score_threshold():
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="P", created_by=owner, min_size=1, max_size=10
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )

    artist = await sync_to_async(ArtistFactory)()
    song_keep = await sync_to_async(SongFactory)(primary_artist=artist)
    song_drop_by_downvote = await sync_to_async(SongFactory)(primary_artist=artist)
    song_drop_by_score = await sync_to_async(SongFactory)(primary_artist=artist)

    keep = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song_keep, contributed_by=owner
    )
    drop_downvote = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song_drop_by_downvote, contributed_by=owner
    )
    drop_score = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song_drop_by_score, contributed_by=owner
    )

    await sync_to_async(Vote.objects.create)(contribution=keep, account=owner, value=1)
    await sync_to_async(Vote.objects.create)(
        contribution=drop_downvote, account=owner, value=-1
    )
    await sync_to_async(Vote.objects.create)(
        contribution=drop_score, account=owner, value=1
    )
    other = await sync_to_async(Account.objects.create)(display_name="Other")
    await sync_to_async(Vote.objects.create)(
        contribution=drop_score, account=other, value=-1
    )

    result = await sync_to_async(roll_playlist)(
        playlist,
        account=owner,
        exclude_my_downvotes=True,
        min_score_threshold=1,
    )

    assert result.song_ids == [song_keep.id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_roll_playlist_target_size_override_forces_exact_size_when_possible():
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="P", created_by=owner, min_size=0, max_size=10
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )

    artist = await sync_to_async(ArtistFactory)()
    for _ in range(5):
        song = await sync_to_async(SongFactory)(primary_artist=artist)
        contribution = await sync_to_async(Contribution.objects.create)(
            playlist=playlist, song=song, contributed_by=owner
        )
        await sync_to_async(Vote.objects.create)(
            contribution=contribution, account=owner, value=1
        )

    result = await sync_to_async(roll_playlist)(
        playlist,
        account=owner,
        target_size_override=3,
    )

    assert len(result.song_ids) == 3
