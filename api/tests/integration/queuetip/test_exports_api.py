"""End-to-end GraphQL integration tests for Phase 2A export operations."""

import json
from unittest.mock import patch

import httpx
import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import Account, Contribution, Playlist, PlaylistMembership, Vote
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
    owner = await sync_to_async(Account.objects.create)(display_name="Owner")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="Test Playlist", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    return owner, playlist


async def _add_song(
    playlist: Playlist,
    contributor: Account,
    *,
    guaranteed: bool = False,
) -> Contribution:
    """Add a song contribution. Pass guaranteed=True to upvote to t_high (+3 net)
    so the selection engine always includes it regardless of RNG roll."""
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    contribution = await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=contributor
    )
    if guaranteed:
        # t_high default is 3; net ≥ t_high → always included
        for _ in range(3):
            voter = await sync_to_async(Account.objects.create)(display_name="v")
            await sync_to_async(Vote.objects.create)(
                contribution=contribution, account=voter, value=1
            )
    return contribution


_CREATE_EXPORT_QUERY = """
mutation CreateExport($playlistId: ID!, $options: ExportOptionsInput) {
  createExport(playlistId: $playlistId, options: $options) {
    id
    parameters
    rngSeed
    m3uUrl
    warningMessage
    tracks {
      position
      song { id title artist }
      inclusionReason
    }
  }
}
"""

_FETCH_EXPORT_QUERY = """
query FetchExport($id: ID!) {
  export(id: $id) {
    id
    parameters
    rngSeed
    tracks { position song { title } }
  }
}
"""

