"""Duplicate classification helpers for Queuetip contributions.

This is intentionally advisory-only logic used for UI warnings and indicators.
No automatic merge/removal behavior is tied to these classifications.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from queuetip.models import Contribution

_VERSION_TOKEN_RE = re.compile(
    r"\b(remaster(?:ed)?|remix|mix|live|edit|radio edit|acoustic|version)\b",
    re.IGNORECASE,
)
_PAREN_RE = re.compile(r"\([^)]*\)")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_DASH_SUFFIX_RE = re.compile(r"\s[-–—]\s.*$")
_MULTISPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


@dataclass(frozen=True)
class DuplicateInfo:
    """Duplicate advisory details for one contribution."""

    kind: str  # "none" | "exact" | "alt_version"
    related_titles: list[str]


def normalize_song_text(value: str) -> str:
    value = value.lower().strip()
    value = _PAREN_RE.sub(" ", value)
    value = _BRACKET_RE.sub(" ", value)
    value = _DASH_SUFFIX_RE.sub("", value)
    value = _NON_ALNUM_RE.sub(" ", value)
    value = _VERSION_TOKEN_RE.sub(" ", value)
    return _MULTISPACE_RE.sub(" ", value).strip()


def _song_label(contribution: Contribution) -> str:
    song = contribution.song
    artist_name = song.primary_artist.name if song.primary_artist_id else ""
    return f"{artist_name} — {song.name}".strip(" —")


def song_family_key(artist: str, title: str) -> tuple[str, str]:
    """Return the normalized (artist, title-family) key for duplicate families."""
    return (normalize_song_text(artist), normalize_song_text(title))


def classify_playlist_duplicates(
    contributions: list[Contribution],
) -> dict[int, DuplicateInfo]:
    """Classify duplicates across a playlist contribution set."""
    by_gid: dict[str, list[Contribution]] = defaultdict(list)
    by_isrc: dict[str, list[Contribution]] = defaultdict(list)
    by_family: dict[tuple[str, str], list[Contribution]] = defaultdict(list)

    for contribution in contributions:
        song = contribution.song
        gid = (song.gid or "").strip()
        isrc = (song.isrc or "").strip().upper()
        artist = normalize_song_text(
            song.primary_artist.name if song.primary_artist_id else ""
        )
        title = normalize_song_text(song.name)
        if gid:
            by_gid[gid].append(contribution)
        if isrc:
            by_isrc[isrc].append(contribution)
        if artist and title:
            by_family[(artist, title)].append(contribution)

    exact_ids: set[int] = set()
    family_ids: set[int] = set()
    groups_for: dict[int, list[list[Contribution]]] = defaultdict(list)

    for group in by_gid.values():
        if len(group) > 1:
            for c in group:
                exact_ids.add(c.id)
                groups_for[c.id].append(group)
    for group in by_isrc.values():
        if len(group) > 1:
            for c in group:
                exact_ids.add(c.id)
                groups_for[c.id].append(group)
    for group in by_family.values():
        if len(group) > 1:
            for c in group:
                family_ids.add(c.id)
                groups_for[c.id].append(group)

    result: dict[int, DuplicateInfo] = {}
    for contribution in contributions:
        cid = contribution.id
        kind = "none"
        if cid in exact_ids:
            kind = "exact"
        elif cid in family_ids:
            kind = "alt_version"

        related: list[str] = []
        if kind != "none":
            seen = {cid}
            for group in groups_for.get(cid, []):
                for other in group:
                    if other.id in seen:
                        continue
                    seen.add(other.id)
                    related.append(_song_label(other))
            related = sorted(dict.fromkeys(related))

        result[cid] = DuplicateInfo(kind=kind, related_titles=related)
    return result
