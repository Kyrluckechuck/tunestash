"""
LRClib lyrics fetcher.

Fetches synced lyrics from lrclib.net and saves as .lrc sidecar files
alongside audio files. Media players (Navidrome, Jellyfin, Plex, foobar2000)
auto-discover .lrc files for synchronized lyrics display.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

LRCLIB_API_URL = "https://lrclib.net/api/get"
REQUEST_TIMEOUT = 10


def fetch_and_save_lyrics(
    file_path: Path,
    track_name: str,
    artist_name: str,
    album_name: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> bool:
    """Fetch lyrics from LRClib and save as .lrc sidecar file.

    Args:
        file_path: Path to the audio file (used to derive .lrc path)
        track_name: Song title
        artist_name: Artist name
        album_name: Album name (improves match accuracy)
        duration_seconds: Track duration in seconds (improves match accuracy)

    Returns:
        True if lyrics were saved, False if not found or error occurred.
    """
    params: dict[str, str | int] = {
        "track_name": track_name,
        "artist_name": artist_name,
    }
    if album_name:
        params["album_name"] = album_name
    if duration_seconds:
        params["duration"] = duration_seconds

    try:
        response = requests.get(
            LRCLIB_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "TuneStash/1.0"},
        )

        if response.status_code == 404:
            return False

        response.raise_for_status()
        data = response.json()

        # Prefer synced lyrics (timestamped), fall back to plain
        lyrics_content = data.get("syncedLyrics") or data.get("plainLyrics")
        if not lyrics_content:
            return False

        lrc_path = file_path.with_suffix(".lrc")
        lrc_path.write_text(lyrics_content, encoding="utf-8")
        logger.debug(f"Saved lyrics to {lrc_path}")
        return True

    except requests.RequestException as e:
        logger.debug(f"LRClib request failed for '{artist_name} - {track_name}': {e}")
        return False
    except Exception as e:
        logger.warning(f"Lyrics fetch error for '{artist_name} - {track_name}': {e}")
        return False


def fetch_and_save_lyrics_if_enabled(
    file_path: Path,
    track_name: str,
    artist_name: str,
    album_name: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> bool:
    """Fetch lyrics only if lyrics_enabled is True in settings."""
    from django.conf import settings as django_settings

    if not getattr(django_settings, "LYRICS_ENABLED", False):
        return False

    return fetch_and_save_lyrics(
        file_path=file_path,
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        duration_seconds=duration_seconds,
    )


def normalize_filename(name: str) -> str:
    """Normalize a filename for fuzzy .lrc matching.

    Strips accents, lowercases, removes non-alphanumeric chars except spaces/hyphens.
    """
    # NFKD decomposition separates base chars from combining marks
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = ascii_only.lower()
    # Keep only alphanumeric, spaces, hyphens
    return "".join(c for c in lowered if c.isalnum() or c in (" ", "-"))


def find_existing_lrc(audio_path: Path) -> Optional[Path]:
    """Find an existing .lrc file for the given audio file.

    Tries exact stem match first, then fuzzy match with accent normalization.
    Guards against remix false positives when multiple .lrc files exist.
    """
    # Exact match
    exact_lrc = audio_path.with_suffix(".lrc")
    if exact_lrc.exists():
        return exact_lrc

    # Fuzzy match: list all .lrc files in same directory
    parent = audio_path.parent
    if not parent.exists():
        return None

    lrc_files = list(parent.glob("*.lrc"))
    if not lrc_files:
        return None

    audio_stem_normalized = normalize_filename(audio_path.stem)

    for lrc_file in lrc_files:
        lrc_stem_normalized = normalize_filename(lrc_file.stem)
        if lrc_stem_normalized == audio_stem_normalized:
            return lrc_file

    return None
