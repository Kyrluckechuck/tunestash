"""Download tasks for the Tunestash."""

import asyncio
import time
import unicodedata
from typing import Any, Optional

from django.db.models.functions import Now

from celery.exceptions import Retry as CeleryRetry
from celery_app import app as celery_app
from downloader.spotipy_tasks import SpotifyRateLimitError
from downloader.utils import sanitize_and_strip_url

from ..models import (
    ALBUM_GROUPS_TO_IGNORE,
    ALBUM_TYPES_TO_DOWNLOAD,
    Album,
    Artist,
    Song,
    TaskHistory,
)
from .core import (
    check_and_update_progress,
    check_spotify_rate_limit,
    check_task_cancellation,
    complete_task,
    create_task_history,
    logger,
    require_download_capability,
    update_task_progress,
)


def _normalize_name(name: str) -> str:
    """Strip accents and lowercase for fuzzy name comparison."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _resolve_album_to_deezer(album: Album) -> Optional[int]:
    """Search Deezer for an album that only has a Spotify ID.

    Returns deezer_id if a confident match is found, else None.
    """
    from src.providers.deezer import DeezerMetadataProvider

    artist_name = album.artist.name if album.artist else ""  # type: ignore[attr-defined]
    if not artist_name or not album.name:
        return None

    try:
        provider = DeezerMetadataProvider()
        results = provider.search_albums(f"{artist_name} {album.name}", limit=5)
        norm_album = _normalize_name(album.name)
        norm_artist = _normalize_name(artist_name)
        for result in results:
            if (
                _normalize_name(result.name) == norm_album
                and _normalize_name(result.artist_name or "") == norm_artist
                and result.deezer_id
            ):
                return result.deezer_id
    except Exception as e:
        logger.debug("Deezer album search failed for '%s': %s", album.name, e)

    return None


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
            albums_to_download = []
            for album in missing_albums.iterator():
                if not album.deezer_id:
                    deezer_id = _resolve_album_to_deezer(album)
                    if deezer_id:
                        album.deezer_id = deezer_id
                        album.save(update_fields=["deezer_id"])
                    else:
                        logger.warning(
                            f"Album '{album.name}' has no deezer_id and "
                            f"couldn't be found on Deezer, skipping"
                        )
                        continue
                albums_to_download.append(album)

            if albums_to_download:
                logger.info(
                    f"Downloading {len(albums_to_download)} albums "
                    f"for artist {artist.name}"
                )
                update_task_progress(
                    task_history,
                    50.0,
                    f"Downloading {len(albums_to_download)} albums via fallback providers",
                )
                for dl_album in albums_to_download:
                    if check_task_cancellation(task_history):
                        logger.info(
                            f"Download cancelled by user for artist {artist.name}"
                        )
                        return
                    try:
                        _download_deezer_album(dl_album, task_history)
                    except Exception as e:
                        logger.error(f"Failed to download album '{dl_album.name}': {e}")
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

    except (SpotifyRateLimitError, CeleryRetry):
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
    # pylint: disable=too-many-return-statements
    """Download a single specific album by ID.

    Resolves to Deezer if needed, then downloads via FallbackDownloader
    (YouTube/Tidal/Qobuz).
    """
    task_history = None
    try:
        try:
            album = Album.objects.get(id=album_id)
        except Album.DoesNotExist:
            logger.warning(f"Album with ID {album_id} does not exist. Skipping task.")
            return

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

        if not album.deezer_id:
            deezer_id = _resolve_album_to_deezer(album)
            if deezer_id:
                album.deezer_id = deezer_id
                album.save(update_fields=["deezer_id"])
            else:
                msg = (
                    f"Album '{album.name}' has no deezer_id and "
                    f"couldn't be found on Deezer"
                )
                logger.error(msg)
                complete_task(task_history, success=False, error_message=msg)
                return

        dl_count, fail_count = _download_deezer_album(album, task_history)
        total = dl_count + fail_count
        if fail_count > 0:
            msg = f"Downloaded {dl_count}/{total} tracks"
            complete_task(task_history, success=False, error_message=msg)
            logger.warning(f"Partial failure for album {album.name}: {msg}")
            return

        if check_and_update_progress(task_history, 100.0, "Download completed"):
            return

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded album: {album.name}")

    except CeleryRetry:
        raise
    except Exception as e:
        error_msg = f"Error downloading album: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


def _download_deezer_album(album: Album, task_history: TaskHistory) -> tuple[int, int]:
    """Download a Deezer-only album via YouTube/Tidal/Qobuz fallback providers.

    Fetches track listing from Deezer, creates Song records, and downloads
    each track using the FallbackDownloader pipeline.

    Returns:
        (downloaded_count, failed_count) tuple.
    """
    from downloader.providers.base import TrackMetadata
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

    album_artist_name = album.artist.name  # type: ignore[attr-defined]

    album_data = provider.get_album(album.deezer_id)
    cover_url = album_data.image_url if album_data else None

    songs_to_download: list[tuple[Song, TrackMetadata]] = []

    for track in deezer_tracks:
        if not track.deezer_id:
            continue

        # ISRC-first matching to avoid duplicates with existing Spotify-imported songs
        song = None
        if track.isrc:
            song = Song.objects.filter(
                isrc=track.isrc, primary_artist=album.artist
            ).first()
            if song and not song.deezer_id:
                song.deezer_id = track.deezer_id
                if not song.album:
                    song.album = album
                song.save(update_fields=["deezer_id", "album"])
                logger.debug(
                    f"Linked deezer_id to existing song '{song.name}' via ISRC"
                )
        if not song:
            song = Song.objects.filter(deezer_id=track.deezer_id).first()
        if not song:
            song = Song.objects.create(
                name=track.name,
                deezer_id=track.deezer_id,
                primary_artist=album.artist,
                album=album,
                isrc=track.isrc,
            )

        if song.downloaded:
            logger.debug(f"Song '{track.name}' already downloaded, skipping")
            continue

        # Build metadata for fallback providers
        metadata = TrackMetadata(
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
        return 0, 0

    update_task_progress(
        task_history,
        30.0,
        f"Downloading {len(songs_to_download)} tracks via fallback providers",
    )

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

    finally:
        try:
            loop.run_until_complete(downloader.close())
        finally:
            loop.close()

    if failed_count == 0:
        album.downloaded = True
        album.save()

    update_task_progress(
        task_history,
        95.0,
        f"Completed: {downloaded_count} downloaded, {failed_count} failed",
    )

    return downloaded_count, failed_count


def _handle_deezer_playlist_download(
    playlist_url: str, tracked: bool, task_id: str
) -> None:
    """Handle a Deezer playlist URL by routing to the Deezer sync pipeline."""
    import re

    from ..models import PlaylistStatus, TrackedPlaylist

    match = re.search(r"deezer\.com/(?:\w+/)?playlist/(\d+)", playlist_url)
    if not match:
        logger.error(f"Could not extract Deezer playlist ID from URL: {playlist_url}")
        return

    deezer_playlist_id = match.group(1)
    canonical_url = f"https://www.deezer.com/playlist/{deezer_playlist_id}"

    playlist, created = TrackedPlaylist.objects.get_or_create(
        url=canonical_url,
        defaults={
            "name": f"Deezer Playlist {deezer_playlist_id}",
            "provider": "deezer",
            "status": PlaylistStatus.ACTIVE,
            "auto_track_artists": tracked,
        },
    )

    if not created and tracked and not playlist.auto_track_artists:
        playlist.auto_track_artists = True
        playlist.save(update_fields=["auto_track_artists"])

    from src.providers.deezer import DeezerMetadataProvider

    provider = DeezerMetadataProvider()
    playlist_info = provider.get_playlist(deezer_playlist_id)
    if playlist_info and playlist_info.name and created:
        playlist.name = playlist_info.name
        playlist.save(update_fields=["name"])

    # Call sync_deezer_playlist via .delay() to get proper Celery context
    from .playlist import sync_deezer_playlist

    sync_deezer_playlist.delay(playlist.id, task_id=task_id)  # type: ignore[attr-defined]


def _match_or_create_song_from_spotify_track(
    track_data: dict, track_artists: bool = False
) -> Optional[Song]:
    """Match or create a Song from a Spotify track dict.

    Returns the Song instance, or None if the track data is invalid.
    """
    from library_manager.validators import extract_spotify_id_from_uri

    track_id = track_data.get("id")
    if not track_id:
        return None

    gid = extract_spotify_id_from_uri(track_id) or track_id

    # Match by Spotify GID
    song = Song.objects.filter(gid=gid).first()
    if song:
        return song

    # Match by ISRC
    isrc = track_data.get("external_ids", {}).get("isrc")
    if isrc:
        song = Song.objects.filter(isrc=isrc).first()
        if song:
            if not song.gid:
                song.gid = gid
                song.save(update_fields=["gid"])
            return song

    # Create new Song
    track_name = track_data.get("name", "Unknown Track")
    artists = track_data.get("artists", [])
    artist_name = (
        artists[0].get("name", "Unknown Artist") if artists else "Unknown Artist"
    )
    artist_gid = artists[0].get("id", "") if artists else ""

    artist = None
    if artist_gid:
        artist = Artist.objects.filter(gid=artist_gid).first()
    if not artist:
        artist, _ = Artist.objects.get_or_create(
            gid=artist_gid or f"unknown-{gid}",
            defaults={"name": artist_name, "tracked": track_artists},
        )

    song = Song.objects.create(
        name=track_name,
        gid=gid,
        isrc=isrc,
        primary_artist=artist,
    )
    return song


@celery_app.task(bind=True, name="library_manager.tasks.download_playlist")
def download_playlist(
    self: Any,
    playlist_url: str,
    tracked: bool = True,
    force_playlist_resync: bool = False,
    task_id: Optional[str] = None,
) -> None:
    if "deezer.com" in playlist_url:
        _handle_deezer_playlist_download(
            playlist_url, tracked, task_id or self.request.id
        )
        return

    # Check Spotify rate limit FIRST, before creating task history or doing any work.
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
        task_history.status = "RUNNING"
        task_history.save()

        if check_task_cancellation(task_history):
            logger.info(f"Playlist download cancelled: {playlist_url}")
            return

        # Fetch tracks from Spotify via spotipy
        from downloader.downloader import SpotifyPlaylistClient

        client = SpotifyPlaylistClient()
        if not client.is_available():
            raise RuntimeError("Spotify OAuth not available for playlist sync")

        update_task_progress(
            task_history, 25.0, "Fetching playlist tracks from Spotify"
        )

        # Extract playlist ID
        sp_playlist_id = None
        if "spotify:playlist:" in playlist_url:
            sp_playlist_id = playlist_url.split("spotify:playlist:", 1)[1]
        elif "/playlist/" in playlist_url:
            sp_playlist_id = playlist_url.split("/playlist/", 1)[1].split("?")[0]

        if not sp_playlist_id:
            raise ValueError(f"Could not extract playlist ID from: {playlist_url}")

        playlist_data = client.get_playlist(sp_playlist_id)
        raw_tracks = playlist_data.get("tracks", {}).get("items", [])

        update_task_progress(
            task_history,
            50.0,
            f"Processing {len(raw_tracks)} tracks from playlist",
        )

        from .maintenance import _download_deezer_songs_via_fallback

        songs_to_download = []
        for item in raw_tracks:
            if check_task_cancellation(task_history):
                logger.info(f"Playlist download cancelled: {playlist_url}")
                return

            track = item.get("track")
            if not track or track.get("is_local"):
                continue

            song = _match_or_create_song_from_spotify_track(track, tracked)
            if song and not song.downloaded:
                songs_to_download.append(song)

        if songs_to_download:
            update_task_progress(
                task_history,
                60.0,
                f"Downloading {len(songs_to_download)} tracks via fallback providers",
            )
            downloaded, failed = _download_deezer_songs_via_fallback(songs_to_download)
            logger.info(f"Playlist download: {downloaded} downloaded, {failed} failed")

        # Store snapshot_id for change detection
        snapshot_id = playlist_data.get("snapshot_id")
        if snapshot_id:
            from ..models import TrackedPlaylist

            tp = TrackedPlaylist.objects.filter(url__contains=sp_playlist_id).first()
            if tp:
                tp.snapshot_id = snapshot_id
                tp.save(update_fields=["snapshot_id"])

        complete_task(task_history, success=True)

    except (SpotifyRateLimitError, CeleryRetry):
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
    # pylint: disable=too-many-branches,too-many-statements

    # Check authentication before proceeding with any DB queries
    require_download_capability()

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
        f"extra album missing albums search for artist {artist.id} "
        f"found {missing_albums.count()}"
    )

    if missing_albums.count() == 0:
        logger.info(
            f"extra album missing albums search for artist {artist.id} "
            f"is skipping since there are none missing"
        )
        artist.last_downloaded_at = Now()
        artist.save()
        return

    task_history = None
    if task_id:
        task_history = TaskHistory.objects.filter(task_id=task_id).first()

    albums_to_download = []
    for album in missing_albums.iterator():
        if not album.deezer_id:
            deezer_id = _resolve_album_to_deezer(album)
            if deezer_id:
                album.deezer_id = deezer_id
                album.save(update_fields=["deezer_id"])
            else:
                logger.warning(
                    f"Extra album '{album.name}' not found on Deezer, skipping"
                )
                continue
        albums_to_download.append(album)

    if albums_to_download:
        logger.info(
            f"Downloading {len(albums_to_download)} extra albums "
            f"for artist {artist.name}"
        )
        for dl_album in albums_to_download:
            try:
                _download_deezer_album(dl_album, task_history or TaskHistory())
            except Exception as e:
                logger.error(f"Failed to download extra album '{dl_album.name}': {e}")

    artist.last_downloaded_at = Now()
    artist.save()


@celery_app.task(bind=True, name="library_manager.tasks.download_album_by_spotify_id")
def download_album_by_spotify_id(self: Any, spotify_album_id: str) -> None:
    """Download an album by its Spotify ID (not database ID).

    Looks up the album in the database and resolves to Deezer if needed.
    """
    task_history = None
    try:
        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=spotify_album_id,
            entity_type="ALBUM",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for album {spotify_album_id}"
        )

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for album {spotify_album_id}")
            return

        album = Album.objects.filter(spotify_gid=spotify_album_id).first()
        if not album:
            raise ValueError(
                f"Album with Spotify ID {spotify_album_id} not in database — "
                f"import via Deezer URL instead"
            )

        if not album.wanted:
            album.wanted = True
            album.save()

        if not album.deezer_id:
            deezer_id = _resolve_album_to_deezer(album)
            if deezer_id:
                album.deezer_id = deezer_id
                album.save(update_fields=["deezer_id"])
            else:
                raise ValueError(f"Album '{album.name}' not found on Deezer")

        update_task_progress(task_history, 50.0, f"Downloading album: {album.name}")

        _download_deezer_album(album, task_history)

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded album: {album.name}")

    except CeleryRetry:
        raise
    except Exception as e:
        error_msg = f"Error downloading album: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


@celery_app.task(bind=True, name="library_manager.tasks.download_album_by_deezer_id")
def download_album_by_deezer_id(self: Any, deezer_album_id: int) -> None:
    """Download an album by its Deezer ID (not database ID).

    Fetches album metadata from Deezer if needed, creates/gets the album
    in the database, and downloads via fallback providers.
    """
    task_history = None
    try:
        from src.providers.deezer import DeezerMetadataProvider

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=str(deezer_album_id),
            entity_type="ALBUM",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for Deezer album {deezer_album_id}"
        )

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for Deezer album {deezer_album_id}")
            return

        album = Album.objects.filter(deezer_id=deezer_album_id).first()

        if not album:
            update_task_progress(
                task_history, 25.0, "Fetching album metadata from Deezer"
            )

            provider = DeezerMetadataProvider()
            album_data = provider.get_album(deezer_album_id)
            if not album_data:
                raise ValueError(f"Album {deezer_album_id} not found on Deezer")

            if not album_data.artist_deezer_id:
                raise ValueError(
                    f"Album {deezer_album_id} has no artist data on Deezer"
                )

            artist, _ = Artist.objects.get_or_create(
                deezer_id=album_data.artist_deezer_id,
                defaults={"name": album_data.artist_name or "Unknown Artist"},
            )

            album = Album.objects.create(
                name=album_data.name,
                deezer_id=deezer_album_id,
                artist=artist,
                spotify_uri="",
                total_tracks=album_data.total_tracks,
                album_type=album_data.album_type,
                album_group=album_data.album_type or "",
                wanted=True,
            )
            logger.info(f"Created album: {album.name}")

        if not album.wanted:
            album.wanted = True
            album.save()

        update_task_progress(task_history, 50.0, f"Downloading album: {album.name}")

        dl_count, fail_count = _download_deezer_album(album, task_history)
        total = dl_count + fail_count
        if fail_count > 0:
            msg = f"Downloaded {dl_count}/{total} tracks"
            complete_task(task_history, success=False, error_message=msg)
            logger.warning(f"Partial failure for album {album.name}: {msg}")
            return

        complete_task(task_history, success=True)
        logger.info(f"Successfully downloaded Deezer album: {album.name}")

    except Exception as e:
        error_msg = f"Error downloading Deezer album {deezer_album_id}: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


@celery_app.task(bind=True, name="library_manager.tasks.download_track_by_spotify_gid")
def download_track_by_spotify_gid(self: Any, track_gid: str) -> None:
    """Download a single track by its Spotify GID.

    Looks up the Song in the database, resolves to Deezer if possible,
    then downloads via FallbackDownloader.
    """
    task_history = None
    try:
        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=track_gid,
            entity_type="TRACK",
        )
        update_task_progress(
            task_history, 0.0, f"Starting download for track {track_gid}"
        )

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for track {track_gid}")
            return

        song = Song.objects.filter(gid=track_gid).first()
        if not song:
            raise ValueError(f"No song in database with Spotify GID {track_gid}")

        if song.deezer_id:
            download_deezer_track.delay(song.id)
            complete_task(task_history, success=True)
            return

        # Try to resolve to Deezer before downloading
        from .maintenance import _try_resolve_to_deezer

        _try_resolve_to_deezer(song)

        if song.deezer_id:
            download_deezer_track.delay(song.id)
            complete_task(task_history, success=True)
            return

        # Fall back to FallbackDownloader with Song model fields
        from .maintenance import _download_deezer_songs_via_fallback

        update_task_progress(task_history, 25.0, f"Downloading track: {song.name}")
        downloaded, failed = _download_deezer_songs_via_fallback([song])
        if downloaded > 0:
            complete_task(task_history, success=True)
        else:
            complete_task(task_history, success=False, error_message="Download failed")

    except CeleryRetry:
        raise
    except Exception as e:
        error_msg = f"Error downloading track: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise


# Keep old name as alias for backwards compatibility with queued tasks
download_single_track = download_track_by_spotify_gid


@celery_app.task(bind=True, name="library_manager.tasks.download_deezer_track")
def download_deezer_track(self: Any, song_id: int) -> None:
    """Download a single track by Song database ID using FallbackDownloader.

    Used for songs sourced from Deezer that don't have a Spotify URI.
    Fetches metadata from Deezer API and downloads via YouTube/Tidal/Qobuz.
    """
    from downloader.providers.base import TrackMetadata
    from downloader.providers.fallback import FallbackDownloader

    from src.providers.deezer import DeezerMetadataProvider

    from ..models import DownloadProvider as DownloadProviderEnum

    task_history = None
    try:
        song = Song.objects.select_related("primary_artist", "album").get(id=song_id)

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=str(song_id),
            entity_type="TRACK",
        )
        update_task_progress(
            task_history, 0.0, f"Starting Deezer download for: {song.name}"
        )

        if not song.deezer_id:
            raise ValueError(f"Song {song_id} ({song.name}) has no deezer_id")

        require_download_capability(task_history)

        if check_task_cancellation(task_history):
            logger.info(f"Task cancelled for song {song_id}")
            return

        provider = DeezerMetadataProvider()
        deezer_track = provider.get_track(song.deezer_id)

        artist_name: str = (
            song.primary_artist.name  # type: ignore[attr-defined]
            if song.primary_artist
            else "Unknown Artist"
        )
        album_name: str = (
            song.album.name if song.album else ""  # type: ignore[attr-defined]
        )

        metadata = TrackMetadata(
            spotify_id="",
            title=song.name,
            artist=deezer_track.artist_name if deezer_track else artist_name,
            album=album_name,
            album_artist=artist_name,
            duration_ms=deezer_track.duration_ms if deezer_track else 0,
            isrc=song.isrc or (deezer_track.isrc if deezer_track else None),
        )

        update_task_progress(
            task_history, 25.0, f"Downloading: {song.name} via fallback providers"
        )

        provider_enum_map = {
            "youtube": DownloadProviderEnum.YOUTUBE,
            "tidal": DownloadProviderEnum.TIDAL,
            "qobuz": DownloadProviderEnum.QOBUZ,
        }

        downloader = FallbackDownloader(
            provider_order=["youtube", "tidal", "qobuz"],
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(downloader.download_track(metadata))
        finally:
            try:
                loop.run_until_complete(downloader.close())
            finally:
                loop.close()

        if result.success and result.file_path:
            dl_provider = provider_enum_map.get(
                result.provider_used or "", DownloadProviderEnum.UNKNOWN
            )
            song.mark_downloaded(
                bitrate=256,
                file_path=str(result.file_path),
                provider=dl_provider,
            )
            complete_task(task_history, success=True)
            logger.info(f"Downloaded '{song.name}' via {result.provider_used}")
        else:
            song.increment_failed_count()
            song.save()
            error_msg = f"Failed to download '{song.name}': {result.error_message}"
            logger.warning(error_msg)
            complete_task(task_history, success=False, error_message=error_msg)

    except Exception as e:
        error_msg = f"Error downloading Deezer track {song_id}: {str(e)}"
        logger.error(error_msg)
        if task_history:
            complete_task(task_history, success=False, error_message=error_msg)
        raise
