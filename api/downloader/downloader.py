import logging
import time
from typing import Any, Callable, Dict, Optional

import spotipy
from spotipy.exceptions import SpotifyException

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 0.5

logger = logging.getLogger(__name__)


class SpotifyPlaylistClient:
    """Lightweight Spotify client for playlist operations only.

    Used for playlist sync (snapshot change detection, track list fetching).
    Uses two separate Spotipy clients to leverage independent rate limit buckets:
    - public_client: Client Credentials flow for public playlists
    - oauth_client: OAuth flow for private playlists
    """

    def __init__(
        self,
        spotipy_client: Optional[spotipy.Spotify] = None,
        public_client: Optional[spotipy.Spotify] = None,
        on_auth_error: Optional[Callable[[], Optional[spotipy.Spotify]]] = None,
    ):
        self.spotipy_client = spotipy_client
        self.public_client = public_client if public_client else spotipy_client
        self._on_auth_error = on_auth_error

    @classmethod
    def create(cls) -> "SpotifyPlaylistClient":
        """Factory method that creates a client using configured credentials."""
        from .spotipy_tasks import OAuthSpotifyClient, PublicSpotifyClient

        try:
            oauth = OAuthSpotifyClient()
            public = PublicSpotifyClient()
            if oauth.sp is None and public.sp is None:
                logger.warning("No Spotify clients available")
                return cls()
            return cls(
                spotipy_client=oauth.sp,
                public_client=public.sp,
                on_auth_error=oauth.refresh_token,
            )
        except Exception:
            logger.warning("Failed to create SpotifyPlaylistClient")
            return cls()

    def is_available(self) -> bool:
        """Check if at least one Spotify client is configured."""
        return self.spotipy_client is not None

    def get_playlist(self, playlist_id: str) -> Dict[str, Any]:
        """Get playlist with all tracks.

        Prefers OAuth client (can access both public and private playlists),
        falls back to public client for unauthenticated users syncing public playlists.
        """
        if not self.is_available():
            raise RuntimeError("No Spotify client available")

        playlist = None
        used_client = None

        # Prefer OAuth client - it can access both public AND private playlists
        if self.public_client != self.spotipy_client:
            try:
                playlist = self.spotipy_client.playlist(playlist_id)
                used_client = self.spotipy_client
            except Exception:
                pass

        # Fall back to public client (unauthenticated users syncing public playlists)
        if playlist is None:
            playlist = self.public_client.playlist(playlist_id)
            used_client = self.public_client

        if playlist is None:
            raise Exception(f"Failed to fetch playlist {playlist_id}")

        # Paginate through all tracks using the same client that succeeded
        playlist_iterator = used_client.next(playlist["tracks"])
        while playlist_iterator is not None:
            playlist["tracks"]["items"].extend(playlist_iterator["items"])
            time.sleep(_API_CALL_DELAY_SECONDS)
            playlist_iterator = used_client.next(playlist_iterator)

        return playlist

    def get_playlist_snapshot_id(self, playlist_id: str) -> str | None:
        """Get only the snapshot_id of a playlist (lightweight API call).

        This allows checking if a playlist has changed without fetching all tracks.
        Uses the fields parameter to minimize API response size.
        """
        if not self.is_available():
            return None

        # Prefer OAuth client - it can access both public AND private playlists
        if self.public_client != self.spotipy_client:
            try:
                result = self.spotipy_client.playlist(playlist_id, fields="snapshot_id")
                return result.get("snapshot_id")
            except SpotifyException as e:
                if e.http_status == 401 and self._on_auth_error:
                    logger.warning(
                        "OAuth token expired during playlist snapshot check, refreshing..."
                    )
                    new_client = self._on_auth_error()
                    if new_client is not None:
                        # Replace the captured reference; the singleton's .sp
                        # was rebuilt and our old reference still holds the
                        # expired token.
                        self.spotipy_client = new_client
                        try:
                            result = self.spotipy_client.playlist(
                                playlist_id, fields="snapshot_id"
                            )
                            return result.get("snapshot_id")
                        except SpotifyException as retry_err:
                            if retry_err.http_status == 401:
                                logger.error(
                                    "OAuth token still invalid after refresh - "
                                    "possible auth configuration issue"
                                )
                        except Exception:
                            pass
                    else:
                        logger.warning(
                            "OAuth token refresh failed, trying public client"
                        )
            except Exception:
                pass

        # Fall back to public client
        try:
            result = self.public_client.playlist(playlist_id, fields="snapshot_id")
            return result.get("snapshot_id")
        except Exception:
            pass

        return None
