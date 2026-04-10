# mypy: disable-error-code=attr-defined
import logging
from typing import Any, List, Optional

from django.db.models import Count, Exists, F, OuterRef, Q

from asgiref.sync import sync_to_async

from library_manager.models import (
    Album,
)
from library_manager.models import Artist as DjangoArtist
from library_manager.models import (
    Song,
    TrackingTier,
    get_album_groups_to_ignore,
    get_album_types_to_download,
)

from ..graphql_types.models import Artist, MutationResult
from .base import BaseService, PageResult

logger = logging.getLogger(__name__)


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

    async def get_page(
        self,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> PageResult[Artist]:
        tracking_tier: Optional[int] = filters.get("tracking_tier")
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
        page, page_size = self.validate_page_params(page, page_size)
        queryset = self.model.objects.all()

        if tracking_tier is not None:
            queryset = queryset.filter(tracking_tier=tracking_tier)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(gid__icontains=search)
            )

        if has_undownloaded is not None:
            album_types_to_download = get_album_types_to_download()
            album_groups_to_ignore = get_album_groups_to_ignore()

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
                queryset = queryset.filter(has_undownloaded_album | has_failed_song)
            else:
                queryset = queryset.exclude(has_undownloaded_album | has_failed_song)

        sort_field_map: dict[str, str] = {
            "name": "name",
            "trackingTier": "tracking_tier",
            "addedAt": "added_at",
            "lastSynced": "last_synced_at",
            "lastDownloaded": "last_downloaded_at",
        }

        timestamp_fields = {"last_synced_at", "last_downloaded_at", "added_at"}

        order_expressions: List[Any] = ["id"]

        if isinstance(sort_by, str):
            mapped_field = sort_field_map.get(sort_by)
            if mapped_field is not None:
                if mapped_field in timestamp_fields:
                    if sort_direction == "desc":
                        order_expressions = [
                            F(mapped_field).desc(nulls_last=True),
                            "id",
                        ]
                    else:
                        order_expressions = [
                            F(mapped_field).asc(nulls_first=True),
                            "id",
                        ]
                else:
                    order_field = mapped_field
                    if sort_direction == "desc":
                        order_expressions = [f"-{order_field}", "id"]
                    else:
                        order_expressions = [order_field, "id"]

        total_count = await queryset.acount()
        offset = (page - 1) * page_size

        def fetch_items() -> List[DjangoArtist]:
            return list(
                queryset.order_by(*order_expressions)[offset : offset + page_size]
            )

        items: List[DjangoArtist] = await sync_to_async(fetch_items)()

        graphql_items: List[Artist] = []
        for item in items:
            graphql_item = await self._to_graphql_type_async(item)
            graphql_items.append(graphql_item)

        return PageResult(
            items=graphql_items,
            page=page,
            page_size=page_size,
            total_count=total_count,
        )

    async def get_unlinked_page(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        has_downloads: Optional[bool] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
    ) -> PageResult[Artist]:
        """Get paginated artists without a deezer_id."""
        page, page_size = self.validate_page_params(page, page_size)
        queryset = self.model.objects.filter(deezer_id__isnull=True)

        if search:
            queryset = queryset.filter(name__icontains=search)

        queryset = queryset.annotate(
            _downloaded_song_count=Count("song", filter=Q(song__downloaded=True)),
            _total_song_count=Count("song"),
        )

        if has_downloads is not None:
            if has_downloads:
                queryset = queryset.filter(_downloaded_song_count__gt=0)
            else:
                queryset = queryset.filter(_downloaded_song_count=0)

        order_expressions: List[Any] = [
            "-tracking_tier",
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
        offset = (page - 1) * page_size

        def fetch_items() -> List[DjangoArtist]:
            return list(
                queryset.order_by(*order_expressions)[offset : offset + page_size]
            )

        items: List[DjangoArtist] = await sync_to_async(fetch_items)()

        graphql_items: List[Artist] = []
        for item in items:
            gql_artist = await self._to_graphql_type_async(item)
            gql_artist.downloaded_song_count = getattr(
                item, "_downloaded_song_count", 0
            )
            gql_artist.song_count = getattr(item, "_total_song_count", 0)
            graphql_items.append(gql_artist)

        return PageResult(
            items=graphql_items,
            page=page,
            page_size=page_size,
            total_count=total_count,
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
                if existing.tracking_tier < TrackingTier.TRACKED:
                    existing.tracking_tier = TrackingTier.TRACKED
                    updated_fields.append("tracking_tier")
                if updated_fields:
                    await existing.asave(update_fields=updated_fields)

                from library_manager.tasks import fetch_all_albums_for_artist

                await sync_to_async(fetch_all_albums_for_artist.delay)(existing.id)

                return MutationResult(
                    success=True,
                    message=f'Now tracking "{existing.name}"',
                    artist=await self._to_graphql_type_async(existing),
                )

            django_artist = await sync_to_async(self.model.objects.create)(
                name=name,
                deezer_id=deezer_id,
                tracking_tier=TrackingTier.TRACKED,
            )

            from library_manager.tasks import fetch_all_albums_for_artist

            await sync_to_async(fetch_all_albums_for_artist.delay)(django_artist.id)

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
            django_artist.tracking_tier = TrackingTier.TRACKED
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
            django_artist.tracking_tier = TrackingTier.UNTRACKED
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
        tracking_tier: Optional[int] = None,
        auto_download: Optional[bool] = None,
    ) -> Artist:
        artist_db_id = int(artist_id)
        django_artist = await self.model.objects.aget(id=artist_db_id)

        if tracking_tier is not None:
            if tracking_tier not in (0, 1, 2):
                raise ValueError(
                    "tracking_tier must be 0 (Untracked), 1 (Tracked), or 2 (Favourite)"
                )
            django_artist.tracking_tier = tracking_tier

        if auto_download and django_artist.tracking_tier < TrackingTier.TRACKED:
            django_artist.tracking_tier = TrackingTier.TRACKED

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
        album_types_to_download = get_album_types_to_download()
        album_groups_to_ignore = get_album_groups_to_ignore()

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
            tracking_tier=django_artist.tracking_tier,
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
            tracking_tier=django_artist.tracking_tier,
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
