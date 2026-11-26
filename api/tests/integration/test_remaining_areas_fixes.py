"""Regression tests for the remaining-areas audit (findings 2, 3, 4, 5, 8).

All data is synthetic. Providers are mocked; nothing touches the network.
"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from library_manager.models import (
    Album,
    Artist,
    ExternalList,
    ExternalListTrack,
    Song,
    TaskHistory,
    TrackingTier,
    TrackMappingCache,
    TrackMappingStatus,
)
from library_manager.release_ids import (
    ALBUM_CREATE,
    ALBUM_EXISTS,
    ALBUM_SKIP,
    classify_deezer_album,
)
from library_manager.tasks import external_list as el
from library_manager.tasks.core import normalize_name
from library_manager.tasks.deezer import _fetch_albums_via_deezer
from library_manager.tasks.periodic import _try_link_artist_to_deezer
from src.providers.base import (
    ExternalListProvider,
    ExternalListResult,
    ExternalTrack,
)
from src.providers.metadata_base import AlbumResult, ArtistResult, TrackResult
from src.services import track_mapping as tm
from src.services.track_mapping import (
    TrackMappingService,
    TransientMappingError,
)

SPOTIFY_ID = "S" * 22
PATCH_UPC = "library_manager.release_ids.fetch_spotify_album_upc"
PATCH_DEEZER_UPC = "library_manager.release_ids.fetch_deezer_album_upc"
VALID_UPC = "5901234123457"
OTHER_UPC = "4062851533126"


def _gid(n: int) -> str:
    return f"{n:022d}"


_artist_counter = iter(range(5000, 9000))


def _unlinked(name, **kw):
    """An artist with a Spotify gid and no Deezer id (the row to be resolved)."""
    return Artist.objects.create(name=name, gid=_gid(next(_artist_counter)), **kw)


def _song(artist, name, n, isrc=None, **kw):
    return Song.objects.create(
        name=name, gid=_gid(n), primary_artist=artist, isrc=isrc, **kw
    )


# ---------------------------------------------------------------------------
# #4 artist identity: names propose, ISRC evidence decides
# ---------------------------------------------------------------------------


def _isrc_provider(by_isrc, search=()):
    provider = MagicMock()
    provider.get_track_by_isrc.side_effect = lambda isrc: by_isrc.get(isrc)
    provider.search_artists.return_value = list(search)
    return provider


def _track(isrc, artist_name, artist_deezer_id):
    return TrackResult(
        name="t",
        artist_name=artist_name,
        isrc=isrc,
        deezer_id=1,
        artist_deezer_id=artist_deezer_id,
    )


@pytest.mark.django_db
def test_name_search_without_isrc_evidence_never_links():
    artist = _unlinked(name="Synthetic Namesake")
    _song(artist, "One", 1, isrc="ISRCNAME0001")
    provider = _isrc_provider(
        {}, search=[ArtistResult(name="Synthetic Namesake", deezer_id=9001)]
    )

    assert _try_link_artist_to_deezer(artist, provider) is None

    artist.refresh_from_db()
    assert artist.deezer_id is None


@pytest.mark.django_db
def test_name_search_confirmed_by_isrc_links_only_that_artist_not_a_namesake():
    tracked = _unlinked("Synthetic Namesake", tracking_tier=TrackingTier.TRACKED)
    for n in range(3):
        _song(tracked, f"Tracked {n}", 10 + n)
    target = _unlinked(name="Synthetic Namesake")
    _song(target, "Only", 20, isrc="ISRCNAME0002")
    provider = _isrc_provider(
        {"ISRCNAME0002": _track("ISRCNAME0002", "Synthetic Namesake", 9002)},
        search=[ArtistResult(name="Synthetic Namesake", deezer_id=9002)],
    )

    linked = _try_link_artist_to_deezer(target, provider)

    assert linked is not None and linked.pk == target.pk
    tracked.refresh_from_db()
    target.refresh_from_db()
    assert target.deezer_id == 9002
    assert tracked.deezer_id is None  # the "bigger" namesake is not chosen


@pytest.mark.django_db
def test_quorum_id_owned_by_namesake_is_not_merged_without_isrc_evidence():
    owner = Artist.objects.create(name="Synthetic Namesake", deezer_id=9003)
    owner_song = _song(owner, "Owner Song", 30, isrc="ISRCOWNER001")
    other = _unlinked(name="Synthetic Namesake")
    other_songs = [
        _song(other, "A", 31, isrc="ISRCOTHER001"),
        _song(other, "B", 32, isrc="ISRCOTHER002"),
    ]
    provider = _isrc_provider(
        {
            "ISRCOTHER001": _track("ISRCOTHER001", "Synthetic Namesake", 9003),
            "ISRCOTHER002": _track("ISRCOTHER002", "Synthetic Namesake", 9003),
        }
    )

    assert _try_link_artist_to_deezer(other, provider) is None

    assert Artist.objects.filter(pk=other.pk).exists()
    assert Artist.objects.get(pk=owner.pk).deezer_id == 9003
    for song in other_songs:
        song.refresh_from_db()
        assert song.primary_artist_id == other.pk
    owner_song.refresh_from_db()
    assert owner_song.primary_artist_id == owner.pk


@pytest.mark.django_db
def test_quorum_id_owned_by_namesake_merges_with_independent_isrc_evidence():
    owner = Artist.objects.create(name="Synthetic Namesake", deezer_id=9004)
    # Same recording (ISRC) on a different, independent song row of the owner.
    _song(owner, "Shared Elsewhere", 40, isrc="ISRCSHARED01")
    dupe = _unlinked(name="synthetic namesake")
    _song(dupe, "Shared Here", 41, isrc="ISRCSHARED01")
    _song(dupe, "Second", 42, isrc="ISRCSHARED02")
    provider = _isrc_provider(
        {
            "ISRCSHARED01": _track("ISRCSHARED01", "Synthetic Namesake", 9004),
            "ISRCSHARED02": _track("ISRCSHARED02", "Synthetic Namesake", 9004),
        }
    )

    linked = _try_link_artist_to_deezer(dupe, provider)

    assert linked is not None and linked.pk == owner.pk
    assert not Artist.objects.filter(pk=dupe.pk).exists()
    # The merge's own dedup collapses the two same-ISRC rows into one.
    assert Song.objects.filter(primary_artist=owner).count() == 2


@pytest.mark.django_db
def test_shared_file_copy_is_not_independent_evidence():
    """A song sharing the artist's own gid-less copy cannot vouch for a merge."""
    owner = Artist.objects.create(name="Synthetic Namesake", deezer_id=9005)
    dupe = _unlinked(name="Synthetic Namesake")
    own = _song(dupe, "Mine", 50, isrc="ISRCCOPY0001", deezer_id=777001)
    _song(dupe, "Mine 2", 51, isrc="ISRCCOPY0002")
    # Owner's row is the same Deezer track id as dupe's song: same recording row.
    _song(owner, "Copy", 52, isrc="ISRCCOPY0001", deezer_id=own.deezer_id)
    provider = _isrc_provider(
        {
            "ISRCCOPY0001": _track("ISRCCOPY0001", "Synthetic Namesake", 9005),
            "ISRCCOPY0002": _track("ISRCCOPY0002", "Synthetic Namesake", 9005),
        }
    )

    assert _try_link_artist_to_deezer(dupe, provider) is None
    assert Artist.objects.filter(pk=dupe.pk).exists()


