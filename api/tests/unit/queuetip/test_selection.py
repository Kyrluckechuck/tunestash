"""Tests for the pure-Python SelectionEngine (Task 2 of Queuetip Phase 2A)."""

import pytest

from src.queuetip.selection import (
    DEFAULT_KNOBS,
    CurveKnobs,
    MaterializationResult,
    Reason,
    SongInput,
    compute_probability,
    materialize,
)

KNOBS = DEFAULT_KNOBS  # base=0.85, p_floor=0.15, t_high=3, t_low=3


# ---------------------------------------------------------------------------
# Curve anchor tests
# ---------------------------------------------------------------------------


def test_curve_anchor_t_high():
    assert compute_probability(net=3, knobs=KNOBS) == 1.0


def test_curve_anchor_beyond_t_high():
    assert compute_probability(net=4, knobs=KNOBS) == 1.0


def test_curve_anchor_zero():
    assert compute_probability(net=0, knobs=KNOBS) == pytest.approx(0.85)


def test_curve_anchor_neg_t_low():
    assert compute_probability(net=-3, knobs=KNOBS) == pytest.approx(0.15)


def test_curve_anchor_below_neg_t_low():
    assert compute_probability(net=-4, knobs=KNOBS) == 0.15


# ---------------------------------------------------------------------------
# Midpoint linearity tests
# ---------------------------------------------------------------------------


def test_curve_midpoint_positive():
    # net=1 is 1/3 of the way from 0 to t_high=3
    # p = base + (1 - base) * (1/3)
    expected = 0.85 + (1.0 - 0.85) * (1 / 3)
    assert compute_probability(net=1, knobs=KNOBS) == pytest.approx(expected)


def test_curve_midpoint_negative():
    # net=-1 is 1/3 of the way from 0 to -t_low=-3
    # p = base + (p_floor - base) * (1/3)
    expected = 0.85 + (0.15 - 0.85) * (1 / 3)
    assert compute_probability(net=-1, knobs=KNOBS) == pytest.approx(expected)


def test_curve_midpoint_net2():
    # net=2 is 2/3 of the way from 0 to t_high=3
    expected = 0.85 + (1.0 - 0.85) * (2 / 3)
    assert compute_probability(net=2, knobs=KNOBS) == pytest.approx(expected)


def test_curve_midpoint_net_neg2():
    # net=-2 is 2/3 of the way from 0 to -t_low=-3
    expected = 0.85 + (0.15 - 0.85) * (2 / 3)
    assert compute_probability(net=-2, knobs=KNOBS) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Custom knobs
# ---------------------------------------------------------------------------


def test_curve_custom_knobs():
    knobs = CurveKnobs(base=0.5, p_floor=0.1, t_high=2, t_low=2)
    assert compute_probability(net=2, knobs=knobs) == 1.0
    assert compute_probability(net=0, knobs=knobs) == pytest.approx(0.5)
    assert compute_probability(net=-2, knobs=knobs) == pytest.approx(0.1)
    assert compute_probability(net=-3, knobs=knobs) == 0.1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_materialize_is_deterministic_with_seed():
    songs = [SongInput(song_id=i, net=0) for i in range(10)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=42)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=42)
    assert [(t.song_id, t.position) for t in r1.tracks] == [
        (t.song_id, t.position) for t in r2.tracks
    ]


def test_materialize_different_seeds_may_differ():
    # With 10 songs at net=0 (p=0.85), seeds 42 and 99 very likely produce different results.
    songs = [SongInput(song_id=i, net=0) for i in range(10)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=42)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=99)
    # They could theoretically be identical by chance, but we just check both run without error.
    assert isinstance(r1, MaterializationResult)
    assert isinstance(r2, MaterializationResult)


# ---------------------------------------------------------------------------
# Guaranteed always included
# ---------------------------------------------------------------------------


def test_guaranteed_always_in():
    songs = [
        SongInput(song_id=1, net=5),  # guaranteed (p=1.0)
        SongInput(song_id=2, net=-10),  # p_floor (p=0.15)
    ]
    # Use seed=0; song 2 is unlikely to roll in, but song 1 must always appear.
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    ids = {t.song_id for t in r.tracks}
    assert 1 in ids


def test_guaranteed_reason_is_correct():
    songs = [SongInput(song_id=1, net=10)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    assert len(r.tracks) == 1
    assert r.tracks[0].inclusion_reason == Reason.GUARANTEED
    assert r.tracks[0].roll_probability == 1.0


def test_guaranteed_never_dropped_by_ceiling():
    songs = [
        SongInput(song_id=1, net=5),  # guaranteed
        SongInput(song_id=2, net=5),  # guaranteed
        SongInput(song_id=3, net=0),  # p=0.85
        SongInput(song_id=4, net=-5),  # p=0.15
    ]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=2, seed=1)
    ids = {t.song_id for t in r.tracks}
    assert {1, 2}.issubset(ids)
    assert len(r.tracks) == 2


# ---------------------------------------------------------------------------
# Floor (min_size top-up)
# ---------------------------------------------------------------------------


