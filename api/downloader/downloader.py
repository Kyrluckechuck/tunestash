import re
from typing import Any, Dict, List, Optional

from library_manager.models import Album, Artist


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
    ):
        """Initialize Downloader with Spotipy client(s).

        Args:
            spotipy_client: Primary client (OAuth preferred) for playlist operations.
                           Also used as fallback if public_client is None.
            public_client: Optional client using Client Credentials for public
                          metadata operations. If None, spotipy_client is used for all.
        """
        self.spotipy_client = spotipy_client
        self.public_client = public_client if public_client else spotipy_client

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

        return all_tracks

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
            album_track_iterator = self.public_client.next(album_track_iterator)
        return album

    def get_playlist(self, playlist_id: str) -> Any:
        """Get playlist with all tracks.

        Tries public client first (works for public playlists, saves OAuth quota),
        falls back to OAuth client for private playlists. This allows users who
        haven't authenticated to still sync public playlists.
        """
        playlist = None
        used_client = None

        # Try public client first (works for public playlists)
        try:
            playlist = self.public_client.playlist(playlist_id)
            used_client = self.public_client
        except Exception:
            pass

        # Fall back to OAuth client (needed for private playlists)
        if playlist is None and self.public_client != self.spotipy_client:
            playlist = self.spotipy_client.playlist(playlist_id)
            used_client = self.spotipy_client

        if playlist is None:
            raise Exception(f"Failed to fetch playlist {playlist_id}")

        # Paginate through all tracks using the same client that succeeded
        playlist_iterator = used_client.next(playlist["tracks"])
        while playlist_iterator is not None:
            playlist["tracks"]["items"].extend(playlist_iterator["items"])
            playlist_iterator = used_client.next(playlist_iterator)

        return playlist

    def get_playlist_snapshot_id(self, playlist_id: str) -> str | None:
        """Get only the snapshot_id of a playlist (lightweight API call).

        This allows checking if a playlist has changed without fetching all tracks.
        Uses the fields parameter to minimize API response size and reduce rate
        limiting risk.

        Tries public client first (public playlists), falls back to OAuth client
        for private playlists. This reduces OAuth rate limit usage.

        Args:
            playlist_id: The Spotify playlist ID (22-character base62 string)

        Returns:
            The playlist's snapshot_id string, or None if request fails
        """
        # Try public client first (works for public playlists, saves OAuth quota)
        try:
            result = self.public_client.playlist(playlist_id, fields="snapshot_id")
            return result.get("snapshot_id")
        except Exception:
            pass

        # Fall back to OAuth client (needed for private playlists)
        if self.public_client != self.spotipy_client:
            try:
                result = self.spotipy_client.playlist(playlist_id, fields="snapshot_id")
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

    def get_song_core_info(self, metadata: Dict[str, Any]) -> Dict[str, str]:
        from library_manager.validators import extract_spotify_id_from_uri

        # Extract base62 Spotify ID from URI/URL (avoids hex encoding)
        song_id = extract_spotify_id_from_uri(metadata["id"])
        if not song_id:
            raise ValueError(
                f"Invalid Spotify track ID format: {metadata['id']}. "
                f"Expected Spotify URI, URL, or base62 ID."
            )

        return {
            "song_gid": song_id,
            "song_name": metadata["name"],
        }