# ---------------------------------------------------------------------------
# #5 albums: UPC decides, titles only rank
# ---------------------------------------------------------------------------


@pytest.fixture
def artist():
    return Artist.objects.create(name="Synthetic Artist", deezer_id=8800001)


def _deezer_albums(*albums):
    provider = MagicMock()
    provider.get_artist_albums.return_value = list(albums)
    return patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider)


def _album_result(deezer_id, name="Test Album"):
    return AlbumResult(name=name, artist_name="Synthetic Artist", deezer_id=deezer_id)


@pytest.mark.django_db
def test_same_title_unproven_album_is_not_linked_or_duplicated(artist):
    local = Album.objects.create(
        name="Test Album", artist=artist, spotify_gid="SPALBUM1", spotify_uri=""
    )
    with (
        _deezer_albums(_album_result(8801)),
        patch(PATCH_DEEZER_UPC, return_value=OTHER_UPC),
        patch(PATCH_UPC, return_value=VALID_UPC),
    ):
        created, linked = _fetch_albums_via_deezer(artist)

    local.refresh_from_db()
    assert (created, linked) == (0, 0)
    assert local.deezer_id is None
    assert Album.objects.filter(artist=artist).count() == 1


@pytest.mark.django_db
def test_same_title_album_with_matching_upc_is_linked(artist):
    local = Album.objects.create(
        name="Test Album", artist=artist, spotify_gid="SPALBUM2", spotify_uri=""
    )
    with (
        _deezer_albums(_album_result(8802)),
        patch(PATCH_DEEZER_UPC, return_value="05901234123457"),
        patch(PATCH_UPC, return_value=VALID_UPC),
    ):
        created, linked = _fetch_albums_via_deezer(artist)

    local.refresh_from_db()
    assert (created, linked) == (0, 1)
    assert local.deezer_id == 8802


