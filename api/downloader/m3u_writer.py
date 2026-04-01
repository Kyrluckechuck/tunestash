"""
M3U playlist file generator.

Generates .m3u files from PlaylistSong records for media server import.
Navidrome, Jellyfin, Plex, and other servers auto-discover .m3u files
placed in the music directory.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _sanitize_playlist_name(name: str) -> str:
    """Sanitize a playlist name for use as a filename."""
    # Remove filesystem-unsafe characters
    sanitized = re.sub(r'[/\\:*?"<>|]', "", name)
    sanitized = sanitized.strip(". ")
    if not sanitized:
        sanitized = "Untitled Playlist"
    return sanitized[:200]


def write_playlist_m3u(
    playlist_id: int,
    output_base_dir: Path,
    playlist_dir_name: str = "Playlists",
) -> Optional[Path]:
    """Generate an .m3u file for a playlist from PlaylistSong records.

    Args:
        playlist_id: ID of the TrackedPlaylist
        output_base_dir: Base music directory (OUTPUT_PATH)
        playlist_dir_name: Subdirectory for playlist files (relative to output_base_dir)

    Returns:
        Path to the generated .m3u file, or None if no tracks to write.
    """
    from library_manager.models import PlaylistSong, TrackedPlaylist

    try:
        playlist = TrackedPlaylist.objects.get(id=playlist_id)
    except TrackedPlaylist.DoesNotExist:
        logger.warning(f"Playlist {playlist_id} not found for M3U generation")
        return None

    playlist_songs = (
        PlaylistSong.objects.filter(playlist=playlist)
        .select_related("song", "song__file_path_ref", "song__primary_artist")
        .order_by("track_order")
    )

    if not playlist_songs.exists():
        return None

    playlist_dir = output_base_dir / playlist_dir_name
    playlist_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_playlist_name(playlist.name)
    m3u_path = playlist_dir / f"TS - {safe_name}.m3u"

    lines = ["#EXTM3U", f"#PLAYLIST:TS | {playlist.name}"]

    for ps in playlist_songs:
        song = ps.song
        file_path = _resolve_song_file_path(song, output_base_dir)

        # Always write the EXTINF line (even if no file path — makes the entry visible)
        artist_name = song.primary_artist.name if song.primary_artist_id else "Unknown"
        lines.append(f"#EXTINF:-1,{artist_name} - {song.name}")

        if file_path:
            # Use path relative to the M3U file's directory (Playlists/)
            # so media servers resolve paths correctly
            try:
                rel_from_root = file_path.relative_to(output_base_dir)
                # Prepend ../ since the M3U lives in a subdirectory of the music root
                lines.append(str(Path("..") / rel_from_root))
            except ValueError:
                lines.append(str(file_path))

    m3u_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.debug(f"Wrote M3U playlist to {m3u_path}")
    return m3u_path


def _resolve_song_file_path(song: "Song", output_base_dir: Path) -> Optional[Path]:  # type: ignore[name-defined]  # noqa: F821, E501
    """Resolve a song to a downloaded file path with cross-release fallback.

    Resolution chain:
    1. Direct: song has downloaded=True and file_path_ref
    2. ISRC fallback: another Song with same ISRC is downloaded
    3. Name+artist fallback: search by exact name and primary_artist
    """
    from library_manager.models import Song

    # Direct match
    if song.downloaded and song.file_path_ref:
        return Path(song.file_path_ref.path)

    # ISRC fallback
    if song.isrc:
        isrc_match = (
            Song.objects.filter(
                isrc=song.isrc,
                downloaded=True,
                file_path_ref__isnull=False,
            )
            .exclude(id=song.id)
            .select_related("file_path_ref")
            .first()
        )
        if isrc_match and isrc_match.file_path_ref:
            return Path(isrc_match.file_path_ref.path)

    # Name+artist fallback — score candidates and pick best
    if song.primary_artist_id:
        from downloader.track_matcher import score_track_match

        candidates = (
            Song.objects.filter(
                name__iexact=song.name,
                primary_artist_id=song.primary_artist_id,
                downloaded=True,
                file_path_ref__isnull=False,
            )
            .exclude(id=song.id)
            .select_related("file_path_ref", "primary_artist")
        )

        best_path: Optional[Path] = None
        best_score = 0.0
        artist_name = song.primary_artist.name if song.primary_artist_id else ""

        for candidate in candidates:
            cand_artist = (
                candidate.primary_artist.name if candidate.primary_artist_id else ""
            )
            score = score_track_match(
                search_title=song.name,
                search_artist=artist_name,
                result_title=candidate.name,
                result_artist=cand_artist,
            )
            if candidate.file_path_ref and score > best_score:
                best_score = score
                best_path = Path(candidate.file_path_ref.path)

        if best_path and best_score >= 0.6:
            return best_path

    return None


def regenerate_m3u_for_song(song_id: int) -> None:
    """Regenerate M3U files for all m3u-enabled playlists that contain a given song.

    Called after a song finishes downloading to update M3U files
    with the newly available track.
    """
    from library_manager.models import PlaylistSong, TrackedPlaylist

    playlist_ids = (
        PlaylistSong.objects.filter(song_id=song_id)
        .values_list("playlist_id", flat=True)
        .distinct()
    )

    if not playlist_ids:
        return

    # Only regenerate for playlists with m3u_enabled=True
    enabled_ids = TrackedPlaylist.objects.filter(
        id__in=list(playlist_ids), m3u_enabled=True
    ).values_list("id", flat=True)

    if not enabled_ids:
        return

    from django.conf import settings as django_settings

    from src.app_settings.registry import get_setting

    output_dir = Path(getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify"))
    playlist_dir = get_setting("m3u_playlists_directory")

    for playlist_id in enabled_ids:
        write_playlist_m3u(playlist_id, output_dir, playlist_dir)
