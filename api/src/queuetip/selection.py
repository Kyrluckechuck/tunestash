"""Pure-Python selection engine for Queuetip exports.

Deterministic given (inputs, knobs, seed). No DB, no async, no GraphQL —
fully unit-tested independently of the rest of the system.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Reason(str, Enum):
    GUARANTEED = "guaranteed"
    ROLLED_IN = "rolled_in"
    TOPPED_UP = "topped_up"


@dataclass(frozen=True)
class CurveKnobs:
    base: float = 0.85
    p_floor: float = 0.15
    t_high: int = 3
    t_low: int = 3


DEFAULT_KNOBS = CurveKnobs()


@dataclass(frozen=True)
class SongInput:
    song_id: int
    net: int


@dataclass(frozen=True)
class MaterializedTrack:
    song_id: int
    position: int
    inclusion_reason: Reason
    roll_probability: float


@dataclass(frozen=True)
class MaterializationResult:
    tracks: list[MaterializedTrack]
    warning_message: str


def compute_probability(*, net: int, knobs: CurveKnobs) -> float:
    """Piecewise-linear net → probability per the program spec."""
    if net >= knobs.t_high:
        return 1.0
    if net >= 0:
        # Linear from (0, base) to (t_high, 1.0).
        return knobs.base + (1.0 - knobs.base) * (net / knobs.t_high)
    if net > -knobs.t_low:
        # Linear from (0, base) to (-t_low, p_floor).
        return knobs.base + (knobs.p_floor - knobs.base) * ((-net) / knobs.t_low)
    return knobs.p_floor


def materialize(
    songs: list[SongInput],
    *,
    knobs: CurveKnobs,
    min_size: int,
    max_size: int | None,
    seed: int,
) -> MaterializationResult:
    """Roll → floor → ceiling → shuffle. See program spec for the algorithm."""
    if not songs:
        return MaterializationResult(tracks=[], warning_message="")

    rng = random.Random(seed)
    warning = ""

    # Compute probabilities once. Sort by song_id for stable order.
    annotated = sorted(
        ((s.song_id, compute_probability(net=s.net, knobs=knobs), s) for s in songs),
        key=lambda t: t[0],
    )

    guaranteed: list[tuple[int, float]] = [
        (sid, p) for sid, p, _ in annotated if p == 1.0
    ]
    non_guaranteed: list[tuple[int, float]] = [
        (sid, p) for sid, p, _ in annotated if p < 1.0
    ]

    # Edge: guaranteed alone exceed max_size — seeded weighted draw among them.
    if max_size is not None and len(guaranteed) > max_size:
        warning = (
            f"Guaranteed songs ({len(guaranteed)}) exceed max_size ({max_size}); "
            "a seeded weighted draw was made among the guaranteed set."
        )
        # All-equal weights since all are p=1.0 — uniform seeded sample.
        chosen = rng.sample(guaranteed, max_size)
        included: list[tuple[int, float, Reason]] = [
            (sid, 1.0, Reason.GUARANTEED) for sid, _ in chosen
        ]
    else:
        # Step 3 — roll non-guaranteed independently.
        included = [(sid, p, Reason.GUARANTEED) for sid, p in guaranteed]
        for sid, p in non_guaranteed:
            if rng.random() < p:
                included.append((sid, p, Reason.ROLLED_IN))

        included_ids = {sid for sid, _, _ in included}

        # Step 4 — floor: top up with highest-p excluded.
        if len(included) < min_size:
            excluded = sorted(
                [(sid, p) for sid, p in non_guaranteed if sid not in included_ids],
                key=lambda t: (-t[1], t[0]),  # highest p first, then song_id ascending
            )
            needed = min_size - len(included)
            for sid, p in excluded[:needed]:
                included.append((sid, p, Reason.TOPPED_UP))

        # Step 5 — ceiling: drop lowest-p non-guaranteed until ≤ max_size.
        if max_size is not None and len(included) > max_size:
            non_g = sorted(
                [t for t in included if t[2] != Reason.GUARANTEED],
                key=lambda t: (t[1], -t[0]),  # lowest p first, then song_id descending
            )
            g = [t for t in included if t[2] == Reason.GUARANTEED]
            slots_for_non_g = max(0, max_size - len(g))
            keep_non_g = (
                non_g[len(non_g) - slots_for_non_g :] if slots_for_non_g > 0 else []
            )
            included = g + keep_non_g

    # Step 6 — shuffle.
    rng.shuffle(included)

    tracks = [
        MaterializedTrack(
            song_id=sid, position=pos, inclusion_reason=reason, roll_probability=p
        )
        for pos, (sid, p, reason) in enumerate(included)
    ]
    return MaterializationResult(tracks=tracks, warning_message=warning)