@pytest.mark.django_db
def test_same_titled_editions_never_share_an_id(artist):
    original = Album.objects.create(name="Test Album", artist=artist, deezer_id=8803)
    with _deezer_albums(_album_result(8804)):
        created, linked = _fetch_albums_via_deezer(artist)

    assert (created, linked) == (1, 0)
    original.refresh_from_db()
    assert original.deezer_id == 8803
    edition = Album.objects.get(deezer_id=8804)
    assert edition.pk != original.pk


@pytest.mark.django_db
def test_classify_outcomes(artist):
    assert classify_deezer_album(artist, 1, "Nothing", normalize_name)[0] == (
        ALBUM_CREATE
    )
    existing = Album.objects.create(name="Has Id", artist=artist, deezer_id=5)
    assert classify_deezer_album(artist, 5, "Has Id", normalize_name) == (
        ALBUM_EXISTS,
        existing,
    )
    Album.objects.create(name="Unlinked", artist=artist, spotify_gid="SPALBUM9")
    with patch(PATCH_DEEZER_UPC, side_effect=RuntimeError("down")):
        assert classify_deezer_album(artist, 6, "unlinked", normalize_name)[0] == (
            ALBUM_SKIP
        )


@pytest.mark.django_db(transaction=True)
def test_import_from_deezer_does_not_adopt_same_title_or_namesake_artist():
    from src.services.album import AlbumService

    namesake = Artist.objects.create(name="Synthetic Artist", deezer_id=8809000)
    local = Album.objects.create(name="Test Album", artist=namesake, deezer_id=8809001)
    data = AlbumResult(
        name="Test Album",
        artist_name="Synthetic Artist",
        deezer_id=8809002,
        artist_deezer_id=8809999,
    )
    provider = MagicMock()
    provider.get_album.return_value = data
    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        result = asyncio.run(AlbumService().import_from_deezer(8809002))

    assert result.success
    local.refresh_from_db()
    assert local.deezer_id == 8809001
    imported = Album.objects.get(deezer_id=8809002)
    assert imported.pk != local.pk
    assert imported.artist.deezer_id == 8809999
    assert imported.artist.pk != namesake.pk


# ---------------------------------------------------------------------------
# #3 / #8 track mapping: provider namespaces and error caching
# ---------------------------------------------------------------------------


@pytest.fixture
def ext_list():
    return ExternalList.objects.create(
        name="Synthetic list",
        source="lastfm",
        list_type="loved",
        username="synthetic-user",
    )


def _row(ext_list, artist="syn artist", track="syn track", mbid=None, **kw):
    return ExternalListTrack.objects.create(
        external_list=ext_list,
        artist_name=artist,
        track_name=track,
        musicbrainz_id=mbid,
        **kw,
    )


@pytest.fixture
def enqueue():
    with (
        patch.object(el, "enqueue_download_track_by_spotify_gid") as spotify,
        patch.object(el, "enqueue_download_deezer_track") as deezer,
    ):
        yield SimpleNamespace(spotify=spotify, deezer=deezer)


