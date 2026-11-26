"""Artist-credit ingestion: lead as primary, every credit stored as a contributor.

All names and ids in this module are synthetic.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from library_manager import artist_credits
from library_manager.artist_credits import (
    create_song_with_credits,
    credits_for_track,
    ensure_song_credits,
    record_contributors,
    replace_contributors,
    resolve_artist,
    resolve_credit,
)
from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    Song,
    TrackingTier,
)
from src.providers.deezer import _to_track_result
from src.providers.metadata_base import ArtistCredit, TrackResult
from src.services.song import SongService


async def _noop() -> None:
    return None


@pytest.fixture(autouse=True)
def _clear_credit_cache():
    artist_credits.clear_track_cache()
    yield
    artist_credits.clear_track_cache()


def _track(
    deezer_id: int = 9001,
    lead: tuple[str, int] = ("Lead Person", 101),
    credits: list[ArtistCredit] | None = None,
    isrc: str | None = "ZZTEST000001",
) -> TrackResult:
    return TrackResult(
        name="Synthetic Song",
        artist_name=lead[0],
        deezer_id=deezer_id,
        isrc=isrc,
        artist_deezer_id=lead[1],
        credits=credits or [],
    )


def _full_credits() -> list[ArtistCredit]:
    return [
        ArtistCredit(name="Lead Person", deezer_id=101, role="main"),
        ArtistCredit(name="Guest Person", deezer_id=102, role="main"),
        ArtistCredit(name="Remixer Person", deezer_id=103, role="featured"),
    ]


@pytest.mark.unit
class TestDeezerTrackConversion:
    def test_contributors_with_roles_become_credits(self) -> None:
        def _artist(aid: int, name: str, role: str) -> SimpleNamespace:
            return SimpleNamespace(
                id=aid, name=name, role=role, _fields=("id", "name", "role")
            )

        lead = _artist(101, "Lead Person", "Main")
        track = SimpleNamespace(
            id=9001,
            title="Synthetic Song",
            artist=lead,
            contributors=[lead, _artist(103, "Remixer Person", "Featured")],
            duration=100,
            _fields=("id", "title", "artist", "contributors", "duration"),
        )

        result = _to_track_result(track)

        assert [(c.deezer_id, c.role) for c in result.credits] == [
            (101, "main"),
            (103, "featured"),
        ]

    def test_listing_without_contributors_has_no_credits(self) -> None:
        lead = SimpleNamespace(id=101, name="Lead Person")
        track = SimpleNamespace(
            id=9001,
            title="Synthetic Song",
            artist=lead,
            duration=100,
            _fields=("id", "title", "artist", "duration"),
        )

        assert _to_track_result(track).credits == []


@pytest.mark.unit
class TestResolveArtist:
    def test_matches_by_deezer_id_first(self) -> None:
        existing = Artist.objects.create(name="Renamed Elsewhere", deezer_id=555)

        assert resolve_artist("Whatever Name", deezer_id=555) == existing

    def test_creates_artist_when_id_unknown(self) -> None:
        artist = resolve_artist("Brand New Person", deezer_id=777)

        assert artist is not None
        assert artist.deezer_id == 777
        assert artist.tracking_tier == TrackingTier.UNTRACKED

    @pytest.mark.parametrize("ids", [{"youtube_id": "synthetic-1"}, {"gid": "h" * 22}])
    def test_unverified_same_name_row_is_ambiguous_and_creates_nothing(
        self, ids: dict
    ) -> None:
        existing = Artist.objects.create(name="Distinctive Quartet", **ids)

        result = resolve_credit("distinctive quartet", deezer_id=778)

        assert result.status == "ambiguous" and result.artist is None
        assert Artist.objects.count() == 1
        existing.refresh_from_db()
        assert existing.deezer_id is None

    def test_same_name_row_with_a_different_deezer_id_is_a_namesake(self) -> None:
        existing = Artist.objects.create(name="Distinctive Quartet", deezer_id=5)

        artist = resolve_artist("Distinctive Quartet", deezer_id=778)

        assert artist is not None and artist != existing
        existing.refresh_from_db()
        assert existing.deezer_id == 5

    def test_short_generic_name_is_never_adopted_without_evidence(self) -> None:
        unlinked = Artist.objects.create(name="Kim", gid="b" * 22)

        assert resolve_artist("Kim", deezer_id=779) is None
        assert Artist.objects.filter(name="Kim").count() == 1
        unlinked.refresh_from_db()
        assert unlinked.deezer_id is None

    def test_several_unlinked_same_name_rows_stay_ambiguous(self) -> None:
        Artist.objects.create(name="Shared Longname", gid="c" * 22)
        Artist.objects.create(name="Shared Longname", youtube_id="yt-2")

        result = resolve_credit(
            "Shared Longname", deezer_id=780, evidence_isrcs=["ZZNOLINK0001"]
        )

        assert result.artist is None
        assert Artist.objects.filter(name="Shared Longname").count() == 2

    def test_artist_with_other_deezer_id_is_not_adopted(self) -> None:
        other = Artist.objects.create(name="Unique Longname", deezer_id=1)

        artist = resolve_artist("Unique Longname", deezer_id=781)

        assert artist is not None and artist != other
        other.refresh_from_db()
        assert other.deezer_id == 1

    def test_without_any_identifier_returns_none(self) -> None:
        assert resolve_artist("Nameless Id") is None

    def test_spotify_credit_without_evidence_does_not_duplicate_deezer_row(
        self,
    ) -> None:
        deezer_only = Artist.objects.create(name="Spotify Twin Name", deezer_id=5)

        assert resolve_artist("Spotify Twin Name", gid="d" * 22) is None
        assert Artist.objects.count() == 1
        deezer_only.refresh_from_db()
        assert deezer_only.gid is None


@pytest.mark.unit
class TestCreditsForTrack:
    def test_listing_track_is_enriched_with_one_cached_lookup(self) -> None:
        provider = MagicMock()
        provider.get_track.return_value = _track(credits=_full_credits())

        first = credits_for_track(_track(), provider=provider)
        second = credits_for_track(_track(), provider=provider)

        assert [c.deezer_id for c in first] == [101, 102, 103]
        assert first == second
        provider.get_track.assert_called_once_with(9001)

    def test_track_with_credits_needs_no_lookup(self) -> None:
        provider = MagicMock()

        result = credits_for_track(_track(credits=_full_credits()), provider=provider)

        assert len(result) == 3
        provider.get_track.assert_not_called()

    def test_failed_lookup_falls_back_to_listing_artist(self) -> None:
        provider = MagicMock()
        provider.get_track.side_effect = RuntimeError("boom")

        result = credits_for_track(_track(), provider=provider)

        assert [(c.deezer_id, c.role) for c in result] == [(101, "main")]

    def test_lookup_can_be_disabled(self) -> None:
        provider = MagicMock()

        result = credits_for_track(_track(), provider=provider, fetch_missing=False)

        assert [c.deezer_id for c in result] == [101]
        provider.get_track.assert_not_called()

    def test_listing_artist_leads_even_if_contributors_reorder(self) -> None:
        reordered = [
            ArtistCredit(name="Guest Person", deezer_id=102, role="main"),
            ArtistCredit(name="Lead Person", deezer_id=101, role="main"),
        ]

        result = credits_for_track(_track(credits=reordered), fetch_missing=False)

        assert result[0].deezer_id == 101


@pytest.mark.unit
class TestCreateSongWithCredits:
    def _tracked_album(self) -> tuple[Artist, Album]:
        tracked = Artist.objects.create(
            name="Tracked Person", deezer_id=102, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=42)
        return tracked, album

    def test_lead_is_primary_and_all_credits_are_contributors(self) -> None:
        tracked, album = self._tracked_album()

        song = create_song_with_credits(_track(credits=_full_credits()), album=album)

        assert song.primary_artist.deezer_id == 101
        assert song.primary_artist != tracked
        linked = set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__deezer_id", flat=True
            )
        )
        assert linked == {101, 102, 103}

    def test_uncredited_tracked_artist_is_not_a_contributor(self) -> None:
        tracked, album = self._tracked_album()
        credits = [ArtistCredit(name="Lead Person", deezer_id=101, role="main")]

        song = create_song_with_credits(_track(credits=credits), album=album)

        assert not ContributingArtist.objects.filter(song=song, artist=tracked).exists()
        assert song.primary_artist.deezer_id == 101

    def test_untracked_album_artist_is_not_force_linked(self) -> None:
        untracked = Artist.objects.create(name="Compiler Person", deezer_id=200)
        album = Album.objects.create(name="Compilation", artist=untracked, deezer_id=43)
        credits = [ArtistCredit(name="Lead Person", deezer_id=101, role="main")]

        song = create_song_with_credits(_track(credits=credits), album=album)

        assert not ContributingArtist.objects.filter(
            song=song, artist=untracked
        ).exists()

    def test_same_name_different_id_is_a_distinct_artist(self) -> None:
        tracked = Artist.objects.create(
            name="Kim", deezer_id=300, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=44)
        credits = [ArtistCredit(name="Kim", deezer_id=301, role="main")]

        song = create_song_with_credits(
            _track(credits=credits, lead=("Kim", 301)),
            album=album,
        )

        assert song.primary_artist.deezer_id == 301
        assert Artist.objects.filter(name="Kim").count() == 2

    def test_no_source_credit_creates_nothing_and_never_uses_tracked_artist(
        self,
    ) -> None:
        tracked, album = self._tracked_album()
        bare = TrackResult(name="Bare", artist_name="", deezer_id=9100)

        song = create_song_with_credits(bare, album=album, fetch_missing=False)

        assert song is None
        assert not Song.objects.filter(deezer_id=9100).exists()
        assert not ContributingArtist.objects.filter(artist=tracked).exists()

    def test_does_not_duplicate_contributor_rows(self) -> None:
        tracked, album = self._tracked_album()
        song = create_song_with_credits(_track(credits=_full_credits()), album=album)

        artist_credits.record_contributors(song, list(Artist.objects.all()))

        assert ContributingArtist.objects.filter(song=song).count() == 3
        assert Song.objects.count() == 1


@pytest.mark.unit
class TestDeezerIngestionSites:
    def test_playlist_sync_creates_song_with_lead_and_credits(self) -> None:
        from library_manager.models import TrackedPlaylist
        from library_manager.tasks import playlist as playlist_tasks

        tracked_playlist = TrackedPlaylist.objects.create(
            name="Synthetic List",
            url="https://www.deezer.com/en/playlist/12345",
            provider="deezer",
        )
        provider = MagicMock()
        provider.get_playlist.return_value = None
        provider.get_playlist_tracks.return_value = [_track(credits=_full_credits())]

        with (
            patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider),
            patch.object(playlist_tasks.helpers, "enqueue_download_deezer_track"),
            patch.object(playlist_tasks, "_generate_m3u_if_enabled"),
        ):
            playlist_tasks.sync_deezer_playlist(tracked_playlist.id, task_id="t-1")

        song = Song.objects.get(deezer_id=9001)
        assert song.primary_artist.deezer_id == 101
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__deezer_id", flat=True
            )
        ) == {101, 102, 103}

    def test_album_download_stores_lead_not_the_discography_artist(self) -> None:
        from library_manager.models import TaskHistory
        from library_manager.tasks.download import _download_deezer_album

        tracked = Artist.objects.create(
            name="Tracked Person", deezer_id=102, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(
            name="Their Album", artist=tracked, deezer_id=42, wanted=True
        )
        listing = _track()  # listing entry: lead only, no credit list
        provider = MagicMock()
        provider.get_album_tracks.return_value = [listing]
        provider.get_album.return_value = MagicMock(image_url=None, genres=[])
        provider.get_track.return_value = _track(credits=_full_credits())
        failed_chain = MagicMock(success=False, error_message="stop", file_path=None)

        async def _no_download(*_args, **_kwargs):
            return failed_chain

        downloader = MagicMock(download_track=_no_download)
        downloader.close = MagicMock(return_value=_noop())

        with (
            patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider),
            patch(
                "downloader.providers.fallback.FallbackDownloader",
                return_value=downloader,
            ),
            patch("library_manager.tasks.download._finalize_provider_diagnostics"),
        ):
            _download_deezer_album(
                album, TaskHistory.objects.create(task_id="t-2", type="DOWNLOAD")
            )

        song = Song.objects.get(deezer_id=9001, album=album)
        assert song.primary_artist.deezer_id == 101
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__deezer_id", flat=True
            )
        ) == {101, 102, 103}

    def test_migration_creates_song_with_lead_and_credits(self) -> None:
        from library_manager.tasks import migration

        tracked = Artist.objects.create(
            name="Tracked Person", deezer_id=102, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=42)

        result = migration._link_or_create_song(
            _track(credits=_full_credits()), tracked, album
        )

        assert result == "created"
        song = Song.objects.get(deezer_id=9001)
        assert song.primary_artist.deezer_id == 101
        assert ContributingArtist.objects.filter(song=song, artist=tracked).exists()

    def test_spotify_track_records_every_credited_artist(self) -> None:
        from library_manager.tasks.download import (
            _match_or_create_song_from_spotify_track,
        )

        payload = {
            "id": "e" * 22,
            "name": "Synthetic Song",
            "external_ids": {"isrc": "ZZTEST000002"},
            "artists": [
                {"id": "f" * 22, "name": "Lead Person"},
                {"id": "g" * 22, "name": "Guest Person"},
            ],
        }

        song = _match_or_create_song_from_spotify_track(payload)

        assert song is not None
        assert song.primary_artist.gid == "f" * 22
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__gid", flat=True
            )
        ) == {"f" * 22, "g" * 22}


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestGuestAppearancesStayInDiscography:
    @pytest.mark.asyncio
    async def test_artist_song_list_includes_contributed_songs(self) -> None:
        from asgiref.sync import sync_to_async

        def _setup() -> tuple[int, int, int]:
            tracked = Artist.objects.create(
                name="Tracked Person",
                deezer_id=102,
                tracking_tier=TrackingTier.TRACKED,
            )
            lead = Artist.objects.create(name="Lead Person", deezer_id=101)
            own = Song.objects.create(name="Own", primary_artist=tracked, deezer_id=1)
            guest = Song.objects.create(name="Guest", primary_artist=lead, deezer_id=2)
            ContributingArtist.objects.create(song=guest, artist=lead)
            ContributingArtist.objects.create(song=guest, artist=tracked)
            Song.objects.create(name="Unrelated", primary_artist=lead, deezer_id=3)
            return tracked.id, own.id, guest.id

        tracked_id, own_id, guest_id = await sync_to_async(_setup)()

        page = await SongService().get_page(artist_id=tracked_id)

        assert {int(s.id) for s in page.items} == {own_id, guest_id}
        assert page.total_count == 2


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestPaginationQueryCount:
    def test_song_page_query_count_is_bounded(self) -> None:
        """Five songs on a page must not cost five extra relation queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from asgiref.sync import async_to_sync
        from tests.factories import ArtistFactory, SongFactory

        from src.services.song import SongService

        artist = ArtistFactory(name="Query Count Artist")
        for i in range(5):
            SongFactory(name=f"Synthetic {i}", primary_artist=artist)

        with CaptureQueriesContext(connection) as ctx:
            result = async_to_sync(SongService().get_page)(page=1, page_size=5)
        queries = [q["sql"] for q in ctx.captured_queries]
        assert len(queries) <= 2, queries
        assert len(result.items) == 5

    @pytest.mark.asyncio
    async def test_artist_filter_returns_distinct_songs(self) -> None:
        from asgiref.sync import sync_to_async

        from src.services.song import SongService

        def setup() -> int:
            artist = Artist.objects.create(name="Query Artist", deezer_id=700)
            for i in range(3):
                create_song_with_credits(
                    TrackResult(
                        name=f"Synthetic {i}",
                        artist_name="Other Lead",
                        deezer_id=7100 + i,
                        credits=[
                            ArtistCredit(name="Other Lead", deezer_id=7200 + i),
                            ArtistCredit(name="Query Artist", deezer_id=700),
                        ],
                    ),
                    fetch_missing=False,
                )
            return artist.pk

        artist_id = await sync_to_async(setup)()
        page = await SongService().get_page(artist_id=artist_id)
        assert page.total_count == 3
        assert len({s.id for s in page.items}) == 3


