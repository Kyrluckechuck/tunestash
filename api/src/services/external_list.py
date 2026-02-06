# mypy: disable-error-code=attr-defined
"""Service for managing external music lists (Last.fm, ListenBrainz, YouTube Music)."""

import logging
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from django.db.models import Q

from asgiref.sync import sync_to_async

from library_manager.models import ExternalList as DjangoExternalList
from library_manager.models import (
    ExternalListSource,
    ExternalListStatus,
    ExternalListType,
)

from ..graphql_types.models import ExternalListType as GQLExternalList
from ..graphql_types.models import MutationResult
from .base import BaseService

logger = logging.getLogger(__name__)


def _parse_url(  # pylint: disable=too-many-return-statements
    source: str, raw_input: str
) -> tuple[str, Optional[str]]:
    """Parse a URL or plain username to extract username and optional identifier.

    Returns:
        (username, list_identifier) — identifier is None for non-playlist URLs.
    """
    raw_input = raw_input.strip()

    if source == ExternalListSource.LASTFM:
        # https://www.last.fm/user/JohnDoe -> johndoe
        if "last.fm" in raw_input:
            parsed = urlparse(raw_input)
            path_parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(path_parts) >= 2 and path_parts[0] == "user":
                return path_parts[1].lower(), None
        return raw_input.lower().strip(), None

    if source == ExternalListSource.LISTENBRAINZ:
        # https://listenbrainz.org/user/JohnDoe -> johndoe
        # https://listenbrainz.org/playlist/abc-123/ -> (user, abc-123)
        if "listenbrainz.org" in raw_input:
            parsed = urlparse(raw_input)
            path_parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(path_parts) >= 2 and path_parts[0] == "user":
                return path_parts[1].lower(), None
            if len(path_parts) >= 2 and path_parts[0] == "playlist":
                return "", path_parts[1]
        return raw_input.lower().strip(), None

    if source == ExternalListSource.YOUTUBE_MUSIC:
        from src.providers.youtube_music import YOUTUBE_MUSIC_SENTINEL

        if "music.youtube.com" in raw_input:
            parsed = urlparse(raw_input)
            # Playlist: /playlist?list=PLxxxxxxx
            qs = parse_qs(parsed.query)
            list_ids = qs.get("list", [])
            if list_ids:
                return YOUTUBE_MUSIC_SENTINEL, list_ids[0]
        # Plain text is treated as a playlist ID
        if raw_input.strip():
            return YOUTUBE_MUSIC_SENTINEL, raw_input.strip()
        return YOUTUBE_MUSIC_SENTINEL, None

    return raw_input.lower().strip(), None


def _generate_list_name(
    source: str,
    list_type: str,
    username: str,
    period: Optional[str] = None,
    list_identifier: Optional[str] = None,
) -> str:
    """Generate a human-readable name for an external list."""
    source_label = dict(ExternalListSource.choices).get(source, source)
    type_label = dict(ExternalListType.choices).get(list_type, list_type)

    if source == ExternalListSource.YOUTUBE_MUSIC:
        if list_type == ExternalListType.PLAYLIST:
            short_id = (list_identifier or "unknown")[:20]
            return f"YouTube Music Playlist - {short_id}"
        if list_type == ExternalListType.LOVED_TRACKS:
            return "YouTube Music Liked Songs"

    if list_type == ExternalListType.CHART:
        tag = list_identifier or "global"
        return f"{source_label} Chart: {tag.title()}"
    if period:
        return f"{source_label} {type_label} ({period}) - {username}"
    return f"{source_label} {type_label} - {username}"


