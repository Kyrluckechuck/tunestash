import logging
import time
from typing import Optional

import requests
import spotipy
from requests.adapters import HTTPAdapter
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials
from urllib3.util.retry import Retry

from library_manager.models import Artist

from .downloader import SpotifyPlaylistClient
from .spotify_auth_helper import get_spotify_oauth_credentials

logger = logging.getLogger(__name__)

# Global flag to enable/disable rate limiting (can be disabled for testing)
RATE_LIMITING_ENABLED = True

# Log API call stats every N calls
_API_CALL_LOG_INTERVAL = 50
_api_call_count = 0  # Thread-local would be better but this is single-worker

# Maximum time (in seconds) to wait for a Spotify rate limit retry
# If Spotify asks for longer, we fail fast and let the task reschedule
MAX_RATE_LIMIT_WAIT_SECONDS = 300  # 5 minutes


class SpotifyRateLimitError(Exception):
    """Raised when Spotify rate limit exceeds our maximum wait threshold."""

    def __init__(self, message: str, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LimitedRetry(Retry):
    """Custom retry class that fails fast on excessive rate limit waits.

    Spotify sometimes returns Retry-After headers of 6+ hours. Rather than
    blocking for that long (holding locks and memory), we fail fast after
    a configurable maximum wait time. This allows tasks to release resources
    and reschedule themselves.
    """

    def get_retry_after(self, response):
        """Override to cap the retry-after time."""
        retry_after = super().get_retry_after(response)
        if retry_after is not None and retry_after > MAX_RATE_LIMIT_WAIT_SECONDS:
            logger.warning(
                f"Spotify rate limit requests {retry_after}s wait, "
                f"exceeds max of {MAX_RATE_LIMIT_WAIT_SECONDS}s - failing fast"
            )
            # Record the rate limit in our global state
            try:
                from library_manager.models import SpotifyRateLimitState

                SpotifyRateLimitState.set_rate_limited(int(retry_after))
            except Exception as e:
                logger.warning(f"Failed to record rate limit state: {e}")

            raise SpotifyRateLimitError(
                f"Spotify rate limit ({retry_after}s) exceeds maximum wait "
                f"({MAX_RATE_LIMIT_WAIT_SECONDS}s)",
                retry_after_seconds=int(retry_after),
            )
        return retry_after


class RateLimitedHTTPAdapter(HTTPAdapter):
    """HTTP adapter that enforces global Spotify API rate limits.

    Before each request, checks the global rate limit state and waits if
    necessary. After each request, records the call for tracking.

    This ensures all Spotify API calls across all workers respect a shared
    rate limit, preventing the aggressive rate limiting that results in
    multi-hour bans.
    """

    def send(self, request, *args, **kwargs):
        """Send a request, respecting global rate limits."""
        if RATE_LIMITING_ENABLED and "api.spotify.com" in request.url:
            self._wait_for_rate_limit()

        response = super().send(request, *args, **kwargs)

        if RATE_LIMITING_ENABLED and "api.spotify.com" in request.url:
            self._record_call(response)

        return response

    def _wait_for_rate_limit(self) -> None:
        """Wait if we're approaching rate limits."""
        try:
            from library_manager.models import SpotifyRateLimitState

            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 0:
                # Cap the wait at 60 seconds - if longer, let task reschedule
                # The detailed reason is already logged by get_delay_seconds()
                if delay > 60:
                    raise SpotifyRateLimitError(
                        f"Internal throttle requires {delay:.1f}s wait",
                        retry_after_seconds=int(delay),
                    )
                logger.debug(f"Rate limit: waiting {delay:.2f}s before API call")
                time.sleep(delay)
        except SpotifyRateLimitError:
            raise
        except Exception as e:
            # If rate limit check fails, proceed anyway to avoid blocking
            logger.warning(f"Rate limit check failed, proceeding anyway: {e}")

    def _record_call(self, response) -> None:
        """Record that an API call was made."""
        global _api_call_count
        try:
            from library_manager.models import SpotifyRateLimitState

            # Record 429 responses for tracking
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "60")
                try:
                    retry_seconds = int(retry_after)
                except ValueError:
                    retry_seconds = 60
                SpotifyRateLimitState.set_rate_limited(retry_seconds)
                logger.warning(
                    f"[SPOTIFY API] 429 Rate Limited! Retry-After: {retry_seconds}s, "
                    f"URL: {response.request.url if response.request else 'unknown'}"
                )
            else:
                # Record successful call
                SpotifyRateLimitState.record_call()

                # Periodic logging of API call stats
                _api_call_count += 1
                if _api_call_count % _API_CALL_LOG_INTERVAL == 0:
                    status = SpotifyRateLimitState.get_status()
                    logger.info(
                        f"[SPOTIFY API] {_api_call_count} calls this session | "
                        f"burst: {status['burst_calls']}/{status['burst_max']} | "
                        f"sustained: {status['sustained_calls']}/{status['sustained_max']} | "
                        f"hourly: {status['hourly_calls']}/{status['hourly_max']} | "
                        f"pressure: {status['backoff_pressure']}"
                    )
        except Exception as e:
            # Don't fail the request if recording fails
            logger.warning(f"Failed to record API call: {e}")