@pytest.mark.unit
class TestContributorReplacement:
    def test_replace_exact_set_and_ensure_reuses_it(self) -> None:
        lead = Artist.objects.create(name="Lead Person", deezer_id=911)
        song = Song.objects.create(
            name="Synthetic", deezer_id=9300, primary_artist=lead
        )
        stale = Artist.objects.create(name="Stale Person", deezer_id=912)
        record_contributors(song, [lead, stale])

        real_guest = Artist.objects.create(name="Real Guest", deezer_id=913)
        replace_contributors(song, [lead, real_guest])

        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist_id", flat=True
            )
        ) == {lead.pk, real_guest.pk}
        ensure_song_credits(song, [ArtistCredit(name="Lead Person", deezer_id=911)])
        assert not ContributingArtist.objects.filter(
            song=song, artist=real_guest
        ).exists()


@pytest.mark.unit
class TestFailedEnrichmentNeverPurges:
    def _song_with_verified_credits(self) -> tuple[Song, Artist, Artist]:
        lead = Artist.objects.create(name="Verified Lead", deezer_id=1)
        guest = Artist.objects.create(name="Verified Guest", deezer_id=2)
        song = Song.objects.create(
            name="Synthetic", deezer_id=9400, primary_artist=lead
        )
        record_contributors(song, [lead, guest])
        return song, lead, guest

    def test_failed_lookup_returns_no_credits_for_reconciliation(self) -> None:
        provider = MagicMock()
        provider.get_track.side_effect = RuntimeError("boom")

        credits = credits_for_track(
            _track(deezer_id=9400), provider=provider, listing_fallback=False
        )

        assert credits == []

    def test_failed_lookup_preserves_existing_contributors(self) -> None:
        song, lead, guest = self._song_with_verified_credits()
        provider = MagicMock()
        provider.get_track.return_value = None

        credits = credits_for_track(
            _track(deezer_id=9400, lead=("Verified Lead", 1)),
            provider=provider,
            listing_fallback=False,
        )

        assert ensure_song_credits(song, credits) is False
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist_id", flat=True
            )
        ) == {lead.pk, guest.pk}

    def test_playlist_reuse_with_failed_lookup_keeps_credits(self) -> None:
        from library_manager.models import TrackedPlaylist
        from library_manager.tasks import playlist as playlist_tasks

        song, lead, guest = self._song_with_verified_credits()
        song.isrc = "ZZTEST000001"
        song.save()
        tracked_playlist = TrackedPlaylist.objects.create(
            name="Synthetic List",
            url="https://www.deezer.com/en/playlist/54321",
            provider="deezer",
        )
        provider = MagicMock()
        provider.get_playlist.return_value = None
        provider.get_playlist_tracks.return_value = [
            _track(deezer_id=9400, lead=("Verified Lead", 1))
        ]
        provider.get_track.side_effect = RuntimeError("deezer down")

        with (
            patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider),
            patch.object(playlist_tasks.helpers, "enqueue_download_deezer_track"),
            patch.object(playlist_tasks, "_generate_m3u_if_enabled"),
        ):
            playlist_tasks.sync_deezer_playlist(tracked_playlist.id, task_id="t-3")

        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist_id", flat=True
            )
        ) == {lead.pk, guest.pk}


