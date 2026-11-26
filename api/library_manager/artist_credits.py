"""Turn provider artist credits into Artist rows and song contributors.

Only artists whose provider id appears in source-confirmed per-track credits
become contributors. The track's lead becomes ``primary_artist``; a tracked
discography artist is *not* added when absent from the source, because
contributor rows are matcher identity evidence.

Artists are matched by provider id first. When the incoming id is unknown but a
same-name row exists without that provider's id (e.g. a Spotify-only artist
meeting its Deezer credit), the id is attached **only** with independent
evidence: a song already linked to that row shares an ISRC with the credited
track. Without evidence nothing is created and the credit is reported as
ambiguous, so a second row never splits an artist's tracking and discography.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Optional, cast

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q

from src.providers.metadata_base import ArtistCredit, TrackResult

from .models import Album, Artist, ContributingArtist, Song, TrackingTier

if TYPE_CHECKING:
    from src.providers.deezer import DeezerMetadataProvider

logger = logging.getLogger(__name__)

MIN_DISTINCTIVE_NAME_LENGTH = 5
_TRACK_CACHE_LIMIT = 4096
_track_cache: dict[int, TrackResult] = {}
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


# (field, row pk, provider value) pairs already proven to be the same artist,
# and (pair, evidence) combinations already proven *not* to be, with a short TTL
# because new songs can later supply the missing link.
_verified_pairs: set[tuple[str, int, str, frozenset[int]]] = set()
_unverified_pairs: dict[tuple[str, int, str, frozenset[int], frozenset[str]], float] = (
    {}
)
_UNVERIFIED_TTL_SECONDS = 600.0
_MEMO_LIMIT = 8192


def clear_track_cache() -> None:
    _track_cache.clear()
    _verified_pairs.clear()
    _unverified_pairs.clear()


def normalize_artist_name(name: str) -> str:
    return _NON_ALNUM.sub("", name.casefold())


def is_ambiguous_artist_name(name: str) -> bool:
    """True when ``name`` cannot safely identify one artist on its own."""
    clean = (name or "").strip()
    if len(normalize_artist_name(clean)) < MIN_DISTINCTIVE_NAME_LENGTH:
        return True
    return Artist.objects.filter(name__iexact=clean).count() > 1


def _find_by_ids(deezer_id: int | None, gid: str | None) -> Optional[Artist]:
    if deezer_id:
        existing = Artist.objects.filter(deezer_id=deezer_id).first()
        if existing:
            return existing
    if gid:
        return Artist.objects.filter(gid=gid).first()
    return None


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one credit.

    ``status`` is ``found`` (matched by id), ``adopted`` (id attached to a
    verified same-name row), ``created``, ``ambiguous`` (unverified same-name
    row; ``artist`` is None), ``unanchored`` (credit carries no id) or, when
    ``create=False``, ``would_adopt`` / ``would_create``.
    """

    artist: Optional[Artist]
    status: str


def _normalized_isrcs(isrcs: Iterable[Optional[str]]) -> frozenset[str]:
    return frozenset(i.strip().upper() for i in isrcs if i and i.strip())


def related_song_ids(
    song_id: Optional[int] = None, deezer_id: Optional[int] = None
) -> frozenset[int]:
    """The song being corrected plus every song that is not independent of it.

    Songs sharing its file or its Deezer/Spotify track id are the same recording
    under another row, so none of them may vouch for an artist identity.
    """
    query = Q()
    if song_id is not None:
        row = (
            Song.objects.filter(pk=song_id)
            .values("file_path_ref_id", "deezer_id", "gid")
            .first()
        ) or {}
        query |= Q(pk=song_id)
        if row.get("file_path_ref_id"):
            query |= Q(file_path_ref_id=row["file_path_ref_id"])
        if row.get("deezer_id"):
            query |= Q(deezer_id=row["deezer_id"])
        if row.get("gid"):
            query |= Q(gid=row["gid"])
        deezer_id = deezer_id or row.get("deezer_id")
    if deezer_id:
        query |= Q(deezer_id=deezer_id)
    if not query:
        return frozenset()
    return frozenset(Song.objects.filter(query).values_list("pk", flat=True))