class ExternalListService(BaseService["GQLExternalList"]):
    def __init__(self) -> None:
        super().__init__()
        self.model = DjangoExternalList

    async def get_by_id(self, id: str) -> Optional["GQLExternalList"]:
        try:
            obj = await self.model.objects.aget(id=int(id))
            return await sync_to_async(self._to_graphql_type)(obj)
        except (self.model.DoesNotExist, ValueError):
            return None

    async def get_connection(
        self,
        first: int = 20,
        after: Optional[str] = None,
        **filters: Any,
    ) -> Tuple[List["GQLExternalList"], bool, int]:
        source = filters.get("source")
        list_type = filters.get("list_type")
        status = filters.get("status")
        search = filters.get("search")
        sort_by = (
            filters.get("sort_by") if isinstance(filters.get("sort_by"), str) else None
        )
        sort_direction = (
            filters.get("sort_direction")
            if isinstance(filters.get("sort_direction"), str)
            else None
        )

        queryset = self.model.objects.all()

        if source:
            queryset = queryset.filter(source=source)
        if list_type:
            queryset = queryset.filter(list_type=list_type)
        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(username__icontains=search)
            )

        sort_field_map: dict[str, str] = {
            "name": "name",
            "source": "source",
            "status": "status",
            "username": "username",
            "lastSyncedAt": "last_synced_at",
            "createdAt": "created_at",
            "totalTracks": "total_tracks",
            "mappedTracks": "mapped_tracks",
        }

        order_field = "-created_at"
        if sort_by:
            mapped_field = sort_field_map.get(sort_by)
            if mapped_field:
                order_field = mapped_field
                if sort_direction == "desc":
                    order_field = f"-{order_field}"

        total_count = await queryset.acount()

        if after:
            id_after = self.decode_cursor(after)
            queryset = queryset.filter(id__gt=id_after)

        def fetch_items() -> List[DjangoExternalList]:
            return list(queryset.order_by(order_field, "id")[: first + 1])

        items: List[DjangoExternalList] = await sync_to_async(fetch_items)()

        has_next_page = len(items) > first
        items = items[:first]

        def convert_items() -> List["GQLExternalList"]:
            return [self._to_graphql_type(item) for item in items]

        return (
            await sync_to_async(convert_items)(),
            has_next_page,
            total_count,
        )

    async def create_external_list(
        self,
        source: str,
        list_type: str,
        username: str,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
        auto_track_artists: bool = False,
    ) -> "GQLExternalList":
        """Create a new external list after validating the user."""
        # Parse URL input to extract username/identifier
        parsed_username, parsed_identifier = await sync_to_async(_parse_url)(
            source, username
        )

        if parsed_identifier and not list_identifier:
            list_identifier = parsed_identifier
        if parsed_username:
            username = parsed_username

        is_youtube_music = source == ExternalListSource.YOUTUBE_MUSIC
        needs_username = not is_youtube_music and list_type != ExternalListType.CHART

        if not username and needs_username:
            raise ValueError("Username is required for non-chart lists")

        # For YouTube Music, set sentinel username (no real username concept)
        if is_youtube_music:
            from src.providers.youtube_music import YOUTUBE_MUSIC_SENTINEL

            if not username:
                username = YOUTUBE_MUSIC_SENTINEL

        # Validate user exists on the external service
        from src.providers import get_provider

        provider = get_provider(source)

        if is_youtube_music:
            # For liked songs, validate cookie auth works
            if list_type == ExternalListType.LOVED_TRACKS:
                is_valid, error = await sync_to_async(provider.validate_user)(username)
                if not is_valid:
                    raise ValueError(error or "YouTube Music authentication failed")
        elif username and list_type != ExternalListType.CHART:
            is_valid, error = await sync_to_async(provider.validate_user)(username)
            if not is_valid:
                raise ValueError(error or f"User '{username}' not found")

        # Check for duplicates
        existing = await sync_to_async(
            lambda: self.model.objects.filter(
                source=source,
                list_type=list_type,
                username=username,
                period=period,
                list_identifier=list_identifier,
            ).first()
        )()

        if existing:
            return await sync_to_async(self._to_graphql_type)(existing)

        name = _generate_list_name(source, list_type, username, period, list_identifier)

        obj = self.model(
            name=name,
            source=source,
            list_type=list_type,
            username=username,
            period=period,
            list_identifier=list_identifier,
            status=ExternalListStatus.ACTIVE,
            auto_track_artists=auto_track_artists,
        )
        await obj.asave()

        # Queue initial sync
        from library_manager.tasks import sync_external_list

        await sync_to_async(sync_external_list.delay)(obj.id)

        return await sync_to_async(self._to_graphql_type)(obj)

    async def update_external_list(
        self,
        list_id: int,
        name: Optional[str] = None,
        username: Optional[str] = None,
        period: Optional[str] = None,
        list_identifier: Optional[str] = None,
    ) -> MutationResult:
        """Update an external list's editable fields."""
        try:
            obj = await self.model.objects.aget(id=list_id)
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="External list not found")

        needs_resync = False

        if name is not None:
            obj.name = name.strip()
        if username is not None:
            old_username = obj.username
            obj.username = username.strip()
            if obj.username != old_username:
                needs_resync = True
        if period is not None:
            obj.period = period.strip() or None
        if list_identifier is not None:
            old_identifier = obj.list_identifier
            obj.list_identifier = list_identifier.strip() or None
            if obj.list_identifier != old_identifier:
                needs_resync = True

        await obj.asave()

        if needs_resync:
            from library_manager.tasks import sync_external_list

            await sync_to_async(sync_external_list.delay)(obj.id, force=True)

        return MutationResult(
            success=True,
            message=f"Updated '{obj.name}'"
            + (" — re-sync queued" if needs_resync else ""),
        )

    async def sync_external_list(
        self, list_id: int, force: bool = False
    ) -> MutationResult:
        try:
            obj = await self.model.objects.aget(id=list_id)
            from library_manager.tasks import sync_external_list

            await sync_to_async(sync_external_list.delay)(obj.id, force=force)
            return MutationResult(
                success=True,
                message=f"Sync started for '{obj.name}'",
            )
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="External list not found")
        except Exception as e:
            return MutationResult(success=False, message=f"Error: {e}")

    async def toggle_external_list(self, list_id: int) -> MutationResult:
        try:
            obj = await self.model.objects.aget(id=list_id)
            if obj.status == ExternalListStatus.ACTIVE:
                obj.status = ExternalListStatus.DISABLED_BY_USER
            elif obj.status == ExternalListStatus.DISABLED_BY_USER:
                obj.status = ExternalListStatus.ACTIVE
            elif obj.status in (
                ExternalListStatus.AUTH_ERROR,
                ExternalListStatus.NOT_FOUND,
                ExternalListStatus.SYNC_ERROR,
            ):
                obj.status = ExternalListStatus.ACTIVE
            else:
                return MutationResult(
                    success=False,
                    message=f"Cannot toggle list with status: {obj.get_status_display()}",
                )
            obj.status_message = None
            await obj.asave()
            return MutationResult(success=True, message="List toggled successfully")
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="External list not found")

    async def toggle_auto_track(self, list_id: int) -> MutationResult:
        try:
            obj = await self.model.objects.aget(id=list_id)
            obj.auto_track_artists = not obj.auto_track_artists
            await obj.asave()
            return MutationResult(
                success=True,
                message=f"Auto-track {'enabled' if obj.auto_track_artists else 'disabled'}",
            )
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="External list not found")

    async def delete_external_list(self, list_id: int) -> MutationResult:
        try:
            obj = await self.model.objects.aget(id=list_id)
            name = obj.name
            await obj.adelete()
            return MutationResult(
                success=True,
                message=f"External list '{name}' deleted",
            )
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="External list not found")

    async def sync_all_external_lists(self) -> MutationResult:
        try:
            from library_manager.tasks import sync_all_external_lists

            await sync_to_async(sync_all_external_lists.delay)()
            return MutationResult(
                success=True,
                message="Sync queued for all active external lists",
            )
        except Exception as e:
            return MutationResult(success=False, message=f"Error: {e}")

    def _to_graphql_type(self, obj: DjangoExternalList) -> "GQLExternalList":
        return GQLExternalList(
            id=int(obj.id),
            name=obj.name,
            source=obj.source,
            list_type=obj.list_type,
            username=obj.username,
            period=obj.period,
            list_identifier=obj.list_identifier,
            status=obj.status,
            status_message=obj.status_message,
            auto_track_artists=obj.auto_track_artists,
            last_synced_at=obj.last_synced_at,
            created_at=obj.created_at,
            total_tracks=obj.total_tracks,
            mapped_tracks=obj.mapped_tracks,
            failed_tracks=obj.failed_tracks,
        )
