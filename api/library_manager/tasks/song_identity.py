"""Shared guards against attaching a Deezer track to a different recording."""

from typing import Any

from library_manager.models import Song

from .core import logger


def _normalize(isrc: str | None) -> str:
    return isrc.strip().upper() if isrc else ""


def isrc_is_compatible(song: Song, candidate_isrc: str | None) -> bool:
    """True when a candidate ISRC agrees with the song's known recording(s).

    A blank candidate carries no identity evidence. An existing ISRC that is
    absent from both ``isrc`` and ``alternate_isrcs`` is a hard conflict: the
    candidate describes a different recording even when title/artist match.
    """
    candidate = _normalize(candidate_isrc)
    if not candidate:
        return True
    known = {
        _normalize(song.isrc),
        *(_normalize(i) for i in song.alternate_isrcs or ()),
    }
    known.discard("")
    if not known:
        return True
    return candidate in known


def apply_identifier_updates(
    song: Song, updates: dict[str, Any], extra_fields: tuple[str, ...] = ()
) -> None:
    """Persist computed identifier updates on ``song`` in one narrow write."""
    fields = [*updates, *extra_fields]
    if not fields:
        return
    for field, value in updates.items():
        setattr(song, field, value)
    song.save(update_fields=fields)


def identifier_updates(
    song: Song, candidate_deezer_id: int | None, candidate_isrc: str | None
) -> dict[str, Any]:
    """Compute safe identifier backfills for ``song`` from a Deezer track.

    Existing identifiers are never replaced. A missing deezer_id is filled only
    when the song's ISRCs agree with the candidate; a missing ISRC is filled
    only when the song has no deezer_id or the candidate is that same track.
    """
    updates: dict[str, Any] = {}
    if candidate_deezer_id and not song.deezer_id:
        if isrc_is_compatible(song, candidate_isrc):
            updates["deezer_id"] = candidate_deezer_id
        else:
            logger.info(
                "song_id=%s isrc conflict with deezer track %s "
                "(song isrc=%s candidate isrc=%s); skipping deezer_id",
                song.id,
                candidate_deezer_id,
                song.isrc,
                candidate_isrc,
            )
    if candidate_isrc and not song.isrc:
        if not song.deezer_id or song.deezer_id == candidate_deezer_id:
            updates["isrc"] = candidate_isrc
        else:
            logger.info(
                "song_id=%s deezer_id conflict %s vs candidate %s; skipping isrc %s",
                song.id,
                song.deezer_id,
                candidate_deezer_id,
                candidate_isrc,
            )
    return updates