def _linked_by_isrc(
    candidate: Artist,
    isrcs: frozenset[str],
    exclude_song_ids: frozenset[int] = frozenset(),
) -> bool:
    """True if a *different* song attached to ``candidate`` carries an ISRC."""
    if not isrcs:
        return False
    return (
        Song.objects.filter(Q(isrc__in=isrcs) | Q(alternate_isrcs__overlap=list(isrcs)))
        .exclude(pk__in=exclude_song_ids)
        .filter(
            Q(primary_artist=candidate)
            | Exists(
                ContributingArtist.objects.filter(
                    song_id=OuterRef("pk"), artist=candidate
                )
            )
        )
        .exists()
    )


def _verified(
    field: str,
    candidate: Artist,
    value: str,
    isrcs: frozenset[str],
    exclude: frozenset[int] = frozenset(),
) -> bool:
    """Independent identity check for (row, provider artist), memoized.

    The memo key includes the excluded songs, so a positive found for one song
    can never vouch for the same pair while correcting another.
    """
    pair = (field, candidate.pk, value, exclude)
    if pair in _verified_pairs:
        return True
    now = time.monotonic()
    negative = (*pair, isrcs)
    if now - _unverified_pairs.get(negative, -_UNVERIFIED_TTL_SECONDS) < (
        _UNVERIFIED_TTL_SECONDS
    ):
        return False
    if _linked_by_isrc(candidate, isrcs, exclude):
        if len(_verified_pairs) >= _MEMO_LIMIT:
            _verified_pairs.clear()
        _verified_pairs.add(pair)
        return True
    if len(_unverified_pairs) >= _MEMO_LIMIT:
        _unverified_pairs.clear()
    _unverified_pairs[negative] = now
    return False


def _attach_id(candidate: Artist, field: str, value: Any) -> bool:
    """Conditionally set the provider id; False if another writer got there."""
    try:
        with transaction.atomic():
            return bool(
                Artist.objects.filter(
                    pk=candidate.pk, **{f"{field}__isnull": True}
                ).update(**{field: value})
            )
    except IntegrityError:
        return False  # the incoming id was claimed by another row meanwhile


def _link_namesake(
    field: str,
    value: Any,
    clean: str,
    isrcs: frozenset[str],
    enabled: bool,
    exclude: frozenset[int] = frozenset(),
) -> Optional[Resolution]:
    """Use an ISRC-linked tracked namesake instead of creating a new row."""
    if field != "deezer_id":
        return None
    namesake = _tracked_namesake(clean, int(value), isrcs, exclude)
    if namesake is not None and enabled:
        return Resolution(namesake, "linked_namesake")
    return None


def _adopt_same_name(
    field: str,
    value: Any,
    clean: str,
    isrcs: frozenset[str],
    create: bool,
    link_tracked_namesakes: bool = False,
    exclude: frozenset[int] = frozenset(),
) -> Optional[Resolution]:
    """Handle unlinked same-name rows; None means there are no candidates.

    Returns ``ambiguous`` unless exactly one candidate is verified by an
    independent ISRC link, then ``adopted`` / ``would_adopt``; ``retry`` means
    another writer attached an id to the candidate first.
    """
    if not clean:
        return None
    candidates = list(
        Artist.objects.filter(
            name__iexact=clean, **{f"{field}__isnull": True}
        ).order_by("pk")[:5]
    )
    if not candidates:
        return _link_namesake(
            field, value, clean, isrcs, link_tracked_namesakes, exclude
        )
    verified = [
        c for c in candidates if _verified(field, c, str(value), isrcs, exclude)
    ]
    if len(verified) != 1:
        logger.warning(
            "ambiguous_artist_identity: %r (%s=%s) matches %d unlinked "
            "same-name row(s) %s with %d verified; no row created",
            clean,
            field,
            value,
            len(candidates),
            [c.pk for c in candidates],
            len(verified),
        )
        return Resolution(None, "ambiguous")
    if not create:
        return Resolution(verified[0], "would_adopt")
    if _attach_id(verified[0], field, value):
        verified[0].refresh_from_db()
        return Resolution(verified[0], "adopted")
    return Resolution(None, "retry")


def same_name_different_id(primary: Artist, credit: ArtistCredit) -> bool:
    """True when ``credit`` names the same artist as ``primary`` under another id.

    Deezer often has duplicate pages for one artist, so a song whose primary
    already carries a different Deezer id but the same normalized name is left
    where it is rather than pulled to a new row.
    """
    return (
        primary.deezer_id is not None
        and credit.deezer_id is not None
        and primary.deezer_id != credit.deezer_id
        and normalize_artist_name(primary.name) == normalize_artist_name(credit.name)
    )


