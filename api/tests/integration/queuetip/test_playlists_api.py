"""End-to-end GraphQL integration tests for Phase 1B playlist + membership ops."""

import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, Playlist, PlaylistMembership
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
    response = await client.post("/graphql", json=payload)
    return response.json()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_playlist_returns_playlist_with_owner_member():
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            """
            mutation($name: String!) {
              createPlaylist(name: $name) {
                id name inviteToken members { account { displayName } role }
              }
            }
            """,
            {"name": "Friday Mix"},
        )
    data = result["data"]["createPlaylist"]
    assert data["name"] == "Friday Mix"
    assert len(data["members"]) == 1
    assert data["members"][0]["role"] == "owner"
    assert data["members"][0]["account"]["displayName"] == "Owner"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_join_via_invite_token_adds_member():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    joiner = await sync_to_async(Account.objects.create)(display_name="J")
    async with _authed_client(joiner.id) as client:
        result = await _gql(
            client,
            """
            mutation($t: String!) {
              joinPlaylist(inviteToken: $t) {
                members { account { displayName } role }
              }
            }
            """,
            {"t": p.invite_token},
        )
    roles = {
        m["account"]["displayName"]: m["role"]
        for m in result["data"]["joinPlaylist"]["members"]
    }
    assert roles == {"O": "owner", "J": "member"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_anonymous_playlist_by_invite_token_returns_metadata():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(
        name="Public Mix", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        result = await _gql(
            client,
            """
            query($t: String!) {
              playlist(inviteToken: $t) {
                name members { account { displayName } }
              }
            }
            """,
            {"t": p.invite_token},
        )
    assert result["data"]["playlist"]["name"] == "Public Mix"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_owner_cannot_update_settings():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    intruder = await sync_to_async(Account.objects.create)(display_name="X")
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=intruder, role="member"
    )
    async with _authed_client(intruder.id) as client:
        result = await _gql(
            client,
            """
            mutation($id: ID!) {
              updatePlaylistSettings(id: $id, name: "Hacked") { name }
            }
            """,
            {"id": str(p.id)},
        )
    assert "errors" in result
    assert any("owner" in e["message"].lower() for e in result["errors"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_owner_can_kick_and_promote():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    member = await sync_to_async(Account.objects.create)(display_name="M")
    other = await sync_to_async(Account.objects.create)(display_name="X")
    p = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    for acct, role in [(owner, "owner"), (member, "member"), (other, "member")]:
        await sync_to_async(PlaylistMembership.objects.create)(
            playlist=p, account=acct, role=role
        )
    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            "mutation($p: ID!, $a: ID!) { promoteMember(playlistId: $p, accountId: $a) { name } }",
            {"p": str(p.id), "a": str(member.id)},
        )
        assert "errors" not in result
        result = await _gql(
            client,
            "mutation($p: ID!, $a: ID!) { kickMember(playlistId: $p, accountId: $a) { deleted } }",
            {"p": str(p.id), "a": str(other.id)},
        )
        assert result["data"]["kickMember"]["deleted"] is True
    m = await sync_to_async(
        lambda: PlaylistMembership.objects.get(playlist=p, account=member)
    )()
    assert m.role == "owner"
    exists = await sync_to_async(
        PlaylistMembership.objects.filter(playlist=p, account=other).exists
    )()
    assert exists is False
