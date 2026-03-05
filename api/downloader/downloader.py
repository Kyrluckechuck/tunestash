import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

import spotipy
from spotipy.exceptions import SpotifyException

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 0.5

logger = logging.getLogger(__name__)


class Downloader:
    """Handles Spotify API operations with dual-client architecture.

    Uses two separate Spotipy clients to leverage independent rate limit buckets:
    - public_client: Client Credentials flow for metadata (tracks, albums, artists)
    - oauth_client: OAuth flow for private playlists and user operations

    This separation reduces rate limiting issues by distributing API calls across
    different authentication contexts.
    """

    def __init__(
        self,
        spotipy_client: spotipy.Spotify,
        public_client: Optional[spotipy.Spotify] = None,
        on_auth_error: Optional[Callable[[], bool]] = None,
    ):
        """Initialize Downloader with Spotipy client(s).

        Args:
            spotipy_client: Primary client (OAuth preferred) for playlist operations.
                           Also used as fallback if public_client is None.
            public_client: Optional client using Client Credentials for public
                          metadata operations. If None, spotipy_client is used for all.
            on_auth_error: Optional callback invoked on 401 auth errors. Should refresh
                          the OAuth token and return True if successful. If provided,
                          failed requests will be retried once after callback returns True.
        """
        self.spotipy_client = spotipy_client
        self.public_client = public_client if public_client else spotipy_client
        self._on_auth_error = on_auth_error

    def get_track(self, track_id: str) -> Dict[str, Any]:
        """Get track metadata. Uses public client since track data is public."""
        return self.public_client.track(track_id)

    def get_album(self, album_id: str) -> Dict[str, Any]:
        """Get album details. Uses public client since album data is public."""
        album = self.public_client.album(album_id)
        album_track_iterator = self.public_client.next(album["tracks"])

        while album_track_iterator is not None:
            album["tracks"]["items"].extend(album_track_iterator["items"])
            # Rate limiting: delay between paginated API calls
            time.sleep(_API_CALL_DELAY_SECONDS)
            album_track_iterator = self.public_client.next(album_track_iterator)
        return album

    def get_playlist(self, playlist_id: str) -> Dict[str, Any]:
        """Get playlist with all tracks.

        Prefers OAuth client (can access both public and private playlists),
        falls back to public client for unauthenticated users syncing public playlists.
        """
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
            # Rate limiting: delay between paginated API calls
            time.sleep(_API_CALL_DELAY_SECONDS)
            playlist_iterator = used_client.next(playlist_iterator)

        return playlist

    def get_playlist_snapshot_id(self, playlist_id: str) -> str | None:
        """Get only the snapshot_id of a playlist (lightweight API call).

        This allows checking if a playlist has changed without fetching all tracks.
        Uses the fields parameter to minimize API response size and reduce rate
        limiting risk.

        Prefers OAuth client (can access both public and private playlists),
        falls back to public client for unauthenticated users.

        If a 401 auth error occurs and an on_auth_error callback is configured,
        the token will be refreshed and the request retried once.

        Args:
            playlist_id: The Spotify playlist ID (22-character base62 string)

        Returns:
            The playlist's snapshot_id string, or None if request fails
        """
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
                    if self._on_auth_error():
                        # Retry once after token refresh
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
                            # Don't retry again, fall through to public client
                        except Exception:
                            pass
                    else:
                        logger.warning(
                            "OAuth token refresh failed, trying public client"
                        )
                # Fall through to public client for other errors
            except Exception:
                pass

        # Fall back to public client (unauthenticated users syncing public playlists)
        try:
            result = self.public_client.playlist(playlist_id, fields="snapshot_id")
            return result.get("snapshot_id")
        except Exception:
            pass

        return None

    def get_download_queue(
        self, url: str, include_metadata: bool = False
    ) -> List[Dict[str, Any]] | tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Get the download queue for a Spotify URL.

        Args:
            url: Spotify URL or URI
            include_metadata: If True, also return playlist/album metadata (including
                snapshot_id for playlists)

        Returns:
            If include_metadata is False: List of track dicts
            If include_metadata is True: Tuple of (track list, metadata dict)
        """
        match = re.search(r"(\w{22})", url)
        if match is None:
            raise ValueError("Invalid Spotify URL format")
        uri = match.group(1)
        download_queue: list[Dict[str, Any]] = []
        metadata: Dict[str, Any] = {}

        if "album" in url:
            album = self.get_album(uri)
            # Album tracks are "simplified" and don't include album data.
            # Inject album metadata so song_from_track_data() has complete info.
            album_info = {
                "id": album.get("id"),
                "name": album.get("name"),
                "artists": album.get("artists", []),
                "images": album.get("images", []),
                "release_date": album.get("release_date"),
                "total_tracks": album.get("total_tracks"),
                "album_type": album.get("album_type"),
            }
            for track in album["tracks"]["items"]:
                track["album"] = album_info
            download_queue.extend(album["tracks"]["items"])
            if include_metadata:
                return download_queue, {"type": "album", "id": uri}
            return download_queue
        if "track" in url:
            download_queue.append(self.get_track(uri))
            if include_metadata:
                return download_queue, {"type": "track", "id": uri}
            return download_queue
        if "playlist" in url:
            from library_manager.validators import is_local_track

            playlist = self.get_playlist(uri)
            raw_playlist = playlist["tracks"]["items"]
            metadata = {
                "type": "playlist",
                "id": uri,
                "snapshot_id": playlist.get("snapshot_id"),
            }
            for i in raw_playlist:
                i["track"]["added_at"] = i["added_at"]
            # Filter out local files - they can't be downloaded via Spotify API
            download_queue.extend(
                [i["track"] for i in raw_playlist if not is_local_track(i["track"])]
            )
            if include_metadata:
                return download_queue, metadata
            return download_queue
        raise Exception("Not a valid Spotify URL")

    def get_download_queue_batch(
        self, urls: List[str]
    ) -> tuple[List[List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
        """Get download queues for multiple URLs.

        Fetches tracks individually (Spotify removed batch endpoints in Feb 2026).

        Args:
            urls: List of Spotify URLs/URIs (tracks, albums, playlists)

        Returns:
            Tuple of (list of download queues, dict mapping URL to metadata)
        """
        download_queues: List[List[Dict[str, Any]]] = [[] for _ in range(len(urls))]
        metadata_map: Dict[str, Dict[str, Any]] = {}

        for idx, url in enumerate(urls):
            try:
                result = self.get_download_queue(url, include_metadata=True)
                if isinstance(result, tuple):
                    download_queues[idx] = result[0]
                    metadata_map[url] = result[1]
                else:
                    download_queues[idx] = result
            except Exception:
                pass
            # Rate limiting between sequential fetches
            if idx < len(urls) - 1:
                time.sleep(_API_CALL_DELAY_SECONDS)

        return download_queues, metadata_map

    def get_song_core_info(self, metadata: Dict[str, Any]) -> Dict[str, Optional[str]]:
        from library_manager.validators import extract_spotify_id_from_uri

        # Extract base62 Spotify ID from URI/URL (avoids hex encoding)
        song_id = extract_spotify_id_from_uri(metadata["id"])
        if not song_id:
            raise ValueError(
                f"Invalid Spotify track ID format: {metadata['id']}. "
                f"Expected Spotify URI, URL, or base62 ID."
            )

        # Extract ISRC from external_ids (may not be present for all tracks)
        isrc = metadata.get("external_ids", {}).get("isrc")

        return {
            "song_gid": song_id,
            "song_name": metadata["name"],
            "isrc": isrc,
        }