_LIST_EXPORTS_QUERY = """
query ListExports($playlistId: ID!) {
  myPlaylistExports(playlistId: $playlistId) {
    id
    createdAt
    tracks { position }
  }
}
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_export_happy_path():
    """createExport returns a snapshot with correct shape for 3 contributed songs.

    Each song is given net=+3 votes (t_high default) so the selection engine
    always includes all three — making the test deterministic regardless of RNG.
    """
    owner, playlist = await _setup_playlist()

    await _add_song(playlist, owner, guaranteed=True)
    await _add_song(playlist, owner, guaranteed=True)
    await _add_song(playlist, owner, guaranteed=True)

    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )

    assert "errors" not in result, result.get("errors")
    data = result["data"]["createExport"]

    # id must be a non-empty string
    assert data["id"]

    # parameters must be valid JSON matching the default options
    params = json.loads(data["parameters"])
    assert params == {"exclude_my_downvotes": False}

    # rngSeed must be a non-empty string (stored as BigInt, rendered as str)
    assert data["rngSeed"] and isinstance(data["rngSeed"], str)

    # m3uUrl must end with /exports/<id>.m3u
    assert data["m3uUrl"].endswith(f"/exports/{data['id']}.m3u")

    # 3 guaranteed songs → snapshot must contain exactly 3 tracks with positions 0..2
    tracks = data["tracks"]
    assert len(tracks) == 3
    positions = sorted(t["position"] for t in tracks)
    assert positions == [0, 1, 2]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_export_excludes_downvoted_songs():
    """createExport with excludeMyDownvotes:true omits songs the caller downvoted.

    The downvoted song gets +1 votes from others so it would be guaranteed
    included — but the caller's downvote filter removes it from the candidate
    list entirely, so it must be absent regardless of roll outcomes.
    """
    owner, playlist = await _setup_playlist()
    member = await sync_to_async(Account.objects.create)(display_name="Member")
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=member, role="member"
    )

    contrib_keep = await _add_song(playlist, owner)
    contrib_downvoted = await _add_song(playlist, owner)

    # Give contrib_keep a guaranteed high score (+3 net) so it's always selected
    for _ in range(3):
        voter = await sync_to_async(Account.objects.create)(display_name="v")
        await sync_to_async(Vote.objects.create)(
            contribution=contrib_keep, account=voter, value=1
        )

    # Owner downvotes contrib_downvoted; give it upvotes from others so without
    # the filter it would also be guaranteed — proving the filter is the cause
    await sync_to_async(Vote.objects.create)(
        contribution=contrib_downvoted, account=owner, value=-1
    )
    for _ in range(4):
        voter = await sync_to_async(Account.objects.create)(display_name="v")
        await sync_to_async(Vote.objects.create)(
            contribution=contrib_downvoted, account=voter, value=1
        )

    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {
                "playlistId": str(playlist.id),
                "options": {"excludeMyDownvotes": True},
            },
        )

    assert "errors" not in result, result.get("errors")
    data = result["data"]["createExport"]

    # parameters must reflect the option
    params = json.loads(data["parameters"])
    assert params == {"exclude_my_downvotes": True}

    # The downvoted song must not appear in any track (excluded before rolling)
    downvoted_song_id = str((await sync_to_async(lambda: contrib_downvoted.song_id)()))
    track_song_ids = {t["song"]["id"] for t in data["tracks"]}
    assert downvoted_song_id not in track_song_ids

    # The guaranteed-upvoted song must be present (net=+3, always selected)
    keep_song_id = str((await sync_to_async(lambda: contrib_keep.song_id)()))
    assert keep_song_id in track_song_ids


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_query_fetches_existing_snapshot():
    """export(id) returns the snapshot previously created by createExport."""
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner)

    async with _authed_client(owner.id) as client:
        created = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
        snapshot_id = created["data"]["createExport"]["id"]

        fetched = await _gql(
            client,
            _FETCH_EXPORT_QUERY,
            {"id": snapshot_id},
        )

    assert "errors" not in fetched, fetched.get("errors")
    assert fetched["data"]["export"]["id"] == snapshot_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_query_rejected_for_non_member():
    """export(id) raises an error when the caller is not a playlist member."""
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner)

    # Create the snapshot as owner
    async with _authed_client(owner.id) as client:
        created = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
    snapshot_id = created["data"]["createExport"]["id"]

    # Try to fetch as a non-member outsider
    outsider = await sync_to_async(Account.objects.create)(display_name="Outsider")
    async with _authed_client(outsider.id) as client:
        result = await _gql(
            client,
            _FETCH_EXPORT_QUERY,
            {"id": snapshot_id},
        )

    assert "errors" in result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_playlist_exports_returns_newest_first():
    """myPlaylistExports lists snapshots with the most recently created one first."""
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner)

    async with _authed_client(owner.id) as client:
        first = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
        second = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )

        listed = await _gql(
            client,
            _LIST_EXPORTS_QUERY,
            {"playlistId": str(playlist.id)},
        )

    assert "errors" not in listed, listed.get("errors")
    exports = listed["data"]["myPlaylistExports"]
    assert len(exports) == 2

    first_id = first["data"]["createExport"]["id"]
    second_id = second["data"]["createExport"]["id"]

    # Newest (second) should come first in the list
    ids = [e["id"] for e in exports]
    assert ids.index(second_id) < ids.index(first_id)


# ---------------------------------------------------------------------------
# REST endpoint: GET /exports/{snapshot_id}.m3u
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m3u_download_happy_path():
    """Owner can download the m3u for their own snapshot. The m3u now embeds
    Subsonic stream URLs from the owner's configured Subsonic connection."""
    from queuetip.models import SubsonicConnection
    from src.queuetip.crypto import encrypt_secret

    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner, guaranteed=True)
    # The m3u flow requires a connection to build stream URLs against.
    await sync_to_async(SubsonicConnection.objects.create)(
        account=owner,
        label="test",
        server_url="https://navi.test",
        username="alice",
        password_encrypted=encrypt_secret("hunter2"),
    )

    async with _authed_client(owner.id) as client:
        created = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
        snapshot_id = created["data"]["createExport"]["id"]

        # Mock the per-track resolver so the test doesn't reach out to a real
        # Subsonic server. Returning None makes every track an "unmatched"
        # comment — the file still renders successfully.
        with patch("src.queuetip.m3u.resolve_song_to_subsonic_id", return_value=None):
            resp = await client.get(f"/exports/{snapshot_id}.m3u")

    assert resp.status_code == 200
    assert "audio/x-mpegurl" in resp.headers["content-type"]
    assert resp.text.startswith("#EXTM3U")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m3u_download_no_cookie_returns_401():
    """Request without a session cookie is rejected with 401."""
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner, guaranteed=True)

    async with _authed_client(owner.id) as client:
        created = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
        snapshot_id = created["data"]["createExport"]["id"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as anon_client:
        resp = await anon_client.get(f"/exports/{snapshot_id}.m3u")

    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m3u_download_non_member_returns_403():
    """A valid session for a non-member account is rejected with 403."""
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner, guaranteed=True)

    async with _authed_client(owner.id) as client:
        created = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )
        snapshot_id = created["data"]["createExport"]["id"]

    outsider = await sync_to_async(Account.objects.create)(display_name="Outsider")
    async with _authed_client(outsider.id) as client:
        resp = await client.get(f"/exports/{snapshot_id}.m3u")

    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m3u_download_unknown_snapshot_returns_404():
    """Requesting a well-formed but non-existent snapshot UUID returns 404."""
    owner, _ = await _setup_playlist()

    async with _authed_client(owner.id) as client:
        resp = await client.get("/exports/00000000-0000-0000-0000-000000000000.m3u")

    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m3u_download_invalid_uuid_returns_400():
    """Requesting a non-UUID snapshot id returns 400."""
    owner, _ = await _setup_playlist()

    async with _authed_client(owner.id) as client:
        resp = await client.get("/exports/not-a-uuid.m3u")

    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_id_is_uuid_format():
    """createExport returns an id that matches UUID format."""
    import re

    uuid_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    owner, playlist = await _setup_playlist()
    await _add_song(playlist, owner, guaranteed=True)

    async with _authed_client(owner.id) as client:
        result = await _gql(
            client,
            _CREATE_EXPORT_QUERY,
            {"playlistId": str(playlist.id)},
        )

    assert "errors" not in result, result.get("errors")
    snapshot_id = result["data"]["createExport"]["id"]
    assert uuid_re.match(snapshot_id), f"Expected UUID, got: {snapshot_id!r}"
