"""Metadata update service.

Provides functionality for querying, applying, and dismissing pending
metadata updates detected from Spotify.

Note: Strawberry runtime-decorated types trigger attr-defined false-positives in MyPy
when instantiated. We disable that check for this module to avoid noisy errors.
"""

# mypy: disable-error-code=attr-defined
import logging
from typing import List, Optional, Tuple

from django.contrib.contenttypes.models import ContentType

from asgiref.sync import sync_to_async

from library_manager.metadata_detection import (
    detect_album_name_change,
    detect_artist_name_change,
    detect_song_name_change,
)
from library_manager.models import Album as DjangoAlbum
from library_manager.models import Artist as DjangoArtist
from library_manager.models import MetadataUpdateStatus as DjangoMetadataUpdateStatus
from library_manager.models import PendingMetadataUpdate as DjangoPendingMetadataUpdate
from library_manager.models import Song as DjangoSong

from ..graphql_types.models import (
    MetadataCheckResult,
    MetadataEntityType,
    MetadataUpdate,
    MetadataUpdateConnection,
    MetadataUpdateStatus,
    MetadataUpdateSummary,
)

logger = logging.getLogger(__name__)


class MetadataUpdateService:
    """Service for managing pending metadata updates."""

    def __init__(self) -> None:
        pass

    def _get_entity_type(self, content_type: ContentType) -> MetadataEntityType:
        """Convert Django ContentType to GraphQL MetadataEntityType."""
        model_name = content_type.model.lower()
        if model_name == "artist":
            return MetadataEntityType.ARTIST
        if model_name == "album":
            return MetadataEntityType.ALBUM
        if model_name == "song":
            return MetadataEntityType.SONG
        return MetadataEntityType.SONG  # fallback

    def _get_status(self, django_status: str) -> MetadataUpdateStatus:
        """Convert Django status string to GraphQL MetadataUpdateStatus."""
        if django_status == DjangoMetadataUpdateStatus.PENDING:
            return MetadataUpdateStatus.PENDING
        if django_status == DjangoMetadataUpdateStatus.APPLIED:
            return MetadataUpdateStatus.APPLIED
        if django_status == DjangoMetadataUpdateStatus.DISMISSED:
            return MetadataUpdateStatus.DISMISSED
        return MetadataUpdateStatus.PENDING  # fallback

    def _get_entity_name(self, content_type: ContentType, object_id: int) -> str:
        """Get the current name of the entity."""
        model_class = content_type.model_class()
        if model_class is None:
            return f"Unknown #{object_id}"

        try:
            entity = model_class.objects.get(id=object_id)
            return str(entity.name)
        except model_class.DoesNotExist:
            return f"Deleted #{object_id}"

    def _count_affected_songs(self, content_type: ContentType, object_id: int) -> int:
        """Count how many songs would be affected by applying this update."""
        model_name = content_type.model.lower()

        if model_name == "artist":
            # Count all downloaded songs by this artist
            return DjangoSong.objects.filter(
                primary_artist_id=object_id,
                downloaded=True,
            ).count()
        if model_name == "album":
            # Count all downloaded songs in this album
            return DjangoSong.objects.filter(
                album_id=object_id,
                downloaded=True,
            ).count()
        if model_name == "song":
            # Just this song
            try:
                song = DjangoSong.objects.get(id=object_id)
                return 1 if song.downloaded else 0
            except DjangoSong.DoesNotExist:
                return 0
        return 0

    def _to_graphql_type(self, update: DjangoPendingMetadataUpdate) -> MetadataUpdate:
        """Convert Django model to GraphQL type."""
        return MetadataUpdate(
            id=update.id,
            entity_type=self._get_entity_type(update.content_type),  # type: ignore[arg-type]
            entity_id=update.object_id,
            entity_name=self._get_entity_name(
                update.content_type, update.object_id  # type: ignore[arg-type]
            ),
            field_name=update.field_name,
            old_value=update.old_value,
            new_value=update.new_value,
            status=self._get_status(update.status),
            detected_at=update.detected_at,
            resolved_at=update.resolved_at,
            affected_songs_count=self._count_affected_songs(
                update.content_type, update.object_id  # type: ignore[arg-type]
            ),
        )

    async def get_pending_updates(
        self,
        entity_type: Optional[MetadataEntityType] = None,
        status: Optional[MetadataUpdateStatus] = None,
        include_resolved: bool = False,
    ) -> MetadataUpdateConnection:
        """Get pending metadata updates with optional filtering."""

        def _query() -> Tuple[List[MetadataUpdate], MetadataUpdateSummary]:
            queryset = DjangoPendingMetadataUpdate.objects.all()

            # Filter by entity type if specified
            if entity_type is not None:
                model_name_map = {
                    MetadataEntityType.ARTIST: "artist",
                    MetadataEntityType.ALBUM: "album",
                    MetadataEntityType.SONG: "song",
                }
                model_name = model_name_map.get(entity_type)
                if model_name:
                    ct = ContentType.objects.get(
                        app_label="library_manager", model=model_name
                    )
                    queryset = queryset.filter(content_type=ct)

            # Filter by status
            if status is not None:
                status_map = {
                    MetadataUpdateStatus.PENDING: DjangoMetadataUpdateStatus.PENDING,
                    MetadataUpdateStatus.APPLIED: DjangoMetadataUpdateStatus.APPLIED,
                    MetadataUpdateStatus.DISMISSED: DjangoMetadataUpdateStatus.DISMISSED,
                }
                django_status = status_map.get(status)
                if django_status:
                    queryset = queryset.filter(status=django_status)
            elif not include_resolved:
                # Default: only show pending
                queryset = queryset.filter(status=DjangoMetadataUpdateStatus.PENDING)

            # Order by detected_at descending
            queryset = queryset.order_by("-detected_at")

            # Convert to GraphQL types
            updates = [self._to_graphql_type(u) for u in queryset]

            # Calculate summary (always for pending)
            pending_queryset = DjangoPendingMetadataUpdate.objects.filter(
                status=DjangoMetadataUpdateStatus.PENDING
            )

            artist_ct = ContentType.objects.get(
                app_label="library_manager", model="artist"
            )
            album_ct = ContentType.objects.get(
                app_label="library_manager", model="album"
            )
            song_ct = ContentType.objects.get(app_label="library_manager", model="song")

            artist_count = pending_queryset.filter(content_type=artist_ct).count()
            album_count = pending_queryset.filter(content_type=album_ct).count()
            song_count = pending_queryset.filter(content_type=song_ct).count()

            # Calculate total affected songs
            total_affected = 0
            for u in pending_queryset:
                total_affected += self._count_affected_songs(
                    u.content_type, u.object_id  # type: ignore[arg-type]
                )

            summary = MetadataUpdateSummary(
                artist_updates=artist_count,
                album_updates=album_count,
                song_updates=song_count,
                total_affected_songs=total_affected,
            )

            return updates, summary

        updates, summary = await sync_to_async(_query)()
        return MetadataUpdateConnection(edges=updates, summary=summary)

    async def apply_update(self, update_id: int) -> Tuple[bool, str]:
        """Apply a metadata update - queues re-downloads for affected songs."""

        def _apply() -> Tuple[bool, str]:
            try:
                update = DjangoPendingMetadataUpdate.objects.get(id=update_id)
            except DjangoPendingMetadataUpdate.DoesNotExist:
                return False, f"Metadata update #{update_id} not found"

            if update.status != DjangoMetadataUpdateStatus.PENDING:
                return (
                    False,
                    f"Update #{update_id} is not pending (status: {update.status})",
                )

            # Queue the apply task
            from library_manager.tasks import apply_metadata_update

            apply_metadata_update.delay(update_id)

            return True, f"Queued metadata update #{update_id} for application"

        return await sync_to_async(_apply)()

    async def dismiss_update(self, update_id: int) -> Tuple[bool, str]:
        """Dismiss a metadata update."""

        def _dismiss() -> Tuple[bool, str]:
            try:
                update = DjangoPendingMetadataUpdate.objects.get(id=update_id)
            except DjangoPendingMetadataUpdate.DoesNotExist:
                return False, f"Metadata update #{update_id} not found"

            if update.status != DjangoMetadataUpdateStatus.PENDING:
                return (
                    False,
                    f"Update #{update_id} is not pending (status: {update.status})",
                )

            update.mark_dismissed()
            logger.info(f"Dismissed metadata update #{update_id}")
            return True, f"Dismissed metadata update #{update_id}"

        return await sync_to_async(_dismiss)()

    async def apply_all_pending(self) -> Tuple[bool, str, int]:
        """Apply all pending metadata updates."""

        def _apply_all() -> Tuple[bool, str, int]:
            pending = DjangoPendingMetadataUpdate.objects.filter(
                status=DjangoMetadataUpdateStatus.PENDING
            )
            count = pending.count()

            if count == 0:
                return True, "No pending metadata updates to apply", 0

            from library_manager.tasks import apply_metadata_update

            for update in pending:
                apply_metadata_update.delay(update.id)

            return True, f"Queued {count} metadata updates for application", count

        return await sync_to_async(_apply_all)()

    async def check_artist_metadata(self, artist_id: int) -> MetadataCheckResult:
        """Check if an artist's metadata has changed on Spotify."""

        def _check() -> MetadataCheckResult:
            try:
                artist = DjangoArtist.objects.get(id=artist_id)
            except DjangoArtist.DoesNotExist:
                return MetadataCheckResult(
                    success=False,
                    message=f"Artist #{artist_id} not found",
                    change_detected=False,
                )

            # Fetch current metadata from Spotify
            try:
                from downloader.spotipy_tasks import SpotifyClient

                sp = SpotifyClient().sp
                spotify_data = sp.artist(artist.gid)
                spotify_name = spotify_data.get("name", "")
            except Exception as e:
                logger.error(f"Failed to fetch artist metadata: {e}")
                return MetadataCheckResult(
                    success=False,
                    message=f"Failed to fetch from Spotify: {str(e)}",
                    change_detected=False,
                )

            # Detect change
            if artist.name != spotify_name:
                detect_artist_name_change(artist, spotify_name)
                return MetadataCheckResult(
                    success=True,
                    message=f"Name change detected: '{artist.name}' → '{spotify_name}'",
                    change_detected=True,
                    old_value=artist.name,
                    new_value=spotify_name,
                )

            return MetadataCheckResult(
                success=True,
                message="No changes detected",
                change_detected=False,
                old_value=artist.name,
                new_value=spotify_name,
            )

        return await sync_to_async(_check)()

    async def check_album_metadata(self, album_id: int) -> MetadataCheckResult:
        """Check if an album's metadata has changed on Spotify."""

        def _check() -> MetadataCheckResult:
            try:
                album = DjangoAlbum.objects.get(id=album_id)
            except DjangoAlbum.DoesNotExist:
                return MetadataCheckResult(
                    success=False,
                    message=f"Album #{album_id} not found",
                    change_detected=False,
                )

            # Fetch current metadata from Spotify
            try:
                from downloader.spotipy_tasks import SpotifyClient

                sp = SpotifyClient().sp
                spotify_data = sp.album(album.spotify_gid)
                spotify_name = spotify_data.get("name", "")
            except Exception as e:
                logger.error(f"Failed to fetch album metadata: {e}")
                return MetadataCheckResult(
                    success=False,
                    message=f"Failed to fetch from Spotify: {str(e)}",
                    change_detected=False,
                )

            # Detect change
            if album.name != spotify_name:
                detect_album_name_change(album, spotify_name)
                return MetadataCheckResult(
                    success=True,
                    message=f"Name change detected: '{album.name}' → '{spotify_name}'",
                    change_detected=True,
                    old_value=album.name,
                    new_value=spotify_name,
                )

            return MetadataCheckResult(
                success=True,
                message="No changes detected",
                change_detected=False,
                old_value=album.name,
                new_value=spotify_name,
            )

        return await sync_to_async(_check)()

    async def check_song_metadata(self, song_id: int) -> MetadataCheckResult:
        """Check if a song's metadata has changed on Spotify."""

        def _check() -> MetadataCheckResult:
            try:
                song = DjangoSong.objects.get(id=song_id)
            except DjangoSong.DoesNotExist:
                return MetadataCheckResult(
                    success=False,
                    message=f"Song #{song_id} not found",
                    change_detected=False,
                )

            # Fetch current metadata from Spotify
            try:
                from downloader.spotipy_tasks import SpotifyClient

                sp = SpotifyClient().sp
                spotify_data = sp.track(song.gid)
                spotify_name = spotify_data.get("name", "")
            except Exception as e:
                logger.error(f"Failed to fetch song metadata: {e}")
                return MetadataCheckResult(
                    success=False,
                    message=f"Failed to fetch from Spotify: {str(e)}",
                    change_detected=False,
                )

            # Detect change
            if song.name != spotify_name:
                detect_song_name_change(song, spotify_name)
                return MetadataCheckResult(
                    success=True,
                    message=f"Name change detected: '{song.name}' → '{spotify_name}'",
                    change_detected=True,
                    old_value=song.name,
                    new_value=spotify_name,
                )

            return MetadataCheckResult(
                success=True,
                message="No changes detected",
                change_detected=False,
                old_value=song.name,
                new_value=spotify_name,
            )

        return await sync_to_async(_check)()
