import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

from spotipy.exceptions import SpotifyException

from library_manager.models import Album, Artist

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
        spotipy_client: Any,
        public_client: Optional[Any] = None,
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

    def get_new_releases(
        self, limit: int = 50, offset: int = 0
    ) -> list[Dict[str, Any]] | None:
        """Get new album releases from Spotify's browse endpoint.

        This endpoint returns globally featured/promoted new releases, which is
        useful for quickly detecting new music from popular tracked artists without
        having to check each artist individually.

        Args:
            limit: Number of releases to fetch (max 50)
            offset: Offset for pagination

        Returns:
            List of album dicts with 'id', 'name', and 'artists' keys,
            or None if the API call fails.
        """
        try:
            result = self.public_client.new_releases(
                limit=min(limit, 50), offset=offset
            )
            if result and result.get("albums", {}).get("items"):
                return [
                    {
                        "id": album.get("id"),
                        "name": album.get("name"),
                        "artists": [
                            {"id": a.get("id"), "name": a.get("name")}
                            for a in album.get("artists", [])
                        ],
                    }
                    for album in result["albums"]["items"]
                    if album.get("id")
                ]
            return []
        except Exception:
            return None

    def get_artist_recent_album_ids(
        self, artist_gid: str, limit: int = 20
    ) -> list[str] | None:
        """Get recent album IDs for an artist (lightweight API call for change detection).

        This is an optimization for change detection: instead of fetching all albums
        with pagination, we fetch the first N albums in a single API call. The caller
        can then compare these against known albums in the database to detect new
        releases.

        Fetching 20 albums costs the same as fetching 1 (1 API call), but provides
        more robust change detection since it doesn't depend on specific ordering.

        Args:
            artist_gid: The Spotify artist ID (22-character base62 string)
            limit: Number of albums to fetch (max 50, default 20)

        Returns:
            List of Spotify album IDs, or None if the API call fails.
            Empty list if artist has no albums.
        """
        try:
            artist_uri = f"spotify:artist:{artist_gid}"
            result = self.public_client.artist_albums(artist_uri, limit=min(limit, 50))
            if result and result.get("items"):
                return [album.get("id") for album in result["items"] if album.get("id")]
            return []
        except Exception:
            return None

    def get_artist_albums(self, artist_gid: str) -> List[Album]:
        """Get all albums (including EPs and Singles) for this artist.

        Uses the public client (Client Credentials) since artist data is public.

        Args:
            artist_gid (str): The artist GID as supplied by Spotify

        Returns:
            list[str]: an array of urls to each album for the artist
        """
        artist = Artist.objects.get(gid=artist_gid)
        albums_to_create_or_update: List[Dict] = []
        # artist_gid is already a Spotify ID, just format as URI
        artist_uri = f"spotify:artist:{artist_gid}"

        # Use public client - artist data doesn't require user auth
        album_iterator = self.public_client.artist_albums(artist_uri, limit=50)

        while album_iterator is not None:
            for album in album_iterator["items"]:
                new_or_updated_album_data: dict = {
                    "spotify_gid": album["id"],
                    "artist": artist,
                    "spotify_uri": album["uri"],
                    "total_tracks": album["total_tracks"],
                    "name": album["name"],
                    "album_type": album["album_type"],
                    "album_group": album["album_group"],
                }

                albums_to_create_or_update.append(new_or_updated_album_data)

            # Rate limiting: delay between paginated API calls
            time.sleep(_API_CALL_DELAY_SECONDS)
            album_iterator = self.public_client.next(album_iterator)

        if len(albums_to_create_or_update) == 0:
            return []

        albums: List[Album] = Album.objects.bulk_create(
            [Album(**album) for album in albums_to_create_or_update],
            update_conflicts=True,
            unique_fields=["spotify_gid"],
            update_fields=albums_to_create_or_update[0].keys(),
        )
        return albums

    def get_track(self, track_id: str) -> Any:
        """Get track metadata. Uses public client since track data is public."""
        return self.public_client.track(track_id)

    def get_tracks_batch(self, track_ids: List[str]) -> List[Any]:
        """Batch fetch multiple tracks in a single API call.

        Uses Spotify's "Get Several Tracks" endpoint which supports up to 50 tracks
        per request, significantly reducing API calls for bulk operations.

        Uses the public client since track metadata is public data.

        Args:
            track_ids: List of Spotify track IDs (max 50 per call, will batch if more)

        Returns:
            List of track objects from the API
        """
        if not track_ids:
            return []

        all_tracks = []
        # Spotify allows max 50 tracks per request
        batch_size = 50

        for i in range(0, len(track_ids), batch_size):
            batch = track_ids[i : i + batch_size]
            # Use public client - track metadata doesn't require user auth
            result = self.public_client.tracks(batch)
            if result and "tracks" in result:
                # Filter out None values (tracks that don't exist)
                all_tracks.extend([t for t in result["tracks"] if t is not None])
            # Rate limiting: delay between batch API calls
            if i + batch_size < len(track_ids):
                time.sleep(_API_CALL_DELAY_SECONDS)

        return all_tracks

    def get_albums_batch(self, album_ids: List[str]) -> List[Any]:
        """Batch fetch multiple albums in a single API call.

        Uses Spotify's "Get Several Albums" endpoint which supports up to 20 albums
        per request, useful for enriching track metadata with full album details.

        Args:
            album_ids: List of Spotify album IDs (max 20 per call, will batch if more)

        Returns:
            List of album objects from the API
        """
        if not album_ids:
            return []

        all_albums = []
        batch_size = 20  # Spotify limit for albums endpoint

        for i in range(0, len(album_ids), batch_size):
            batch = album_ids[i : i + batch_size]
            result = self.public_client.albums(batch)
            if result and "albums" in result:
                all_albums.extend([a for a in result["albums"] if a is not None])
            if i + batch_size < len(album_ids):
                time.sleep(_API_CALL_DELAY_SECONDS)

        return all_albums

    def get_artists_batch(self, artist_ids: List[str]) -> List[Any]:
        """Batch fetch multiple artists in a single API call.

        Uses Spotify's "Get Several Artists" endpoint which supports up to 50 artists
        per request, useful for fetching artist genres.

        Args:
            artist_ids: List of Spotify artist IDs (max 50 per call, will batch if more)

        Returns:
            List of artist objects from the API
        """
        if not artist_ids:
            return []

        all_artists = []
        batch_size = 50  # Spotify limit for artists endpoint

        for i in range(0, len(artist_ids), batch_size):
            batch = artist_ids[i : i + batch_size]
            result = self.public_client.artists(batch)
            if result and "artists" in result:
                all_artists.extend([a for a in result["artists"] if a is not None])
            if i + batch_size < len(artist_ids):
                time.sleep(_API_CALL_DELAY_SECONDS)

        return all_artists

    def enrich_tracks_metadata(
        self, tracks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Enrich track metadata with full album and artist details.

        Efficiently batch-fetches album and artist data to add genres, publisher,
        copyright, and other metadata that isn't included in playlist/album track
        listings.

        For a playlist with 100 tracks from ~80 artists and ~60 albums, this uses
        ~5 API calls instead of 200 (2 per track for artist+album).

        Args:
            tracks: List of track dicts from playlist/album fetch

        Returns:
            List of tracks with enriched metadata in '_enriched' key
        """
        if not tracks:
            return tracks

        # Collect unique album and artist IDs
        album_ids = set()
        artist_ids = set()

        for track in tracks:
            album = track.get("album", {})
            if album.get("id"):
                album_ids.add(album["id"])
            artists = track.get("artists", [])
            if artists and artists[0].get("id"):
                artist_ids.add(artists[0]["id"])

        # Batch fetch albums and artists
        albums_data = self.get_albums_batch(list(album_ids))
        artists_data = self.get_artists_batch(list(artist_ids))

        # Build lookup dicts
        albums_by_id = {a["id"]: a for a in albums_data}
        artists_by_id = {a["id"]: a for a in artists_data}

        # Enrich each track
        for track in tracks:
            album_id = track.get("album", {}).get("id")
            artist_id = (
                track.get("artists", [{}])[0].get("id")
                if track.get("artists")
                else None
            )

            enriched = {}
            if album_id and album_id in albums_by_id:
                full_album = albums_by_id[album_id]
                enriched["album_genres"] = full_album.get("genres", [])
                enriched["publisher"] = full_album.get("label", "")
                enriched["copyrights"] = full_album.get("copyrights", [])
                enriched["disc_count"] = (
                    int(full_album["tracks"]["items"][-1]["disc_number"])
                    if full_album.get("tracks", {}).get("items")
                    else 1
                )

            if artist_id and artist_id in artists_by_id:
                full_artist = artists_by_id[artist_id]
                enriched["artist_genres"] = full_artist.get("genres", [])

            track["_enriched"] = enriched

        return tracks

    def create_album(self, album_id: str, artist: Artist) -> Album:
        album_details = self.get_album(album_id)
        album = Album.objects.create(
            spotify_gid=album_details["id"],
            artist=artist,
            spotify_uri=album_details["uri"],
            total_tracks=album_details["total_tracks"],
            name=album_details["name"],
        )
        return album

    def get_album(self, album_id: str) -> Any:
        """Get album details. Uses public client since album data is public."""
        album = self.public_client.album(album_id)
        album_track_iterator = self.public_client.next(album["tracks"])

        while album_track_iterator is not None:
            album["tracks"]["items"].extend(album_track_iterator["items"])
            # Rate limiting: delay between paginated API calls
            time.sleep(_API_CALL_DELAY_SECONDS)
            album_track_iterator = self.public_client.next(album_track_iterator)
        return album

    def get_playlist(self, playlist_id: str) -> Any:
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
        """Get download queues for multiple URLs with optimized batching.

        This method batches individual track requests to reduce API calls.
        For example, 100 individual track URLs become 2 API calls (50 tracks each)
        instead of 100 individual calls.

        Args:
            urls: List of Spotify URLs/URIs (tracks, albums, playlists)

        Returns:
            Tuple of (list of download queues, dict mapping URL to metadata)
        """
        download_queues: List[List[Dict[str, Any]]] = []
        metadata_map: Dict[str, Dict[str, Any]] = {}

        # Separate URLs by type for batch processing
        track_urls: List[tuple[int, str, str]] = []  # (index, url, track_id)
        other_urls: List[tuple[int, str]] = []  # (index, url)

        for idx, url in enumerate(urls):
            match = re.search(r"(\w{22})", url)
            if match is None:
                continue

            uri = match.group(1)

            if "track" in url:
                track_urls.append((idx, url, uri))
            else:
                other_urls.append((idx, url))

        # Initialize result lists with correct size
        download_queues = [[] for _ in range(len(urls))]

        # Batch fetch all tracks at once
        if track_urls:
            track_ids = [t[2] for t in track_urls]
            tracks = self.get_tracks_batch(track_ids)

            # Map results back to their indices
            track_id_to_data = {t["id"]: t for t in tracks if t}
            for idx, url, track_id in track_urls:
                if track_id in track_id_to_data:
                    download_queues[idx] = [track_id_to_data[track_id]]
                    metadata_map[url] = {"type": "track", "id": track_id}

        # Process non-track URLs individually (albums/playlists already efficient)
        for idx, url in other_urls:
            try:
                result = self.get_download_queue(url, include_metadata=True)
                if isinstance(result, tuple):
                    download_queues[idx] = result[0]
                    metadata_map[url] = result[1]
                else:
                    download_queues[idx] = result
            except Exception:
                # Skip failed URLs
                pass

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