@pytest.mark.django_db
def test_local_deezer_only_song_is_linked_not_failed(ext_list, enqueue):
    owner = _unlinked(name="Syn Artist")
    song = Song.objects.create(
        name="Syn Track", gid=None, deezer_id=777002, primary_artist=owner
    )
    row = _row(ext_list)

    el._map_external_list_tracks_internal(ext_list, task_id="t-local")

    row.refresh_from_db()
    assert row.mapping_status == TrackMappingStatus.MAPPED
    assert row.song_id == song.pk
    assert row.spotify_track_id is None
    enqueue.spotify.assert_not_called()
    enqueue.deezer.assert_not_called()


@pytest.mark.django_db
def test_musicbrainz_isrc_result_is_a_deezer_id_never_a_spotify_gid(ext_list, enqueue):
    owner = _unlinked(name="Other Artist")

    def make_song(deezer_id):
        song = Song.objects.create(
            name="Syn Track", gid=None, deezer_id=deezer_id, primary_artist=owner
        )
        return song, None

    row = _row(ext_list, mbid="mbid-1")
    with (
        patch.object(
            tm, "resolve_via_listenbrainz_labs", return_value={"mbid-1": None}
        ),
        patch.object(tm, "resolve_via_musicbrainz", return_value=424242),
        patch.object(el, "_song_for_deezer_track", side_effect=make_song) as make,
    ):
        el._map_external_list_tracks_internal(ext_list, task_id="t-mb")

    row.refresh_from_db()
    assert row.mapping_status == TrackMappingStatus.MAPPED
    assert row.mapping_method == "musicbrainz_isrc"
    assert row.spotify_track_id is None
    enqueue.spotify.assert_not_called()
    make.assert_called_once_with(424242)
    enqueue.deezer.assert_called_once()
    assert enqueue.deezer.call_args.args[0] == row.song_id


@pytest.mark.django_db
def test_cached_deezer_results_keep_their_namespace(ext_list, enqueue):
    TrackMappingCache.objects.create(
        name_lookup_key="a1::t1",
        deezer_track_id=555001,
        mapping_method="deezer_search",
    )
    # Legacy rows stored the Deezer id as a decimal string in spotify_track_id.
    TrackMappingCache.objects.create(
        name_lookup_key="a2::t2",
        spotify_track_id="555002",
        mapping_method="musicbrainz_isrc",
    )
    results = TrackMappingService().map_tracks_batch(
        [("a1", "t1", None), ("a2", "t2", None)]
    )

    assert [(r.provider, r.provider_id) for r in results] == [
        ("deezer", "555001"),
        ("deezer", "555002"),
    ]
    assert all(r.method.startswith("cache_") for r in results)


@pytest.mark.django_db
def test_spotify_id_from_labs_is_queued_as_a_spotify_gid(ext_list, enqueue):
    row = _row(ext_list, mbid="mbid-2")
    with patch.object(
        tm, "resolve_via_listenbrainz_labs", return_value={"mbid-2": SPOTIFY_ID}
    ):
        el._map_external_list_tracks_internal(ext_list, task_id="t-sp")

    row.refresh_from_db()
    assert row.spotify_track_id == SPOTIFY_ID
    enqueue.spotify.assert_called_once()
    assert enqueue.spotify.call_args.args[0] == SPOTIFY_ID
    enqueue.deezer.assert_not_called()


@pytest.mark.django_db
def test_provider_outage_is_not_cached_as_no_match_and_is_retried(ext_list, enqueue):
    row = _row(ext_list)
    with patch.object(
        tm, "resolve_via_deezer_search", side_effect=TransientMappingError("down")
    ):
        el._map_external_list_tracks_internal(ext_list, task_id="t-out")

    row.refresh_from_db()
    assert row.mapping_status == TrackMappingStatus.FAILED
    assert row.mapping_method == el.TRANSIENT_METHOD
    assert not TrackMappingCache.objects.filter(no_match=True).exists()

    # Not retried before the short delay, then put back to PENDING.
    assert el._requeue_transient_failures(ext_list) == 0
    ExternalListTrack.objects.filter(pk=row.pk).update(
        mapped_at=timezone.now() - timedelta(hours=1)
    )
    assert el._requeue_transient_failures(ext_list) == 1
    row.refresh_from_db()
    assert row.mapping_status == TrackMappingStatus.PENDING


