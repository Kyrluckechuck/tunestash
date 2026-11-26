# mypy: disable-error-code=attr-defined
# mypy: disable-error-code=arg-type
"""Repair ``Album.deezer_id`` values that point at the wrong Deezer release.

The Spotify album UPC is the authoritative release key: Deezer indexes some
UPCs zero-padded, so both sides are compared in canonical form (as in
``repair_release_ids``). A UPC lookup alone is not enough — a reissue can share
a UPC with a different edition — so the resolved Deezer album's title, artist
and track count must also agree with the Spotify album before an id is written.

Songs are never touched. After an album fix its songs become repairable by
``repair_release_ids``. A Deezer id already held by another Album row is
reported as a possible duplicate album and never merged.

Dry-run by default; ``--apply`` requires a new ``--audit-file`` (mode 0600),
written and fsynced before each batch and after each conditional write.
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

from library_manager.models import Album

REPAIRABLE = "repairable"
ALREADY_CORRECT = "already_correct"
SKIP_NO_GID = "skip_no_spotify_gid"
SKIP_NO_UPC = "skip_no_valid_upc"
SKIP_UNRESOLVABLE = "skip_album_unresolvable"
SKIP_METADATA_MISMATCH = "skip_deezer_metadata_mismatch"
SKIP_DUPLICATE = "skip_duplicate_album"
SKIP_LOOKUP_FAILED = "skip_lookup_failed"
SKIP_CHANGED = "skip_changed_concurrently"

RETRYABLE = frozenset({SKIP_LOOKUP_FAILED, SKIP_CHANGED})
NO_DATA_CODE = 800


class LookupFailed(Exception):
    """A transient provider error; the album is retried on a later run."""


@dataclass
class AlbumPlan:
    album_id: int
    name: str
    status: str
    old_deezer_id: Optional[int] = None
    new_deezer_id: Optional[int] = None
    spotify_gid: str = ""
    upc: str = ""
    resolved_from_upc: Optional[int] = None
    deezer_title: str = ""
    deezer_artist: str = ""
    deezer_tracks: Optional[int] = None
    spotify_title: str = ""
    spotify_artist: str = ""
    spotify_tracks: Optional[int] = None
    duplicate_album_ids: list[int] = field(default_factory=list)
    detail: str = ""

    @property
    def is_repairable(self) -> bool:
        return self.status == REPAIRABLE


def norm_upc(value: Optional[str]) -> str:
    """Canonical UPC/EAN for comparison: digits only, no leading zeros."""
    text = (value or "").strip()
    if not text.isdigit():
        return ""
    return text.lstrip("0") or "0"


def valid_upc(value: Optional[str]) -> bool:
    """A plausible UPC/EAN: 8, 12, 13 or 14 digits (as in repair_release_ids)."""
    text = (value or "").strip()
    return text.isdigit() and len(text) in (8, 12, 13, 14)


def norm_text(value: Optional[str]) -> str:
    return (value or "").strip().casefold()


def names_agree(spotify: str, deezer: str) -> bool:
    """Compare a Spotify album credit with a Deezer one, ignoring credit order.

    Deezer sometimes folds featured artists into the lead credit, so substring
    agreement in either direction is enough (the same rule used by
    ``repair_song_identity`` when matching album artists).
    """
    left, right = norm_text(spotify), norm_text(deezer)
    return bool(left and right and (left in right or right in left))


def metadata_agrees(plan: AlbumPlan) -> bool:
    """True when the UPC-resolved Deezer album is the same release as Spotify's."""
    if not names_agree(plan.spotify_title, plan.deezer_title):
        return False
    if not names_agree(plan.spotify_artist, plan.deezer_artist):
        return False
    # Deezer normally reports an exact track count. A missing count is not
    # evidence of agreement, so it must not authorize a write.
    if plan.spotify_tracks is None or plan.deezer_tracks is None:
        return False
    return int(plan.spotify_tracks) == int(plan.deezer_tracks)