def _tracked_namesake(
    clean: str,
    deezer_id: int,
    isrcs: frozenset[str],
    exclude: frozenset[int] = frozenset(),
) -> Optional[Artist]:
    """A tracked same-name row with another Deezer id, if ISRC-linked.

    Logs every same-name/different-id situation; returns the row only when
    exactly one tracked namesake is tied to the credited track by an ISRC.
    """
    namesakes = list(
        Artist.objects.filter(name__iexact=clean, deezer_id__isnull=False)
        .exclude(deezer_id=deezer_id)
        .order_by("pk")[:5]
    )
    if not namesakes:
        return None
    linked = [
        n
        for n in namesakes
        if n.tracking_tier >= TrackingTier.TRACKED
        and _linked_by_isrc(n, isrcs, exclude)
    ]
    logger.warning(
        "same_name_different_id: %r (deezer_id=%s) vs existing row(s) %s "
        "(tracked and ISRC-linked: %s)",
        clean,
        deezer_id,
        [(n.pk, n.deezer_id, n.tracking_tier) for n in namesakes],
        [n.pk for n in linked],
    )
    return linked[0] if len(linked) == 1 else None


def resolve_credit(
    name: str,
    deezer_id: int | None = None,
    gid: str | None = None,
    *,
    evidence_isrcs: Iterable[Optional[str]] = (),
    tier: int = TrackingTier.UNTRACKED,
    create: bool = True,
    link_tracked_namesakes: bool = False,
    exclude_song_ids: frozenset[int] = frozenset(),
) -> Resolution:
    """Resolve a provider credit to an Artist without creating duplicates.

    With ``link_tracked_namesakes`` (new songs only), a tracked same-name row
    carrying another Deezer id is used instead of creating a new row when an
    ISRC links it to the credited track (status ``linked_namesake``).

    With ``create=False`` nothing is written; the status says what would
    happen. A same-name row lacking this provider's id is adopted only when
    ``evidence_isrcs`` link it to the credited track; with no such evidence the
    credit is ``ambiguous`` and no row is created.
    """
    if not deezer_id and not gid:
        return Resolution(None, "unanchored")
    field, value = ("deezer_id", deezer_id) if deezer_id else ("gid", gid)
    isrcs = _normalized_isrcs(evidence_isrcs)
    clean = (name or "").strip()

    for _attempt in range(2):  # the second pass handles a lost adoption race
        existing = _find_by_ids(deezer_id, gid)
        if existing is not None:
            return Resolution(existing, "found")

        adoption = _adopt_same_name(
            field, value, clean, isrcs, create, link_tracked_namesakes, exclude_song_ids
        )
        if adoption is not None and adoption.status != "retry":
            return adoption
        if adoption is not None:
            continue  # lost the race: re-evaluate from the top

        if not create:
            return Resolution(None, "would_create")
        try:
            with transaction.atomic():
                created = Artist.objects.create(
                    name=clean or "Unknown Artist",
                    tracking_tier=tier,
                    **{field: value},
                )
            return Resolution(created, "created")
        except IntegrityError:
            continue  # a concurrent ingest created it first
    return Resolution(_find_by_ids(deezer_id, gid), "found")


def resolve_artist(
    name: str,
    deezer_id: int | None = None,
    gid: str | None = None,
    *,
    evidence_isrcs: Iterable[Optional[str]] = (),
    tier: int = TrackingTier.UNTRACKED,
    create: bool = True,
) -> Optional[Artist]:
    """``resolve_credit`` returning only the Artist (None when ambiguous)."""
    return resolve_credit(
        name,
        deezer_id=deezer_id,
        gid=gid,
        evidence_isrcs=evidence_isrcs,
        tier=tier,
        create=create,
    ).artist


def _listing_credit(track: TrackResult) -> list[ArtistCredit]:
    if not track.artist_deezer_id and not track.artist_name:
        return []
    return [
        ArtistCredit(
            name=track.artist_name,
            deezer_id=track.artist_deezer_id,
            role="main",
        )
    ]


def lead_first(
    credits: list[ArtistCredit], lead_deezer_id: int | None = None
) -> list[ArtistCredit]:
    """Order credits lead first; the one rule shared by ingestion and backfill.

    The lead is the credit the provider names as the track artist
    (``lead_deezer_id``); failing that, the first credit with role "main";
    failing that, the first credit. The rest keep their provider order.
    """
    index = None
    if lead_deezer_id:
        index = next(
            (i for i, c in enumerate(credits) if c.deezer_id == lead_deezer_id), None
        )
    if index is None:
        index = next((i for i, c in enumerate(credits) if c.role == "main"), 0)
    if index == 0 or not credits:
        return list(credits)
    return [credits[index], *credits[:index], *credits[index + 1 :]]


