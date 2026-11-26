# mypy: disable-error-code=attr-defined
# mypy: disable-error-code=arg-type
"""Repair Song.deezer_id values that point at another release of the recording.

Songs are per album, so each release of one recording has its own Deezer track
id. A stored id that belongs to a different release (the artist's EP, a
compilation, another edition) makes credits and metadata describe the wrong
release. The correct id is the track on the song's *own* Deezer album whose
ISRC (or alternate ISRC) matches, disambiguated by disc/track number when the
ISRC repeats on that release. An ISRC or name lookup is never used: those return
whichever release Deezer indexed first.

Dry-run by default with a categorized summary. ``--apply`` requires a new
``--audit-file`` (mode 0600) holding the full old/new values; each batch's plan
is fsynced before its writes and a per-song ``complete`` record follows the
commit. Each write is ``UPDATE ... WHERE deezer_id = <old>`` guarded by the full
selection pre-image, so a concurrent change is skipped, never overwritten.
Only ``deezer_id`` is ever written: shared ``Album`` rows are never mutated
(``--fix-albums`` is refused), file paths and download state are untouched.
Release identity is verified by UPC by default; a song whose release cannot be
authoritatively resolved is reported and skipped.
"""

from __future__ import annotations

import json
import os
import stat
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from library_manager.models import Album, Song
from library_manager.release_ids import (
    SELECT_AMBIGUOUS,
    SELECT_FOUND,
    select_release_track,
)
from src.providers.metadata_base import TrackResult

REPAIRABLE = "repairable"
REPAIRABLE_ALBUM_FIX = "repairable_album_fix"
ALREADY_CORRECT = "already_correct"
SKIP_NO_ALBUM = "skip_no_album"
SKIP_NO_ISRC = "skip_no_isrc"
SKIP_ALBUM_UNRESOLVABLE = "skip_album_unresolvable"
SKIP_ALBUM_NOT_ON_DEEZER = "skip_album_not_on_deezer"
SKIP_ALBUM_MISMATCH = "skip_album_mismatch"
SKIP_NO_MATCHING_TRACK = "skip_no_matching_track"
SKIP_RECORDING_MISMATCH = "skip_recording_mismatch"
SKIP_AMBIGUOUS = "skip_ambiguous_candidates"
SKIP_DUPLICATE = "skip_duplicate_on_album"
SKIP_LOOKUP_FAILED = "skip_lookup_failed"
SKIP_CHANGED = "skip_changed_concurrently"
SKIP_UNVERIFIED_RELEASE = "skip_unverified_release"
SKIP_ALBUM_UNCHANGED = "album_correction_reported_only"

# May succeed on a later run, so the resume cursor never passes them.
RETRYABLE = frozenset({SKIP_LOOKUP_FAILED, SKIP_CHANGED})
# Deezer error code for a deleted/unknown album.
NO_DATA_CODE = 800
MEMORY_ALBUM_LIMIT = 4000


class AlbumMissing(Exception):
    """Deezer has no such album (deleted or region-locked)."""


class LookupFailed(Exception):
    """A transient provider error; the song is retried on a later run."""


@dataclass
class SongPlan:
    song_id: int
    name: str
    status: str
    isrc: Optional[str] = None
    alternate_isrcs: list[str] = field(default_factory=list)
    album_id: Optional[int] = None
    old_deezer_id: Optional[int] = None
    new_deezer_id: Optional[int] = None
    old_album_deezer_id: Optional[int] = None
    new_album_deezer_id: Optional[int] = None  # reported only; never applied
    album_spotify_gid: str = ""
    expected_album_deezer_id: Optional[int] = None
    target_album_deezer_id: Optional[int] = None
    old_id_album_deezer_id: Optional[int] = None
    candidate_ids: list[int] = field(default_factory=list)
    duplicate_song_ids: list[int] = field(default_factory=list)
    held_elsewhere_song_ids: list[int] = field(default_factory=list)
    detail: str = ""

    @property
    def is_repairable(self) -> bool:
        return self.status == REPAIRABLE