class Command(BaseCommand):
    help = (
        "Repair Album.deezer_id from the Spotify album UPC, with title/artist/"
        "track-count verification. Dry-run by default; --apply requires a new "
        "--audit-file. Songs are never changed."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None
        self._spotify: Any = None
        self._sleep = 0.0
        self._calls: Counter[str] = Counter()
        self._sp_album: dict[str, dict[str, Any]] = {}
        self._upc_album: dict[str, Optional[int]] = {}
        self._dz_album: dict[str, dict[str, Any]] = {}
        self._show = 10
        self._examples: dict[str, list[AlbumPlan]] = {}

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-file")
        parser.add_argument("--album", type=int, action="append", default=[])
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--limit", type=int, default=0, help="Max albums (0=all)")
        parser.add_argument("--after-id", type=int, default=0, help="Resume point")
        parser.add_argument(
            "--sleep", type=float, default=0.25, help="Seconds between provider calls"
        )
        parser.add_argument(
            "--cache-file", help="JSON cache of Spotify/Deezer lookups (written)"
        )
        parser.add_argument(
            "--seed-cache", help="Read-only JSON cache used to warm lookups"
        )
        parser.add_argument(
            "--show", type=int, default=10, help="Examples shown per category"
        )
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

    def _spotify_client(self) -> Any:
        if self._spotify is None:
            from downloader.spotipy_tasks import (  # pylint: disable=import-outside-toplevel
                PublicSpotifyClient,
            )

            self._spotify = PublicSpotifyClient().sp
        return self._spotify

    def _fetch_spotify_album(self, gid: str) -> dict[str, Any]:
        client = self._spotify_client()
        if client is None:
            raise LookupFailed("Spotify client unavailable")
        try:
            return dict(client.album(gid) or {})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise LookupFailed(str(exc)) from exc

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

    def _fetch_deezer_album(self, album_id: int) -> dict[str, Any]:
        """Title, artist, track count and UPC of a Deezer album."""
        try:
            album = self._deezer().get_album(album_id)
            return {
                "title": getattr(album, "title", "") or "",
                "artist": getattr(album.artist, "name", "") if album.artist else "",
                "tracks": (
                    int(album.nb_tracks)
                    if getattr(album, "nb_tracks", None) is not None
                    else None
                ),
                "upc": getattr(album, "upc", None),
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if _is_no_data(exc):
                return {"missing": True}
            raise LookupFailed(str(exc)) from exc

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
                    "sp_album": self._sp_album,
                    "upc_album": self._upc_album,
                    "dz_album": self._dz_album,
                },
                handle,
            )
        os.replace(tmp, path)

    def _spotify_album(self, gid: str) -> dict[str, Any]:
        if gid not in self._sp_album:
            self._throttle("spotify_album")
            raw = self._fetch_spotify_album(gid)
            self._sp_album[gid] = {
                "name": raw.get("name") or "",
                "artist": ", ".join(
                    a.get("name") or ""
                    for a in (raw.get("artists") or [])
                    if a.get("name")
                ),
                "tracks": raw.get("total_tracks"),
                "upc": (raw.get("external_ids") or {}).get("upc"),
            }
        return self._sp_album[gid]

    @staticmethod
    def _upc_variants(upc: str) -> list[str]:
        if not valid_upc(upc):
            return []
        canonical = norm_upc(upc)
        return list(
            dict.fromkeys([upc, canonical, canonical.zfill(12), canonical.zfill(13)])
        )

    def _album_by_upc(self, upc: str) -> Optional[int]:
        """Deezer album id for a UPC. The resolved id is not trusted on its own."""
        if upc not in self._upc_album:
            found: Optional[int] = None
            for variant in self._upc_variants(upc):
                self._throttle("deezer_upc")
                found = self._fetch_album_id_by_upc(variant)
                if found is not None:
                    break
            self._upc_album[upc] = found
        return self._upc_album[upc]

    def _deezer_album(self, album_id: int) -> dict[str, Any]:
        key = str(album_id)
        if key not in self._dz_album:
            self._throttle("deezer_album")
            self._dz_album[key] = self._fetch_deezer_album(album_id)
        return self._dz_album[key]

    # -- planning --------------------------------------------------------

    def _candidates(self, options: dict[str, Any], after_id: int) -> Any:
        qs = Album.objects.all()
        if options["album"]:
            qs = qs.filter(id__in=options["album"])
        return qs.filter(id__gt=after_id).select_related("artist")

    @staticmethod
    def _gid(album: Album) -> str:
        if album.spotify_gid:
            return str(album.spotify_gid).rsplit(":", 1)[-1]
        if album.spotify_uri:
            return str(album.spotify_uri).rsplit(":", 1)[-1]
        return ""

    def _plan_album(  # pylint: disable=too-many-return-statements
        self, album: Album
    ) -> AlbumPlan:
        plan = AlbumPlan(
            album_id=album.pk,
            name=album.name,
            status="unplanned",
            old_deezer_id=album.deezer_id,
            spotify_gid=self._gid(album),
        )
        if not plan.spotify_gid:
            plan.status = SKIP_NO_GID
            plan.detail = "album has no Spotify gid; UPC verification is impossible"
            return plan
        try:
            sp = self._spotify_album(plan.spotify_gid)
        except LookupFailed as exc:
            plan.status = SKIP_LOOKUP_FAILED
            plan.detail = str(exc)[:200]
            return plan
        plan.spotify_title = sp.get("name", "")
        plan.spotify_artist = sp.get("artist", "")
        plan.spotify_tracks = sp.get("tracks")
        raw_upc = sp.get("upc")
        if not valid_upc(raw_upc):
            plan.status = SKIP_NO_UPC
            plan.detail = f"Spotify album {plan.spotify_gid} has no valid UPC"
            return plan
        plan.upc = str(raw_upc).strip()
        try:
            resolved = self._album_by_upc(plan.upc)
        except LookupFailed as exc:
            plan.status = SKIP_LOOKUP_FAILED
            plan.detail = str(exc)[:200]
            return plan
        if resolved is None:
            plan.status = SKIP_UNRESOLVABLE
            plan.detail = f"no Deezer album for UPC {plan.upc}"
            return plan
        plan.resolved_from_upc = resolved
        try:
            dz = self._deezer_album(resolved)
        except LookupFailed as exc:
            plan.status = SKIP_LOOKUP_FAILED
            plan.detail = str(exc)[:200]
            return plan
        if dz.get("missing"):
            plan.status = SKIP_UNRESOLVABLE
            plan.detail = f"Deezer album {resolved} returned no data"
            return plan
        plan.deezer_title = dz.get("title", "")
        plan.deezer_artist = dz.get("artist", "")
        plan.deezer_tracks = dz.get("tracks")
        if not metadata_agrees(plan):
            plan.status = SKIP_METADATA_MISMATCH
            plan.detail = (
                f"UPC {plan.upc} resolves to Deezer album {resolved} "
                f"({plan.deezer_title!r} / {plan.deezer_artist!r} / "
                f"{plan.deezer_tracks} tracks) which disagrees with Spotify "
                f"({plan.spotify_title!r} / {plan.spotify_artist!r} / "
                f"{plan.spotify_tracks} tracks)"
            )
            return plan
        if album.deezer_id is not None and int(album.deezer_id) == resolved:
            plan.status = ALREADY_CORRECT
            return plan
        # An id held by another album row is a possible duplicate album:
        # report it and leave both rows unchanged. Never merge.
        duplicates = list(
            Album.objects.filter(deezer_id=resolved)
            .exclude(pk=album.pk)
            .values_list("pk", flat=True)
        )
        if duplicates:
            plan.status = SKIP_DUPLICATE
            plan.duplicate_album_ids = duplicates
            plan.detail = (
                f"Deezer album {resolved} is already held by album row(s) "
                f"{duplicates}; possible duplicate album, not merged"
            )
            return plan
        plan.new_deezer_id = resolved
        plan.status = REPAIRABLE
        return plan

    # -- applying --------------------------------------------------------

    def _apply_plan(  # pylint: disable=too-many-return-statements
        self, plan: AlbumPlan
    ) -> str:
        """Conditionally write one album's deezer_id with the full pre-image."""
        if not plan.is_repairable:
            return plan.status
        if plan.new_deezer_id == plan.old_deezer_id:
            return plan.status
        try:
            with transaction.atomic():
                locked = list(
                    Album.objects.select_for_update().filter(pk=plan.album_id)
                )
                if not locked:
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
                album = locked[0]
                if (
                    album.deezer_id != plan.old_deezer_id
                    or self._gid(album) != plan.spotify_gid
                    or album.name != plan.name
                ):
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
                if (
                    Album.objects.filter(deezer_id=plan.new_deezer_id)
                    .exclude(pk=plan.album_id)
                    .exists()
                ):
                    transaction.set_rollback(True)
                    return SKIP_DUPLICATE
                updated = Album.objects.filter(
                    pk=plan.album_id, deezer_id=plan.old_deezer_id
                ).update(deezer_id=plan.new_deezer_id)
                if updated != 1:
                    transaction.set_rollback(True)
                    return SKIP_CHANGED
        except IntegrityError:
            return SKIP_DUPLICATE
        return plan.status

    @staticmethod
    def _write_and_sync(handle: Any, record: dict[str, Any]) -> None:
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
        seed = self._load_json(options["seed_cache"])
        cached = self._load_json(options["cache_file"])
        self._sp_album = {
            **dict(seed.get("sp_album", {})),
            **dict(cached.get("sp_album", {})),
        }
        self._upc_album = {
            **dict(seed.get("upc_album", {})),
            **dict(cached.get("upc_album", {})),
        }
        self._dz_album = {
            **dict(seed.get("dz_album", {})),
            **dict(cached.get("dz_album", {})),
        }
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
                        Album.objects.filter(id__in=pending_failed)
                        .select_related("artist")
                        .order_by("id")[:size]
                    )
                else:
                    batch = list(
                        self._candidates(options, scan_id).order_by("id")[:size]
                    )
                if not batch:
                    break
                plans = [self._plan_album(album) for album in batch]
                processed += len(batch)
                scan_id = max(scan_id, batch[-1].pk)

                if audit_handle is not None:
                    for plan in plans:
                        self._write_and_sync(
                            audit_handle, {"record": "plan", **asdict(plan)}
                        )

                for plan in plans:
                    outcome = self._apply_plan(plan) if apply else plan.status
                    counts[outcome] += 1
                    self._remember(plan, outcome)
                    pending_failed.discard(plan.album_id)
                    failed = outcome in RETRYABLE
                    blocked = blocked or failed
                    if not blocked:
                        committed_id = max(committed_id, plan.album_id)
                    if audit_handle is not None:
                        self._write_and_sync(
                            audit_handle,
                            {
                                "record": "failed" if failed else "complete",
                                "album_id": plan.album_id,
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
                "command": "repair_album_ids",
                "after_id": options["after_id"],
                "batch_size": options["batch_size"],
                "songs_mutated": False,
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
                ids.append(int(record["album_id"]))
        return ids

    def _remember(self, plan: AlbumPlan, outcome: str) -> None:
        if outcome == ALREADY_CORRECT:
            return
        bucket = self._examples.setdefault(outcome, [])
        if len(bucket) < self._show:
            bucket.append(plan)

    @staticmethod
    def _describe(plan: AlbumPlan) -> str:
        parts = [
            f"album {plan.album_id} {plan.name!r}",
            f"UPC {plan.upc} -> Deezer {plan.resolved_from_upc}",
            f"deezer_id {plan.old_deezer_id} -> {plan.new_deezer_id}",
        ]
        if plan.deezer_title:
            parts.append(
                f"Deezer {plan.deezer_title!r}/{plan.deezer_artist!r}/"
                f"{plan.deezer_tracks} tracks"
            )
            parts.append(
                f"Spotify {plan.spotify_title!r}/{plan.spotify_artist!r}/"
                f"{plan.spotify_tracks} tracks"
            )
        if plan.duplicate_album_ids:
            parts.append(f"duplicate_albums={plan.duplicate_album_ids}")
        if plan.detail:
            parts.append(plan.detail)
        return "; ".join(parts)

    def _summary(self, counts: Counter[str], processed: int, cursor: int) -> None:
        self.stdout.write(f"albums examined: {processed}")
        self.stdout.write(
            "provider calls: "
            + ", ".join(f"{k}={v}" for k, v in sorted(self._calls.items()))
        )
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")
        self.stdout.write(
            f"repairable: {counts[REPAIRABLE]} (Album.deezer_id only; songs "
            "are never changed and duplicate albums are never merged)"
        )
        for status in sorted(self._examples):
            self.stdout.write(f"examples [{status}]:")
            for plan in self._examples[status]:
                self.stdout.write(f"  {self._describe(plan)}")
        self.stdout.write(f"resume with --after-id {cursor}")


def _is_no_data(exc: BaseException) -> bool:
    payload = exc.args[0] if exc.args else None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("code") == NO_DATA_CODE:
            return True
    return type(exc).__name__ == "DeezerNotFoundError"
