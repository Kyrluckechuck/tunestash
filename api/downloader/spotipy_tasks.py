from typing import Optional

from django.conf import settings

import spotipy

# from huey.api import Task  # Removed for Celery migration
from spotipy.oauth2 import SpotifyClientCredentials

from library_manager.models import Artist

from .downloader import Downloader
from .spotify_auth_helper import get_spotify_oauth_credentials


class PublicSpotifyClient:
    """Spotify client using Client Credentials flow (app-level auth).

    This client uses separate rate limit buckets from OAuth clients, making it
    ideal for public metadata operations like fetching track info, album details,
    and artist data. Does NOT support private playlist access.

    Rate limits are per-app rather than per-user, providing better throughput
    for bulk operations that don't require user authorization.
    """

    _instance: Optional["PublicSpotifyClient"] = None

    def __new__(cls) -> "PublicSpotifyClient":
        """Singleton pattern to reuse the same client instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        client_credentials_manager = SpotifyClientCredentials(
            client_id=getattr(settings, "SPOTIPY_CLIENT_ID", ""),
            client_secret=getattr(settings, "SPOTIPY_CLIENT_SECRET", ""),
        )
        self.sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing or token refresh)."""
        cls._instance = None


class OAuthSpotifyClient:
    """Spotify client using OAuth flow (user-level auth).

    This client supports private playlist access and user-specific operations.
    Falls back to Client Credentials if no OAuth token is available.

    Use this client ONLY for operations that require user authorization:
    - Private playlist access
    - User profile operations
    - Library modifications
    """

    _instance: Optional["OAuthSpotifyClient"] = None

    def __new__(cls) -> "OAuthSpotifyClient":
        """Singleton pattern to reuse the same client instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        oauth_creds = get_spotify_oauth_credentials()

        if oauth_creds:
            self.sp = spotipy.Spotify(auth=oauth_creds["access_token"])
            self.is_oauth = True
        else:
            # Fall back to client credentials (public access only)
            client_credentials_manager = SpotifyClientCredentials(
                client_id=getattr(settings, "SPOTIPY_CLIENT_ID", ""),
                client_secret=getattr(settings, "SPOTIPY_CLIENT_SECRET", ""),
            )
            self.sp = spotipy.Spotify(
                client_credentials_manager=client_credentials_manager
            )
            self.is_oauth = False

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for token refresh)."""
        cls._instance = None

    def refresh_token(self) -> bool:
        """Refresh OAuth token and reinitialize the client.

        Returns:
            True if refresh successful, False otherwise.
        """
        oauth_creds = get_spotify_oauth_credentials()
        if oauth_creds:
            self.sp = spotipy.Spotify(auth=oauth_creds["access_token"])
            self.is_oauth = True
            return True
        return False


# Backwards compatibility alias
class SpotifyClient(OAuthSpotifyClient):
    """Legacy alias for OAuthSpotifyClient. Prefer using OAuthSpotifyClient directly."""

    pass


def track_artists_in_playlist(playlist_url: str, task_id: Optional[str] = None) -> None:
    """Mark all primary artists in a playlist as tracked."""
    # Use OAuth client for playlist access (may be private)
    oauth_client = OAuthSpotifyClient()
    # Use public client for any metadata operations
    public_client = PublicSpotifyClient()
    downloader = Downloader(oauth_client.sp, public_client=public_client.sp)
    playlist = downloader.get_playlist(playlist_url)
    # pp(playlist)
    artists_to_track = []
    for track in playlist["tracks"]["items"]:
        from library_manager.validators import is_local_track

        # Skip local files - they're user-uploaded and have no Spotify metadata
        if is_local_track(track["track"]):
            print(
                f"Skipping local file '{track['track']['name']}' - cannot track artists from local files"
            )
            continue
        if len(track["track"]["artists"]) == 0:
            print(
                f"Skipping track {track['track']['name']}('{track['track']['uri']}') due to lack of artists"
            )
            print(track["track"])
            continue
        primary_artist = track["track"]["artists"][0]
        if primary_artist["id"] is None:
            print(
                f"Skipping track {track['track']['name']}('{track['track']['uri']}') due to being placeholder artist"
            )
            print(primary_artist)
            continue
        from library_manager.validators import extract_spotify_id_from_uri

        # Extract base62 Spotify ID from URI/URL (avoids hex encoding)
        primary_artist_gid = extract_spotify_id_from_uri(primary_artist["id"])
        if not primary_artist_gid:
            print(f"Skipping artist with invalid ID format: {primary_artist['id']}")
            continue

        primary_artist_info = {
            "name": primary_artist["name"],
            "gid": primary_artist_gid,
            "tracked": True,
        }
        if primary_artist_info not in artists_to_track:
            artists_to_track.append(primary_artist_info)

    for artist_info in artists_to_track:
        artist_gid = artist_info["gid"]
        # Get or create artist
        try:
            artist = Artist.objects.get(gid=artist_gid)
            # Update existing artist
            artist.name = artist_info["name"]
            artist.tracked = artist_info["tracked"]
            artist.save()
        except Artist.DoesNotExist:
            Artist.objects.create(**artist_info)

    print(f"ensured {len(artists_to_track)} artists were tracked")