def _norm_upc(value: Optional[str]) -> str:
    """Canonical UPC/EAN for *comparison*: strip spaces and leading zeros.

    Only digits are accepted; an empty or non-digit value is not a UPC and
    never authorizes a release match (it is reported instead).
    """
    text = (value or "").strip()
    if not text.isdigit():
        return ""
    return text.lstrip("0") or "0"


def _valid_upc(value: Optional[str]) -> bool:
    """True for a plausible UPC/EAN: 8, 12, 13 or 14 digits only.

    A strict GS1 check digit is deliberately not enforced: some Spotify UPCs
    carry a final digit that does not match a computed checksum, and rejecting
    them would cause mass false negatives on real releases.
    """
    text = (value or "").strip()
    return text.isdigit() and len(text) in (8, 12, 13, 14)


def _spotify_album_gid(album: Album) -> str:
    if album.spotify_gid:
        return str(album.spotify_gid).rsplit(":", 1)[-1]
    if album.spotify_uri:
        return str(album.spotify_uri).rsplit(":", 1)[-1]
    return ""


def _is_no_data(exc: BaseException) -> bool:
    payload = exc.args[0] if exc.args else None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("code") == NO_DATA_CODE:
            return True
    return type(exc).__name__ == "DeezerNotFoundError"


class Command(BaseCommand):
    help = (
        "Point each song's deezer_id at the track on its own Deezer album. "
        "Dry-run by default; --apply requires a new --audit-file."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None
        self._spotify: Any = None
        self._sleep = 0.0
        self._calls: Counter[str] = Counter()
        self._albums: dict[str, dict[str, Any]] = {}
        self._sp_upc: dict[str, str] = {}
        self._upc_album: dict[str, Optional[int]] = {}
        self._seed: dict[str, Any] = {}
        self._persist = False
        self._examples: dict[str, list[SongPlan]] = {}
        self._show = 10

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-file")
        parser.add_argument("--song", type=int, action="append", default=[])
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--limit", type=int, default=0, help="Max songs (0=all)")
        parser.add_argument("--after-id", type=int, default=0, help="Resume point")
        parser.add_argument(
            "--sleep", type=float, default=0.25, help="Seconds between provider calls"
        )
        parser.add_argument(
            "--cache-file", help="JSON cache of album track lists (written)"
        )
        parser.add_argument(
            "--seed-cache",
            help="Read-only JSON cache (e.g. the credits cache) used only to report "
            "which album a song's current id belongs to",
        )
        parser.add_argument(
            "--show", type=int, default=10, help="Examples shown per category"
        )
        parser.add_argument("--downloaded-only", action="store_true")
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry ids recorded as failed in --audit-file",
        )

    # -- provider access (patched in tests) ------------------------------

    def _throttle(self, kind: str) -> None:
        if self._calls and self._sleep:
            time.sleep(self._sleep)
        self._calls[kind] += 1

    def _deezer(self) -> Any:
        import deezer  # pylint: disable=import-outside-toplevel

        if self._client is None:
            self._client = deezer.Client()
        return self._client

    def _fetch_album(self, album_id: int) -> tuple[list[TrackResult], Optional[str]]:
        """One Deezer album with its track list and UPC."""
        from src.providers.deezer import (  # pylint: disable=import-outside-toplevel
            _to_track_result,
        )

        try:
            album = self._deezer().get_album(album_id)
            upc = getattr(album, "upc", None)
            tracks = [_to_track_result(t) for t in album.get_tracks()]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if _is_no_data(exc):
                raise AlbumMissing(str(album_id)) from exc
            raise LookupFailed(str(exc)) from exc
        return tracks, upc

    def _fetch_album_id_by_upc(self, upc: str) -> Optional[int]:
        import deezer  # pylint: disable=import-outside-toplevel

        try:
            raw = self._deezer().request(
                "GET", f"album/upc:{upc}", resource_type=deezer.Album
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if _is_no_data(exc):
                return None
            raise LookupFailed(str(exc)) from exc
        return int(raw.id) if raw is not None and getattr(raw, "id", None) else None

    def _spotify_client(self) -> Any:
        if self._spotify is None:
            from downloader.spotipy_tasks import (  # pylint: disable=import-outside-toplevel
                PublicSpotifyClient,
            )

            self._spotify = PublicSpotifyClient().sp
        return self._spotify

    def _fetch_spotify_upc(self, gid: str) -> Optional[str]:
        client = self._spotify_client()
        if client is None:
            return None
        try:
            album = dict(client.album(gid) or {})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise LookupFailed(str(exc)) from exc
        return (album.get("external_ids") or {}).get("upc")

    def _fetch_spotify_position(
        self, gid: str
    ) -> Optional[tuple[Optional[int], Optional[int]]]:
        client = self._spotify_client()
        if client is None:
            return None
        try:
            track = dict(client.track(gid) or {})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise LookupFailed(str(exc)) from exc
        return track.get("disc_number"), track.get("track_number")

    # -- caches ----------------------------------------------------------

    def _load_json(self, path: Optional[str]) -> dict[str, Any]:
        if path and Path(path).exists():
            return dict(json.loads(Path(path).read_text(encoding="utf-8")))
        return {}

    def _save_cache(self, path: Optional[str]) -> None:
        if not path:
            return
        tmp = f"{path}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "albums": self._albums,
                    "sp_upc": self._sp_upc,
                    "upc_album": self._upc_album,
                },
                handle,
            )
        os.replace(tmp, path)

    def _album_entry(self, album_id: int) -> dict[str, Any]:
        key = str(album_id)
        entry = self._albums.get(key)
        if entry is not None:
            return entry
        self._throttle("deezer_album")
        try:
            tracks, upc = self._fetch_album(album_id)
        except AlbumMissing:
            entry = {"missing": True}
        else:
            entry = {
                "upc": upc,
                "tracks": [
                    {
                        "id": t.deezer_id,
                        "isrc": t.isrc,
                        "disc": t.disc_number,
                        "pos": t.track_number,
                        "title": t.name,
                    }
                    for t in tracks
                ],
            }
        self._albums[key] = entry
        if not self._persist and len(self._albums) > MEMORY_ALBUM_LIMIT:
            self._albums.pop(next(iter(self._albums)))
        return entry

    @staticmethod
    def _entry_tracks(entry: dict[str, Any]) -> list[TrackResult]:
        return [
            TrackResult(
                name=t.get("title") or "",
                artist_name="",
                deezer_id=t["id"],
                isrc=t.get("isrc"),
                track_number=t.get("pos"),
                disc_number=t.get("disc"),
            )
            for t in entry.get("tracks", [])
        ]

    def _spotify_upc_for(self, gid: str) -> str:
        """The UPC as Spotify returns it (used verbatim for Deezer lookups)."""
        if gid not in self._sp_upc:
            self._throttle("spotify_album")
            self._sp_upc[gid] = (self._fetch_spotify_upc(gid) or "").strip()
        return self._sp_upc[gid]

    @staticmethod
    def _upc_variants(upc: str) -> list[str]:
        """Raw, canonical and zero-padded 12/13-digit forms of a valid UPC."""
        if not _valid_upc(upc):
            return []
        canonical = _norm_upc(upc)
        return list(
            dict.fromkeys(
                [
                    upc,
                    canonical,
                    canonical.zfill(12),
                    canonical.zfill(13),
                ]
            )
        )

    def _album_by_upc(self, upc: str) -> Optional[int]:
        """Deezer album for a UPC; both sides use the same canonical form."""
        if upc not in self._upc_album:
            found: Optional[int] = None
            for variant in self._upc_variants(upc):
                self._throttle("deezer_upc")
                found = self._fetch_album_id_by_upc(variant)
                if found is not None:
                    break
            self._upc_album[upc] = found
        return self._upc_album[upc]

    # -- planning --------------------------------------------------------

    def _candidates(self, options: dict[str, Any], after_id: int) -> Any:
        qs = Song.objects.filter(deezer_id__isnull=False)
        if options["song"]:
            qs = qs.filter(id__in=options["song"])
        if options["downloaded_only"]:
            qs = qs.filter(downloaded=True)
        return qs.filter(id__gt=after_id).select_related("album")

    def _resolve_album(  # pylint: disable=too-many-return-statements
        self, song: Song, plan: SongPlan
    ) -> Optional[int]:
        """Authoritatively resolve the Deezer album holding this song's track.

        UPC verification is mandatory: a stored ``Album.deezer_id`` is only a
        hint. When the album row has a Spotify gid, the Deezer album's UPC must
        match the Spotify album's UPC (canonical comparison) or the row is
        reported as unverifiable and no id is written. No Spotify gid means the
        release cannot be checked against an independent authority, so the song
        is skipped even if the album has a Deezer id. A potential album
        correction is *reported only* — shared Album rows are never mutated.
        """
        album = song.album
        current = album.deezer_id
        gid = _spotify_album_gid(album)
        plan.album_spotify_gid = gid
        if not gid:
            plan.status = SKIP_UNVERIFIED_RELEASE
            plan.detail = (
                f"album {album.pk} has no Spotify gid; release identity cannot "
                "be independently verified by UPC"
            )
            return None
        sp_upc = self._spotify_upc_for(gid)
        if not _valid_upc(sp_upc):
            plan.status = SKIP_UNVERIFIED_RELEASE
            plan.detail = f"Spotify album {gid} has no valid UPC ({sp_upc!r})"
            return None
        authoritative = self._album_by_upc(sp_upc)
        if authoritative is None:
            plan.status = SKIP_ALBUM_UNRESOLVABLE
            plan.detail = f"no Deezer album for Spotify album {gid} (UPC {sp_upc})"
            return None
        if current is None:
            plan.status = SKIP_ALBUM_UNCHANGED
            plan.new_album_deezer_id = authoritative
            plan.detail = (
                f"album {album.pk} has no Deezer id; correct release would be "
                f"{authoritative} (left unchanged; shared albums are not mutated)"
            )
            return None
        if int(current) != authoritative:
            plan.status = SKIP_ALBUM_UNCHANGED
            plan.new_album_deezer_id = authoritative
            plan.detail = (
                f"album {album.pk} points at Deezer album {current}, but UPC "
                f"{sp_upc} resolves to {authoritative} (left unchanged; shared "
                "albums are not mutated)"
            )
            return None
        # UPCs agree: the stored album id is now independently confirmed.
        plan.expected_album_deezer_id = authoritative
        return authoritative

    def _plan_song(self, song: Song) -> SongPlan:
        album = song.album
        plan = SongPlan(
            song_id=song.pk,
            name=song.name,
            status="unplanned",
            isrc=song.isrc,
            alternate_isrcs=list(song.alternate_isrcs or []),
            album_id=album.pk if album else None,
            old_deezer_id=song.deezer_id,
            old_album_deezer_id=album.deezer_id if album else None,
        )
        seeded = self._seed.get(str(song.deezer_id))
        if isinstance(seeded, dict):
            plan.old_id_album_deezer_id = seeded.get("album_deezer_id")
        if album is None:
            plan.status = SKIP_NO_ALBUM
            return plan
        if not (song.isrc or song.alternate_isrcs):
            plan.status = SKIP_NO_ISRC
            return plan
        try:
            return self._plan_on_album(song, plan)
        except LookupFailed as exc:
            plan.status = SKIP_LOOKUP_FAILED
            plan.detail = str(exc)[:200]
            return plan

    def _plan_on_album(  # pylint: disable=too-many-return-statements
        self, song: Song, plan: SongPlan
    ) -> SongPlan:
        target = self._resolve_album(song, plan)
        if target is None:
            return plan
        plan.target_album_deezer_id = target
        entry = self._album_entry(target)
        if entry.get("missing"):
            plan.status = SKIP_ALBUM_NOT_ON_DEEZER
            plan.detail = f"Deezer album {target} returned no data"
            return plan

        tracks = self._entry_tracks(entry)
        selection = select_release_track(song, tracks)
        if selection.status == SELECT_AMBIGUOUS and song.gid:
            self._throttle("spotify_track")
            position = self._fetch_spotify_position(song.gid)
            selection = select_release_track(song, tracks, position)
        if selection.status == SELECT_AMBIGUOUS:
            plan.status = SKIP_AMBIGUOUS
            plan.candidate_ids = list(selection.candidate_ids)
            return plan
        if selection.status != SELECT_FOUND or selection.track is None:
            on_album = {t.deezer_id for t in tracks}
            if song.deezer_id in on_album:
                plan.status = SKIP_RECORDING_MISMATCH
                plan.detail = (
                    "current id is a track on this album with a different ISRC; "
                    "use repair_song_identity"
                )
            else:
                plan.status = SKIP_NO_MATCHING_TRACK
                plan.detail = f"no track with ISRC {song.isrc} on album {target}"
            return plan

        new_id = int(selection.track.deezer_id)
        plan.new_deezer_id = new_id
        if new_id == song.deezer_id and plan.new_album_deezer_id is None:
            plan.status = ALREADY_CORRECT
            return plan
        duplicates = list(
            Song.objects.filter(album_id=song.album_id, deezer_id=new_id)
            .exclude(pk=song.pk)
            .values_list("pk", flat=True)
        )
        if duplicates:
            plan.status = SKIP_DUPLICATE
            plan.duplicate_song_ids = duplicates
            plan.detail = "another song on this album already holds that id"
            return plan
        plan.held_elsewhere_song_ids = list(
            Song.objects.filter(deezer_id=new_id)
            .exclude(album_id=song.album_id)
            .values_list("pk", flat=True)[:5]
        )
        plan.status = REPAIRABLE
        return plan

    # -- applying --------------------------------------------------------

    def _apply_plan(  # pylint: disable=too-many-return-statements
        self, plan: SongPlan
    ) -> str:
        """Conditionally write one song's deezer_id using the full pre-image.

        All provider calls happened while planning, outside this transaction:
        the locks here are held only for the short DB recheck and write. Lock
        order is always song -> album; no other writer in this codebase locks
        an Album before a Song (there were no Album row locks at all before
        this command), so there is no known inverse-order deadlock path. Every
        field used to select the new id is checked while both rows are locked
        and repeated in the guarded UPDATE, so a concurrent identity change is
        either blocked until commit or makes the update affect zero rows.
        """
        if not plan.is_repairable:
            return plan.status
        if plan.new_deezer_id == plan.old_deezer_id:
            return plan.status
        try:
            with transaction.atomic():
                locked = list(Song.objects.select_for_update().filter(pk=plan.song_id))
                if not locked:
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
                song = locked[0]
                # Lock the album in a separate statement after the song lock.
                # PostgreSQL rejects FOR UPDATE on a nullable outer join, so a
                # joined song+album lock is not possible. The order is always
                # song -> album, matching the other identity writers in this
                # codebase (none of which lock an Album first), so there is no
                # known reverse-order path to deadlock against. Both row locks
                # stay held for the rest of this transaction, including the
                # UPDATE below. No provider call happens under either lock.
                album = (
                    Album.objects.select_for_update().filter(pk=song.album_id).first()
                )
                # Re-freeze every field used in selection while both locks are
                # held; a concurrent album change cannot slip between this
                # check and the write.
                if not self._preimage_matches(plan, song, album):
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
                if (
                    Song.objects.filter(
                        album_id=plan.album_id, deezer_id=plan.new_deezer_id
                    )
                    .exclude(pk=plan.song_id)
                    .exists()
                ):
                    transaction.set_rollback(True)
                    return SKIP_DUPLICATE
                updated = Song.objects.filter(
                    pk=plan.song_id,
                    deezer_id=plan.old_deezer_id,
                    album_id=plan.album_id,
                    isrc=plan.isrc,
                    alternate_isrcs=plan.alternate_isrcs,
                ).update(deezer_id=plan.new_deezer_id)
                if updated != 1:
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
        except IntegrityError:
            return SKIP_DUPLICATE
        return plan.status

    @staticmethod
    def _preimage_matches(plan: SongPlan, song: Song, album: Optional[Album]) -> bool:
        """True when the locked row still matches everything the plan relied on."""
        if album is None or album.pk != plan.album_id:
            return False
        if song.deezer_id != plan.old_deezer_id or song.isrc != plan.isrc:
            return False
        if sorted(song.alternate_isrcs or []) != sorted(plan.alternate_isrcs):
            return False
        if album.deezer_id != plan.expected_album_deezer_id:
            return False
        if _spotify_album_gid(album) != plan.album_spotify_gid:
            return False
        return True

    def _write_and_sync(self, handle: Any, record: dict[str, Any]) -> None:
        handle.write(json.dumps(record, cls=DjangoJSONEncoder) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    # -- entry point -----------------------------------------------------

    def handle(self, *args: Any, **options: Any) -> None:
        apply = options["apply"]
        audit_file = options["audit_file"]
        if apply and not audit_file:
            raise CommandError("--apply requires --audit-file")
        if not apply and audit_file:
            raise CommandError("--audit-file only applies with --apply")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        self._sleep = options["sleep"]
        self._calls = Counter()
        self._show = options["show"]
        self._examples = {}
        self._persist = bool(options["cache_file"])
        cached = self._load_json(options["cache_file"])
        self._albums = dict(cached.get("albums", {}))
        self._sp_upc = dict(cached.get("sp_upc", {}))
        self._upc_album = dict(cached.get("upc_album", {}))
        self._seed = self._load_json(options["seed_cache"])
        pending_failed = (
            set(self._failed_ids(audit_file)) if options["retry_failed"] else set()
        )

        audit_handle = self._open_audit(options, apply, audit_file)
        counts: Counter[str] = Counter()
        processed = 0
        scan_id = committed_id = options["after_id"]
        blocked = False
        limit = options["limit"]
        self.stdout.write(
            "APPLY" if apply else "DRY RUN — no changes made, no audit file written"
        )
        try:
            batches = 0
            while True:
                size = options["batch_size"]
                if limit:
                    size = min(size, limit - processed)
                    if size <= 0:
                        break
                if pending_failed:
                    batch = list(
                        Song.objects.filter(id__in=pending_failed)
                        .select_related("album")
                        .order_by("id")[:size]
                    )
                else:
                    batch = list(
                        self._candidates(options, scan_id).order_by("id")[:size]
                    )
                if not batch:
                    break
                plans = [self._plan_song(song) for song in batch]
                processed += len(batch)
                scan_id = max(scan_id, batch[-1].pk)

                if audit_handle is not None:
                    for plan in plans:
                        audit_handle.write(
                            json.dumps(
                                {"record": "plan", **asdict(plan)},
                                cls=DjangoJSONEncoder,
                            )
                            + "\n"
                        )
                    audit_handle.flush()
                    os.fsync(audit_handle.fileno())

                for plan in plans:
                    outcome = self._apply_plan(plan) if apply else plan.status
                    counts[outcome] += 1
                    if plan.old_id_album_deezer_id is not None and (
                        plan.target_album_deezer_id is not None
                        and plan.old_id_album_deezer_id != plan.target_album_deezer_id
                    ):
                        counts["old_id_on_other_release_seeded"] += 1
                    if plan.held_elsewhere_song_ids and plan.is_repairable:
                        counts["new_id_also_on_other_album_rows"] += 1
                    self._remember(plan, outcome)
                    pending_failed.discard(plan.song_id)
                    failed = outcome in RETRYABLE
                    blocked = blocked or failed
                    if not blocked:
                        committed_id = max(committed_id, plan.song_id)
                    if audit_handle is not None:
                        self._write_and_sync(
                            audit_handle,
                            {
                                "record": "failed" if failed else "complete",
                                "song_id": plan.song_id,
                                "outcome": outcome,
                                "cursor": committed_id,
                            },
                        )
                batches += 1
                if batches % 20 == 0:
                    self._save_cache(options["cache_file"])
                self.stdout.write(f"batch done; committed_id={committed_id}")
        finally:
            self._save_cache(options["cache_file"])
            if audit_handle is not None:
                audit_handle.close()

        self._summary(counts, processed, committed_id)

    def _open_audit(
        self, options: dict[str, Any], apply: bool, audit_file: Optional[str]
    ) -> Any:
        if not apply or audit_file is None:
            return None
        path = Path(audit_file)
        if path.exists() and not options["retry_failed"]:
            raise CommandError(f"audit file already exists: {path}")
        if options["retry_failed"] and path.exists():
            return open(
                path, "a", encoding="utf-8"
            )  # pylint: disable=consider-using-with
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        self._write_and_sync(
            handle,
            {
                "record": "header",
                "command": "repair_release_ids",
                "after_id": options["after_id"],
                "batch_size": options["batch_size"],
                "verify_by_upc": True,
                "albums_mutated": False,
            },
        )
        return handle

    @staticmethod
    def _failed_ids(audit_file: Optional[str]) -> list[int]:
        if not audit_file or not Path(audit_file).exists():
            return []
        ids = []
        for line in Path(audit_file).read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record") == "failed":
                ids.append(int(record["song_id"]))
        return ids

    def _remember(self, plan: SongPlan, outcome: str) -> None:
        if outcome == ALREADY_CORRECT:
            return
        bucket = self._examples.setdefault(outcome, [])
        if len(bucket) < self._show:
            bucket.append(plan)

    def _describe(self, plan: SongPlan) -> str:
        parts = [
            f"song {plan.song_id} {plan.name!r} isrc={plan.isrc}",
            f"album_row={plan.album_id}",
            f"deezer_id {plan.old_deezer_id} (on album {plan.old_id_album_deezer_id})"
            f" -> {plan.new_deezer_id}",
            f"album.deezer_id {plan.old_album_deezer_id}"
            f" (UPC-verified {plan.expected_album_deezer_id})",
        ]
        if plan.new_album_deezer_id is not None:
            parts.append(
                f"potential album correction (reported only): "
                f"{plan.new_album_deezer_id}"
            )
        if plan.candidate_ids:
            parts.append(f"candidates={plan.candidate_ids}")
        if plan.duplicate_song_ids:
            parts.append(f"duplicate_songs={plan.duplicate_song_ids}")
        if plan.detail:
            parts.append(plan.detail)
        return "; ".join(parts)

    def _summary(self, counts: Counter[str], processed: int, cursor: int) -> None:
        self.stdout.write(f"songs examined: {processed}")
        self.stdout.write(
            "provider calls: "
            + ", ".join(f"{k}={v}" for k, v in sorted(self._calls.items()))
        )
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")
        self.stdout.write(
            f"repairable: {counts[REPAIRABLE]} "
            "(song deezer_id only; shared Album rows are never mutated)"
        )
        for status in sorted(self._examples):
            self.stdout.write(f"examples [{status}]:")
            for plan in self._examples[status]:
                self.stdout.write(f"  {self._describe(plan)}")
        self.stdout.write(f"resume with --after-id {cursor}")
