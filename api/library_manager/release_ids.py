# mypy: disable-error-code=attr-defined
"""Per-release Deezer track ids.

TuneStash stores one ``Song`` per album, so the same recording (same ISRC) has a
different Deezer track id on every release. ``track/isrc:`` and name searches
return whichever release Deezer indexed first, which is rarely the song's own.
A song's id must therefore come from the track list of *its own* Deezer album.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from library_manager.models import Song
from src.providers.metadata_base import TrackResult

logger = logging.getLogger(__name__)

SELECT_FOUND = "found"
SELECT_NONE = "no_matching_track"
SELECT_AMBIGUOUS = "ambiguous_candidates"


@dataclass(frozen=True)
class Selection:
    status: str
    track: Optional[TrackResult] = None
    candidate_ids: tuple[int, ...] = ()


def normalize_isrc(value: Optional[str]) -> str:
    return value.strip().upper() if value else ""


def known_isrcs(song: Song) -> set[str]:
    """Every ISRC that identifies this song's recording."""
    found = {normalize_isrc(song.isrc)}
    found.update(normalize_isrc(i) for i in song.alternate_isrcs or ())
    found.discard("")
    return found


def select_release_track(
    song: Song,
    tracks: Iterable[TrackResult],
    position: Optional[tuple[Optional[int], Optional[int]]] = None,
) -> Selection:
    """Pick the track on an album's track list that is this song's recording.

    ``position`` is ``(disc_number, track_number)`` and is consulted only when
    the ISRC appears more than once on the release.
    """
    isrcs = known_isrcs(song)
    candidates = [t for t in tracks if t.deezer_id and normalize_isrc(t.isrc) in isrcs]
    if not candidates:
        return Selection(SELECT_NONE)
    if len(candidates) == 1:
        return Selection(SELECT_FOUND, candidates[0])
    if position is not None:
        disc, number = position
        narrowed = [
            t
            for t in candidates
            if (number is None or t.track_number == number)
            and (disc is None or t.disc_number is None or t.disc_number == disc)
        ]
        if len(narrowed) == 1:
            return Selection(SELECT_FOUND, narrowed[0])
    return Selection(
        SELECT_AMBIGUOUS, candidate_ids=tuple(int(t.deezer_id) for t in candidates)  # type: ignore[arg-type]
    )


def fits_release(song: Song, track: TrackResult) -> bool:
    """May this Deezer track id be stored on ``song``?

    A song without an album has no release to contradict. An albumed song needs
    an *authoritative* release identity: its Deezer album id. Title/artist
    matching (the ``release_match`` fallback) is not reliable and must never
    authorize writing an id, because a same-titled edition by the same artist
    can pass it. Such rows need their album resolved by UPC first.
    """
    if song.album_id is None:
        return True
    album = song.album
    if album is None or album.deezer_id is None:
        return False
    if track.album_deezer_id is None:
        return False
    return int(album.deezer_id) == int(track.album_deezer_id)


def resolve_release_deezer_id(song: Song, provider: Any = None) -> Optional[int]:
    """The Deezer track id of ``song`` on its own album, or ``None``.

    Needs the album's Deezer id; never falls back to another release.
    """
    album = song.album
    if album is None or album.deezer_id is None:
        return None
    if provider is None:
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
    try:
        tracks = provider.get_album_tracks(album.deezer_id)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Album %s track list failed: %s", album.deezer_id, exc)
        return None
    selection = select_release_track(song, tracks)
    if selection.track is None:
        return None
    return int(selection.track.deezer_id)  # type: ignore[arg-type]
