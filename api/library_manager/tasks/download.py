"""Download tasks for the Spotify library manager."""

import asyncio
import time
from typing import Any, Optional

from django.db.models.functions import Now

from celery.exceptions import Retry as CeleryRetry
from celery_app import app as celery_app
from downloader.spotdl_wrapper import YouTubeRateLimitError
from downloader.spotipy_tasks import SpotifyRateLimitError
from downloader.utils import sanitize_and_strip_url
from lib.config_class import Config

from ..models import (
    ALBUM_GROUPS_TO_IGNORE,
    ALBUM_TYPES_TO_DOWNLOAD,
    Album,
    Artist,
    Song,
    TaskHistory,
)
from .core import (
    TaskCancelledException,
    check_and_update_progress,
    check_if_cancelled,
    check_spotify_rate_limit,
    check_task_cancellation,
    complete_task,
    create_task_history,
    logger,
    require_download_capability,
    spotdl_wrapper,
    update_task_progress,
)


@celery_app.task(
    bind=True, name="library_manager.tasks.download_missing_albums_for_artist"
)
def download_missing_albums_for_artist(
    self: Any, artist_id: int, delay: int = 0
) -> None:
    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements

    task_history = None
    try:
        time.sleep(delay)

        try:
            artist = Artist.objects.get(id=artist_id)
        except Artist.DoesNotExist:
            logger.warning(f"Artist with ID {artist_id} does not exist. Skipping task.")
            return

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=str(artist.id),
            entity_type="ARTIST",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for artist {artist.name}"
        )

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for artist {artist.name}")
            return

        missing_albums = Album.objects.filter(
            artist=artist,
            downloaded=False,
            wanted=True,
            album_type__in=ALBUM_TYPES_TO_DOWNLOAD,
        ).exclude(album_group__in=ALBUM_GROUPS_TO_IGNORE)
        logger.info(
            f"missing albums search for artist {artist.id} found {missing_albums.count()}"
        )

        if check_and_update_progress(
            task_history, 25.0, f"Found {missing_albums.count()} missing albums"
        ):
            return

        if missing_albums.count() > 0:
            # Split into Spotify and Deezer-only albums
            spotify_albums = []
            deezer_only_albums = []
            for album in missing_albums.iterator():
                if album.spotify_uri:
                    spotify_albums.append(album)
                else:
                    deezer_only_albums.append(album)

            # Spotify path: batch download via spotdl
            if spotify_albums:
                rate_limit_delay = check_spotify_rate_limit()
                if rate_limit_delay is not None:
                    logger.info(
                        f"Spotify rate limited for {rate_limit_delay}s, "
                        f"rescheduling artist {artist.name}"
                    )
                    raise self.retry(
                        exc=SpotifyRateLimitError(
                            f"Rate limited for {rate_limit_delay}s", rate_limit_delay
                        ),
                        countdown=rate_limit_delay,
                        max_retries=2,
                    )

                downloader_config = Config()
                downloader_config.urls = [a.spotify_uri for a in spotify_albums]

                logger.info(
                    f"Downloading {len(downloader_config.urls)} Spotify albums "
                    f"for artist {artist.name}"
                )

                if check_and_update_progress(
                    task_history,
                    50.0,
                    f"Downloading {len(downloader_config.urls)} Spotify albums",
                ):
                    return

                def progress_callback(progress_pct: float, message: str) -> None:
                    try:
                        check_if_cancelled(self.request.id)
                    except TaskCancelledException:
                        logger.info(
                            f"Download cancelled by user for artist {artist.name}"
                        )
                        raise
                    update_task_progress(task_history, progress_pct, message)

                try:
                    spotdl_wrapper.execute(
                        downloader_config, task_progress_callback=progress_callback
                    )
                except TaskCancelledException as e:
                    logger.info(f"Task cancelled during download: {e}")
                    if task_history:
                        task_history.status = "CANCELLED"
                        task_history.error_message = "Cancelled by user"
                        task_history.save()
                    return
                except YouTubeRateLimitError as rate_limit_error:
                    retry_after = rate_limit_error.retry_after_seconds
                    logger.warning(
                        f"YouTube rate limit hit for artist {artist.name}, "
                        f"rescheduling in {retry_after}s"
                    )
                    if task_history:
                        task_history.status = "PENDING"
                        task_history.add_log_message(
                            f"Rate limited by YouTube, rescheduling in {retry_after // 60} minutes"
                        )
                        task_history.save()
                    raise self.retry(
                        exc=rate_limit_error,
                        countdown=retry_after,
                        max_retries=3,
                    )

            # Deezer path: download each album individually via fallback providers
            if deezer_only_albums:
                logger.info(
                    f"Downloading {len(deezer_only_albums)} Deezer-only albums "
                    f"for artist {artist.name}"
                )
                update_task_progress(
                    task_history,
                    75.0,
                    f"Downloading {len(deezer_only_albums)} Deezer-only albums",
                )
                for deezer_album in deezer_only_albums:
                    try:
                        _download_deezer_album(deezer_album, task_history)
                    except Exception as e:
                        logger.error(
                            f"Failed to download Deezer album '{deezer_album.name}': {e}"
                        )
        else:
            logger.info(f"No missing albums for artist {artist.id}, skipping")
            if task_history:
                update_task_progress(
                    task_history, 100.0, "No missing albums to download"
                )

        if check_task_cancellation(task_history):
            return

        artist.last_downloaded_at = Now()
        artist.save()

        if task_history:
            complete_task(task_history, success=True)

    except (YouTubeRateLimitError, SpotifyRateLimitError, CeleryRetry):
        raise
    except Exception as e:
        logger.error(
            "Error in download_missing_albums_for_artist: %s", e, exc_info=True
        )
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(bind=True, name="library_manager.tasks.download_single_album")
def download_single_album(self: Any, album_id: int) -> None:
    """Download a single specific album by ID.

    Routes to spotdl (Spotify path) or fallback providers (Deezer path)
    based on whether the album has a Spotify URI.
    """
    task_history = None
    try:
        try:
            album = Album.objects.get(id=album_id)
        except Album.DoesNotExist:
            logger.warning(f"Album with ID {album_id} does not exist. Skipping task.")
            return

        is_deezer_only = not album.spotify_uri

        # Only check Spotify rate limit for Spotify-path albums
        if not is_deezer_only:
            rate_limit_delay = check_spotify_rate_limit()
            if rate_limit_delay is not None:
                logger.info(
                    f"Skipping album {album_id} download - rate limited, "
                    f"rescheduling in {rate_limit_delay}s"
                )
                raise self.retry(
                    exc=SpotifyRateLimitError(
                        f"Rate limited for {rate_limit_delay}s", rate_limit_delay
                    ),
                    countdown=rate_limit_delay,
                    max_retries=2,
                )

        # Use album DB ID as entity_id (works for both Spotify and Deezer albums)
        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=str(album.id),
            entity_type="ALBUM",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for album {album.name}"
        )

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for album {album.name}")
            return

        if not album.wanted:
            album.wanted = True
            album.save()

        if is_deezer_only:
            _download_deezer_album(album, task_history)
        else:
            if check_and_update_progress(
                task_history, 25.0, "Preparing download configuration"
            ):
                return

            downloader_config = Config()
            downloader_config.urls = [album.spotify_uri]

            if check_and_update_progress(
                task_history, 50.0, f"Downloading album {album.name}"
            ):
                return

            logger.info(
                f"Downloading album: {album.name} (spotify_uri: {album.spotify_uri})"
            )
            spotdl_wrapper.execute(downloader_config)

            album.downloaded = True
            album.save()

        if check_and_update_progress(task_history, 100.0, "Download completed"):
            return

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded album: {album.name}")

    except YouTubeRateLimitError as rate_limit_error:
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"YouTube rate limit hit for album {album_id}, rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by YouTube, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=3,
        )
    except SpotifyRateLimitError as rate_limit_error:
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"Spotify rate limit hit for album {album_id}, rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by Spotify, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=2,
        )
    except CeleryRetry:
        raise
    except Exception as e:
        error_msg = f"Error downloading album: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