@pytest.mark.django_db
def test_listenbrainz_labs_failure_is_not_a_negative_answer():
    with (
        patch.object(tm, "check_api_rate_limit"),
        patch.object(tm.requests, "post", side_effect=RuntimeError("503")),
    ):
        assert tm.resolve_via_listenbrainz_labs(["m1"]) == {}


@pytest.mark.django_db
def test_definitive_no_match_is_cached(ext_list, enqueue):
    row = _row(ext_list)
    with patch.object(tm, "resolve_via_deezer_search", return_value=(None, 0.0)):
        el._map_external_list_tracks_internal(ext_list, task_id="t-neg")

    row.refresh_from_db()
    assert row.mapping_status == TrackMappingStatus.FAILED
    assert row.mapping_method == "none"
    assert TrackMappingCache.objects.filter(no_match=True).count() == 1


def _claim(task_id, ext_list):
    return TaskHistory.objects.create(
        task_id=task_id,
        type="SYNC",
        entity_id=str(ext_list.pk),
        entity_type="PLAYLIST",
        status="PENDING",
    )


@pytest.mark.django_db
def test_mapping_task_adopts_and_completes_its_claim(ext_list, enqueue):
    _row(ext_list)
    claim = _claim("claim-done", ext_list)
    with patch.object(tm, "resolve_via_deezer_search", return_value=(None, 0.0)):
        el._map_external_list_tracks_internal(ext_list, task_id="claim-done")

    claim.refresh_from_db()
    assert claim.status == "COMPLETED"


@pytest.mark.django_db
def test_mapping_chain_keeps_claim_running_until_the_last_batch(ext_list, enqueue):
    _row(ext_list, track="one")
    _row(ext_list, track="two")
    claim = _claim("claim-chain", ext_list)
    with (
        patch.object(tm, "resolve_via_deezer_search", return_value=(None, 0.0)),
        patch.object(el.map_external_list_tracks, "apply_async") as chain,
    ):
        el._map_external_list_tracks_internal(
            ext_list, batch_size=1, task_id="claim-chain"
        )
        claim.refresh_from_db()
        assert claim.status == "RUNNING"
        chain.assert_called_once()
        assert chain.call_args.kwargs["task_id"] == "claim-chain"

        el._map_external_list_tracks_internal(
            ext_list, batch_size=1, task_id="claim-chain"
        )
    claim.refresh_from_db()
    assert claim.status == "COMPLETED"


