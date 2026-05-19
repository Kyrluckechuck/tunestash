"""End-to-end GraphQL integration tests for Phase 1C contribution + voting."""

from unittest.mock import patch

import httpx
import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import Account, Contribution, Playlist, PlaylistMembership
from src.queuetip.app import app
from src.queuetip.auth import SESSION_COOKIE, make_session_token


def _authed_client(account_id: int) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(SESSION_COOKIE, make_session_token(account_id))
    return client


async def _gql(client: httpx.AsyncClient, query: str, variables: dict | None = None):
    payload: dict = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    return (await client.post("/graphql", json=payload)).json()


async def _setup_playlist():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    return owner, playlist


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_happy_path():
    owner, playlist = await _setup_playlist()
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        async with _authed_client(owner.id) as client:
            result = await _gql(
                client,
                """
                mutation($p: ID!, $u: String!) {
                  contributeFromLink(playlistId: $p, url: $u) {
                    alreadyPresent
                    contribution { id song { title } netScore }
                  }
                }
                """,
                {"p": str(playlist.id), "u": "https://www.deezer.com/track/1"},
            )
    data = result["data"]["contributeFromLink"]
    assert data["alreadyPresent"] is False
    assert data["contribution"]["netScore"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_contribute_from_link_duplicate_returns_existing():
    owner, playlist = await _setup_playlist()
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    with (
        patch("src.queuetip.services.contribution.resolve_link") as resolve,
        patch("src.queuetip.services.contribution.ingest_track", return_value=song),
    ):
        resolve.return_value = object()
        async with _authed_client(owner.id) as client:
            first = await _gql(
                client,
                """
                mutation($p: ID!, $u: String!) {
                  contributeFromLink(playlistId: $p, url: $u) {
                    alreadyPresent contribution { id }
                  }
                }
                """,
                {"p": str(playlist.id), "u": "https://www.deezer.com/track/1"},
            )
            second = await _gql(
                client,
                """
                mutation($p: ID!, $u: String!) {
                  contributeFromLink(playlistId: $p, url: $u) {
                    alreadyPresent contribution { id }
                  }
                }
                """,
                {"p": str(playlist.id), "u": "https://www.deezer.com/track/1"},
            )
    assert first["data"]["contributeFromLink"]["alreadyPresent"] is False
    assert second["data"]["contributeFromLink"]["alreadyPresent"] is True
    assert (
        first["data"]["contributeFromLink"]["contribution"]["id"]
        == second["data"]["contributeFromLink"]["contribution"]["id"]
    )
    count = await sync_to_async(Contribution.objects.filter(playlist=playlist).count)()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cast_vote_then_clear_round_trip():
    owner, playlist = await _setup_playlist()
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    contribution = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )
    async with _authed_client(owner.id) as client:
        plus = await _gql(
            client,
            """
            mutation($c: ID!) { castVote(contributionId: $c, value: 1) { netScore } }
            """,
            {"c": str(contribution.id)},
        )
        assert plus["data"]["castVote"]["netScore"] == 1
        flip = await _gql(
            client,
            """
            mutation($c: ID!) { castVote(contributionId: $c, value: -1) { netScore } }
            """,
            {"c": str(contribution.id)},
        )
        assert flip["data"]["castVote"]["netScore"] == -1
        cleared = await _gql(
            client,
            """
            mutation($c: ID!) { clearVote(contributionId: $c) { netScore } }
            """,
            {"c": str(contribution.id)},
        )
        assert cleared["data"]["clearVote"]["netScore"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_contribution_by_non_member_rejected():
    owner, playlist = await _setup_playlist()
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    contribution = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )
    outsider = await sync_to_async(Account.objects.create)(display_name="X")
    async with _authed_client(outsider.id) as client:
        result = await _gql(
            client,
            "mutation($id: ID!) { removeContribution(id: $id) { deleted } }",
            {"id": str(contribution.id)},
        )
    assert "errors" in result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bulk_import_playlist_queues_job_and_is_queryable():
    owner, playlist = await _setup_playlist()
    with patch("queuetip.tasks.bulk_import_playlist.delay") as delay:
        async with _authed_client(owner.id) as client:
            queued = await _gql(
                client,
                """
                mutation($p: ID!, $u: String!) {
                  bulkImportPlaylist(playlistId: $p, url: $u) {
                    id status sourceUrl
                  }
                }
                """,
                {
                    "p": str(playlist.id),
                    "u": "https://open.spotify.com/playlist/abc",
                },
            )
        delay.assert_called_once()
        job = queued["data"]["bulkImportPlaylist"]
        assert job["status"] == "pending"
        assert job["sourceUrl"] == "https://open.spotify.com/playlist/abc"

        async with _authed_client(owner.id) as client:
            polled = await _gql(
                client,
                "query($id: ID!) { bulkImportJob(id: $id) { id status sourceUrl } }",
                {"id": job["id"]},
            )
        assert polled["data"]["bulkImportJob"]["id"] == job["id"]
        assert polled["data"]["bulkImportJob"]["status"] == "pending"