def _download_deezer_album(album: Album, task_history: TaskHistory) -> None:
    """Download a Deezer-only album via YouTube/Tidal/Qobuz fallback providers.

    Fetches track listing from Deezer, creates Song records, and downloads
    each track using the FallbackDownloader pipeline.
    """
    from downloader.providers.base import SpotifyTrackMetadata
    from downloader.providers.fallback import FallbackDownloader

    from src.providers.deezer import DeezerMetadataProvider

    from ..models import DownloadProvider as DownloadProviderEnum

    if not album.deezer_id:
        raise ValueError(f"Album {album.name} has no deezer_id and no spotify_uri")

    update_task_progress(
        task_history, 10.0, f"Fetching track listing from Deezer for {album.name}"
    )

    provider = DeezerMetadataProvider()
    deezer_tracks = provider.get_album_tracks(album.deezer_id)

    if not deezer_tracks:
        raise ValueError(f"No tracks found on Deezer for album {album.deezer_id}")

    update_task_progress(
        task_history,
        20.0,
        f"Found {len(deezer_tracks)} tracks, creating song records",
    )

    # Get album artist name for metadata
    album_artist_name = album.artist.name  # type: ignore[attr-defined]

    # Get or create the album's cover URL from Deezer
    album_data = provider.get_album(album.deezer_id)
    cover_url = album_data.image_url if album_data else None

    # Create Song records and prepare download list
    songs_to_download: list[tuple[Song, SpotifyTrackMetadata]] = []

    for track in deezer_tracks:
        if not track.deezer_id:
            continue

        song, created = Song.objects.get_or_create(
            deezer_id=track.deezer_id,
            defaults={
                "name": track.name,
                "primary_artist": album.artist,
                "album": album,
                "isrc": track.isrc,
            },
        )

        if not created and song.downloaded:
            logger.debug(f"Song '{track.name}' already downloaded, skipping")
            continue

        # Build metadata for fallback providers
        metadata = SpotifyTrackMetadata(
            spotify_id="",
            title=track.name,
            artist=track.artist_name or album_artist_name,
            album=album.name,
            album_artist=album_artist_name,
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            track_number=track.track_number,
            total_tracks=len(deezer_tracks),
            disc_number=track.disc_number,
            cover_url=cover_url,
        )
        songs_to_download.append((song, metadata))

    if not songs_to_download:
        logger.info(f"All tracks for album '{album.name}' already downloaded")
        album.downloaded = True
        album.save()
        return

    update_task_progress(
        task_history,
        30.0,
        f"Downloading {len(songs_to_download)} tracks via fallback providers",
    )

    # Map provider name to DownloadProvider enum
    provider_enum_map = {
        "youtube": DownloadProviderEnum.YOUTUBE,
        "tidal": DownloadProviderEnum.TIDAL,
        "qobuz": DownloadProviderEnum.QOBUZ,
    }

    downloader = FallbackDownloader(
        provider_order=["youtube", "tidal", "qobuz"],
    )

    downloaded_count = 0
    failed_count = 0

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for i, (song, metadata) in enumerate(songs_to_download):
            progress = 30.0 + (60.0 * (i / len(songs_to_download)))
            update_task_progress(
                task_history,
                progress,
                f"Downloading {i + 1}/{len(songs_to_download)}: {song.name}",
            )

            result = loop.run_until_complete(downloader.download_track(metadata))

            if result.success and result.file_path:
                dl_provider = provider_enum_map.get(
                    result.provider_used or "", DownloadProviderEnum.UNKNOWN
                )
                song.mark_downloaded(
                    bitrate=256,
                    file_path=str(result.file_path),
                    provider=dl_provider,
                )
                downloaded_count += 1
                logger.info(f"Downloaded '{song.name}' via {result.provider_used}")
            else:
                failed_count += 1
                song.increment_failed_count()
                song.save()
                logger.warning(
                    f"Failed to download '{song.name}': {result.error_message}"
                )

        loop.run_until_complete(downloader.close())
        loop.close()
    except Exception:
        try:
            loop.run_until_complete(downloader.close())
            loop.close()
        except Exception:
            pass
        raise

    # Mark album downloaded if all tracks succeeded
    if failed_count == 0:
        album.downloaded = True
        album.save()

    update_task_progress(
        task_history,
        95.0,
        f"Completed: {downloaded_count} downloaded, {failed_count} failed",
    )