@pytest.mark.unit
class TestIdentityPreImageGuard:
    def test_stale_reconciliation_does_not_overwrite_newer_identity(self) -> None:
        from library_manager.artist_credits import (
            identity_snapshot,
            replace_identity_if_unchanged,
        )

        lead = Artist.objects.create(name="Old Lead", deezer_id=1)
        song = Song.objects.create(
            name="Synthetic", deezer_id=9500, primary_artist=lead
        )
        stale_view = identity_snapshot(song.pk)
        newer = Artist.objects.create(name="Newer Guest", deezer_id=2)
        record_contributors(song, [newer])  # a newer correction lands

        stale_credits = [
            ArtistCredit(name="Old Lead", deezer_id=1),
            ArtistCredit(name="Brand New Person", deezer_id=777),
        ]
        replaced = replace_identity_if_unchanged(song.pk, stale_view, stale_credits)

        assert replaced == "changed"
        assert ContributingArtist.objects.filter(song=song, artist=newer).exists()
        # A stale plan creates no Artist rows at all.
        assert not Artist.objects.filter(deezer_id=777).exists()


@pytest.mark.unit
class TestMigrationIsrcOrder:
    def test_isrc_conflicting_match_is_not_reconciled(self) -> None:
        from library_manager.tasks import migration

        tracked = Artist.objects.create(
            name="Tracked Person", deezer_id=102, tracking_tier=TrackingTier.TRACKED
        )
        album = Album.objects.create(name="Their Album", artist=tracked, deezer_id=42)
        old_lead = Artist.objects.create(name="Old Lead", deezer_id=1)
        other = Song.objects.create(
            name="Synthetic Song",
            gid="m" * 22,
            isrc="ZZOTHER00009",
            primary_artist=old_lead,
        )
        record_contributors(other, [old_lead])

        with patch.object(migration, "_find_matching_song", return_value=other):
            result = migration._link_or_create_song(
                _track(credits=_full_credits()), tracked, album
            )

        other.refresh_from_db()
        assert result == "created"
        assert other.primary_artist == old_lead
        assert other.deezer_id is None
        assert set(
            ContributingArtist.objects.filter(song=other).values_list(
                "artist_id", flat=True
            )
        ) == {old_lead.pk}


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestArtistCardQueryCount:
    def test_artist_page_counts_are_batched(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from asgiref.sync import async_to_sync

        from src.services.artist import ArtistService

        artists = []
        for i in range(6):
            artist = Artist.objects.create(
                name=f"Card Artist {i}",
                deezer_id=6000 + i,
                tracking_tier=TrackingTier.TRACKED,
            )
            album = Album.objects.create(
                name=f"Album {i}",
                artist=artist,
                deezer_id=6100 + i,
                wanted=True,
                album_type="album",
                album_group="album",
            )
            Song.objects.create(
                name=f"Failing {i}",
                deezer_id=6200 + i,
                primary_artist=artist,
                album=album,
                failed_count=2,
            )
            artists.append(artist)
        guest_song = Song.objects.create(
            name="Guest Fail",
            deezer_id=6300,
            primary_artist=artists[1],
            failed_count=1,
        )
        ContributingArtist.objects.create(song=guest_song, artist=artists[0])

        with CaptureQueriesContext(connection) as ctx:
            page = async_to_sync(ArtistService().get_page)(page=1, page_size=50)

        assert 1 <= len(ctx.captured_queries) <= 8, [
            q["sql"][:80] for q in ctx.captured_queries
        ]
        by_name = {a.name: a for a in page.items}
        assert by_name["Card Artist 0"].failed_song_count == 2  # own + guest link
        assert by_name["Card Artist 1"].failed_song_count == 2  # own + led guest song
        assert by_name["Card Artist 2"].failed_song_count == 1


@pytest.mark.unit
class TestEvidenceBasedAdoption:
    def _spotify_only_with_song(
        self, isrc: str = "ZZEVID000001", tier: int = TrackingTier.UNTRACKED
    ) -> tuple[Artist, Song]:
        row = Artist.objects.create(
            name="Evidence Person", gid="e" * 22, tracking_tier=tier
        )
        song = Song.objects.create(
            name="Linked Song", gid="s" * 22, isrc=isrc, primary_artist=row
        )
        return row, song

    def test_verified_adoption_sets_the_deezer_id_once(self) -> None:
        row, _song = self._spotify_only_with_song()

        first = resolve_credit(
            "Evidence Person", deezer_id=500, evidence_isrcs=["zzevid000001"]
        )
        second = resolve_credit("Evidence Person", deezer_id=500)

        assert (first.status, first.artist) == ("adopted", row)
        assert (second.status, second.artist) == ("found", row)
        row.refresh_from_db()
        assert row.deezer_id == 500 and row.gid == "e" * 22
        assert Artist.objects.count() == 1

    def test_contributor_link_and_alternate_isrc_also_verify(self) -> None:
        row = Artist.objects.create(name="Guest Evidence", gid="g" * 22)
        lead = Artist.objects.create(name="Some Lead", deezer_id=9)
        song = Song.objects.create(
            name="Guest Song",
            gid="t" * 22,
            isrc="ZZEVID000002",
            alternate_isrcs=["ZZEVID000003"],
            primary_artist=lead,
        )
        record_contributors(song, [lead, row])

        result = resolve_credit(
            "Guest Evidence", deezer_id=501, evidence_isrcs=["ZZEVID000003"]
        )

        assert (result.status, result.artist) == ("adopted", row)

    def test_dry_resolution_reports_without_writing(self) -> None:
        row, _song = self._spotify_only_with_song()

        result = resolve_credit(
            "Evidence Person",
            deezer_id=500,
            evidence_isrcs=["ZZEVID000001"],
            create=False,
        )

        assert result.status == "would_adopt"
        row.refresh_from_db()
        assert row.deezer_id is None

    def test_unrelated_isrc_is_not_evidence(self) -> None:
        row, _song = self._spotify_only_with_song()

        result = resolve_credit(
            "Evidence Person", deezer_id=500, evidence_isrcs=["ZZOTHER00001"]
        )

        assert result.status == "ambiguous"
        assert Artist.objects.count() == 1

    def test_tracked_artist_without_deezer_id_is_adopted_by_isrc_link(self) -> None:
        tracked, existing = self._spotify_only_with_song(tier=TrackingTier.TRACKED)
        track = TrackResult(
            name="Synthetic Song",
            artist_name="Evidence Person",
            deezer_id=9600,
            isrc="ZZEVID000001",
            artist_deezer_id=500,
            credits=[ArtistCredit(name="Evidence Person", deezer_id=500)],
        )

        song = create_song_with_credits(track, fetch_missing=False)

        assert song is not None and song.primary_artist == tracked
        tracked.refresh_from_db()
        assert tracked.deezer_id == 500
        assert tracked.tracking_tier == TrackingTier.TRACKED
        assert Artist.objects.count() == 1
        assert existing.primary_artist == tracked

    def test_unverified_lead_skips_the_song_and_creates_no_row(self) -> None:
        Artist.objects.create(name="Evidence Person", gid="e" * 22)
        track = TrackResult(
            name="Synthetic Song",
            artist_name="Evidence Person",
            deezer_id=9601,
            isrc="ZZNOLINK0002",
            artist_deezer_id=500,
            credits=[ArtistCredit(name="Evidence Person", deezer_id=500)],
        )

        assert create_song_with_credits(track, fetch_missing=False) is None
        assert Artist.objects.count() == 1
        assert not Song.objects.filter(deezer_id=9601).exists()

    def test_unverified_guest_is_skipped_but_the_song_is_created(self) -> None:
        Artist.objects.create(name="Evidence Guest", gid="e" * 22)
        track = TrackResult(
            name="Synthetic Song",
            artist_name="Lead Person",
            deezer_id=9602,
            isrc="ZZNOLINK0003",
            artist_deezer_id=101,
            credits=[
                ArtistCredit(name="Lead Person", deezer_id=101),
                ArtistCredit(name="Evidence Guest", deezer_id=502),
            ],
        )

        song = create_song_with_credits(track, fetch_missing=False)

        assert song is not None and song.primary_artist.deezer_id == 101
        assert set(
            ContributingArtist.objects.filter(song=song).values_list(
                "artist__deezer_id", flat=True
            )
        ) == {101}
        assert Artist.objects.filter(name="Evidence Guest").count() == 1

    def test_concurrent_adoption_of_the_same_id_resolves_to_one_row(self) -> None:
        row, _song = self._spotify_only_with_song()

        def racing_writer(*_a: object, **_k: object) -> bool:
            # Another worker adopts the same Deezer artist first.
            Artist.objects.filter(pk=row.pk).update(deezer_id=500)
            return True

        with patch.object(artist_credits, "_linked_by_isrc", racing_writer):
            result = resolve_credit(
                "Evidence Person", deezer_id=500, evidence_isrcs=["ZZEVID000001"]
            )

        assert (result.status, result.artist) == ("found", row)
        assert Artist.objects.count() == 1

    def test_concurrent_adoption_by_another_deezer_artist_makes_a_namesake(
        self,
    ) -> None:
        row, _song = self._spotify_only_with_song()

        def racing_writer(*_a: object, **_k: object) -> bool:
            Artist.objects.filter(pk=row.pk).update(deezer_id=999)
            return True

        with patch.object(artist_credits, "_linked_by_isrc", racing_writer):
            result = resolve_credit(
                "Evidence Person", deezer_id=500, evidence_isrcs=["ZZEVID000001"]
            )

        row.refresh_from_db()
        assert row.deezer_id == 999  # the winner keeps its id, never overwritten
        assert result.artist is not None and result.artist != row
        assert result.artist.deezer_id == 500

    def test_ambiguous_credit_rolls_back_rows_made_for_the_same_plan(self) -> None:
        from library_manager.artist_credits import (
            identity_snapshot,
            replace_identity_if_unchanged,
        )

        Artist.objects.create(name="Evidence Guest", gid="e" * 22)
        lead = Artist.objects.create(name="Old Lead", deezer_id=1)
        song = Song.objects.create(
            name="Synthetic", deezer_id=9700, primary_artist=lead
        )
        credits = [
            ArtistCredit(name="Fresh Lead", deezer_id=801),
            ArtistCredit(name="Evidence Guest", deezer_id=802),
        ]

        outcome = replace_identity_if_unchanged(
            song.pk, identity_snapshot(song.pk), credits, ["ZZNOLINK0004"]
        )

        assert outcome == "ambiguous"
        assert not Artist.objects.filter(deezer_id=801).exists()
        song.refresh_from_db()
        assert song.primary_artist == lead


@pytest.mark.unit
class TestSameNameDifferentId:
    def _tracked_with_song(self, isrc: str = "ZZNAME000001") -> tuple[Artist, Song]:
        tracked = Artist.objects.create(
            name="Namesake Person", deezer_id=300, tracking_tier=TrackingTier.TRACKED
        )
        song = Song.objects.create(
            name="Existing", gid="n" * 22, isrc=isrc, primary_artist=tracked
        )
        return tracked, song

    def _track(self, isrc: str) -> TrackResult:
        return TrackResult(
            name="Synthetic Song",
            artist_name="Namesake Person",
            deezer_id=9800,
            isrc=isrc,
            artist_deezer_id=301,
            credits=[ArtistCredit(name="Namesake Person", deezer_id=301)],
        )

    def test_new_song_joins_the_tracked_row_when_an_isrc_links_them(self) -> None:
        tracked, _existing = self._tracked_with_song()

        song = create_song_with_credits(
            self._track("ZZNAME000001"), fetch_missing=False
        )

        assert song is not None and song.primary_artist == tracked
        assert Artist.objects.count() == 1
        tracked.refresh_from_db()
        assert tracked.deezer_id == 300  # the tracked row is never rewritten

    def test_new_song_without_isrc_link_creates_the_namesake_and_logs(self) -> None:
        tracked, _existing = self._tracked_with_song()

        with patch.object(artist_credits.logger, "warning") as warning:
            song = create_song_with_credits(
                self._track("ZZUNRELATED01"), fetch_missing=False
            )

        assert song is not None and song.primary_artist != tracked
        assert song.primary_artist.deezer_id == 301
        assert Artist.objects.filter(name="Namesake Person").count() == 2
        assert any(
            "same_name_different_id" in c.args[0] for c in warning.call_args_list
        )

    def test_untracked_namesake_is_not_linked_even_with_an_isrc(self) -> None:
        untracked = Artist.objects.create(name="Namesake Person", deezer_id=300)
        Song.objects.create(
            name="Existing", gid="n" * 22, isrc="ZZNAME000001", primary_artist=untracked
        )

        song = create_song_with_credits(
            self._track("ZZNAME000001"), fetch_missing=False
        )

        assert song is not None and song.primary_artist != untracked
        assert song.primary_artist.deezer_id == 301

    def test_reconciling_an_existing_song_keeps_a_same_name_primary(self) -> None:
        tracked, existing = self._tracked_with_song()

        with patch.object(artist_credits.logger, "warning") as warning:
            changed = ensure_song_credits(
                existing, [ArtistCredit(name="Namesake Person", deezer_id=301)]
            )

        existing.refresh_from_db()
        assert changed is False and existing.primary_artist == tracked
        assert Artist.objects.count() == 1
        assert any(
            "same_name_different_id" in c.args[0] for c in warning.call_args_list
        )


@pytest.mark.unit
class TestSongCannotVouchForItself:
    def _setup(self) -> tuple[Artist, Song]:
        row = Artist.objects.create(name="Evidence Person", gid="e" * 22)
        song = Song.objects.create(
            name="Being Corrected",
            gid="a" * 22,
            deezer_id=9900,
            isrc="ZZSELF000001",
            primary_artist=row,
        )
        return row, song

    def _credits(self) -> list[ArtistCredit]:
        return [ArtistCredit(name="Evidence Person", deezer_id=500)]

    def test_only_the_reconciled_song_shares_the_isrc_so_nothing_is_adopted(
        self,
    ) -> None:
        row, song = self._setup()

        changed = ensure_song_credits(song, self._credits())

        assert changed is False
        row.refresh_from_db()
        assert row.deezer_id is None
        assert Artist.objects.count() == 1

    def test_a_song_sharing_its_deezer_id_or_file_is_not_independent(self) -> None:
        from library_manager.models import FilePath

        row, song = self._setup()
        shared = FilePath.objects.create(path="/tmp/synthetic/shared.m4a")
        Song.objects.filter(pk=song.pk).update(file_path_ref=shared)
        Song.objects.create(  # same Deezer track id on another album copy
            name="Copy",
            gid="b" * 22,
            deezer_id=9900,
            isrc="ZZSELF000001",
            primary_artist=row,
        )
        Song.objects.create(  # same audio file
            name="Alias",
            gid="c" * 22,
            isrc="ZZSELF000001",
            primary_artist=row,
            file_path_ref=shared,
        )

        assert ensure_song_credits(song, self._credits()) is False
        row.refresh_from_db()
        assert row.deezer_id is None

    def test_a_distinct_linked_song_with_the_isrc_allows_adoption(self) -> None:
        row, song = self._setup()
        Song.objects.create(
            name="Independent", gid="d" * 22, isrc="ZZSELF000001", primary_artist=row
        )

        changed = ensure_song_credits(song, self._credits())

        assert changed is True
        row.refresh_from_db()
        song.refresh_from_db()
        assert row.deezer_id == 500 and song.primary_artist == row

    def test_a_cached_positive_cannot_vouch_for_a_song_that_is_its_own_evidence(
        self,
    ) -> None:
        row, song = self._setup()
        other = Song.objects.create(
            name="Independent", gid="d" * 22, isrc="ZZSELF000001", primary_artist=row
        )
        isrcs = ["ZZSELF000001"]

        first = resolve_credit(
            "Evidence Person",
            deezer_id=500,
            evidence_isrcs=isrcs,
            create=False,
            exclude_song_ids=frozenset({song.pk}),
        )
        # Same pair, but now the independent song is the one being corrected.
        second = resolve_credit(
            "Evidence Person",
            deezer_id=500,
            evidence_isrcs=isrcs,
            create=False,
            exclude_song_ids=frozenset({other.pk}),
        )
        third = resolve_credit(
            "Evidence Person",
            deezer_id=500,
            evidence_isrcs=isrcs,
            create=False,
            exclude_song_ids=frozenset({song.pk, other.pk}),
        )

        assert first.status == "would_adopt"
        assert second.status == "would_adopt"  # `song` is independent of `other`
        assert third.status == "ambiguous"  # nothing independent remains
