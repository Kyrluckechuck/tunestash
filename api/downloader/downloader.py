import re
from typing import Any, Dict, List

from library_manager.models import Album, Artist


class Downloader:
    def __init__(self, spotipy_client):
        self.spotipy_client = spotipy_client

    def get_artist_albums(self, artist_gid: str) -> List[Album]:
        """Get all albums (including EPs and Singles) for this artist

        Args:
            artist_gid (str): The artist GID as supplied by Spotify

        Returns:
            list[str]: an array of urls to each album for the artist
        """
        artist = Artist.objects.get(gid=artist_gid)
        albums_to_create_or_update: List[Dict] = []
        # artist_gid is already a Spotify ID, just format as URI
        artist_uri = f"spotify:artist:{artist_gid}"

        album_iterator = self.spotipy_client.artist_albums(artist_uri, limit=50)

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

            album_iterator = self.spotipy_client.next(album_iterator)

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
        return self.spotipy_client.track(track_id)

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
        album = self.spotipy_client.album(album_id)
        album_track_iterator = self.spotipy_client.next(album["tracks"])

        while album_track_iterator is not None:
            album["tracks"]["items"].extend(album_track_iterator["items"])
            album_track_iterator = self.spotipy_client.next(album_track_iterator)
        return album

    def get_playlist(self, playlist_id: str) -> Any:
        playlist = self.spotipy_client.playlist(playlist_id)
        playlist_iterator = self.spotipy_client.next(playlist["tracks"])

        while playlist_iterator is not None:
            playlist["tracks"]["items"].extend(playlist_iterator["items"])
            playlist_iterator = self.spotipy_client.next(playlist_iterator)
        return playlist

    def get_playlist_snapshot_id(self, playlist_id: str) -> str | None:
        """Get only the snapshot_id of a playlist (lightweight API call).

        This allows checking if a playlist has changed without fetching all tracks.
        Uses the fields parameter to minimize API response size and reduce rate
        limiting risk.

        Args:
            playlist_id: The Spotify playlist ID (22-character base62 string)

        Returns:
            The playlist's snapshot_id string, or None if request fails
        """
        try:
            # Request only snapshot_id field for minimal API usage
            result = self.spotipy_client.playlist(playlist_id, fields="snapshot_id")
            return result.get("snapshot_id")
        except Exception:
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
            playlist = self.get_playlist(uri)
            raw_playlist = playlist["tracks"]["items"]
            metadata = {
                "type": "playlist",
                "id": uri,
                "snapshot_id": playlist.get("snapshot_id"),
            }
            for i in raw_playlist:
                i["track"]["added_at"] = i["added_at"]
            download_queue.extend([i["track"] for i in raw_playlist])
            if include_metadata:
                return download_queue, metadata
            return download_queue
        raise Exception("Not a valid Spotify URL")

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