@celery_app.task(bind=True, name="library_manager.tasks.download_playlist")
def download_playlist(
    self: Any,
    playlist_url: str,
    tracked: bool = True,
    force_playlist_resync: bool = False,
    task_id: Optional[str] = None,
) -> None:
    # Check rate limit FIRST, before creating task history or doing any work.
    rate_limit_delay = check_spotify_rate_limit()
    if rate_limit_delay is not None:
        logger.info(
            f"Skipping playlist {playlist_url} download - rate limited, "
            f"rescheduling in {rate_limit_delay}s"
        )
        raise self.retry(
            exc=SpotifyRateLimitError(
                f"Rate limited for {rate_limit_delay}s", rate_limit_delay
            ),
            countdown=rate_limit_delay,
            max_retries=2,
        )

    task_history = None
    try:
        # Use the Celery task ID if no task_id is provided
        if task_id is None:
            task_id = self.request.id

        playlist_url = sanitize_and_strip_url(playlist_url)

        # Extract playlist ID from URL for task history
        playlist_id = (
            playlist_url.split(":")[-1] if ":" in playlist_url else playlist_url
        )

        # Create task history record (always create, even without Celery context)
        task_history = create_task_history(
            task_id=task_id,
            task_type="DOWNLOAD",
            entity_id=playlist_id,
            entity_type="PLAYLIST",
            task_name="download_playlist",
        )

        # Check authentication before proceeding
        require_download_capability(task_history)

        update_task_progress(
            task_history, 0.0, f"Starting playlist download: {playlist_url}"
        )
        # Mark as running
        task_history.status = "RUNNING"
        task_history.save()

        # Check for cancellation before proceeding
        if check_task_cancellation(task_history):
            logger.info(f"Playlist download cancelled: {playlist_url}")
            return

        downloader_config = Config(
            urls=[playlist_url],
            track_artists=tracked,
            force_playlist_resync=force_playlist_resync,
        )

        # Check for cancellation before download
        if check_and_update_progress(task_history, 50.0, "Downloading playlist tracks"):
            logger.info(f"Playlist download cancelled before download: {playlist_url}")
            return

        # Create callback to update task progress during playlist download
        def playlist_progress_callback(progress_pct: float, message: str) -> None:
            # Check for cancellation during download (checks both TaskResult and TaskHistory)
            try:
                check_if_cancelled(task_id)
            except TaskCancelledException:
                logger.info(f"Playlist download cancelled by user: {playlist_url}")
                raise
            update_task_progress(
                task_history, 50.0 + (progress_pct / 2), message
            )  # Scale to 50-100%

        try:
            spotdl_wrapper.execute(
                downloader_config, task_progress_callback=playlist_progress_callback
            )
        except TaskCancelledException as e:
            logger.info(f"Playlist download cancelled: {e}")
            if task_history:
                task_history.status = "CANCELLED"
                task_history.error_message = "Cancelled by user"
                task_history.save()
            return
        except YouTubeRateLimitError as rate_limit_error:
            # YouTube rate limit - reschedule task for later
            retry_after = rate_limit_error.retry_after_seconds
            logger.warning(
                f"YouTube rate limit hit for playlist {playlist_url}, "
                f"rescheduling in {retry_after}s"
            )
            if task_history:
                task_history.status = "PENDING"
                task_history.add_log_message(
                    f"Rate limited by YouTube, rescheduling in {retry_after // 60} minutes"
                )
                task_history.save()
            raise self.retry(
                exc=rate_limit_error,
                countdown=retry_after,
                max_retries=3,
            )

        # Final cancellation check
        if check_task_cancellation(task_history):
            logger.info(
                f"Playlist download cancelled before completion: {playlist_url}"
            )
            return

        complete_task(task_history, success=True)

    except (YouTubeRateLimitError, SpotifyRateLimitError, CeleryRetry):
        # Rate limit or retry - task will be rescheduled, don't mark as failed
        raise
    except Exception as e:
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True, name="library_manager.tasks.download_extra_album_types_for_artist"
)
def download_extra_album_types_for_artist(
    self: Any, artist_id: int, task_id: Optional[str] = None
) -> None:
    # Check rate limit FIRST, before creating task history or doing any work.
    rate_limit_delay = check_spotify_rate_limit()
    if rate_limit_delay is not None:
        logger.info(
            f"Skipping artist {artist_id} extra albums - rate limited, "
            f"rescheduling in {rate_limit_delay}s"
        )
        raise self.retry(
            exc=SpotifyRateLimitError(
                f"Rate limited for {rate_limit_delay}s", rate_limit_delay
            ),
            countdown=rate_limit_delay,
            max_retries=2,
        )

    # Check authentication before proceeding with any DB queries
    require_download_capability()

    # Check if artist exists before proceeding
    try:
        artist = Artist.objects.get(id=artist_id)
    except Artist.DoesNotExist:
        logger.warning(f"Artist with ID {artist_id} does not exist. Skipping task.")
        return

    missing_albums = Album.objects.filter(
        artist=artist,
        downloaded=False,
        wanted=True,
        album_group__in=ALBUM_GROUPS_TO_IGNORE,
    )
    logger.info(
        f"extra album missing albums search for artist {artist.gid} found {missing_albums.count()}"
    )
    downloader_config = Config()
    downloader_config.urls = []  # This must be reset or it will persist between runs
    if missing_albums.count() > 0:
        for missing_album in missing_albums.iterator():
            downloader_config.urls.append(missing_album.spotify_uri)

        logger.info(
            f"extra album missing albums search for artist {artist.gid} kicking off {len(downloader_config.urls)}"
        )

        # Create progress callback if task history is available
        task_progress_callback = None
        if task_id:
            task_history = TaskHistory.objects.filter(task_id=task_id).first()
            if task_history:
                # Capture task_history in closure to avoid cell-var-from-loop
                captured_task_history = task_history

                def update_task_progress_callback(
                    progress_pct: float, message: str
                ) -> None:
                    captured_task_history.update_progress(progress_pct)

                task_progress_callback = update_task_progress_callback

        try:
            spotdl_wrapper.execute(downloader_config, task_progress_callback)
        except YouTubeRateLimitError as rate_limit_error:
            # YouTube rate limit - reschedule task for later
            retry_after = rate_limit_error.retry_after_seconds
            logger.warning(
                f"YouTube rate limit hit for artist {artist_id} extra albums, "
                f"rescheduling in {retry_after}s"
            )
            raise self.retry(
                exc=rate_limit_error,
                countdown=retry_after,
                max_retries=3,
            )
    else:
        logger.info(
            f"extra album missing albums search for artist {artist.gid} is skipping since there are none missing"
        )
    # Update last_downloaded_at timestamp (extra albums download completed)
    artist.last_downloaded_at = Now()
    artist.save()


