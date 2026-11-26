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

from django.db import IntegrityError, transaction

from library_manager.models import Album, Song
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


def normalize_upc(value: Optional[str]) -> str:
    """Canonical UPC/EAN for comparison; empty when not a plausible UPC."""
    text = (value or "").strip()
    if not text.isdigit() or len(text) not in (8, 12, 13, 14):
        return ""
    return text.lstrip("0") or "0"


def _local_spotify_album_gid(album: Any) -> str:
    for raw in (album.spotify_gid, album.spotify_uri):
        if raw:
            return str(raw).rsplit(":", 1)[-1]
    return ""


def fetch_deezer_album_upc(deezer_album_id: int) -> Optional[str]:
    from src.providers.deezer import DeezerMetadataProvider

    album = DeezerMetadataProvider().client.get_album(int(deezer_album_id))
    return getattr(album, "upc", None)


def fetch_spotify_album_upc(spotify_gid: str) -> Optional[str]:
    from downloader.spotipy_tasks import PublicSpotifyClient

    client = PublicSpotifyClient().sp
    if client is None:
        return None
    album = dict(client.album(spotify_gid) or {})
    return (album.get("external_ids") or {}).get("upc")


def album_matches_by_upc(
    album: Any,
    deezer_album_id: int,
    deezer_upc: Optional[str] = None,
    spotify_upc_fetcher: Any = None,
) -> bool:
    """Is the local ``album`` the same release as Deezer album ``deezer_album_id``?

    Only a shared UPC proves it. A title match is not identity: original,
    deluxe, live and remastered editions share titles. Any lookup failure or a
    missing/invalid UPC on either side is "unverified", never a match.
    """
    gid = _local_spotify_album_gid(album)
    wanted = normalize_upc(deezer_upc)
    if not gid or not wanted:
        return False
    fetch = spotify_upc_fetcher or fetch_spotify_album_upc
    try:
        local = normalize_upc(fetch(gid))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Spotify UPC lookup for album %s failed: %s", gid, exc)
        return False
    return bool(local) and local == wanted


def verified_unlinked_album(
    candidates: Iterable[Any],
    deezer_album_id: int,
    deezer_upc_fetcher: Any = None,
    spotify_upc_fetcher: Any = None,
) -> Optional[Any]:
    """The one same-titled, unlinked local album proven to be this release.

    ``candidates`` (title/artist matches without a Deezer id) only rank
    possibilities; the UPC decides. Zero or several proven matches return
    ``None`` so the caller leaves the rows apart.
    """
    pool = [c for c in candidates if c.deezer_id is None]
    if not pool:
        return None
    fetch = deezer_upc_fetcher or fetch_deezer_album_upc
    try:
        deezer_upc = fetch(int(deezer_album_id))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Deezer UPC lookup for album %s failed: %s", deezer_album_id, exc)
        return None
    proven = [
        c
        for c in pool[:5]
        if album_matches_by_upc(c, deezer_album_id, deezer_upc, spotify_upc_fetcher)
    ]
    return proven[0] if len(proven) == 1 else None


ALBUM_EXISTS = "exists"
ALBUM_LINK = "link"
ALBUM_CREATE = "create"
ALBUM_SKIP = "skip"


def classify_deezer_album(
    artist: Any,
    deezer_album_id: int,
    album_name: str,
    normalize: Any,
    deezer_upc_fetcher: Any = None,
    spotify_upc_fetcher: Any = None,
) -> tuple[str, Optional[Album]]:
    """Decide what a Deezer album listing entry means for the local library.

    ``exists``: a row already carries this Deezer id. ``link``: an unlinked
    same-titled row is proven to be this release by UPC. ``skip``: unlinked
    same-titled rows exist but none is proven, so neither link nor duplicate
    (an operator or the UPC repair resolves it). ``create``: no unlinked
    same-titled row could be this release; same-titled rows that already carry
    a different Deezer id are other editions and never share this id.
    """
    existing = Album.objects.filter(deezer_id=deezer_album_id).first()
    if existing is not None:
        return ALBUM_EXISTS, existing
    wanted = normalize(album_name)
    unlinked = [
        a
        for a in Album.objects.filter(artist=artist, deezer_id__isnull=True)
        if normalize(a.name) == wanted
    ]
    if not unlinked:
        return ALBUM_CREATE, None
    proven = verified_unlinked_album(
        unlinked, deezer_album_id, deezer_upc_fetcher, spotify_upc_fetcher
    )
    if proven is not None:
        return ALBUM_LINK, proven
    logger.warning(
        "Deezer album %s %r matches unlinked local album(s) %s by title only; "
        "not linked (no UPC proof)",
        deezer_album_id,
        album_name,
        [a.pk for a in unlinked],
    )
    return ALBUM_SKIP, None


# Everything the classifier and UPC proof read: the artist and name that
# ranked the candidate, and the Spotify identity (gid, else uri) that was
# looked up. If any changes, the proof no longer describes this row.
_PROOF_FIELDS = ("artist_id", "name", "spotify_gid", "spotify_uri")


def link_album_deezer_id(album: Album, deezer_album_id: int) -> bool:
    """Attach ``deezer_album_id`` to ``album`` iff it is still what was proven.

    The UPC proof was made against a snapshot. Under a row lock the album must
    still be unlinked with the same Spotify gid and name, and the write is a
    conditional UPDATE, so a concurrent repair/import is never overwritten.
    False means a concurrent change (or the id being claimed elsewhere): the
    caller skips. On success ``album`` reflects the stored id.
    """
    try:
        with transaction.atomic():
            row = Album.objects.select_for_update().filter(pk=album.pk).first()
            if (
                row is None
                or row.deezer_id is not None
                or any(getattr(row, f) != getattr(album, f) for f in _PROOF_FIELDS)
            ):
                logger.info(
                    "Album %s changed since it was verified; not linking Deezer %s",
                    album.pk,
                    deezer_album_id,
                )
                return False
            pre_image = {f: getattr(album, f) for f in _PROOF_FIELDS}
            updated = Album.objects.filter(
                pk=album.pk, deezer_id__isnull=True, **pre_image
            ).update(deezer_id=deezer_album_id)
    except IntegrityError:
        logger.info("Deezer album %s was claimed by another row", deezer_album_id)
        return False
    if updated:
        album.deezer_id = deezer_album_id
    return bool(updated)


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
