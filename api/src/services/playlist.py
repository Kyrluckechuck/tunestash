# mypy: disable-error-code=attr-defined
from typing import Any, List, Optional, Tuple, cast

from django.db.models import Q

from asgiref.sync import sync_to_async
from downloader.utils import normalize_spotify_url

from library_manager.models import PlaylistStatus
from library_manager.models import TrackedPlaylist as DjangoPlaylist
from library_manager.tasks.core import extract_deezer_playlist_id
from library_manager.validators import is_spotify_owned_playlist

from ..graphql_types.models import MutationResult, Playlist
from .base import BaseService


class PlaylistService(BaseService[Playlist]):
    def __init__(self) -> None:
        super().__init__()
        self.model = DjangoPlaylist

    @staticmethod
    def _is_deezer_url(url: str) -> bool:
        return "deezer.com" in url

    @staticmethod
    def _extract_deezer_playlist_id(url: str) -> Optional[str]:
        return extract_deezer_playlist_id(url)

    @staticmethod
    def _normalize_deezer_url(url: str) -> str:
        """Extract canonical Deezer playlist URL."""
        playlist_id = extract_deezer_playlist_id(url)
        if playlist_id:
            return f"https://www.deezer.com/playlist/{playlist_id}"
        return url

    @staticmethod
    def _normalize_spotify_url(url: str) -> str:
        return normalize_spotify_url(url)

    def _find_duplicate_playlist(
        self, normalized_url: str, exclude_id: Optional[int] = None
    ) -> Optional[DjangoPlaylist]:
        """Find existing playlist that matches the normalized URL in either format.

        Args:
            normalized_url: The normalized playlist URL (URI or HTTP format)
            exclude_id: Optional playlist ID to exclude from search (for update operations)

        Returns:
            Matching playlist if found, None otherwise
        """
        # Build base queryset with exact URL match
        queryset = self.model.objects.filter(url=normalized_url)
        if exclude_id is not None:
            queryset = queryset.exclude(id=exclude_id)

        existing = cast(Optional[DjangoPlaylist], queryset.first())
        if existing:
            return existing

        # If normalized_url is a URI, also check for HTTP format
        if normalized_url.startswith("spotify:"):
            # Convert URI back to HTTP format to check existing HTTP URLs
            parts = normalized_url.split(":")
            if len(parts) == 3:
                content_type, content_id = parts[1], parts[2]
                http_url = f"https://open.spotify.com/{content_type}/{content_id}"

                # Check for HTTP URLs with various parameter patterns
                queryset = self.model.objects.filter(
                    Q(url=http_url) | Q(url__startswith=f"{http_url}?")
                )
                if exclude_id is not None:
                    queryset = queryset.exclude(id=exclude_id)

                existing = cast(Optional[DjangoPlaylist], queryset.first())
                if existing:
                    return existing

        return None

    async def get_by_id(self, id: str) -> Optional[Playlist]:
        try:
            # First try to find by database ID (more specific)
            django_playlist = await self.model.objects.aget(id=int(id))
            return self._to_graphql_type(django_playlist)
        except (self.model.DoesNotExist, ValueError):
            try:
                # If not found by database ID, try to find by URL containing the ID
                django_playlist = await self.model.objects.aget(url__contains=id)
                return self._to_graphql_type(django_playlist)
            except (self.model.DoesNotExist, self.model.MultipleObjectsReturned):
                return None

    async def get_connection(
        self,
        first: int = 20,
        after: Optional[str] = None,
        **filters: Any,
    ) -> Tuple[List[Playlist], bool, int]:
        enabled: Optional[bool] = filters.get("enabled")
        status_filter: Optional[str] = filters.get("status")
        search: Optional[str] = filters.get("search")
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
        if status_filter is not None:
            queryset = queryset.filter(status=status_filter)
        elif enabled is not None:
            # Backwards compatibility: enabled=True means status=active
            if enabled:
                queryset = queryset.filter(status=PlaylistStatus.ACTIVE)
            else:
                queryset = queryset.exclude(status=PlaylistStatus.ACTIVE)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(url__icontains=search)
            )

        # Apply sorting
        sort_field_map: dict[str, str] = {
            "name": "name",
            "status": "status",
            "enabled": "status",  # Backwards compatibility
            "autoTrackArtists": "auto_track_artists",
            "lastSyncedAt": "last_synced_at",
        }

        order_field = "id"  # default
        if isinstance(sort_by, str):
            mapped_field = sort_field_map.get(sort_by)
            if mapped_field is not None:
                order_field = mapped_field
                if sort_direction == "desc":
                    order_field = f"-{order_field}"

        total_count = await queryset.acount()

        # Apply cursor-based pagination
        if after:
            id_after = self.decode_cursor(after)
            queryset = queryset.filter(id__gt=id_after)

        # Get one extra item to determine if there are more pages
        def fetch_items() -> List[DjangoPlaylist]:
            return list(queryset.order_by(order_field, "id")[: first + 1])

        items: List[DjangoPlaylist] = await sync_to_async(fetch_items)()

        has_next_page = len(items) > first
        items = items[:first]  # Remove the extra item

        return (
            [self._to_graphql_type(item) for item in items],
            has_next_page,
            total_count,
        )

    async def track_playlist(
        self, playlist_id: str, auto_track_artists: bool = False
    ) -> Playlist:
        django_playlist = await self.model.objects.aget(url__contains=playlist_id)
        django_playlist.status = PlaylistStatus.ACTIVE
        django_playlist.status_message = None
        django_playlist.auto_track_artists = auto_track_artists
        await django_playlist.asave()

        # Queue tasks - local imports to avoid circular import during module initialization
        from library_manager.tasks import (
            sync_tracked_playlist,
            sync_tracked_playlist_artists,
        )

        await sync_to_async(sync_tracked_playlist.delay)(django_playlist.id)
        if auto_track_artists:
            await sync_to_async(sync_tracked_playlist_artists.delay)(django_playlist.id)

        return self._to_graphql_type(django_playlist)

    async def save_playlist_by_spotify_id(
        self, spotify_id: str, auto_track_artists: bool = False
    ) -> Playlist:
        """
        Save a playlist by its Spotify ID, fetching the name from Spotify.
        Creates the playlist if it doesn't exist, or returns existing one.

        Raises:
            ValueError: If the playlist is a Spotify-owned algorithmic playlist
        """
        # Block Spotify-owned playlists (Discover Weekly, Daily Mix, etc.)
        if is_spotify_owned_playlist(spotify_id):
            raise ValueError(
                "This is a Spotify-generated playlist (like Discover Weekly or Daily Mix) "
                "which cannot be accessed via Spotify's API. "
                "Try copying the tracks to your own playlist instead."
            )

        spotify_uri = f"spotify:playlist:{spotify_id}"

        existing_playlist = await sync_to_async(
            lambda: self._find_duplicate_playlist(spotify_uri)
        )()

        if existing_playlist:
            # Enable tracking if not already enabled
            if not existing_playlist.enabled:
                existing_playlist.status = PlaylistStatus.ACTIVE
                existing_playlist.status_message = None
                existing_playlist.auto_track_artists = auto_track_artists
                await existing_playlist.asave()

                # Queue sync tasks
                from library_manager.tasks import (
                    sync_tracked_playlist,
                    sync_tracked_playlist_artists,
                )

                await sync_to_async(sync_tracked_playlist.delay)(existing_playlist.id)
                if auto_track_artists:
                    await sync_to_async(sync_tracked_playlist_artists.delay)(
                        existing_playlist.id
                    )

            return self._to_graphql_type(existing_playlist)

        # Fetch playlist name from Spotify
        def get_playlist_name() -> str:
            from downloader.spotipy_tasks import SpotifyClient

            sp = SpotifyClient().sp
            if sp is None:
                return f"Playlist {spotify_id}"
            playlist_data = sp.playlist(spotify_id, fields="name")
            return str(playlist_data.get("name", f"Playlist {spotify_id}"))

        playlist_name = await sync_to_async(get_playlist_name)()

        # Create the playlist
        return await self.create_playlist(
            name=playlist_name,
            url=spotify_uri,
            auto_track_artists=auto_track_artists,
        )

    async def create_playlist(
        self, name: str, url: str, auto_track_artists: bool = False
    ) -> Playlist:
        """Create a new playlist, checking for duplicates using normalized URLs.

        Supports both Spotify and Deezer playlist URLs.

        Raises:
            ValueError: If the playlist is a Spotify-owned algorithmic playlist
        """
        is_deezer = self._is_deezer_url(url)

        if is_deezer:
            normalized_url = self._normalize_deezer_url(url)
        else:
            normalized_url = self._normalize_spotify_url(url)

            # Block Spotify-owned playlists (Discover Weekly, Daily Mix, etc.)
            if is_spotify_owned_playlist(normalized_url):
                raise ValueError(
                    "This is a Spotify-generated playlist (like Discover Weekly or Daily Mix) "
                    "which cannot be accessed via Spotify's API. "
                    "Try copying the tracks to your own playlist instead."
                )

        existing_playlist = await sync_to_async(
            lambda: self._find_duplicate_playlist(normalized_url)
        )()

        if existing_playlist:
            return self._to_graphql_type(existing_playlist)

        django_playlist = self.model(
            name=name,
            url=normalized_url,
            status=PlaylistStatus.ACTIVE,
            auto_track_artists=auto_track_artists,
            provider="deezer" if is_deezer else "spotify",
        )
        await django_playlist.asave()

        if is_deezer:
            from library_manager.tasks import sync_deezer_playlist

            await sync_to_async(sync_deezer_playlist.delay)(django_playlist.id)
        else:
            from library_manager.tasks import (
                sync_tracked_playlist,
                sync_tracked_playlist_artists,
            )

            await sync_to_async(sync_tracked_playlist.delay)(django_playlist.id)
            if auto_track_artists:
                await sync_to_async(sync_tracked_playlist_artists.delay)(
                    django_playlist.id
                )

        return self._to_graphql_type(django_playlist)

    async def update_playlist(
        self,
        playlist_id: int,
        name: str,
        url: str,
        auto_track_artists: bool,
    ) -> MutationResult:
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)

            # Normalize the URL to strip tracking parameters
            normalized_url = self._normalize_spotify_url(url)

            # Check if another playlist already has this normalized URL
            # Only check if the URL is actually changing
            current_normalized = self._normalize_spotify_url(django_playlist.url)
            if normalized_url != current_normalized:
                existing_playlist = await sync_to_async(
                    lambda: self._find_duplicate_playlist(
                        normalized_url, exclude_id=playlist_id
                    )
                )()

                if existing_playlist:
                    return MutationResult(
                        success=False,
                        message=f"A playlist with this URL already exists: {existing_playlist.name}",
                    )

            django_playlist.name = name
            django_playlist.url = normalized_url
            django_playlist.auto_track_artists = auto_track_artists

            await django_playlist.asave()

            return MutationResult(
                success=True,
                message="Playlist updated successfully",
                playlist=self._to_graphql_type(django_playlist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Playlist not found", playlist=None
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error updating playlist: {str(e)}",
                playlist=None,
            )

    async def toggle_playlist(self, playlist_id: int) -> MutationResult:
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)

            # Can only toggle between ACTIVE and DISABLED_BY_USER
            if django_playlist.status == PlaylistStatus.ACTIVE:
                django_playlist.status = PlaylistStatus.DISABLED_BY_USER
                django_playlist.status_message = None
            elif django_playlist.status == PlaylistStatus.DISABLED_BY_USER:
                django_playlist.status = PlaylistStatus.ACTIVE
                django_playlist.status_message = None
            else:
                # Cannot toggle restricted/not_found playlists
                return MutationResult(
                    success=False,
                    message=f"Cannot enable playlist with status: {django_playlist.get_status_display()}",
                    playlist=self._to_graphql_type(django_playlist),
                )

            await django_playlist.asave()

            return MutationResult(
                success=True,
                message="Playlist toggled successfully",
                playlist=self._to_graphql_type(django_playlist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Playlist not found", playlist=None
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error toggling playlist: {str(e)}",
                playlist=None,
            )

    async def toggle_playlist_auto_track(self, playlist_id: int) -> MutationResult:
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)
            django_playlist.auto_track_artists = not django_playlist.auto_track_artists
            await django_playlist.asave()

            return MutationResult(
                success=True,
                message="Playlist auto-track toggled successfully",
                playlist=self._to_graphql_type(django_playlist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Playlist not found", playlist=None
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error toggling playlist auto-track: {str(e)}",
                playlist=None,
            )

    async def toggle_playlist_m3u(self, playlist_id: int) -> MutationResult:
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)
            django_playlist.m3u_enabled = not django_playlist.m3u_enabled
            await django_playlist.asave()

            if django_playlist.m3u_enabled:
                # Generate M3U file
                await sync_to_async(self._generate_m3u)(django_playlist)
                message = "M3U export enabled"
            else:
                # Delete M3U file
                await sync_to_async(self._delete_m3u)(django_playlist)
                message = "M3U export disabled"

            return MutationResult(
                success=True,
                message=message,
                playlist=self._to_graphql_type(django_playlist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Playlist not found", playlist=None
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error toggling M3U export: {str(e)}",
                playlist=None,
            )

    @staticmethod
    def _generate_m3u(django_playlist: DjangoPlaylist) -> None:
        from pathlib import Path

        from django.conf import settings as django_settings

        from downloader.m3u_writer import write_playlist_m3u

        from src.app_settings.registry import get_setting

        output_dir = Path(getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify"))
        playlist_dir = get_setting("m3u_playlists_directory")
        write_playlist_m3u(django_playlist.pk, output_dir, playlist_dir)

    @staticmethod
    def _delete_m3u(django_playlist: DjangoPlaylist) -> None:
        import re
        from pathlib import Path

        from django.conf import settings as django_settings

        from src.app_settings.registry import get_setting

        output_dir = Path(getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify"))
        playlist_dir_name = get_setting("m3u_playlists_directory")
        safe_name = re.sub(r'[/\\:*?"<>|]', "", django_playlist.name)
        safe_name = safe_name.strip(". ")[:200]
        m3u_path = output_dir / playlist_dir_name / f"TS - {safe_name}.m3u"
        if m3u_path.exists():
            m3u_path.unlink()

    async def delete_playlist(self, playlist_id: int) -> MutationResult:
        """Delete a tracked playlist from the database."""
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)
            playlist_name = django_playlist.name
            await django_playlist.adelete()

            return MutationResult(
                success=True,
                message=f"Playlist '{playlist_name}' deleted successfully",
            )
        except self.model.DoesNotExist:
            return MutationResult(success=False, message="Playlist not found")
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error deleting playlist: {str(e)}",
            )

    async def get_spotify_playlist_info(self, url: str) -> Optional[dict[str, Any]]:
        """
        Fetch playlist metadata from Spotify without creating a database record.

        Used by the frontend to auto-populate playlist name when a URL is pasted.

        Args:
            url: Spotify playlist URL or URI

        Returns:
            Dict with 'name', 'owner_name', 'track_count', 'image_url' or None if not found
        """
        normalized_url = self._normalize_spotify_url(url)

        # Extract the playlist ID from the normalized URI
        if not normalized_url.startswith("spotify:playlist:"):
            return None

        spotify_id = normalized_url.split(":")[-1]

        # Block Spotify-owned playlists
        if is_spotify_owned_playlist(normalized_url):
            return None

        def fetch_from_spotify() -> Optional[dict[str, Any]]:
            try:
                from downloader.spotipy_tasks import SpotifyClient

                sp = SpotifyClient().sp
                if sp is None:
                    return None
                playlist_data = sp.playlist(
                    spotify_id, fields="name,owner(display_name),tracks(total),images"
                )

                # Get the best image (first one is usually the largest)
                images = playlist_data.get("images", [])
                image_url = images[0].get("url") if images else None

                return {
                    "name": playlist_data.get("name", f"Playlist {spotify_id}"),
                    "owner_name": playlist_data.get("owner", {}).get("display_name"),
                    "track_count": playlist_data.get("tracks", {}).get("total", 0),
                    "image_url": image_url,
                }
            except Exception:
                return None

        return await sync_to_async(fetch_from_spotify)()

    async def get_deezer_playlist_info(self, url: str) -> Optional[dict[str, Any]]:
        """Fetch playlist metadata from Deezer without creating a database record."""
        playlist_id = self._extract_deezer_playlist_id(url)
        if not playlist_id:
            return None

        def fetch_from_deezer() -> Optional[dict[str, Any]]:
            try:
                from src.providers.deezer import DeezerMetadataProvider

                provider = DeezerMetadataProvider()
                info = provider.get_playlist(playlist_id)
                if info is None:
                    return None
                return {
                    "name": info.name,
                    "owner_name": info.creator_name,
                    "track_count": info.track_count,
                    "image_url": info.image_url,
                }
            except Exception:
                return None

        return await sync_to_async(fetch_from_deezer)()

    async def get_playlist_info(self, url: str) -> Optional[dict[str, Any]]:
        """Auto-detect provider from URL and fetch playlist info."""
        if self._is_deezer_url(url):
            result = await self.get_deezer_playlist_info(url)
            if result:
                result["provider"] = "deezer"
            return result

        result = await self.get_spotify_playlist_info(url)
        if result:
            result["provider"] = "spotify"
        return result

    async def save_playlist_by_deezer_id(
        self, deezer_id: str, auto_track_artists: bool = False
    ) -> Playlist:
        """Save a playlist by its Deezer ID, fetching name from Deezer API."""
        deezer_url = f"https://www.deezer.com/playlist/{deezer_id}"

        existing = await sync_to_async(
            lambda: self._find_duplicate_playlist(deezer_url)
        )()

        if existing:
            if not existing.enabled:
                existing.status = PlaylistStatus.ACTIVE
                existing.status_message = None
                existing.auto_track_artists = auto_track_artists
                await existing.asave()

                from library_manager.tasks import sync_deezer_playlist

                await sync_to_async(sync_deezer_playlist.delay)(existing.id)

            return self._to_graphql_type(existing)

        def get_playlist_name() -> str:
            from src.providers.deezer import DeezerMetadataProvider

            provider = DeezerMetadataProvider()
            info = provider.get_playlist(deezer_id)
            return info.name if info else f"Deezer Playlist {deezer_id}"

        playlist_name = await sync_to_async(get_playlist_name)()

        return await self.create_playlist(
            name=playlist_name,
            url=deezer_url,
            auto_track_artists=auto_track_artists,
        )

    async def sync_playlist(
        self, playlist_id: int, force: bool = False, recheck: bool = False
    ) -> MutationResult:
        try:
            django_playlist = await self.model.objects.aget(id=playlist_id)

            # If recheck=True, reset error status to ACTIVE before syncing
            if recheck and django_playlist.status in (
                PlaylistStatus.NOT_FOUND,
                PlaylistStatus.SPOTIFY_API_RESTRICTED,
            ):
                django_playlist.status = PlaylistStatus.ACTIVE
                django_playlist.status_message = None
                await django_playlist.asave()

            if django_playlist.provider == "deezer":
                from library_manager.tasks import sync_deezer_playlist

                await sync_to_async(sync_deezer_playlist.delay)(django_playlist.id)
                message = "Deezer playlist sync started successfully"
            elif force or recheck:
                from library_manager.tasks import download_playlist

                await sync_to_async(download_playlist.delay)(
                    playlist_url=django_playlist.url,
                    tracked=django_playlist.auto_track_artists,
                    force_playlist_resync=True,
                )
                message = (
                    "Playlist recheck started successfully"
                    if recheck
                    else "Playlist force sync started successfully"
                )
            else:
                from library_manager.tasks import sync_tracked_playlist

                await sync_to_async(sync_tracked_playlist.delay)(django_playlist.id)
                message = "Playlist sync started successfully"

            return MutationResult(
                success=True,
                message=message,
                playlist=self._to_graphql_type(django_playlist),
            )
        except self.model.DoesNotExist:
            return MutationResult(
                success=False, message="Playlist not found", playlist=None
            )
        except Exception as e:
            return MutationResult(
                success=False,
                message=f"Error syncing playlist: {str(e)}",
                playlist=None,
            )

    def _to_graphql_type(self, django_playlist: DjangoPlaylist) -> Playlist:
        return Playlist(
            id=int(django_playlist.id),
            name=django_playlist.name,
            url=django_playlist.url,
            status=django_playlist.status,
            status_message=django_playlist.status_message,
            enabled=django_playlist.enabled,
            auto_track_artists=django_playlist.auto_track_artists,
            m3u_enabled=django_playlist.m3u_enabled,
            last_synced_at=django_playlist.last_synced_at,
            provider=django_playlist.provider,
        )