@celery_app.task(bind=True, name="library_manager.tasks.download_album_by_spotify_id")
def download_album_by_spotify_id(self: Any, spotify_album_id: str) -> None:
    """
    Download an album by its Spotify ID (not database ID).

    This task fetches album metadata from Spotify if needed, creates/gets the album
    in the database, and then queues the actual download.
    """
    # Check rate limit FIRST, before creating task history or doing any work.
    rate_limit_delay = check_spotify_rate_limit()
    if rate_limit_delay is not None:
        logger.info(
            f"Skipping album {spotify_album_id} download - rate limited, "
            f"rescheduling in {rate_limit_delay}s"
        )
        raise self.retry(
            exc=SpotifyRateLimitError(
                f"Rate limited for {rate_limit_delay}s", rate_limit_delay
            ),
            countdown=rate_limit_delay,
            max_retries=2,
        )

    task_history = None
    try:
        from downloader.downloader import Downloader

        from library_manager.validators import (
            extract_spotify_id_from_uri,
            normalize_spotify_gid,
        )

        # Create task history record
        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=spotify_album_id,
            entity_type="ALBUM",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for album {spotify_album_id}"
        )

        # Check authentication before proceeding
        require_download_capability(task_history)

        # Check for cancellation before proceeding
        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for album {spotify_album_id}")
            return

        # Check if album already exists in DB
        try:
            album = Album.objects.get(spotify_gid=spotify_album_id)
            logger.info(f"Album {album.name} already exists in database")
        except Album.DoesNotExist:
            # Fetch from Spotify
            update_task_progress(
                task_history, 25.0, "Fetching album metadata from Spotify"
            )

            # Get SpotifyClient from spotdl_wrapper
            spotify_client = spotdl_wrapper.spotipy_client
            downloader = Downloader(spotify_client)

            album_data = downloader.get_album(spotify_album_id)
            if not album_data:
                raise ValueError(
                    f"Album {spotify_album_id} not found on Spotify"
                ) from None

            # Get or create the artist
            artist_data = album_data.get("artists", [{}])[0]
            if not artist_data:
                raise ValueError(
                    f"Album {spotify_album_id} has no artist data"
                ) from None

            raw_artist_id = artist_data.get("id") or artist_data.get("uri")
            if not raw_artist_id:
                raise ValueError(
                    "Album artist missing both 'id' and 'uri' fields"
                ) from None

            artist_gid = extract_spotify_id_from_uri(raw_artist_id)
            if not artist_gid:
                raise ValueError(f"Invalid artist ID/URI: {raw_artist_id}") from None

            artist_gid = normalize_spotify_gid(artist_gid)

            artist, _ = Artist.objects.get_or_create(
                gid=artist_gid,
                defaults={"name": artist_data.get("name", "Unknown Artist")},
            )

            # Create the album
            album = Album.objects.create(
                spotify_gid=album_data["id"],
                artist=artist,
                spotify_uri=album_data.get("uri", f"spotify:album:{album_data['id']}"),
                total_tracks=album_data.get("total_tracks", 0),
                name=album_data.get("name", "Unknown Album"),
                album_type=album_data.get("album_type"),
                wanted=True,
            )
            logger.info(f"Created album: {album.name}")

        # Mark album as wanted if not already
        if not album.wanted:
            album.wanted = True
            album.save()

        update_task_progress(task_history, 50.0, f"Downloading album: {album.name}")

        # Now download using the standard single album task logic inline
        # (avoiding task chaining complexity)
        downloader_config = Config()
        downloader_config.urls = [album.spotify_uri]

        spotdl_wrapper.execute(downloader_config)

        # Mark album as downloaded
        album.downloaded = True
        album.save()

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded album: {album.name}")

    except YouTubeRateLimitError as rate_limit_error:
        # YouTube rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"YouTube rate limit hit for album {spotify_album_id}, "
            f"rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by YouTube, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=3,
        )
    except SpotifyRateLimitError as rate_limit_error:
        # Spotify rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"Spotify rate limit hit for album {spotify_album_id}, "
            f"rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by Spotify, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=2,
        )
    except CeleryRetry:
        # Celery Retry exception - task will be rescheduled, don't mark as failed
        raise
    except Exception as e:
        error_msg = f"Error downloading album: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


