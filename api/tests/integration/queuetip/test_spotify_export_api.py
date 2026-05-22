"""Integration tests for the Spotify export GraphQL surface.

Covers:
- me.externalServices reflects linked services
- createSpotifyExportTarget find-or-creates a Spotify PlaylistExportTarget
"""

from django.utils import timezone

import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import (
    Account,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
    PlaylistMembership,
)
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

_CREATE_SPOTIFY_TARGET = """
mutation CreateSpotifyExportTarget($playlistId: ID!) {
  createSpotifyExportTarget(playlistId: $playlistId) {
    id
    destinationType
    spotifyUserId
  }
}
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_external_services_empty_when_no_link():
    account = await _make_account()
    async with _authed_client(account.id) as client:
        result = await _gql(client, _ME_QUERY)
    assert "errors" not in result, result.get("errors")
    assert result["data"]["me"]["externalServices"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_external_services_shows_linked_spotify():
    account = await _make_account()
    await _make_spotify_link(account, service_user_id="spotify_uid_42")
    async with _authed_client(account.id) as client:
        result = await _gql(client, _ME_QUERY)
    assert "errors" not in result, result.get("errors")
    svcs = result["data"]["me"]["externalServices"]
    assert len(svcs) == 1
    assert svcs[0]["service"] == "spotify"
    assert svcs[0]["serviceUserId"] == "spotify_uid_42"
    assert svcs[0]["linkedAt"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_spotify_export_target_find_or_creates():
    """createSpotifyExportTarget registers a Spotify target for the caller's
    linked account, and is idempotent on repeat calls."""
    account = await _make_account()
    playlist = await _make_playlist_with_owner(account)
    await _make_spotify_link(account, service_user_id="me42")

    async with _authed_client(account.id) as client:
        first = await _gql(
            client, _CREATE_SPOTIFY_TARGET, {"playlistId": str(playlist.id)}
        )
        second = await _gql(
            client, _CREATE_SPOTIFY_TARGET, {"playlistId": str(playlist.id)}
        )

    assert "errors" not in first, first.get("errors")
    t = first["data"]["createSpotifyExportTarget"]
    assert t["destinationType"] == "spotify"
    assert t["spotifyUserId"] == "me42"
    # Idempotent — same row id on the second call.
    assert second["data"]["createSpotifyExportTarget"]["id"] == t["id"]

    count = await sync_to_async(
        lambda: PlaylistExportTarget.objects.filter(
            account=account,
            playlist=playlist,
            destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        ).count()
    )()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_spotify_export_target_without_link_errors():
    """Without a Spotify link, creating a Spotify target is rejected."""
    account = await _make_account()
    playlist = await _make_playlist_with_owner(account)

    async with _authed_client(account.id) as client:
        result = await _gql(
            client, _CREATE_SPOTIFY_TARGET, {"playlistId": str(playlist.id)}
        )

    assert result["data"] is None
    assert result.get("errors")