@pytest.mark.django_db
def test_mapping_task_fails_its_claim_on_error(ext_list, enqueue):
    _row(ext_list)
    claim = _claim("claim-boom", ext_list)
    with patch.object(
        TrackMappingService, "map_tracks_batch", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            el._map_external_list_tracks_internal(ext_list, task_id="claim-boom")

    claim.refresh_from_db()
    assert claim.status == "FAILED"


# ---------------------------------------------------------------------------
# #2 removals: unlink on sync, never wipe on a bad fetch
# ---------------------------------------------------------------------------


def _fetch(tracks, complete=True, total=None):
    ext = [ExternalTrack(artist_name=a, track_name=t) for a, t in tracks]
    return ExternalListResult(
        tracks=ext,
        total_count=len(ext) if total is None else total,
        content_hash=ExternalListResult.compute_content_hash(ext),
        complete=complete,
    )


def _sync(ext_list, result, **kw):
    provider = MagicMock()
    provider.fetch_all_tracks.return_value = result
    with (
        patch("src.providers.get_provider", return_value=provider),
        patch.object(el, "enqueue_map_external_list_tracks") as queue,
    ):
        el._sync_external_list_internal(ext_list, task_id=kw.pop("task_id", "sync-1"))
    return queue


@pytest.mark.django_db
def test_tracks_removed_upstream_are_unlinked_but_songs_stay(ext_list):
    owner = _unlinked(name="Syn Artist")
    kept_song = Song.objects.create(name="Gone", gid=_gid(60), primary_artist=owner)
    _sync(ext_list, _fetch([("a", "keep"), ("a", "gone"), ("b", "other")]))
    ExternalListTrack.objects.filter(track_name="gone").update(
        mapping_status=TrackMappingStatus.MAPPED, song=kept_song
    )

    _sync(ext_list, _fetch([("a", "keep"), ("b", "other")]), task_id="sync-2")

    ext_list.refresh_from_db()
    names = set(ext_list.tracks.values_list("track_name", flat=True))
    assert names == {"keep", "other"}
    assert ext_list.total_tracks == 2
    assert Song.objects.filter(pk=kept_song.pk).exists()


@pytest.mark.django_db
def test_counts_are_recomputed_after_removals(ext_list):
    _sync(ext_list, _fetch([("a", "x"), ("a", "y")]))
    ExternalListTrack.objects.filter(track_name="y").update(
        mapping_status=TrackMappingStatus.MAPPED
    )
    ExternalListTrack.objects.filter(track_name="x").update(
        mapping_status=TrackMappingStatus.FAILED
    )
    _sync(ext_list, _fetch([("a", "x")]), task_id="sync-3")

    ext_list.refresh_from_db()
    assert (ext_list.total_tracks, ext_list.mapped_tracks, ext_list.failed_tracks) == (
        1,
        0,
        1,
    )


@pytest.mark.django_db
def test_empty_upstream_does_not_wipe_the_list(ext_list):
    _sync(ext_list, _fetch([("a", "x"), ("a", "y")]))
    ext_list.refresh_from_db()
    old_hash = ext_list.content_hash

    _sync(ext_list, _fetch([]), task_id="sync-4")

    ext_list.refresh_from_db()
    assert ext_list.tracks.count() == 2
    assert ext_list.content_hash == old_hash


@pytest.mark.django_db
def test_partial_fetch_adds_but_never_removes(ext_list):
    _sync(ext_list, _fetch([("a", "x"), ("a", "y")]))

    _sync(
        ext_list,
        _fetch([("a", "x"), ("a", "z")], complete=False),
        task_id="sync-5",
    )
    ext_list.refresh_from_db()
    assert set(ext_list.tracks.values_list("track_name", flat=True)) == {"x", "y", "z"}
    assert ext_list.content_hash is None


# ---------------------------------------------------------------------------
# Final-review follow-ups: explicit completeness, SKIP means skip, album CAS
# ---------------------------------------------------------------------------


class _PagedProvider(ExternalListProvider):
    def __init__(self, pages, total):
        self.pages = pages
        self.total = total

    def validate_user(self, username):
        return True, None

    def fetch_tracks(
        self, username, list_type, period=None, list_identifier=None, page=1, limit=200
    ):
        tracks = self.pages[page - 1] if page <= len(self.pages) else []
        return ExternalListResult(
            tracks=[ExternalTrack(artist_name=a, track_name=t) for a, t in tracks],
            total_count=self.total,
        )


def _fetch_all(provider):
    return ExternalListProvider.fetch_all_tracks(provider, "u", "loved")


def test_default_result_is_incomplete():
    assert ExternalListResult().complete is False
    assert ExternalListResult(tracks=[], total_count=3).complete is False


def test_paginated_fetch_is_complete_only_when_pages_match_upstream_total():
    assert _fetch_all(_PagedProvider([[("a", "1"), ("a", "2")]], 2)).complete is True
    # An early short page while upstream says there is more: unproven.
    assert _fetch_all(_PagedProvider([[("a", "1")]], 5)).complete is False
    # A source that reports no total cannot prove completeness.
    assert _fetch_all(_PagedProvider([[("a", "1"), ("a", "2")]], 0)).complete is False


def test_youtube_whole_list_proof_requires_every_item_parsed_and_headroom():
    from src.providers.youtube_music import YouTubeMusicProvider

    t = [ExternalTrack(artist_name="a", track_name="1")]
    whole = YouTubeMusicProvider._is_whole_list
    assert whole([{}], t, 1, 5000)
    assert not whole([{}, {}], t, 1, 5000)  # an item failed to parse
    assert not whole([{}], t, 1, 1)  # response hit the limit: may be truncated
    assert not whole([{}], t, 2, 5000)  # not the first page
    assert not whole([], [], 1, 5000)


@pytest.mark.django_db
def test_result_without_positive_completeness_never_removes_rows(ext_list):
    _sync(ext_list, _fetch([("a", "x"), ("a", "y")]))
    unproven = ExternalListResult(
        tracks=[ExternalTrack(artist_name="a", track_name="x")],
        total_count=1,
        content_hash="h-unproven",
    )
    _sync(ext_list, unproven, task_id="sync-unproven")

    assert set(ext_list.tracks.values_list("track_name", flat=True)) == {"x", "y"}


@pytest.mark.django_db(transaction=True)
def test_import_from_deezer_skip_creates_nothing(artist):
    from src.services.album import AlbumService

    local = Album.objects.create(
        name="Test Album", artist=artist, spotify_gid="SPALBUMSKIP", wanted=False
    )
    data = AlbumResult(
        name="Test Album",
        artist_name="Synthetic Artist",
        deezer_id=8810001,
        artist_deezer_id=artist.deezer_id,
    )
    provider = MagicMock()
    provider.get_album.return_value = data
    with (
        patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider),
        patch(PATCH_DEEZER_UPC, return_value=OTHER_UPC),
        patch(PATCH_UPC, return_value=VALID_UPC),
    ):
        result = asyncio.run(AlbumService().import_from_deezer(8810001))

    assert result.success is False
    assert Album.objects.filter(artist=artist).count() == 1
    local.refresh_from_db()
    assert local.deezer_id is None and local.wanted is False