def create_limited_session() -> requests.Session:
    """Create a requests session with rate-limit-aware retry configuration.

    Uses RateLimitedHTTPAdapter which:
    1. Enforces global rate limits before each request (shared across workers)
    2. Records each API call for tracking
    3. Fails fast if rate limited, allowing tasks to reschedule
    """
    session = requests.Session()

    # Configure retry with our custom LimitedRetry class
    retry = LimitedRetry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],
    )

    # Use our rate-limited adapter that enforces global limits
    adapter = RateLimitedHTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


class PublicSpotifyClient:
    """Spotify client using Client Credentials flow (app-level auth).

    This client uses separate rate limit buckets from OAuth clients, making it
    ideal for public metadata operations like fetching track info, album details,
    and artist data. Does NOT support private playlist access.

    Rate limits are per-app rather than per-user, providing better throughput
    for bulk operations that don't require user authorization.

    Uses a custom session with LimitedRetry to fail fast on excessive rate limits.
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

        from src.app_settings.registry import get_setting_with_default

        client_id = get_setting_with_default("spotipy_client_id", "") or ""
        client_secret = get_setting_with_default("spotipy_client_secret", "") or ""

        # Only initialize if credentials are available
        if not client_id or not client_secret:
            logger.warning(
                "SPOTIPY_CLIENT_ID or SPOTIPY_CLIENT_SECRET not configured - "
                "PublicSpotifyClient will not be functional"
            )
            self.sp = None
            return

        logger.info("[SPOTIFY INIT] Initializing PublicSpotifyClient...")
        client_credentials_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
            cache_handler=MemoryCacheHandler(),
        )
        # Use custom session with rate-limit-aware retry
        self.sp = spotipy.Spotify(
            client_credentials_manager=client_credentials_manager,
            requests_session=create_limited_session(),
        )
        logger.info("[SPOTIFY INIT] ✓ PublicSpotifyClient ready")

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

    Uses a custom session with LimitedRetry to fail fast on excessive rate limits.
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

        logger.info("[SPOTIFY INIT] Initializing OAuthSpotifyClient...")
        oauth_creds = get_spotify_oauth_credentials()

        if oauth_creds:
            logger.info("[SPOTIFY INIT] Using OAuth token for OAuthSpotifyClient")
            # Use custom session with rate-limit-aware retry
            self.sp = spotipy.Spotify(
                auth=oauth_creds["access_token"],
                requests_session=create_limited_session(),
            )
            self.is_oauth = True
        else:
            logger.info(
                "[SPOTIFY INIT] No OAuth token, falling back to client credentials"
            )
            # Fall back to client credentials (public access only)
            from src.app_settings.registry import get_setting_with_default

            client_credentials_manager = SpotifyClientCredentials(
                client_id=get_setting_with_default("spotipy_client_id", "") or "",
                client_secret=get_setting_with_default("spotipy_client_secret", "")
                or "",
                cache_handler=MemoryCacheHandler(),
            )
            self.sp = spotipy.Spotify(
                client_credentials_manager=client_credentials_manager,
                requests_session=create_limited_session(),
            )
            self.is_oauth = False
        logger.info("[SPOTIFY INIT] ✓ OAuthSpotifyClient ready")

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
            self.sp = spotipy.Spotify(
                auth=oauth_creds["access_token"],
                requests_session=create_limited_session(),
            )
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
    client = SpotifyPlaylistClient(oauth_client.sp, public_client=public_client.sp)
    playlist = client.get_playlist(playlist_url)
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