def fetch_full_track(
    deezer_id: int, provider: "DeezerMetadataProvider | Any | None" = None
) -> Optional[TrackResult]:
    """Single-track lookup (the only Deezer response that lists contributors).

    Cached per process; the provider's client is already rate limited.
    """
    cached = _track_cache.get(deezer_id)
    if cached is not None:
        return cached
    if provider is None:
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
    full = provider.get_track(deezer_id)
    if isinstance(full, TrackResult):
        if len(_track_cache) >= _TRACK_CACHE_LIMIT:
            _track_cache.clear()
        _track_cache[deezer_id] = full
    return full


def credits_for_track(
    track: TrackResult,
    *,
    fetch_missing: bool = True,
    provider: "DeezerMetadataProvider | Any | None" = None,
    listing_fallback: bool = True,
) -> list[ArtistCredit]:
    """Every credit on ``track``, lead first.

    Listing responses carry only the lead artist, so a lookup is made when the
    track has no credits of its own. With ``listing_fallback`` a failed lookup
    degrades to the listing lead (acceptable for a brand-new song). Reconciling
    an existing song must pass ``listing_fallback=False`` so a failed or empty
    enrichment yields ``[]`` and can never replace verified credits.
    """
    credits = list(track.credits)
    if not credits and fetch_missing and track.deezer_id:
        try:
            full = fetch_full_track(track.deezer_id, provider)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Deezer credit lookup failed for track %s: %s", track.deezer_id, exc
            )
            full = None
        if isinstance(full, TrackResult):
            credits = list(full.credits)
    if not credits:
        return _listing_credit(track) if listing_fallback else []
    return lead_first(credits, track.artist_deezer_id)


def source_credit_for(song: Song) -> str:
    """Build the matcher's source credit from this track's own artists.

    Ordered lead first, then contributors in id order. The album's artist is
    deliberately not included, and provider search results are never used as
    evidence about the source's credits.
    """
    primary = cast(Artist, song.primary_artist)
    lead = primary.name
    names = list(
        ContributingArtist.objects.filter(song=song)
        .exclude(artist=primary)
        .order_by("artist_id")
        .values_list("artist__name", flat=True)
    )
    return ", ".join([lead, *names])


def replace_contributors(song: Song, artists: Iterable[Artist]) -> None:
    """Set the exact source-confirmed contributor set, purging stale rows."""
    wanted = {a.pk for a in artists if a is not None and a.pk is not None}
    for stale in ContributingArtist.objects.filter(song=song).exclude(
        artist_id__in=wanted
    ):
        stale.delete()
    for artist_id in wanted:
        ContributingArtist.objects.get_or_create(song=song, artist_id=artist_id)


def record_contributors(song: Song, artists: Iterable[Optional[Artist]]) -> None:
    """Link artists to a song; never removes existing links."""
    seen: set[int] = set()
    for artist in artists:
        if artist is None or artist.pk in seen:
            continue
        seen.add(artist.pk)
        ContributingArtist.objects.get_or_create(song=song, artist=artist)


def resolve_credits(
    credits: list[ArtistCredit],
    evidence_isrcs: Iterable[Optional[str]] = (),
    *,
    create: bool = True,
    link_tracked_namesakes: bool = False,
    exclude_song_ids: frozenset[int] = frozenset(),
) -> list[Resolution]:
    """Resolve each credit (see ``resolve_credit``), preserving order."""
    isrcs = _normalized_isrcs(evidence_isrcs)
    return [
        resolve_credit(
            c.name,
            deezer_id=c.deezer_id,
            gid=getattr(c, "gid", None),
            evidence_isrcs=isrcs,
            create=create,
            link_tracked_namesakes=link_tracked_namesakes,
            exclude_song_ids=exclude_song_ids,
        )
        for c in credits
    ]


def _complete_credits(credits: list[ArtistCredit]) -> bool:
    """True when every credit is anchored by a provider id."""
    return bool(credits) and all(
        c.deezer_id is not None or getattr(c, "gid", None) for c in credits
    )


