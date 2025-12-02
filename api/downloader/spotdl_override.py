import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Optional, Tuple, Union

from downloader.spotify_auth_helper import get_spotify_oauth_credentials
from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptionalOptions, DownloaderOptions
from spotdl.types.song import Song
from spotdl.utils.spotify import SpotifyClient

logger = logging.getLogger(__name__)

# Maximum time (in seconds) to wait for a single song download
# If exceeded, assume we're rate-limited and fail fast to release resources
DOWNLOAD_TIMEOUT_SECONDS = 300  # 5 minutes per song


class DownloadTimeoutError(Exception):
    """Raised when a song download takes too long, likely due to rate limiting."""

    pass


# Class SpotDl
# Monkeypatch The Spotdl class to only init SpotifyClient if it doesn't already exist
def __init__(
    self: "Downloader",
    client_id: str,
    client_secret: str,
    user_auth: bool = False,
    cache_path: Optional[str] = None,
    no_cache: bool = False,
    headless: bool = False,
    downloader_settings: Optional[
        Union[DownloaderOptionalOptions, DownloaderOptions]
    ] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """
    Initialize the Spotdl class

    ### Arguments
    - client_id: Spotify client id
    - client_secret: Spotify client secret
    - user_auth: If true, user will be prompted to authenticate
    - cache_path: Path to cache directory
    - no_cache: If true, no cache will be used
    - headless: If true, no browser will be opened
    - downloader_settings: Settings for the downloader
    - loop: Event loop to use
    """

    if downloader_settings is None:
        downloader_settings = {}

    # Initialize spotify client
    if SpotifyClient._instance is None:
        oauth_creds = get_spotify_oauth_credentials()

        # If OAuth token is available, pass it directly; otherwise use client credentials
        if oauth_creds:
            # For OAuth authentication, pass the token directly
            # This bypasses client credentials and uses the OAuth token
            SpotifyClient.init(
                client_id=client_id or "",
                client_secret=client_secret or "",
                user_auth=user_auth,
                cache_path=cache_path,
                no_cache=no_cache,
                headless=headless,
                auth_token=oauth_creds["access_token"],
            )
        else:
            # Standard client credentials authentication
            SpotifyClient.init(
                client_id=client_id,
                client_secret=client_secret,
                user_auth=user_auth,
                cache_path=cache_path,
                no_cache=no_cache,
                headless=headless,
            )

    # Initialize downloader
    self.downloader = Downloader(
        settings=downloader_settings,
        loop=loop,
    )


# Class Spotdl.download.downloader.Downloader
# Monkeypatch to handle asyncio event loops not correctly assigning
def download_song(self: "Downloader", song: Song) -> Tuple[Song, Optional[Path]]:
    """
    Download a single song with timeout protection.

    If a download takes longer than DOWNLOAD_TIMEOUT_SECONDS, it's assumed to be
    rate-limited by YouTube and raises DownloadTimeoutError. This allows the calling
    code to release resources (like download locks) and reschedule the task.

    ### Arguments
    - song: The song to download.

    ### Returns
    - tuple with the song and the path to the downloaded file if successful.

    ### Raises
    - DownloadTimeoutError: If download exceeds timeout (likely rate-limited)
    """
    # Always run the download in a separate thread with its own event loop.
    # This is required for Python 3.13+ compatibility where asyncio.gather()
    # fails if called before run_until_complete() starts the loop.
    # Using a thread pool also provides clean timeout handling.
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_download_song_sync, self, song)
        try:
            result = future.result(timeout=DOWNLOAD_TIMEOUT_SECONDS)
            return result
        except FuturesTimeoutError:
            logger.error(
                f"Download timed out after {DOWNLOAD_TIMEOUT_SECONDS}s for "
                f"'{song.name}' - likely rate-limited by YouTube"
            )
            raise DownloadTimeoutError(
                f"Download timed out for '{song.name}' after {DOWNLOAD_TIMEOUT_SECONDS}s. "
                f"YouTube may be rate-limiting requests."
            )


def _download_song_sync(
    downloader: "Downloader", song: Song
) -> Tuple[Song, Optional[Path]]:
    """
    Helper function to download a song synchronously in a separate thread.
    This avoids event loop conflicts when called from an async context.

    In Python 3.13+, asyncio.gather() requires a running event loop in the
    current thread. We create a fresh event loop for this thread and call
    pool_download directly within a running loop context.
    """
    # Create a fresh event loop for this thread (Python 3.13+ requirement)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Update downloader's loop reference so internal async code uses our loop
    original_loop = downloader.loop
    downloader.loop = loop

    try:
        downloader.progress_handler.set_song_count(1)

        # Call pool_download directly within a running event loop
        # This avoids the Python 3.13 issue where asyncio.gather() fails
        # because it's called before run_until_complete starts the loop
        result = loop.run_until_complete(downloader.pool_download(song))
        return result
    finally:
        # Restore original loop reference and clean up
        downloader.loop = original_loop
        loop.close()
