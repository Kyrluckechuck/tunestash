"""Integration tests for the Spotify export GraphQL surface.

Covers:
- me.externalServices returns [] when no link exists
- me.externalServices returns the linked service after direct DB insert
- exportToSpotify happy path (SpotifyExportService mocked)
- exportToSpotify without a Spotify link raises an error
"""

from unittest.mock import AsyncMock, patch

from django.utils import timezone

import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, ExternalServiceLink, Playlist, PlaylistMembership
from src.queuetip.app import app
from src.queuetip.auth import SESSION_COOKIE, make_session_token
from src.queuetip.services.spotify_export import SpotifyExportResult

# ---------------------------------------------------------------------------
# Helpers (mirror test_exports_api.py conventions)
# ---------------------------------------------------------------------------


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


async def _make_account(display_name: str = "Tester") -> Account:
    return await sync_to_async(Account.objects.create)(display_name=display_name)


async def _make_playlist_with_owner(owner: Account) -> Playlist:
    playlist = await sync_to_async(Playlist.objects.create)(
        name="Test Playlist", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    return playlist


async def _make_spotify_link(
    account: Account, service_user_id: str = "u1"
) -> ExternalServiceLink:
    return await sync_to_async(ExternalServiceLink.objects.create)(
        account=account,
        service=ExternalServiceLink.SERVICE_SPOTIFY,
        service_user_id=service_user_id,
        access_token="fake-access",
        refresh_token="fake-refresh",
        expires_at=timezone.now().replace(year=2099),
        scope="playlist-modify-private",
    )


_ME_QUERY = """
query Me {
  me {
    id
    displayName
    externalServices {
      service
      serviceUserId
      linkedAt
    }
  }
}
"""

_EXPORT_TO_SPOTIFY_MUTATION = """
mutation ExportToSpotify($snapshotId: ID!, $playlistName: String) {
  exportToSpotify(snapshotId: $snapshotId, playlistName: $playlistName) {
    spotifyPlaylistUrl
    addedCount
    skippedCount
    skippedTitles
  }
}
"""

# ---------------------------------------------------------------------------
# me.externalServices
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_external_services_empty_when_no_link():
    """me.externalServices returns an empty list for an account without a linked service."""
    account = await _make_account()

    async with _authed_client(account.id) as client:
        result = await _gql(client, _ME_QUERY)

    assert "errors" not in result, result.get("errors")
    me = result["data"]["me"]
    assert me["externalServices"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_external_services_shows_linked_spotify():
    """me.externalServices returns the Spotify entry after a link is created."""
    account = await _make_account()
    await _make_spotify_link(account, service_user_id="spotify_uid_42")

    async with _authed_client(account.id) as client:
        result = await _gql(client, _ME_QUERY)

    assert "errors" not in result, result.get("errors")
    me = result["data"]["me"]
    assert len(me["externalServices"]) == 1
    svc = me["externalServices"][0]
    assert svc["service"] == "spotify"
    assert svc["serviceUserId"] == "spotify_uid_42"
    assert svc["linkedAt"]  # non-empty ISO timestamp


# ---------------------------------------------------------------------------
# exportToSpotify mutation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_to_spotify_happy_path():
    """exportToSpotify returns the expected payload when SpotifyExportService succeeds."""
    from tests.factories import ArtistFactory, SongFactory

    from queuetip.models import Contribution

    account = await _make_account()
    playlist = await _make_playlist_with_owner(account)
    await _make_spotify_link(account)

    # Add a contribution so createExport has at least one song to snapshot
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=account
    )

    # First, create an export snapshot to get a real snapshot_id
    create_export_mutation = """
    mutation CreateExport($playlistId: ID!) {
      createExport(playlistId: $playlistId) { id }
    }
    """
    async with _authed_client(account.id) as client:
        created = await _gql(
            client, create_export_mutation, {"playlistId": str(playlist.id)}
        )
    assert "errors" not in created, created.get("errors")
    snapshot_id = created["data"]["createExport"]["id"]

    fixture_result = SpotifyExportResult(
        spotify_playlist_url="https://open.spotify.com/playlist/abc123",
        added_count=3,
        skipped_count=1,
        skipped_titles=["Unknown Artist — Mystery Track"],
    )

    with patch(
        "src.queuetip.services.spotify_export.SpotifyExportService.export",
        new=AsyncMock(return_value=fixture_result),
    ):
        async with _authed_client(account.id) as client:
            result = await _gql(
                client,
                _EXPORT_TO_SPOTIFY_MUTATION,
                {"snapshotId": snapshot_id, "playlistName": "My Party Mix"},
            )

    assert "errors" not in result, result.get("errors")
    data = result["data"]["exportToSpotify"]
    assert data["spotifyPlaylistUrl"] == "https://open.spotify.com/playlist/abc123"
    assert data["addedCount"] == 3
    assert data["skippedCount"] == 1
    assert data["skippedTitles"] == ["Unknown Artist — Mystery Track"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_to_spotify_without_link_returns_error():
    """exportToSpotify returns a GraphQL error when Spotify is not linked."""
    from tests.factories import ArtistFactory, SongFactory

    from queuetip.models import Contribution

    account = await _make_account()
    playlist = await _make_playlist_with_owner(account)

    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=account
    )

    create_export_mutation = """
    mutation CreateExport($playlistId: ID!) {
      createExport(playlistId: $playlistId) { id }
    }
    """
    async with _authed_client(account.id) as client:
        created = await _gql(
            client, create_export_mutation, {"playlistId": str(playlist.id)}
        )
    snapshot_id = created["data"]["createExport"]["id"]

    # No Spotify link exists → service raises NotFoundError
    async with _authed_client(account.id) as client:
        result = await _gql(
            client,
            _EXPORT_TO_SPOTIFY_MUTATION,
            {"snapshotId": snapshot_id},
        )

    assert "errors" in result
    error_messages = " ".join(e["message"] for e in result["errors"])
    assert "Spotify" in error_messages
