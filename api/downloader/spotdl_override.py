import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from downloader.spotify_auth_helper import get_spotify_oauth_credentials
from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptionalOptions, DownloaderOptions
from spotdl.types.song import Song
from spotdl.utils.spotify import SpotifyClient

logger = logging.getLogger(__name__)

# Maximum time (in seconds) to wait for a single song download
# If exceeded, assume we're rate-limited and fail fast to release resources
DOWNLOAD_TIMEOUT_SECONDS = 300  # 5 minutes per song

# Timeout multiplier for batch downloads (per song in batch)
# Batches get more time since multiple songs download in parallel
BATCH_TIMEOUT_PER_SONG_SECONDS = 180  # 3 minutes per song in batch


class DownloadTimeoutError(Exception):
    """Raised when a song download takes too long, likely due to rate limiting."""

    pass


def song_from_track_data(track: Dict[str, Any]) -> Song:
    """
    Create a SpotDL Song object from Spotify track data without additional API calls.

    This avoids the 3 API calls that Song.from_url() makes (track, artist, album)
    by using the track data we already have from playlist/album fetches.

    If the track has been enriched via Downloader.enrich_tracks_metadata(), the
    '_enriched' key contains additional data (genres, publisher, copyright, disc_count).

    Args:
        track: Spotify track dict from playlist/album fetch, optionally with '_enriched'

    Returns:
        SpotDL Song object ready for download
    """
    album = track.get("album", {})
    release_date = album.get("release_date", "1970-01-01")
    enriched = track.get("_enriched", {})

    # Get the best quality cover image
    cover_url = None
    if album.get("images"):
        images = album["images"]
        if images:
            cover_url = max(
                images,
                key=lambda i: i.get("width", 0) * i.get("height", 0),
            ).get("url")

    # Combine album + artist genres (same as Song.from_url does)
    genres = enriched.get("album_genres", []) + enriched.get("artist_genres", [])

    # Get copyright text from enriched data
    copyright_text = None
    copyrights = enriched.get("copyrights", [])
    if copyrights:
        copyright_text = copyrights[0].get("text")

    return Song(
        name=track.get("name", ""),
        artists=[a["name"] for a in track.get("artists", [])],
        artist=track["artists"][0]["name"] if track.get("artists") else "",
        artist_id=track["artists"][0]["id"] if track.get("artists") else None,
        genres=genres,
        disc_number=track.get("disc_number", 1),
        disc_count=enriched.get("disc_count", 1),
        album_name=album.get("name", ""),
        album_artist=album["artists"][0]["name"] if album.get("artists") else "",
        album_id=album.get("id", ""),
        album_type=album.get("album_type"),
        duration=int(track.get("duration_ms", 0) / 1000),
        year=int(release_date[:4]) if release_date else 1970,
        date=release_date or "1970-01-01",
        track_number=track.get("track_number", 1),
        tracks_count=album.get("total_tracks", 1),
        song_id=track.get("id", ""),
        explicit=track.get("explicit", False),
        publisher=enriched.get("publisher", ""),
        url=track.get("external_urls", {}).get("spotify", ""),
        isrc=track.get("external_ids", {}).get("isrc"),
        cover_url=cover_url,
        copyright_text=copyright_text,
        popularity=track.get("popularity"),
    )


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

        # Release memory back to OS
        _malloc_trim()


def _malloc_trim() -> None:
    """
    Release memory back to the OS using malloc_trim().

    Python's allocator (pymalloc) doesn't normally return memory to the OS.
    On Linux with glibc, malloc_trim() forces this.

    Note: ies_clear, re.purge(), and gc.collect() were tested and found to
    release 0MB in production - malloc_trim does all the actual work.
    """
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except (OSError, AttributeError):
        pass  # Not on Linux/glibc


def download_multiple_songs(
    self: "Downloader", songs: List[Song]
) -> List[Tuple[Song, Optional[Path]]]:
    """
    Download multiple songs in a batch with timeout protection.

    This is more efficient than downloading songs one at a time because:
    - Single event loop creation for the entire batch
    - asyncio.gather runs downloads concurrently
    - Memory cleanup happens once per batch instead of per song

    If the batch download takes too long, raises DownloadTimeoutError.

    ### Arguments
    - songs: List of songs to download.

    ### Returns
    - List of tuples with (song, path) for each song (path is None if failed).

    ### Raises
    - DownloadTimeoutError: If batch download exceeds timeout
    """
    if not songs:
        return []

    # Calculate timeout based on batch size
    batch_timeout = max(
        DOWNLOAD_TIMEOUT_SECONDS,
        len(songs) * BATCH_TIMEOUT_PER_SONG_SECONDS,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_download_multiple_songs_sync, self, songs)
        try:
            results = future.result(timeout=batch_timeout)
            return results
        except FuturesTimeoutError:
            logger.error(
                f"Batch download timed out after {batch_timeout}s for "
                f"{len(songs)} songs - likely rate-limited by YouTube"
            )
            raise DownloadTimeoutError(
                f"Batch download of {len(songs)} songs timed out after {batch_timeout}s. "
                f"YouTube may be rate-limiting requests."
            )


def _download_multiple_songs_sync(
    downloader: "Downloader", songs: List[Song]
) -> List[Tuple[Song, Optional[Path]]]:
    """
    Helper function to download multiple songs synchronously in a separate thread.
    This avoids event loop conflicts when called from an async context.

    Uses asyncio.gather to download songs concurrently within a single event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    original_loop = downloader.loop
    downloader.loop = loop

    try:
        downloader.progress_handler.set_song_count(len(songs))

        # Create download tasks for all songs
        async def download_batch():
            tasks = [downloader.pool_download(song) for song in songs]
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = loop.run_until_complete(download_batch())

        # Process results - convert exceptions to (song, None) tuples
        processed_results = []
        for song, result in zip(songs, results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to download '{song.name}': {result}")
                processed_results.append((song, None))
            else:
                processed_results.append(result)

        return processed_results
    finally:
        downloader.loop = original_loop
        loop.close()

        _malloc_trim()