def identity_snapshot(song_id: int) -> tuple[Optional[int], frozenset[int]]:
    """The identity pre-image: primary artist id and contributor artist ids."""
    primary = (
        Song.objects.filter(pk=song_id).values_list("primary_artist_id", flat=True)
    ).first()
    contributors = frozenset(
        ContributingArtist.objects.filter(song_id=song_id).values_list(
            "artist_id", flat=True
        )
    )
    return primary, contributors


def replace_identity_if_unchanged(
    song_id: int,
    expected: tuple[Optional[int], frozenset[int]],
    credits: list[ArtistCredit],
    evidence_isrcs: Iterable[Optional[str]] = (),
) -> str:
    """Swap primary + contributors if, and only if, the pre-image still holds.

    Artists are resolved *inside* the same transaction and only after the
    guarded check, so a stale plan creates nothing, and an ambiguous credit
    rolls back any row created or adopted for the same plan. Returns
    ``applied``, ``changed`` (pre-image differs), ``ambiguous`` or
    ``same_name_different_id`` (the primary is a same-name namesake of the lead;
    the song is left alone).
    """
    with transaction.atomic():
        locked = Song.objects.select_for_update().filter(pk=song_id).first()
        if locked is None or identity_snapshot(song_id) != expected:
            return "changed"
        primary = Artist.objects.filter(pk=expected[0]).first()
        if primary is not None and same_name_different_id(primary, credits[0]):
            logger.warning(
                "same_name_different_id: song %s keeps %r; credited lead %r has "
                "deezer_id=%s",
                song_id,
                primary.name,
                credits[0].name,
                credits[0].deezer_id,
            )
            return "same_name_different_id"
        resolutions = resolve_credits(
            credits, evidence_isrcs, exclude_song_ids=related_song_ids(song_id)
        )
        if any(r.artist is None for r in resolutions):
            transaction.set_rollback(True)
            return "ambiguous"
        artists = [cast(Artist, r.artist) for r in resolutions]
        Song.objects.filter(pk=song_id).update(primary_artist=artists[0])
        replace_contributors(locked, artists)
    return "applied"


def _song_isrcs(song: Song) -> list[Optional[str]]:
    return [song.isrc, *(song.alternate_isrcs or [])]


def ensure_song_credits(song: Song, credits: list[ArtistCredit]) -> bool:
    """Reconcile an existing song from complete, source-confirmed credits.

    An empty or partial payload, an ambiguous artist, or a concurrent identity
    change leaves the song untouched. Returns True when identity was updated.
    """
    if not _complete_credits(credits):
        return False
    expected = identity_snapshot(song.pk)
    outcome = replace_identity_if_unchanged(
        song.pk, expected, credits, _song_isrcs(song)
    )
    if outcome != "applied":
        logger.info("Song %s credits left unchanged (%s)", song.pk, outcome)
        return False
    song.refresh_from_db(fields=["primary_artist"])
    return True


def create_song_with_credits(
    track: TrackResult,
    *,
    album: Optional[Album] = None,
    fetch_missing: bool = True,
    provider: "DeezerMetadataProvider | Any | None" = None,
) -> Optional[Song]:
    """Create a Song whose primary artist is the track's lead, with credits.

    Returns None (and creates nothing) when the source supplies no resolvable
    lead, or when the lead is ambiguous against an existing same-name artist.
    An ambiguous non-lead credit is skipped and logged. Identity is never
    inferred from the tracked/discography artist.
    """
    credits = credits_for_track(track, fetch_missing=fetch_missing, provider=provider)
    with transaction.atomic():
        resolutions = resolve_credits(
            credits,
            [track.isrc],
            link_tracked_namesakes=True,
            exclude_song_ids=related_song_ids(deezer_id=track.deezer_id),
        )
        if not resolutions or resolutions[0].artist is None:
            logger.warning(
                "No resolvable lead for Deezer track %s (%s); song not created",
                track.deezer_id,
                resolutions[0].status if resolutions else "no credits",
            )
            transaction.set_rollback(True)
            return None
        for credit, resolution in zip(credits, resolutions):
            if resolution.artist is None:
                logger.warning(
                    "Skipping contributor %r on Deezer track %s: %s",
                    credit.name,
                    track.deezer_id,
                    resolution.status,
                )
        artists = [r.artist for r in resolutions if r.artist is not None]
        song = Song.objects.create(
            name=track.name,
            deezer_id=track.deezer_id,
            isrc=track.isrc,
            primary_artist=artists[0],
            album=album,
        )
        replace_contributors(song, artists)
    return song