@celery_app.task(bind=True, name="library_manager.tasks.download_single_track")
def download_single_track(self: Any, track_id: str) -> None:
    """
    Download a single track by its Spotify ID.

    Downloads only the requested track, not the entire album.
    """
    # Check rate limit FIRST, before creating task history or doing any work.
    rate_limit_delay = check_spotify_rate_limit()
    if rate_limit_delay is not None:
        logger.info(
            f"Skipping track {track_id} download - rate limited, "
            f"rescheduling in {rate_limit_delay}s"
        )
        raise self.retry(
            exc=SpotifyRateLimitError(
                f"Rate limited for {rate_limit_delay}s", rate_limit_delay
            ),
            countdown=rate_limit_delay,
            max_retries=2,
        )

    task_history = None
    try:
        # Create task history record
        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=track_id,
            entity_type="TRACK",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for track {track_id}"
        )

        # Check authentication before proceeding
        require_download_capability(task_history)

        # Check for cancellation before proceeding
        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for track {track_id}")
            return

        # Build the track URI
        track_uri = f"spotify:track:{track_id}"

        update_task_progress(task_history, 25.0, f"Downloading track: {track_id}")

        # Download just this single track using spotdl
        downloader_config = Config()
        downloader_config.urls = [track_uri]

        # Execute download with progress callback
        def task_progress_callback(progress_pct: float, message: str = "") -> None:
            # Scale progress: 25% (start) to 95% (before completion)
            scaled_progress = 25.0 + (progress_pct * 0.70)
            update_task_progress(task_history, scaled_progress, message)

        spotdl_wrapper.execute(downloader_config, task_progress_callback)

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded track: {track_id}")

    except YouTubeRateLimitError as rate_limit_error:
        # YouTube rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"YouTube rate limit hit for track {track_id}, rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by YouTube, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=3,
        )
    except SpotifyRateLimitError as rate_limit_error:
        # Spotify rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"Spotify rate limit hit for track {track_id}, rescheduling in {retry_after}s"
        )
        if task_history:
            task_history.status = "PENDING"
            task_history.add_log_message(
                f"Rate limited by Spotify, rescheduling in {retry_after // 60} minutes"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=2,
        )
    except CeleryRetry:
        # Celery Retry exception - task will be rescheduled, don't mark as failed
        raise
    except Exception as e:
        error_msg = f"Error downloading track: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise
