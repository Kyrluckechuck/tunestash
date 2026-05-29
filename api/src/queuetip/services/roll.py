"""In-memory selection roll for a playlist's current contributions.

The "roll" is queuetip's core mechanic: given a playlist's contributions and
their net votes, the selection engine (`..selection.materialize`) produces a
randomized subset — songs with more upvotes are more likely to be included,
within the playlist's size bounds. Each roll uses a fresh random seed, so two
rolls of the same playlist differ. That's the feature: "give me a fresh mix."

This module exposes that as a pure function returning an ordered list of song
ids. The roll is ephemeral: push flows (Spotify, Subsonic) call this at push
time, send the result to the remote, and discard it — nothing persists the
rolled list. The target only records sync status and matched/total counts.

Sync (Django ORM, no async) — callers wrap in sync_to_async or run from
Celery as appropriate.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from queuetip.models import Account, Contribution, Playlist

from ..selection import CurveKnobs, SongInput, materialize


@dataclass
class RollResult:
    """An in-memory rolled selection. `song_ids` is ordered by the engine's
    chosen position; `warning_message` surfaces engine notes (e.g. "playlist
    smaller than min_size")."""

    song_ids: list[int]
    warning_message: str = ""
    seed: int = 0
    # Per-song detail for UI display ("rolled in" vs "guaranteed", probability).
    # Keyed by song_id. Optional — push flows ignore it; the UI may show it.
    detail: dict[int, dict] = field(default_factory=dict)


def roll_playlist(
    playlist: Playlist,
    *,
    account: Account | None = None,
    exclude_my_downvotes: bool = False,
    min_score_threshold: int | None = None,
    target_size_override: int | None = None,
    unique_versions_only: bool = False,
) -> RollResult:
    """Roll the selection engine over `playlist`'s current contributions.

    `account` + `exclude_my_downvotes`: when both are set, drop contributions
    the account downvoted before rolling (the "don't include songs I dislike"
    option). `account` is required for that filter to mean anything.
    """
    contributions = list(
        Contribution.objects.filter(playlist=playlist)
        .select_related("song")
        .prefetch_related("votes")
    )

    if exclude_my_downvotes and account is not None:
        contributions = [
            c
            for c in contributions
            if not any(
                v.account_id == account.id and v.value == -1 for v in c.votes.all()
            )
        ]

    song_inputs: list[SongInput] = []
    for contribution in contributions:
        net = sum(v.value for v in contribution.votes.all())
        if min_score_threshold is not None and net < min_score_threshold:
            continue
        song_inputs.append(
            SongInput(
                song_id=contribution.song_id,
                net=net,
            )
        )

    knobs = CurveKnobs(
        base=playlist.base,
        p_floor=playlist.p_floor,
        t_high=playlist.t_high,
        t_low=playlist.t_low,
    )
    seed = secrets.randbits(63)
    if target_size_override is not None:
        min_size = target_size_override
        max_size = target_size_override
    else:
        min_size = playlist.min_size
        max_size = playlist.max_size

    result = materialize(
        song_inputs,
        knobs=knobs,
        min_size=min_size,
        max_size=max_size,
        seed=seed,
    )

    ordered = sorted(result.tracks, key=lambda t: t.position)
    song_ids = [t.song_id for t in ordered]
    if unique_versions_only:
        song_ids = _dedupe_song_versions(song_ids)
    return RollResult(
        song_ids=song_ids,
        warning_message=result.warning_message,
        seed=seed,
        detail={
            t.song_id: {
                "inclusion_reason": t.inclusion_reason.value,
                "roll_probability": t.roll_probability,
            }
            for t in ordered
        },
    )


def _dedupe_song_versions(song_ids: list[int]) -> list[int]:
    """Keep only one song per normalized artist/title family, preserving order."""
    from library_manager.models import Song as SongModel

    if not song_ids:
        return song_ids
    from ..duplicates import song_family_key

    order = {sid: i for i, sid in enumerate(song_ids)}
    songs = sorted(
        SongModel.objects.filter(id__in=song_ids).select_related("primary_artist"),
        key=lambda song: order.get(song.id, 0),
    )
    keep: list[int] = []
    seen_families: set[tuple[str, str]] = set()
    for song in songs:
        artist_name = song.primary_artist.name if song.primary_artist_id else ""
        family = song_family_key(artist_name, song.name)
        if family in seen_families:
            continue
        seen_families.add(family)
        keep.append(song.id)
    return keep
