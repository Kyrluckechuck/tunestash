"""End-to-end GraphQL integration tests for Phase 1B playlist + membership ops."""

import httpx
import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    Contribution,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
    PlaylistMembership,
    Vote,
)
from src.queuetip.app import app
from src.queuetip.auth import SESSION_COOKIE, make_session_token
from src.queuetip.services.export import ExportService


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
              playlistByInviteToken(inviteToken: $t) {
                name members { account { displayName } }
              }
            }
            """,
            {"t": p.invite_token},
        )
    assert result["data"]["playlistByInviteToken"]["name"] == "Public Mix"


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
    assert any(
        "not found or not allowed" in e["message"].lower() for e in result["errors"]
    )


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_playlist_by_invite_token_does_not_expose_engine_settings():
    """playlistByInviteToken returns PlaylistPreviewType which has no engineSettings field."""
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    p = await sync_to_async(Playlist.objects.create)(
        name="Secret Settings", created_by=owner, t_high=7, p_floor=0.05
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        # Attempt to request engineSettings on the preview type — schema should reject it
        result = await client.post(
            "/graphql",
            json={
                "query": """
                query($t: String!) {
                  playlistByInviteToken(inviteToken: $t) {
                    id name engineSettings { tHigh }
                  }
                }
                """,
                "variables": {"t": p.invite_token},
            },
        )
    body = result.json()
    assert (
        "errors" in body
    ), "Schema should reject engineSettings on PlaylistPreviewType"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delete_playlist_cascades_contributions_votes_snapshots():
    """deletePlaylist removes all child rows (contributions, votes, snapshots, memberships)."""
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="To Delete", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )

    # Add two contributions with votes
    contributions = []
    for i in range(2):
        artist = await sync_to_async(ArtistFactory)()
        song = await sync_to_async(SongFactory)(primary_artist=artist)
        c = await sync_to_async(Contribution.objects.create)(
            playlist=playlist, song=song, contributed_by=owner
        )
        await sync_to_async(Vote.objects.create)(contribution=c, account=owner, value=1)
        contributions.append(c)

    # Create an export snapshot (result not needed; side-effect is the DB rows)
    await ExportService.create(owner, playlist.id)
    playlist_id = playlist.id

    # Delete via GraphQL
    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            "mutation($id: ID!) { deletePlaylist(id: $id) { deleted } }",
            {"id": str(playlist_id)},
        )
    assert result["data"]["deletePlaylist"]["deleted"] is True

    # All child rows must be gone
    assert await sync_to_async(Playlist.objects.filter(id=playlist_id).count)() == 0
    assert (
        await sync_to_async(
            Contribution.objects.filter(playlist_id=playlist_id).count
        )()
        == 0
    )
    assert (
        await sync_to_async(
            Vote.objects.filter(contribution__playlist_id=playlist_id).count
        )()
        == 0
    )
    assert (
        await sync_to_async(
            ExportSnapshot.objects.filter(playlist_id=playlist_id).count
        )()
        == 0
    )
    assert (
        await sync_to_async(
            ExportSnapshotTrack.objects.filter(snapshot__playlist_id=playlist_id).count
        )()
        == 0
    )
    assert (
        await sync_to_async(
            PlaylistMembership.objects.filter(playlist_id=playlist_id).count
        )()
        == 0
    )


_PLAYLIST_QUERY = """
query FetchPlaylist($id: ID!) {
  playlist(id: $id) { id name }
}
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_error_messages_uniform_for_not_found_vs_permission():
    """Both NotFoundError and PermissionDeniedError reach the client as the same
    message so callers cannot probe for resource existence.
    """
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    p = await sync_to_async(Playlist.objects.create)(name="Private", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=p, account=owner, role="owner"
    )

    outsider = await sync_to_async(Account.objects.create)(display_name="X")

    async with _authed_client(outsider.id) as client:
        # NotFoundError path: playlist 99999999 does not exist
        not_found_result = await _gql(client, _PLAYLIST_QUERY, {"id": "99999999"})
        # PermissionDeniedError path: playlist exists but outsider is not a member
        permission_result = await _gql(client, _PLAYLIST_QUERY, {"id": str(p.id)})

    expected = "not found or not allowed"
    assert "errors" in not_found_result
    assert any(
        expected in e["message"].lower() for e in not_found_result["errors"]
    ), f"Expected '{expected}' in: {not_found_result['errors']}"

    assert "errors" in permission_result
    assert any(
        expected in e["message"].lower() for e in permission_result["errors"]
    ), f"Expected '{expected}' in: {permission_result['errors']}"