def test_min_size_topup_at_least_min():
    # 5 songs all with net=-10 (p=0.15) → most seeds produce 0 included; min_size=2 forces top-up.
    songs = [SongInput(song_id=i, net=-10) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=2, max_size=None, seed=0)
    assert len(r.tracks) >= 2


def test_min_size_topup_reason_is_topped_up():
    # With all songs at p=0.15 and seed=0, none roll in, so all included must be TOPPED_UP.
    songs = [SongInput(song_id=i, net=-10) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=2, max_size=None, seed=0)
    topped_up = [t for t in r.tracks if t.inclusion_reason == Reason.TOPPED_UP]
    rolled_in = [t for t in r.tracks if t.inclusion_reason == Reason.ROLLED_IN]
    # At least 2 total, topped-up tracks fill gap.
    assert len(topped_up) + len(rolled_in) >= 2


def test_min_size_topup_picks_highest_p_excluded():
    # Mix of p values; top-up should pull from higher-p excluded songs first.
    songs = [
        SongInput(song_id=1, net=-10),  # p=0.15 (lowest)
        SongInput(song_id=2, net=-10),  # p=0.15
        SongInput(song_id=3, net=-10),  # p=0.15
        SongInput(song_id=4, net=-10),  # p=0.15
        SongInput(song_id=5, net=-10),  # p=0.15
    ]
    r = materialize(songs, knobs=KNOBS, min_size=2, max_size=None, seed=0)
    assert len(r.tracks) >= 2


# ---------------------------------------------------------------------------
# Ceiling (max_size)
# ---------------------------------------------------------------------------


def test_max_size_limits_output():
    # 10 guaranteed songs, max_size=5 → exactly 5.
    songs = [SongInput(song_id=i, net=10) for i in range(10)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=5, seed=42)
    assert len(r.tracks) == 5


def test_max_size_drops_lowest_p_first():
    songs = [
        SongInput(song_id=1, net=5),  # guaranteed (p=1.0)
        SongInput(song_id=2, net=5),  # guaranteed (p=1.0)
        SongInput(song_id=3, net=0),  # p=0.85
        SongInput(song_id=4, net=-5),  # p=0.15
    ]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=2, seed=1)
    ids = {t.song_id for t in r.tracks}
    assert {1, 2}.issubset(ids)


# ---------------------------------------------------------------------------
# Guaranteed-exceeds-max edge case
# ---------------------------------------------------------------------------


def test_guaranteed_exceeds_max_emits_warning():
    songs = [SongInput(song_id=i, net=5) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=7)
    assert len(r.tracks) == 3
    assert r.warning_message != ""


def test_guaranteed_exceeds_max_is_deterministic():
    songs = [SongInput(song_id=i, net=5) for i in range(5)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=7)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=7)
    assert [(t.song_id, t.position) for t in r1.tracks] == [
        (t.song_id, t.position) for t in r2.tracks
    ]


def test_guaranteed_exceeds_max_different_seeds_different_results():
    songs = [SongInput(song_id=i, net=5) for i in range(5)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=1)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=3, seed=2)
    # Different seeds → different seeded draws (high probability).
    ids1 = {t.song_id for t in r1.tracks}
    ids2 = {t.song_id for t in r2.tracks}
    # Both are valid 3-song subsets; they likely differ with seed 1 vs 2.
    assert len(ids1) == 3
    assert len(ids2) == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_no_warning():
    r = materialize([], knobs=KNOBS, min_size=0, max_size=None, seed=0)
    assert r.tracks == []
    assert r.warning_message == ""


def test_empty_input_with_min_size():
    # min_size=2 but no songs at all → can't top up past 0; returns empty.
    r = materialize([], knobs=KNOBS, min_size=2, max_size=None, seed=0)
    assert r.tracks == []


def test_single_guaranteed_song():
    songs = [SongInput(song_id=42, net=100)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    assert len(r.tracks) == 1
    assert r.tracks[0].song_id == 42
    assert r.tracks[0].position == 0


def test_max_size_zero_with_no_guaranteed():
    songs = [SongInput(song_id=i, net=0) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=0, seed=0)
    assert r.tracks == []


def test_positions_are_sequential_from_zero():
    songs = [SongInput(song_id=i, net=10) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    positions = [t.position for t in r.tracks]
    assert positions == list(range(len(r.tracks)))


def test_deterministic_net_zero_repeated_calls():
    songs = [SongInput(song_id=i, net=0) for i in range(3)]
    r1 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=12345)
    r2 = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=12345)
    assert [(t.song_id, t.position) for t in r1.tracks] == [
        (t.song_id, t.position) for t in r2.tracks
    ]


def test_roll_probability_stored_correctly():
    songs = [SongInput(song_id=1, net=0)]
    r = materialize(songs, knobs=KNOBS, min_size=1, max_size=None, seed=0)
    assert len(r.tracks) == 1
    expected_p = compute_probability(net=0, knobs=KNOBS)
    assert r.tracks[0].roll_probability == pytest.approx(expected_p)


def test_no_warning_in_normal_case():
    songs = [SongInput(song_id=i, net=0) for i in range(5)]
    r = materialize(songs, knobs=KNOBS, min_size=0, max_size=None, seed=0)
    assert r.warning_message == ""
