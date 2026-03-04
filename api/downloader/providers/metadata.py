"""
Metadata embedding for downloaded audio files.

This module handles embedding metadata (title, artist, album, cover art, etc.)
into audio files downloaded from providers like Tidal that don't include metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import requests

from .base import TrackMatch, TrackMetadata

logger = logging.getLogger(__name__)

# Request timeout for fetching cover art
COVER_ART_TIMEOUT = 10


class MetadataEmbedder:
    """
    Embeds metadata into audio files using mutagen.

    Supports:
    - M4A/AAC files (MP4 tags)
    - FLAC files (Vorbis comments)
    """

    def embed_metadata(
        self,
        file_path: Path,
        track_metadata: TrackMetadata,
        track_match: Optional[TrackMatch] = None,
    ) -> bool:
        """
        Embed metadata into an audio file.

        Args:
            file_path: Path to the audio file
            track_metadata: Track metadata for embedding (title, artist, album, etc.)
            track_match: Optional match from the download provider (for cover art fallback)

        Returns:
            True if metadata was successfully embedded, False otherwise.
        """
        suffix = file_path.suffix.lower()

        try:
            if suffix in (".m4a", ".mp4", ".aac"):
                return self._embed_mp4_metadata(file_path, track_metadata, track_match)
            elif suffix == ".flac":
                return self._embed_flac_metadata(file_path, track_metadata, track_match)
            else:
                logger.warning(f"Unsupported audio format for metadata: {suffix}")
                return False
        except Exception as e:
            logger.error(f"Failed to embed metadata in {file_path}: {e}")
            return False

    def _embed_mp4_metadata(
        self,
        file_path: Path,
        track_metadata: TrackMetadata,
        track_match: Optional[TrackMatch],
    ) -> bool:
        """Embed metadata into MP4/M4A files."""
        from mutagen.mp4 import MP4, MP4Cover

        try:
            audio = MP4(str(file_path))
        except Exception as e:
            logger.error(f"Failed to open MP4 file {file_path}: {e}")
            return False

        # MP4 tag mapping
        # https://mutagen.readthedocs.io/en/latest/api/mp4.html
        audio["\xa9nam"] = [track_metadata.title]  # Title
        audio["\xa9ART"] = [track_metadata.artist]  # Artist
        audio["\xa9alb"] = [track_metadata.album]  # Album
        audio["aART"] = [track_metadata.album_artist]  # Album Artist

        if track_metadata.track_number:
            total = track_metadata.total_tracks or 0
            audio["trkn"] = [(track_metadata.track_number, total)]

        if track_metadata.disc_number:
            total = track_metadata.total_discs or 0
            audio["disk"] = [(track_metadata.disc_number, total)]

        if track_metadata.release_date:
            audio["\xa9day"] = [track_metadata.release_date]

        if track_metadata.genres:
            audio["\xa9gen"] = [", ".join(track_metadata.genres)]

        if track_metadata.copyright:
            audio["cprt"] = [track_metadata.copyright]

        if track_metadata.isrc:
            # ISRC is stored in a custom atom
            audio["----:com.apple.iTunes:ISRC"] = [track_metadata.isrc.encode("utf-8")]

        # Embed cover art
        cover_url = track_metadata.cover_url
        if not cover_url and track_match:
            cover_url = track_match.cover_url

        if cover_url:
            cover_data = self._fetch_cover_art(cover_url)
            if cover_data:
                # Determine image format from data
                if cover_data[:3] == b"\xff\xd8\xff":
                    image_format = MP4Cover.FORMAT_JPEG
                elif cover_data[:8] == b"\x89PNG\r\n\x1a\n":
                    image_format = MP4Cover.FORMAT_PNG
                else:
                    image_format = MP4Cover.FORMAT_JPEG  # Default assumption

                audio["covr"] = [MP4Cover(cover_data, imageformat=image_format)]

        audio.save()
        logger.debug(f"Embedded MP4 metadata in {file_path}")
        return True

    def _embed_flac_metadata(
        self,
        file_path: Path,
        track_metadata: TrackMetadata,
        track_match: Optional[TrackMatch],
    ) -> bool:
        """Embed metadata into FLAC files."""
        from mutagen.flac import FLAC, Picture

        try:
            audio = FLAC(str(file_path))
        except Exception as e:
            logger.error(f"Failed to open FLAC file {file_path}: {e}")
            return False

        # FLAC uses Vorbis comments
        audio["TITLE"] = [track_metadata.title]
        audio["ARTIST"] = [track_metadata.artist]
        audio["ALBUM"] = [track_metadata.album]
        audio["ALBUMARTIST"] = [track_metadata.album_artist]

        if track_metadata.track_number:
            audio["TRACKNUMBER"] = [str(track_metadata.track_number)]
        if track_metadata.total_tracks:
            audio["TRACKTOTAL"] = [str(track_metadata.total_tracks)]

        if track_metadata.disc_number:
            audio["DISCNUMBER"] = [str(track_metadata.disc_number)]
        if track_metadata.total_discs:
            audio["DISCTOTAL"] = [str(track_metadata.total_discs)]

        if track_metadata.release_date:
            audio["DATE"] = [track_metadata.release_date]

        if track_metadata.genres:
            audio["GENRE"] = list(track_metadata.genres)

        if track_metadata.copyright:
            audio["COPYRIGHT"] = [track_metadata.copyright]

        if track_metadata.isrc:
            audio["ISRC"] = [track_metadata.isrc]

        # Embed cover art
        cover_url = track_metadata.cover_url
        if not cover_url and track_match:
            cover_url = track_match.cover_url

        if cover_url:
            cover_data = self._fetch_cover_art(cover_url)
            if cover_data:
                picture = Picture()
                picture.type = 3  # Cover (front)
                picture.desc = "Cover"
                picture.data = cover_data

                # Determine MIME type from data
                if cover_data[:3] == b"\xff\xd8\xff":
                    picture.mime = "image/jpeg"
                elif cover_data[:8] == b"\x89PNG\r\n\x1a\n":
                    picture.mime = "image/png"
                else:
                    picture.mime = "image/jpeg"  # Default

                audio.add_picture(picture)

        audio.save()
        logger.debug(f"Embedded FLAC metadata in {file_path}")
        return True

    def _fetch_cover_art(self, url: str) -> Optional[bytes]:
        """Fetch cover art from URL."""
        try:
            response = requests.get(url, timeout=COVER_ART_TIMEOUT)
            response.raise_for_status()
            return response.content
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch cover art from {url}: {e}")
            return None


def create_metadata_from_match(
    track_match: TrackMatch,
    spotify_id: str = "",
    album_artist: Optional[str] = None,
) -> TrackMetadata:
    """
    Create TrackMetadata from a TrackMatch.

    Useful when we only have provider metadata (e.g., from Tidal)
    and need to create a TrackMetadata object for embedding.

    Args:
        track_match: Track match from a provider
        spotify_id: Optional Spotify ID (empty string for non-Spotify sources)
        album_artist: Optional album artist (defaults to track artist)

    Returns:
        TrackMetadata populated from the track match
    """
    return TrackMetadata(
        spotify_id=spotify_id,
        title=track_match.title,
        artist=track_match.artist,
        album=track_match.album,
        album_artist=album_artist or track_match.artist,
        duration_ms=track_match.duration_ms,
        isrc=track_match.isrc,
        track_number=track_match.track_number,
        total_tracks=track_match.total_tracks,
        release_date=track_match.release_date,
        cover_url=track_match.cover_url,
    )


# Backward-compat alias
create_spotify_metadata_from_match = create_metadata_from_match
