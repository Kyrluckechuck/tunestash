"""Pure m3u rendering for ExportSnapshots.

Emits extended m3u (#EXTM3U) with #EXTINF:-1,Artist - Title per track
followed by the local file path. Songs without a downloaded local file are
skipped per the program spec.

Song has no duration field, so -1 (the EXTM3U convention for unknown)
is used as the duration.
"""

from __future__ import annotations

from typing import cast

from queuetip.models import ExportSnapshot, ExportSnapshotTrack, Playlist


def render_m3u(snapshot: ExportSnapshot) -> str:
    """Render an ExportSnapshot as extended m3u text.

    Callers should pre-fetch snapshot.tracks with
    select_related("song", "song__primary_artist") to avoid lazy loads;
    this function issues its own select_related when querying tracks.
    """
    lines: list[str] = [
        "#EXTM3U",
        f'# Queuetip export — playlist "{cast(Playlist, snapshot.playlist).name}" — snapshot {snapshot.id}',
    ]
    tracks = snapshot.tracks.select_related("song", "song__primary_artist").order_by(
        "position"
    )
    for track in cast(list[ExportSnapshotTrack], tracks):
        from library_manager.models import Song

        song = cast(Song, track.song)
        file_path = song.file_path
        if not song.downloaded or not file_path:
            continue
        artist_name = (
            song.primary_artist.name  # type: ignore[attr-defined]
            if song.primary_artist_id and song.primary_artist  # type: ignore[attr-defined]
            else ""
        )
        lines.append(f"#EXTINF:-1,{artist_name} - {song.name}")
        lines.append(str(file_path))
    return "\n".join(lines) + "\n"
