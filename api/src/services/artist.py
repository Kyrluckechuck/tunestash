# mypy: disable-error-code=attr-defined
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

from django.conf import settings
from django.db.models import Count, Exists, F, OuterRef, Q

from asgiref.sync import sync_to_async

from library_manager.models import Album
from library_manager.models import Artist as DjangoArtist
from library_manager.models import Song

from ..graphql_types.models import Artist, MutationResult
from .base import BaseService

logger = logging.getLogger(__name__)


@dataclass
class ArtistConnectionResult:
    """Result of get_connection with cursor info for pagination."""

    items: List[Artist]
    has_next_page: bool
    total_count: int
    # For offset-based pagination (custom sorting), this is the next offset
    # For cursor-based (ID sorting), this is None and item IDs are used
    end_cursor_offset: Optional[int] = None


class ArtistService(BaseService[Artist]):
    def __init__(self) -> None:
        super().__init__()
        self.model = DjangoArtist

    async def get_by_id(self, id: str) -> Optional[Artist]:
        try:
            # First try to find by GID
            django_artist = await self.model.objects.aget(gid=id)
            return await self._to_graphql_type_async(
                django_artist, include_full_counts=True
            )
        except self.model.DoesNotExist:
            try:
                # If not found by GID, try to find by database ID
                django_artist = await self.model.objects.aget(id=int(id))
                return await self._to_graphql_type_async(
                    django_artist, include_full_counts=True
                )
            except (self.model.DoesNotExist, ValueError):
                return None

    async def get_connection(
        self,
        first: int = 20,
        after: Optional[str] = None,
        **filters: Any,
    ) -> Union[Tuple[List[Artist], bool, int], ArtistConnectionResult]:
        is_tracked: Optional[bool] = filters.get("is_tracked")
        search: Optional[str] = filters.get("search")
        has_undownloaded: Optional[bool] = filters.get("has_undownloaded")
        sort_by = (
            filters.get("sort_by") if isinstance(filters.get("sort_by"), str) else None
        )
        sort_direction = (
            filters.get("sort_direction")
            if isinstance(filters.get("sort_direction"), str)
            else None
        )
        queryset = self.model.objects.all()

        # Apply filters
        if is_tracked is not None:
            queryset = queryset.filter(tracked=is_tracked)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(gid__icontains=search)
            )

        # Apply has_undownloaded filter at database level using subqueries
        # This ensures proper pagination counts
        if has_undownloaded is not None:
            # Get settings for album type filtering (must match _get_undownloaded_count)
            album_types_to_download = getattr(
                settings, "ALBUM_TYPES_TO_DOWNLOAD", ["single", "album", "compilation"]
            )
            album_groups_to_ignore = getattr(
                settings, "ALBUM_GROUPS_TO_IGNORE", ["appears_on"]
            )

            has_undownloaded_album = Exists(
                Album.objects.filter(
                    artist_id=OuterRef("pk"),
                    wanted=True,
                    downloaded=False,
                    album_type__in=album_types_to_download,
                ).exclude(album_group__in=album_groups_to_ignore)
            )
            has_failed_song = Exists(
                Song.objects.filter(
                    primary_artist_id=OuterRef("pk"),
                    failed_count__gt=0,
                    unavailable=False,
                    downloaded=False,
                )
            )

            if has_undownloaded:
                # Filter to artists with undownloaded albums OR failed songs
                queryset = queryset.filter(has_undownloaded_album | has_failed_song)
            else:
                # Filter to artists with NO undownloaded albums AND NO failed songs
                queryset = queryset.exclude(has_undownloaded_album | has_failed_song)

        # Apply sorting
        sort_field_map: dict[str, str] = {
            "name": "name",
            "isTracked": "tracked",
            "addedAt": "added_at",
            "lastSynced": "last_synced_at",
            "lastDownloaded": "last_downloaded_at",
        }

        # Timestamp fields where null = "earliest" (never synced/downloaded)
        timestamp_fields = {"last_synced_at", "last_downloaded_at", "added_at"}

        order_expressions: List[Any] = ["id"]  # default
        uses_custom_sort = sort_by is not None and sort_by != "id"

        if isinstance(sort_by, str):
            mapped_field = sort_field_map.get(sort_by)
            if mapped_field is not None:
                # For timestamp fields, nulls should be treated as earliest
                if mapped_field in timestamp_fields:
                    if sort_direction == "desc":
                        # Descending: newest first, nulls last (never = earliest)
                        order_expressions = [
                            F(mapped_field).desc(nulls_last=True),
                            "id",
                        ]
                    else:
                        # Ascending: oldest first, nulls first (never = earliest)
                        order_expressions = [
                            F(mapped_field).asc(nulls_first=True),
                            "id",
                        ]
                else:
                    # Non-timestamp fields use standard sorting
                    order_field = mapped_field
                    if sort_direction == "desc":
                        order_expressions = [f"-{order_field}", "id"]
                    else:
                        order_expressions = [order_field, "id"]

        total_count = await queryset.acount()

        # Apply pagination - use offset for custom sorting, cursor for ID sorting
        # Cursor-based pagination (id__gt) only works when sorting by ID
        offset = 0
        if after:
            if uses_custom_sort:
                # Custom sorting: decode cursor as offset
                decoded = self.decode_cursor(after)
                offset = int(decoded) if isinstance(decoded, (int, str)) else 0
            else:
                # ID sorting: use cursor-based filtering
                id_after = self.decode_cursor(after)
                queryset = queryset.filter(id__gt=id_after)

        # Get one extra item to determine if there are more pages
        def fetch_items() -> List[DjangoArtist]:
            if uses_custom_sort:
                # Offset-based: skip `offset` items, take `first + 1`
                return list(
                    queryset.order_by(*order_expressions)[offset : offset + first + 1]
                )
            return list(queryset.order_by(*order_expressions)[: first + 1])

        items: List[DjangoArtist] = await sync_to_async(fetch_items)()

        has_next_page = len(items) > first
        items = items[:first]  # Remove the extra item

        # Convert items to GraphQL types with async undownloaded counts
        graphql_items: List[Artist] = []
        for item in items:
            graphql_item = await self._to_graphql_type_async(item)
            graphql_items.append(graphql_item)

        # Note: has_undownloaded filtering is now done at database level (above)
        # using Exists subqueries for proper pagination

        # For custom sorting, return the next offset as cursor info
        if uses_custom_sort:
            next_offset = offset + len(items) if has_next_page else None
            return ArtistConnectionResult(
                items=graphql_items,
                has_next_page=has_next_page,
                total_count=total_count,
                end_cursor_offset=next_offset,
            )

        return (
            graphql_items,
            has_next_page,
            total_count,
        )

    async def get_unlinked_connection(
        self,
        first: int = 20,
        after: Optional[str] = None,
        search: Optional[str] = None,
        has_downloads: Optional[bool] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
    ) -> ArtistConnectionResult:
        """Get paginated artists without a deezer_id."""
        queryset = self.model.objects.filter(deezer_id__isnull=True)

        if search:
            queryset = queryset.filter(name__icontains=search)

        # Annotate with song counts (Song.primary_artist → queryset lookup is "song")
        queryset = queryset.annotate(
            _downloaded_song_count=Count("song", filter=Q(song__downloaded=True)),
            _total_song_count=Count("song"),
        )

        if has_downloads is not None:
            if has_downloads:
                queryset = queryset.filter(_downloaded_song_count__gt=0)
            else:
                queryset = queryset.filter(_downloaded_song_count=0)

        # Default sort: tracked first, then most downloads, then ID
        order_expressions: List[Any] = [
            "-tracked",
            "-_downloaded_song_count",
            "id",
        ]

        sort_field_map: dict[str, str] = {
            "name": "name",
            "downloadedSongCount": "_downloaded_song_count",
            "songCount": "_total_song_count",
        }
        if sort_by and sort_by in sort_field_map:
            mapped = sort_field_map[sort_by]
            if sort_direction == "desc":
                order_expressions = [f"-{mapped}", "id"]
            else:
                order_expressions = [mapped, "id"]

        total_count = await queryset.acount()

        # Always use offset-based pagination (custom sort fields)
        offset = 0
        if after:
            decoded = self.decode_cursor(after)
            offset = int(decoded) if isinstance(decoded, (int, str)) else 0

        def fetch_items() -> List[DjangoArtist]:
            return list(
                queryset.order_by(*order_expressions)[offset : offset + first + 1]
            )

        items: List[DjangoArtist] = await sync_to_async(fetch_items)()

        has_next_page = len(items) > first
        items = items[:first]

        graphql_items: List[Artist] = []
        for item in items:
            gql_artist = await self._to_graphql_type_async(item)
            # Override with annotated values
            gql_artist.downloaded_song_count = getattr(
                item, "_downloaded_song_count", 0
            )
            gql_artist.song_count = getattr(item, "_total_song_count", 0)
            graphql_items.append(gql_artist)

        next_offset = offset + len(items) if has_next_page else None
        return ArtistConnectionResult(
            items=graphql_items,
            has_next_page=has_next_page,
            total_count=total_count,
            end_cursor_offset=next_offset,
        )

    async def link_to_deezer(self, artist_id: int, deezer_id: int) -> MutationResult:
        """Link an existing artist to a Deezer ID and trigger migration."""
        try:
            django_artist = await self.model.objects.aget(id=artist_id)
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="Artist not found")

        # Check if deezer_id is already claimed
        conflict = await sync_to_async(
            lambda: self.model.objects.filter(deezer_id=deezer_id)
            .exclude(id=artist_id)
            .first()
        )()
        if conflict:
            return MutationResult(
                success=False,
                message=f'Deezer ID {deezer_id} is already linked to "{conflict.name}"',
            )

        # Validate against Deezer API
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        result = await sync_to_async(provider.get_artist)(deezer_id)
        if result is None:
            return MutationResult(
                success=False,
                message=f"Deezer ID {deezer_id} not found on Deezer",
            )

        django_artist.deezer_id = deezer_id
        await django_artist.asave(update_fields=["deezer_id"])

        from library_manager.tasks import migrate_artist_to_deezer

        await sync_to_async(migrate_artist_to_deezer.delay)(django_artist.id)

        logger.info(
            "Linked artist %s (id=%d) to Deezer ID %d, migration queued",
            django_artist.name,
            django_artist.id,
            deezer_id,
        )

        return MutationResult(
            success=True,
            message=f'Linked "{django_artist.name}" to Deezer artist "{result.name}" — migration queued',
        )

    async def import_from_deezer(self, deezer_id: int, name: str) -> MutationResult:
        """Import an artist from Deezer search and start tracking."""
        try:
            existing = await sync_to_async(
                lambda: self.model.objects.filter(
                    Q(deezer_id=deezer_id) | Q(name__iexact=name)
                ).first()
            )()

            if existing:
                updated_fields = []
                if not existing.deezer_id:
                    existing.deezer_id = deezer_id
                    updated_fields.append("deezer_id")
                if not existing.tracked:
                    existing.tracked = True
                    updated_fields.append("tracked")
                if updated_fields:
                    await existing.asave(update_fields=updated_fields)

                from library_manager.tasks import fetch_artist_albums_from_deezer

                await sync_to_async(fetch_artist_albums_from_deezer.delay)(existing.id)

                return MutationResult(
                    success=True,
                    message=f'Now tracking "{existing.name}"',
                    artist=await self._to_graphql_type_async(existing),
                )

            django_artist = await sync_to_async(self.model.objects.create)(
                name=name,
                deezer_id=deezer_id,
                tracked=True,
            )

            from library_manager.tasks import fetch_artist_albums_from_deezer

            await sync_to_async(fetch_artist_albums_from_deezer.delay)(django_artist.id)

            return MutationResult(
                success=True,
                message=f'Imported and tracking "{name}"',
                artist=await self._to_graphql_type_async(django_artist),
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Failed to import artist: {str(e)}",
            )

    async def track_artist(self, artist_id: int) -> MutationResult:
        try:
            django_artist = await self.model.objects.aget(id=artist_id)
            django_artist.tracked = True
            await django_artist.asave()

            return MutationResult(
                success=True,
                message="Artist tracked successfully",
                artist=await self._to_graphql_type_async(django_artist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Artist not found", artist=None
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error tracking artist: {str(e)}", artist=None
            )

    async def untrack_artist(self, artist_id: int) -> MutationResult:
        try:
            django_artist = await self.model.objects.aget(id=artist_id)
            django_artist.tracked = False
            await django_artist.asave()

            return MutationResult(
                success=True,
                message="Artist untracked successfully",
                artist=await self._to_graphql_type_async(django_artist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Artist not found", artist=None
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error untracking artist: {str(e)}", artist=None
            )

    async def update_artist(
        self,
        artist_id: str,
        is_tracked: Optional[bool] = None,
        auto_download: Optional[bool] = None,
    ) -> Artist:
        django_artist = await self.model.objects.aget(gid=artist_id)

        if is_tracked is not None:
            django_artist.tracked = is_tracked

        if auto_download and not django_artist.tracked:
            django_artist.tracked = True

        await django_artist.asave()

        if auto_download:
            # Local import to avoid circular import during module initialization
            from library_manager.tasks import download_missing_albums_for_artist

            await sync_to_async(download_missing_albums_for_artist.delay)(
                django_artist.id
            )

        return await self._to_graphql_type_async(django_artist)

    async def sync_artist(self, artist_id: str) -> Artist:
        try:
            # Convert string to int since frontend sends database ID
            artist_db_id = int(artist_id)
            django_artist = await self.model.objects.aget(id=artist_db_id)
            from library_manager.tasks import fetch_all_albums_for_artist

            await sync_to_async(fetch_all_albums_for_artist.delay)(django_artist.id)
            return await self._to_graphql_type_async(django_artist)
        except ValueError as exc:
            raise ValueError(f"Invalid artist ID format: {artist_id}") from exc
        except self.model.DoesNotExist as exc:
            raise ValueError(f"Artist with ID {artist_id} not found") from exc
        except Exception as e:
            raise RuntimeError(f"Error syncing artist: {str(e)}") from e

    async def download_artist(self, artist_id: str) -> MutationResult:
        try:
            # Convert string to int since frontend sends database ID
            artist_db_id = int(artist_id)
            django_artist = await self.model.objects.aget(id=artist_db_id)

            # Start download task for missing albums
            # Local import to avoid circular import during module initialization
            from library_manager.tasks import download_missing_albums_for_artist

            await sync_to_async(download_missing_albums_for_artist.delay)(
                django_artist.id
            )

            return MutationResult(
                success=True, message=f"Download started for {django_artist.name}"
            )
        except ValueError:
            return MutationResult(
                success=False, message=f"Invalid artist ID format: {artist_id}"
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message=f"Artist with ID {artist_id} not found"
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error starting download for artist: {str(e)}"
            )

    async def retry_failed_songs(self, artist_id: str) -> MutationResult:
        try:
            artist_db_id = int(artist_id)
            django_artist = await self.model.objects.aget(id=artist_db_id)

            # Check if there are any failed songs to retry
            failed_count = await self._get_failed_song_count(django_artist)
            if failed_count == 0:
                return MutationResult(
                    success=False,
                    message=f"No failed songs to retry for {django_artist.name}",
                )

            from library_manager.tasks import retry_failed_songs_for_artist

            await sync_to_async(retry_failed_songs_for_artist.delay)(django_artist.id)

            return MutationResult(
                success=True,
                message=f"Retrying {failed_count} failed songs for {django_artist.name}",
            )
        except ValueError:
            return MutationResult(
                success=False, message=f"Invalid artist ID format: {artist_id}"
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message=f"Artist with ID {artist_id} not found"
            )
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error retrying failed songs: {str(e)}"
            )

    async def _get_undownloaded_count(self, django_artist: DjangoArtist) -> int:
        """Calculate undownloaded count for an artist asynchronously."""
        album_types_to_download = getattr(
            settings, "ALBUM_TYPES_TO_DOWNLOAD", ["single", "album", "compilation"]
        )
        album_groups_to_ignore = getattr(
            settings, "ALBUM_GROUPS_TO_IGNORE", ["appears_on"]
        )

        return await (
            Album.objects.filter(
                artist=django_artist,
                downloaded=False,
                wanted=True,
                album_type__in=album_types_to_download,
            )
            .exclude(album_group__in=album_groups_to_ignore)
            .acount()
        )

    async def _get_album_count(self, django_artist: DjangoArtist) -> int:
        """Get total album count for an artist."""
        return await Album.objects.filter(artist=django_artist).acount()

    async def _get_downloaded_album_count(self, django_artist: DjangoArtist) -> int:
        """Get downloaded album count for an artist."""
        return await Album.objects.filter(
            artist=django_artist, downloaded=True
        ).acount()

    async def _get_song_count(self, django_artist: DjangoArtist) -> int:
        """Get total song count for an artist."""
        return await Song.objects.filter(primary_artist=django_artist).acount()

    async def _get_downloaded_song_count(self, django_artist: DjangoArtist) -> int:
        """Get count of downloaded songs for an artist."""
        return await Song.objects.filter(
            primary_artist=django_artist, downloaded=True
        ).acount()

    async def _get_failed_song_count(self, django_artist: DjangoArtist) -> int:
        """Get count of songs that have failed downloads but aren't permanently unavailable."""
        return await Song.objects.filter(
            primary_artist=django_artist,
            failed_count__gt=0,
            unavailable=False,
            downloaded=False,
        ).acount()

    async def _to_graphql_type_async(
        self, django_artist: DjangoArtist, include_full_counts: bool = False
    ) -> Artist:
        """Convert Django artist to GraphQL type with async database operations.

        Args:
            django_artist: The Django model instance
            include_full_counts: If True, fetch all counts (album, downloaded, song).
                               Use for single-artist detail views, not lists.
        """
        raw_id = getattr(django_artist, "id", None)
        safe_id: int = int(raw_id) if isinstance(raw_id, (int, str)) else 0

        spotify_uri = django_artist.spotify_uri or None

        undownloaded_count = await self._get_undownloaded_count(django_artist)
        failed_song_count = await self._get_failed_song_count(django_artist)

        album_count = 0
        downloaded_album_count = 0
        song_count = 0
        downloaded_song_count = 0

        if include_full_counts:
            album_count = await self._get_album_count(django_artist)
            downloaded_album_count = await self._get_downloaded_album_count(
                django_artist
            )
            song_count = await self._get_song_count(django_artist)
            downloaded_song_count = await self._get_downloaded_song_count(django_artist)

        return Artist(
            id=safe_id,
            name=django_artist.name,
            gid=django_artist.gid,
            spotify_uri=spotify_uri,
            is_tracked=django_artist.tracked,
            last_synced=django_artist.last_synced_at,
            last_downloaded=django_artist.last_downloaded_at,
            added_at=(
                django_artist.added_at if hasattr(django_artist, "added_at") else None
            ),
            undownloaded_count=undownloaded_count,
            album_count=album_count,
            downloaded_album_count=downloaded_album_count,
            song_count=song_count,
            downloaded_song_count=downloaded_song_count,
            failed_song_count=failed_song_count,
            deezer_id=str(django_artist.deezer_id) if django_artist.deezer_id else None,
        )

    def _to_graphql_type(self, django_artist: DjangoArtist) -> Artist:
        """Convert Django artist to GraphQL type (sync version without counts)."""
        raw_id = getattr(django_artist, "id", None)
        safe_id: int = int(raw_id) if isinstance(raw_id, (int, str)) else 0

        spotify_uri = django_artist.spotify_uri or None

        return Artist(
            id=safe_id,
            name=django_artist.name,
            gid=django_artist.gid,
            spotify_uri=spotify_uri,
            is_tracked=django_artist.tracked,
            last_synced=django_artist.last_synced_at,
            last_downloaded=django_artist.last_downloaded_at,
            added_at=(
                django_artist.added_at if hasattr(django_artist, "added_at") else None
            ),
            undownloaded_count=0,
            album_count=0,
            downloaded_album_count=0,
            song_count=0,
            failed_song_count=0,
            deezer_id=str(django_artist.deezer_id) if django_artist.deezer_id else None,
        )
