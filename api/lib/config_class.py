from pathlib import Path
from typing import List, Optional

from src.app_settings.registry import get_setting


class Config:
    def __init__(
        self,
        urls: Optional[List[str]] = None,
        cookies_location: Optional[Path] = None,
        youtube_cookies_location: Optional[Path] = None,
        spotify_user_auth_enabled: Optional[bool] = None,
        po_token: Optional[str] = None,
        log_level: Optional[str] = None,
        no_lrc: Optional[bool] = None,
        overwrite: Optional[bool] = None,
        track_artists: bool = False,
        print_exceptions: bool = True,
        force_playlist_resync: bool = False,
        fallback_quality: Optional[str] = None,
        download_provider_order: Optional[List[str]] = None,
        qobuz_use_mp3: Optional[bool] = None,
    ):
        # Cookie path is now hardcoded (managed via UI cookie upload)
        self.youtube_cookies_location = youtube_cookies_location or Path(
            "/config/youtube_music_cookies.txt"
        )
        if cookies_location:
            self.youtube_cookies_location = Path(cookies_location)
        self.cookies_location = self.youtube_cookies_location

        self.spotify_user_auth_enabled = (
            spotify_user_auth_enabled
            if spotify_user_auth_enabled is not None
            else get_setting("spotify_user_auth_enabled")
        )
        self.po_token = po_token if po_token is not None else get_setting("po_token")
        self.log_level = (
            log_level if log_level is not None else get_setting("log_level")
        )
        self.no_lrc = (
            no_lrc if no_lrc is not None else get_setting("lyrics_enabled") is False
        )
        self.overwrite = (
            overwrite if overwrite is not None else get_setting("overwrite")
        )

        self.fallback_quality = (
            fallback_quality
            if fallback_quality is not None
            else get_setting("fallback_quality")
        )

        raw_order = (
            download_provider_order
            if download_provider_order is not None
            else get_setting("download_provider_order")
        )
        # Map legacy "spotdl" -> "youtube" (both use YouTube Music via yt-dlp)
        self.download_provider_order = [
            "youtube" if p == "spotdl" else p for p in raw_order
        ]

        self.qobuz_use_mp3 = (
            qobuz_use_mp3 if qobuz_use_mp3 is not None else get_setting("qobuz_use_mp3")
        )

        # Direct assignments
        self.urls = urls or []
        self.track_artists = track_artists
        self.print_exceptions = print_exceptions
        self.force_playlist_resync = force_playlist_resync