@pytest.mark.django_db
def test_link_album_requires_the_frozen_pre_image(artist):
    from library_manager.release_ids import link_album_deezer_id

    first = Album.objects.create(name="Frozen", artist=artist, spotify_gid="SPFROZEN1")
    assert link_album_deezer_id(first, 8820001)
    assert Album.objects.get(pk=first.pk).deezer_id == 8820001

    # Concurrently linked elsewhere between proof and write: not overwritten.
    stale = Album.objects.create(
        name="Frozen 2", artist=artist, spotify_gid="SPFROZEN2"
    )
    Album.objects.filter(pk=stale.pk).update(deezer_id=8820002)
    stale.deezer_id = None  # the caller's stale snapshot
    assert not link_album_deezer_id(stale, 8820003)
    assert Album.objects.get(pk=stale.pk).deezer_id == 8820002

    # Spotify gid changed under us: the proof no longer applies.
    moved = Album.objects.create(
        name="Frozen 3", artist=artist, spotify_gid="SPFROZEN3"
    )
    Album.objects.filter(pk=moved.pk).update(spotify_gid="SPOTHER3")
    assert not link_album_deezer_id(moved, 8820004)
    assert Album.objects.get(pk=moved.pk).deezer_id is None

    # The Deezer id was claimed by another row: IntegrityError is a skip.
    clash = Album.objects.create(
        name="Frozen 4", artist=artist, spotify_gid="SPFROZEN4"
    )
    assert not link_album_deezer_id(clash, 8820001)
    assert Album.objects.get(pk=clash.pk).deezer_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["name", "spotify_gid", "spotify_uri", "artist_id"])
def test_link_album_skips_when_any_proof_field_changed_concurrently(artist, field):
    from library_manager.release_ids import link_album_deezer_id

    album = Album.objects.create(
        name="Proof",
        artist=artist,
        spotify_gid="SPPROOF1",
        spotify_uri="spotify:album:SPPROOF1",
    )
    other = Artist.objects.create(name="Other Synthetic", deezer_id=8830001)
    changed = {
        "name": "Proof (Deluxe)",
        "spotify_gid": "SPPROOF2",
        "spotify_uri": "spotify:album:SPPROOF2",
        "artist_id": other.pk,
    }[field]
    Album.objects.filter(pk=album.pk).update(**{field: changed})

    assert not link_album_deezer_id(album, 8830002)  # album is the stale snapshot
    assert Album.objects.get(pk=album.pk).deezer_id is None
