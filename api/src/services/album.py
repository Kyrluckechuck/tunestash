# mypy: disable-error-code=attr-defined
import logging
from typing import Any, List, Optional, Tuple

from django.db.models import F, Q

from asgiref.sync import sync_to_async
from celery.result import AsyncResult

from library_manager.models import Album as DjangoAlbum
from library_manager.models import Artist as DjangoArtist

from ..graphql_types.models import Album, MutationResult
from .base import BaseService

logger = logging.getLogger(__name__)


class AlbumService(BaseService[Album]):
    def __init__(self) -> None:
        super().__init__()
        self.model = DjangoAlbum

    async def import_from_deezer(self, deezer_id: int) -> MutationResult:
        """Import an album from Deezer into the library."""
        try:
            from ..providers.deezer import DeezerMetadataProvider

            provider = DeezerMetadataProvider()
            album_data = await sync_to_async(provider.get_album)(deezer_id)
            if not album_data:
                return MutationResult(
                    success=False, message="Album not found on Deezer"
                )

            artist_deezer_id = album_data.artist_deezer_id
            artist = await sync_to_async(
                lambda: (
                    DjangoArtist.objects.filter(
                        Q(deezer_id=artist_deezer_id)
                        | Q(name__iexact=album_data.artist_name)
                    ).first()
                    if artist_deezer_id
                    else DjangoArtist.objects.filter(
                        name__iexact=album_data.artist_name
                    ).first()
                )
            )()

            if not artist:
                artist = await sync_to_async(DjangoArtist.objects.create)(
                    name=album_data.artist_name,
                    deezer_id=artist_deezer_id,
                )
            elif artist_deezer_id and not artist.deezer_id:
                artist.deezer_id = artist_deezer_id
                await artist.asave()

            existing = await sync_to_async(
                lambda: DjangoAlbum.objects.filter(
                    Q(deezer_id=deezer_id)
                    | Q(name__iexact=album_data.name, artist=artist)
                ).first()
            )()

            if existing:
                updated = []
                if not existing.deezer_id:
                    existing.deezer_id = deezer_id
                    updated.append("deezer_id")
                if not existing.wanted:
                    existing.wanted = True
                    updated.append("wanted")
                if updated:
                    await existing.asave()
                return MutationResult(
                    success=True,
                    message=f'Album "{existing.name}" marked as wanted',
                    album=await sync_to_async(self._to_graphql_type)(existing),
                )

            django_album = await sync_to_async(DjangoAlbum.objects.create)(
                name=album_data.name,
                deezer_id=deezer_id,
                artist=artist,
                spotify_uri="",
                total_tracks=album_data.total_tracks or 0,
                album_type=album_data.album_type,
                wanted=True,
            )

            return MutationResult(
                success=True,
                message=f'Imported "{album_data.name}" by {album_data.artist_name}',
                album=await sync_to_async(self._to_graphql_type)(django_album),
            )
        except Exception as e:
            logger.exception("Failed to import album from Deezer")
            return MutationResult(
                success=False,
                message=f"Failed to import album: {str(e)}",
            )

    async def get_by_id(self, id: str) -> Optional[Album]:
        try:
            django_album = await self.model.objects.aget(spotify_gid=id)
            return await sync_to_async(self._to_graphql_type)(django_album)
        except self.model.DoesNotExist:
            return None

    async def get_by_db_id(self, id: int) -> Optional[Album]:
        try:
            django_album = await sync_to_async(
                lambda: self.model.objects.select_related("artist").get(id=id)
            )()
            return await sync_to_async(self._to_graphql_type)(django_album)
        except self.model.DoesNotExist:
            return None

    async def get_connection(
        self,
        first: int = 20,
        after: Optional[str] = None,
        **filters: Any,
    ) -> Tuple[List[Album], bool, int]:
        artist_id: Optional[int] = filters.get("artist_id")
        downloaded: Optional[bool] = filters.get("downloaded")
        wanted: Optional[bool] = filters.get("wanted")
        search: Optional[str] = filters.get("search")
        sort_by = (
            filters.get("sort_by") if isinstance(filters.get("sort_by"), str) else None
        )
        sort_direction = (
            filters.get("sort_direction")
            if isinstance(filters.get("sort_direction"), str)
            else None
        )

        def fetch_items() -> Tuple[List[Album], bool, int]:
            queryset = self.model.objects.all()

            # Apply filters
            if artist_id:
                queryset = queryset.filter(artist__id=artist_id)

            if downloaded is not None:
                queryset = queryset.filter(downloaded=downloaded)

            if wanted is not None:
                queryset = queryset.filter(wanted=wanted)

            if search:
                queryset = queryset.filter(
                    Q(name__icontains=search) | Q(spotify_gid__icontains=search)
                )

            # Apply sorting
            sort_field_map: dict[str, str] = {
                "name": "name",
                "artist": "artist__name",
                "downloaded": "downloaded",
                "wanted": "wanted",
                "totalTracks": "total_tracks",
                "createdAt": "created_at",
                "albumType": "album_type",
                "albumGroup": "album_group",
            }

            # Timestamp fields where null = "earliest"
            timestamp_fields = {"created_at"}

            order_expressions: List[Any] = ["id"]  # default
            if isinstance(sort_by, str):
                mapped_field = sort_field_map.get(sort_by)
                if mapped_field is not None:
                    # For timestamp fields, nulls should be treated as earliest
                    if mapped_field in timestamp_fields:
                        if sort_direction == "desc":
                            # Descending: newest first, nulls last
                            order_expressions = [
                                F(mapped_field).desc(nulls_last=True),
                                "id",
                            ]
                        else:
                            # Ascending: oldest first, nulls first
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

            total_count = queryset.count()

            # Apply cursor-based pagination
            if after:
                id_after = self.decode_cursor(after)
                queryset = queryset.filter(id__gt=id_after)

            # Get one extra item to determine if there are more pages
            items = list(queryset.order_by(*order_expressions)[: first + 1])

            has_next_page = len(items) > first
            items = items[:first]  # Remove the extra item

            return (
                [self._to_graphql_type(item) for item in items],
                has_next_page,
                total_count,
            )

        return await sync_to_async(fetch_items)()

    async def update_album(
        self, album_id: str, is_wanted: Optional[bool] = None
    ) -> Album:
        try:
            # Try to parse as database ID first (for internal operations)
            if album_id.isdigit():
                django_album = await self.model.objects.aget(id=int(album_id))
            else:
                # Fall back to spotify_gid for external API calls
                django_album = await self.model.objects.aget(spotify_gid=album_id)

            if is_wanted is not None:
                django_album.wanted = is_wanted
                if is_wanted:
                    django_album.clear_failure_state()
                await django_album.asave()

            return await sync_to_async(self._to_graphql_type)(django_album)
        except ValueError as exc:
            raise ValueError(f"Invalid album ID format: {album_id}") from exc
        except self.model.DoesNotExist as exc:
            raise ValueError(f"Album with ID {album_id} not found") from exc
        except Exception as e:
            raise RuntimeError(f"Error updating album: {str(e)}") from e

    async def download_album(self, album_id: str) -> Album:
        try:
            # Try to get existing album from database first
            django_album: Optional[DjangoAlbum] = None
            try:
                if album_id.isdigit():
                    django_album = await self.model.objects.aget(id=int(album_id))
                else:
                    django_album = await self.model.objects.aget(spotify_gid=album_id)
            except self.model.DoesNotExist:
                # Album doesn't exist in DB - queue task that fetches metadata in worker
                # This avoids needing SpotifyClient in the web container
                def queue_spotify_album_task() -> None:
                    from library_manager.tasks import download_album_by_spotify_id

                    download_album_by_spotify_id.delay(album_id)

                await sync_to_async(queue_spotify_album_task)()

                # Return a placeholder album object since we don't have metadata yet
                # The frontend will show the task in progress
                return Album(
                    id=0,
                    spotify_gid=album_id,
                    name="Download queued...",
                    downloaded=False,
                    wanted=True,
                    album_type=None,
                    album_group=None,
                    total_tracks=0,
                    artist="Loading...",
                    artist_id=None,
                    artist_gid=None,
                )

            # Album exists in DB - ensure it's marked as wanted
            if not django_album.wanted:
                django_album.wanted = True
                await django_album.asave()

            # Queue download for this specific album
            album_db_id = django_album.id

            def queue_task() -> AsyncResult:
                from library_manager.tasks import download_single_album

                return download_single_album.delay(album_db_id)

            await sync_to_async(queue_task)()

            # Convert to GraphQL type
            return await sync_to_async(self._to_graphql_type)(django_album)
        except ValueError as exc:
            raise ValueError(f"Invalid album ID format: {album_id}") from exc
        except Exception as e:
            raise RuntimeError(f"Error downloading album: {str(e)}") from e

    async def set_album_wanted(self, album_id: int, wanted: bool) -> MutationResult:
        try:
            # Perform DB work in a thread to avoid blocking
            django_album = await sync_to_async(
                lambda: self.model.objects.select_related("artist").get(id=album_id)
            )()
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="Album not found", album=None)
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error updating album: {e}", album=None
            )

        try:
            django_album.wanted = wanted
            await django_album.asave()
        except Exception as e:
            return MutationResult(
                success=False, message=f"Error updating album: {e}", album=None
            )

        return MutationResult(
            success=True,
            message="Album wanted status updated successfully",
            album=await sync_to_async(self._to_graphql_type)(django_album),
        )

    def _to_graphql_type(self, django_album: DjangoAlbum) -> Album:
        raw_id = getattr(django_album, "id", None)
        safe_id: int = int(raw_id) if isinstance(raw_id, (int, str)) else 0
        return Album(
            id=safe_id,
            name=django_album.name,
            spotify_gid=django_album.spotify_gid,
            total_tracks=django_album.total_tracks,
            wanted=django_album.wanted,
            downloaded=django_album.downloaded,
            album_type=django_album.album_type,
            album_group=django_album.album_group,
            artist=django_album.artist.name if django_album.artist else None,
            artist_id=django_album.artist.id if django_album.artist else None,
            artist_gid=django_album.artist.gid if django_album.artist else None,
            deezer_id=str(django_album.deezer_id) if django_album.deezer_id else None,
        )
