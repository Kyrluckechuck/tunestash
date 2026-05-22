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

    song_inputs = [
        SongInput(
            song_id=c.song_id,
            net=sum(v.value for v in c.votes.all()),
        )
        for c in contributions
    ]

    knobs = CurveKnobs(
        base=playlist.base,
        p_floor=playlist.p_floor,
        t_high=playlist.t_high,
        t_low=playlist.t_low,
    )
    seed = secrets.randbits(63)
    result = materialize(
        song_inputs,
        knobs=knobs,
        min_size=playlist.min_size,
        max_size=playlist.max_size,
        seed=seed,
    )

    ordered = sorted(result.tracks, key=lambda t: t.position)
    return RollResult(
        song_ids=[t.song_id for t in ordered],
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
