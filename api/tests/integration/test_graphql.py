"""Integration tests for GraphQL queries."""

from django.test import TransactionTestCase

from asgiref.sync import sync_to_async

from library_manager.models import Album, Artist, Song
from src.schema import schema


class TestArtistQueries(TransactionTestCase):
    """Test artist-related queries."""

    async def test_artists_query_with_data(self):
        """Test artists query with data."""
        # Create test data
        await sync_to_async(Artist.objects.create)(
            name="Test Artist", gid="test123", tracking_tier=1
        )

        query = """
        query Artists {
            artists {
                edges {
                    id
                    name
                    trackingTier
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query)

        assert result.errors is None
        assert result.data["artists"]["totalCount"] >= 1
        assert len(result.data["artists"]["edges"]) >= 1

    async def test_artists_query_with_filter(self):
        """Test artists query with filtering."""
        # Create test data
        await sync_to_async(Artist.objects.create)(
            name="Tracked Artist", gid="tracked123", tracking_tier=1
        )
        await sync_to_async(Artist.objects.create)(
            name="Untracked Artist", gid="untracked123", tracking_tier=0
        )

        query = """
        query Artists($trackingTier: Int) {
            artists(trackingTier: $trackingTier) {
                edges {
                    id
                    name
                    trackingTier
                }
                totalCount
            }
        }
        """

        variables = {"trackingTier": 1}
        result = await schema.execute(query, variable_values=variables)

        assert result.errors is None
        # Should only return tracked artists
        for artist in result.data["artists"]["edges"]:
            assert artist["trackingTier"] == 1

    async def test_artists_query_with_pagination(self):
        """Test artists query with pagination."""
        # Create test data
        for i in range(3):
            await sync_to_async(Artist.objects.create)(
                name=f"Artist {i}", gid=f"artist{i}", tracking_tier=1
            )

        query = """
        query Artists($first: Int) {
            artists(first: $first) {
                edges {
                    id
                    name
                }
                pageInfo {
                    hasNextPage
                    hasPreviousPage
                }
                totalCount
            }
        }
        """

        variables = {"first": 1}
        result = await schema.execute(query, variable_values=variables)

        assert result.errors is None
        assert len(result.data["artists"]["edges"]) <= 1
        assert result.data["artists"]["totalCount"] >= 1

    async def test_artists_query_with_search(self):
        """Test artists query with search."""
        # Create test data
        await sync_to_async(Artist.objects.create)(
            name="Zebra Artist", gid="zebra123", tracking_tier=1
        )
        await sync_to_async(Artist.objects.create)(
            name="Alpha Artist", gid="alpha123", tracking_tier=1
        )

        query = """
        query Artists($search: String) {
            artists(search: $search) {
                edges {
                    id
                    name
                }
                totalCount
            }
        }
        """

        variables = {"search": "Zebra"}
        result = await schema.execute(query, variable_values=variables)

        assert result.errors is None
        assert result.data["artists"]["totalCount"] >= 1

    async def test_artist_detail_query_empty_counts(self):
        """Test single artist query returns zero counts when no albums/songs."""
        # Create test artist with no albums or songs
        artist = await sync_to_async(Artist.objects.create)(
            name="Empty Artist", gid="emptyartist123", tracking_tier=1
        )

        query = """
        query GetArtist($id: String!) {
            artist(id: $id) {
                id
                name
                albumCount
                downloadedAlbumCount
                songCount
                undownloadedCount
            }
        }
        """

        variables = {"id": str(artist.id)}
        result = await schema.execute(query, variable_values=variables)

        assert result.errors is None
        assert result.data["artist"]["name"] == "Empty Artist"
        assert result.data["artist"]["albumCount"] == 0
        assert result.data["artist"]["downloadedAlbumCount"] == 0
        assert result.data["artist"]["songCount"] == 0
        assert result.data["artist"]["undownloadedCount"] == 0

    async def test_artist_detail_query_with_counts(self):
        """Test single artist query returns album and song counts."""
        # Create test artist
        artist = await sync_to_async(Artist.objects.create)(
            name="Count Test Artist", gid="counttest123", tracking_tier=1
        )

        # Create albums (2 total, 1 downloaded)
        await sync_to_async(Album.objects.create)(
            name="Downloaded Album",
            spotify_gid="dlalbum123",
            artist=artist,
            total_tracks=10,
            wanted=True,
            downloaded=True,
            album_type="album",
        )
        await sync_to_async(Album.objects.create)(
            name="Pending Album",
            spotify_gid="pendingalbum123",
            artist=artist,
            total_tracks=8,
            wanted=True,
            downloaded=False,
            album_type="album",
        )

        # Create songs (3 total)
        for i in range(3):
            await sync_to_async(Song.objects.create)(
                name=f"Test Song {i}",
                gid=f"testsong{i}123",
                primary_artist=artist,
                downloaded=i == 0,  # Only first song downloaded
            )

        query = """
        query GetArtist($id: String!) {
            artist(id: $id) {
                id
                name
                albumCount
                downloadedAlbumCount
                songCount
                undownloadedCount
            }
        }
        """

        variables = {"id": str(artist.id)}
        result = await schema.execute(query, variable_values=variables)

        assert result.errors is None
        assert result.data["artist"]["name"] == "Count Test Artist"
        assert result.data["artist"]["albumCount"] == 2
        assert result.data["artist"]["downloadedAlbumCount"] == 1
        assert result.data["artist"]["songCount"] == 3
        assert (
            result.data["artist"]["undownloadedCount"] == 1
        )  # 1 wanted, not downloaded


class TestArtistHasUndownloadedFilter(TransactionTestCase):
    """Test hasUndownloaded filter for artists query.

    This filter uses database-level Exists subqueries to ensure proper pagination.
    It must match the same logic as _get_undownloaded_count (album_type, album_group filters).
    """

    async def test_has_undownloaded_filter_with_undownloaded_albums(self):
        """Test hasUndownloaded=true returns artists with undownloaded wanted albums."""
        # Artist WITH undownloaded albums (should be included)
        artist_with_undownloaded = await sync_to_async(Artist.objects.create)(
            name="Has Undownloaded", gid="hasundownloaded123", tracking_tier=1
        )
        await sync_to_async(Album.objects.create)(
            name="Pending Album",
            spotify_gid="pending123",
            artist=artist_with_undownloaded,
            total_tracks=10,
            wanted=True,
            downloaded=False,
            album_type="album",
            album_group="album",
        )

        # Artist WITHOUT undownloaded albums (should be excluded)
        artist_all_downloaded = await sync_to_async(Artist.objects.create)(
            name="All Downloaded", gid="alldownloaded123", tracking_tier=1
        )
        await sync_to_async(Album.objects.create)(
            name="Downloaded Album",
            spotify_gid="downloaded123",
            artist=artist_all_downloaded,
            total_tracks=10,
            wanted=True,
            downloaded=True,
            album_type="album",
            album_group="album",
        )

        query = """
        query Artists($hasUndownloaded: Boolean) {
            artists(hasUndownloaded: $hasUndownloaded) {
                edges {
                    id
                    name
                    undownloadedCount
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query, variable_values={"hasUndownloaded": True})

        assert result.errors is None
        artist_names = [a["name"] for a in result.data["artists"]["edges"]]
        assert "Has Undownloaded" in artist_names
        assert "All Downloaded" not in artist_names

    async def test_has_undownloaded_filter_excludes_appears_on_albums(self):
        """Test hasUndownloaded filter respects album_group exclusions (appears_on)."""
        # Artist with ONLY "appears_on" albums (should be excluded from hasUndownloaded)
        artist_appears_on = await sync_to_async(Artist.objects.create)(
            name="Only Appears On", gid="appearson123", tracking_tier=1
        )
        await sync_to_async(Album.objects.create)(
            name="Compilation Appearance",
            spotify_gid="compilation123",
            artist=artist_appears_on,
            total_tracks=20,
            wanted=True,
            downloaded=False,
            album_type="compilation",
            album_group="appears_on",  # This should be excluded
        )

        query = """
        query Artists($hasUndownloaded: Boolean) {
            artists(hasUndownloaded: $hasUndownloaded) {
                edges {
                    id
                    name
                    undownloadedCount
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query, variable_values={"hasUndownloaded": True})

        assert result.errors is None
        artist_names = [a["name"] for a in result.data["artists"]["edges"]]
        # Should NOT appear because all undownloaded albums are "appears_on"
        assert "Only Appears On" not in artist_names

    async def test_has_undownloaded_filter_includes_failed_songs(self):
        """Test hasUndownloaded=true includes artists with failed (retryable) songs."""
        # Artist with failed songs but no undownloaded albums
        artist_failed_songs = await sync_to_async(Artist.objects.create)(
            name="Has Failed Songs", gid="failedsongs123", tracking_tier=1
        )
        await sync_to_async(Song.objects.create)(
            name="Failed Song",
            gid="failedsong123",
            primary_artist=artist_failed_songs,
            failed_count=3,
            unavailable=False,
            downloaded=False,
        )

        query = """
        query Artists($hasUndownloaded: Boolean) {
            artists(hasUndownloaded: $hasUndownloaded) {
                edges {
                    id
                    name
                    failedSongCount
                    undownloadedCount
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query, variable_values={"hasUndownloaded": True})

        assert result.errors is None
        artist_names = [a["name"] for a in result.data["artists"]["edges"]]
        # Should appear because of failed songs
        assert "Has Failed Songs" in artist_names

    async def test_has_undownloaded_filter_excludes_unavailable_songs(self):
        """Test hasUndownloaded filter excludes permanently unavailable songs."""
        # Artist with unavailable (not retryable) songs
        artist_unavailable = await sync_to_async(Artist.objects.create)(
            name="Has Unavailable Songs", gid="unavailable123", tracking_tier=1
        )
        await sync_to_async(Song.objects.create)(
            name="Unavailable Song",
            gid="unavailablesong123",
            primary_artist=artist_unavailable,
            failed_count=5,
            unavailable=True,  # Marked as unavailable - should NOT count
            downloaded=False,
        )

        query = """
        query Artists($hasUndownloaded: Boolean) {
            artists(hasUndownloaded: $hasUndownloaded) {
                edges {
                    id
                    name
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query, variable_values={"hasUndownloaded": True})

        assert result.errors is None
        artist_names = [a["name"] for a in result.data["artists"]["edges"]]
        # Should NOT appear because failed songs are marked unavailable
        assert "Has Unavailable Songs" not in artist_names

    async def test_has_undownloaded_total_count_matches_edges(self):
        """Test that totalCount matches the actual number of filtered results."""
        # Create multiple artists with various states
        for i in range(3):
            artist = await sync_to_async(Artist.objects.create)(
                name=f"Artist With Albums {i}", gid=f"withalbums{i}", tracking_tier=1
            )
            await sync_to_async(Album.objects.create)(
                name=f"Undownloaded Album {i}",
                spotify_gid=f"undownloaded{i}",
                artist=artist,
                total_tracks=10,
                wanted=True,
                downloaded=False,
                album_type="album",
                album_group="album",
            )

        # Artist without undownloaded content
        await sync_to_async(Artist.objects.create)(
            name="No Undownloaded", gid="noundownloaded123", tracking_tier=1
        )

        query = """
        query Artists($hasUndownloaded: Boolean) {
            artists(hasUndownloaded: $hasUndownloaded) {
                edges {
                    id
                    name
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query, variable_values={"hasUndownloaded": True})

        assert result.errors is None
        # totalCount should match actual edges returned
        assert result.data["artists"]["totalCount"] == len(
            result.data["artists"]["edges"]
        )


class TestAlbumQueries(TransactionTestCase):
    """Test album-related queries."""

    async def test_albums_query(self):
        """Test albums query."""
        # Create test data
        artist = await sync_to_async(Artist.objects.create)(
            name="Test Artist", gid="test123", tracking_tier=1
        )
        await sync_to_async(Album.objects.create)(
            name="Test Album",
            spotify_gid="album123",
            artist=artist,
            total_tracks=10,
            wanted=True,
            downloaded=False,
        )

        query = """
        query Albums {
            albums {
                edges {
                    id
                    name
                    wanted
                    downloaded
                }
                totalCount
            }
        }
        """

        result = await schema.execute(query)

        assert result.errors is None
        assert result.data["albums"]["totalCount"] >= 1
        assert len(result.data["albums"]["edges"]) >= 1


# Artist mutations tests moved to test_mutations.py to avoid duplication
