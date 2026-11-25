# mypy: disable-error-code=attr-defined
# mypy: disable-error-code=no-any-return
"""Repair songs whose identifiers describe two different recordings.

Corrections come from run-time lookups: the song's Spotify gid identifies the
recording and its album; the Deezer album that *is that Spotify album* supplies
the per-album Deezer track id. An ISRC lookup alone is not enough — the same
recording appears on multiple albums, each with its own Deezer track id.
Dry-run by default; --apply requires a new audit file written before any write.
Merge mode (--merge-into KEEP:DROP) deletes DROP and refuses unless DROP is the
same recording (matching ISRC) on the same release (matching UPC) as KEEP.
"""

import json
import logging
import os
import stat
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import OneToOneField

from library_manager.models import (
    Album,
    Artist,
    ContributingArtist,
    PendingMetadataUpdate,
    Song,
)
from library_manager.tasks import TaskPriority

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackTruth:
    """Identity of the recording the song's gid describes, resolved per album."""

    title: str
    isrc: str
    deezer_track_id: int | None
    deezer_album_id: int | None
    artist_name: str
    artist_deezer_id: int | None
    all_artist_names: tuple[str, ...]
    duration_ms: int
    local_album_ok: bool
    reason: str | None
    sp_album_id: str | None = None
    sp_album_upc: str | None = None
    different_release: bool = False


@dataclass(frozen=True)
class AlbumIdentity:
    upc: str | None
    release_date: str | None
    label: str | None
    artist_name: str | None
    deezer_id: int | None


def fetch_album_identity(album: Any) -> AlbumIdentity:
    """Resolve an Album row's release identity read-only from its gid or Deezer id."""
    from downloader.spotipy_tasks import PublicSpotifyClient

    from src.providers.deezer import DeezerMetadataProvider

    spotify_album = None
    gid = ""
    if album.spotify_gid:
        gid = album.spotify_gid.rsplit(":", 1)[-1]
    elif getattr(album, "spotify_uri", None):
        gid = album.spotify_uri.rsplit(":", 1)[-1]
    if gid:
        client = PublicSpotifyClient()
        if client.sp is not None:
            try:
                spotify_album = dict(client.sp.album(gid) or {})
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Spotify album lookup failed for %s: %s", gid, exc)
    if spotify_album:
        return AlbumIdentity(
            upc=(spotify_album.get("external_ids") or {}).get("upc"),
            release_date=spotify_album.get("release_date"),
            label=spotify_album.get("label"),
            artist_name=", ".join(
                a.get("name") or "" for a in (spotify_album.get("artists") or [])
            ),
            deezer_id=album.deezer_id,
        )
    if album.deezer_id:
        try:
            track = DeezerMetadataProvider().get_album(album.deezer_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Deezer album lookup failed for %s: %s", album.deezer_id, exc)
            track = None
        if track:
            return AlbumIdentity(
                upc=None,
                release_date=track.release_date,
                label=track.label,
                artist_name=track.artist_name,
                deezer_id=album.deezer_id,
            )
    return AlbumIdentity(None, None, None, None, album.deezer_id)


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def fetch_truth(song: Song) -> TrackTruth:
    """Resolve a song through Spotify, then find *its album* on Deezer."""
    import deezer  # pylint: disable=import-error
    from downloader.spotipy_tasks import PublicSpotifyClient

    from src.providers.deezer import DeezerMetadataProvider

    if not song.gid or not song.isrc:
        raise CommandError(f"song {song.id} needs both gid and isrc for repair")
    spotify = PublicSpotifyClient()
    if spotify.sp is None:
        raise CommandError("Spotify client unavailable")
    try:
        sp_track = dict(spotify.sp.track(song.gid) or {})
        sp_album_id = ((sp_track.get("album") or {}).get("id")) or ""
        sp_album = dict(spotify.sp.album(sp_album_id) or {}) if sp_album_id else {}
    except Exception as exc:  # pylint: disable=broad-except
        raise CommandError(f"Spotify lookup for song {song.id} failed: {exc}") from exc

    sp_isrc = (sp_track.get("external_ids") or {}).get("isrc")
    if not sp_isrc or _norm(sp_isrc) != _norm(song.isrc):
        raise CommandError(
            f"song {song.id} ISRC {song.isrc} disagrees with Spotify {sp_isrc}"
        )
    track_number = sp_track.get("track_number") or 0
    upc = (sp_album.get("external_ids") or {}).get("upc")
    album_name = sp_album.get("name") or ""
    album_artists = [
        a.get("name") for a in (sp_album.get("artists") or []) if a.get("name")
    ]
    total_tracks = sp_album.get("total_tracks") or 0

    provider = DeezerMetadataProvider()
    candidates: dict[int, Any] = {}
    if upc:
        try:
            raw = provider.client.request(
                "GET", f"album/upc:{upc}", resource_type=deezer.Album
            )
            if raw and getattr(raw, "id", None):
                candidates[int(raw.id)] = provider.get_album(raw.id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Deezer UPC lookup failed for %s: %s", upc, exc)
    for album_data in provider.search_albums(
        " ".join([album_name, *(album_artists[:1])]), limit=10
    ):
        if album_data.deezer_id:
            candidates.setdefault(album_data.deezer_id, album_data)

    matching = [
        album_data
        for album_data in candidates.values()
        if album_data
        and _norm(album_data.name) == _norm(album_name)
        and any(
            _norm(album_data.artist_name) in _norm(a)
            or _norm(a) in _norm(album_data.artist_name)
            for a in album_artists
        )
        and (not total_tracks or album_data.total_tracks == total_tracks)
    ]
    if len(matching) != 1:
        return _unresolved(
            song,
            sp_track,
            sp_isrc,
            sp_album_id,
            upc,
            f"ambiguous Deezer album for Spotify album {sp_album_id} "
            f"({album_name}, UPC {upc}): {len(matching)} candidates; "
            "leaving deezer_id NULL instead of borrowing another album's id",
        )

    deezer_album = matching[0]
    if not deezer_album.deezer_id:
        raise CommandError(
            f"song {song.id}: matched Deezer album has no id; "
            f"leaving deezer_id unchanged"
        )
    tracks = provider.get_album_tracks(deezer_album.deezer_id)
    known_isrcs = {_norm(sp_isrc)}
    matches = [
        track
        for track in tracks
        if _norm(track.isrc) in known_isrcs
        and (
            not track_number
            or not track.track_number
            or track.track_number == track_number
        )
    ]
    if len(matches) != 1 or not matches[0].deezer_id:
        return _unresolved(
            song,
            sp_track,
            sp_isrc,
            sp_album_id,
            upc,
            f"no unique Deezer track for ISRC {sp_isrc} on album "
            f"{deezer_album.deezer_id} at position {track_number}: "
            f"{len(matches)} candidates; leaving deezer_id NULL",
        )

    deezer_track = matches[0]
    local_album_ok = _local_album_is(
        song, sp_album_id, deezer_album.deezer_id, album_name, album_artists
    )
    return TrackTruth(
        title=sp_track.get("name") or song.name,
        isrc=sp_isrc,
        deezer_track_id=deezer_track.deezer_id,
        deezer_album_id=deezer_album.deezer_id,
        artist_name=deezer_track.artist_name
        or (album_artists[0] if album_artists else ""),
        artist_deezer_id=deezer_track.artist_deezer_id,
        all_artist_names=tuple(
            a.get("name") for a in (sp_track.get("artists") or []) if a.get("name")
        ),
        duration_ms=int(sp_track.get("duration_ms") or deezer_track.duration_ms or 0),
        local_album_ok=local_album_ok,
        reason=None,
        sp_album_id=sp_album_id,
        sp_album_upc=upc,
        different_release=_is_different_release(song, upc, sp_album_id),
    )


def _is_different_release(song: Song, upc: str | None, sp_album_id: str) -> bool:
    """True when the song's gid belongs to a different release than its album row."""
    album = song.album
    if not album:
        return False
    identity = fetch_album_identity(album)
    if identity.upc and upc:
        return identity.upc != upc
    album_gid = (
        (album.spotify_uri or "").rsplit(":", 1)[-1] if album.spotify_uri else ""
    )
    return bool(album_gid and sp_album_id and album_gid != sp_album_id)


def _unresolved(
    song: Song,
    sp_track: dict[str, Any],
    sp_isrc: str,
    sp_album_id: str,
    upc: str | None,
    reason: str,
) -> TrackTruth:
    return TrackTruth(
        title=sp_track.get("name") or song.name,
        isrc=sp_isrc,
        deezer_track_id=None,
        deezer_album_id=None,
        artist_name="",
        artist_deezer_id=None,
        all_artist_names=tuple(
            a.get("name") for a in (sp_track.get("artists") or []) if a.get("name")
        ),
        duration_ms=int(sp_track.get("duration_ms") or 0),
        local_album_ok=False,
        reason=reason,
        sp_album_id=sp_album_id,
        sp_album_upc=upc,
    )


def _local_album_is(
    song: Song,
    sp_album_id: str,
    deezer_album_id: int,
    album_name: str,
    album_artists: list[str],
) -> bool:
    album = song.album
    if not album:
        return False
    # A stale Spotify URI or Deezer album id proves the row is a different
    # album even when its name/artist credit happens to look compatible.
    if album.spotify_uri and album.spotify_uri != f"spotify:album:{sp_album_id}":
        return False
    if album.deezer_id and album.deezer_id != deezer_album_id:
        return False
    if album.spotify_uri == f"spotify:album:{sp_album_id}" or (
        album.deezer_id == deezer_album_id
    ):
        return True
    return _norm(album.name) == _norm(album_name) and any(
        _norm(album.artist.name) in _norm(a) or _norm(a) in _norm(album.artist.name)
        for a in album_artists
    )


@dataclass
class RepairPlan:
    song: Song
    truth: TrackTruth
    song_updates: dict[str, Any]
    album_updates: dict[str, Any]
    contributor_names: list[str]
    target_artist_name: str | None
    target_artist_deezer_id: int | None
    file_to_remove: Path | None
    reason: str | None
    queue_by_gid: bool

    @property
    def changes(self) -> dict[str, Any]:
        return {
            "song": self.song_updates,
            "album": self.album_updates,
            "contributing_artists": self.contributor_names,
            "remove_file": str(self.file_to_remove) if self.file_to_remove else None,
        }

    @property
    def has_changes(self) -> bool:
        return any(self.changes.values())


@dataclass
class MergePlan:
    keep: Song
    drop: Song
    truth: TrackTruth
    song_updates: dict[str, Any]
    album_updates: dict[str, Any]
    album_merge: dict[str, Any] | None = None
    leftover_album: dict[str, Any] | None = None
    relations: list[dict[str, Any]] = dc_field(default_factory=list)
    files_to_remove: list[str] = dc_field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.song_updates or self.album_updates or self.relations)


def _song_relations() -> list[tuple[Any, Any]]:
    """Enumerate every FK/OneToOne field in the project that points at Song."""
    from django.apps import apps
    from django.db.models import ForeignKey, OneToOneField

    relations = []
    for model in apps.get_models():
        for relation in model._meta.get_fields():
            if (
                isinstance(relation, (ForeignKey, OneToOneField))
                and getattr(relation, "related_model", None) is Song
            ):
                relations.append((model, relation))
    return relations


def plan_album_mergeable(keep: Song, drop: Song) -> bool:
    """True when the drop album can be folded into the keep album safely."""
    if not keep.album or not drop.album or keep.album_id == drop.album_id:
        return False
    others = Song.objects.filter(album_id=drop.album_id).exclude(
        id__in=[keep.id, drop.id]
    )
    return not others.exists() or _norm(drop.album.name) == _norm(keep.album.name)


def _duplicate_on_keep(model: Any, relation: Any, row: Any, keep_id: int) -> bool:
    """True when moving ``row`` to keep would violate a uniqueness contract."""
    from library_manager.models import (
        ContributingArtist,
        PendingMetadataUpdate,
        PlaylistSong,
    )

    if isinstance(relation, OneToOneField):
        return model.objects.filter(**{relation.name + "_id": keep_id}).exists()
    if model is PlaylistSong:
        return PlaylistSong.objects.filter(
            playlist_id=row.playlist_id, song_id=keep_id
        ).exists()
    if model is ContributingArtist:
        return ContributingArtist.objects.filter(
            artist_id=row.artist_id, song_id=keep_id
        ).exists()
    if model._meta.label == "queuetip.Contribution":
        return model.objects.filter(
            playlist_id=row.playlist_id,
            song_id=keep_id,
            contributed_by_id=row.contributed_by_id,
        ).exists()
    if model is PendingMetadataUpdate:
        return PendingMetadataUpdate.objects.filter(
            content_type_id=row.content_type_id,
            object_id=keep_id,
            field_name=row.field_name,
        ).exists()
    return False


class Command(BaseCommand):
    help = (
        "Repair song identity from per-album Spotify/Deezer lookups. "
        "Dry-run by default; --apply requires a new --audit-file."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--song", type=int, action="append", default=[])
        parser.add_argument(
            "--merge-into",
            metavar="KEEP:DROP",
            help="Merge DROP song into KEEP (explicitly authorizes deleting DROP)",
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-file")
        parser.add_argument(
            "--scan", action="store_true", help="Report candidates without changes"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from library_manager import helpers

        if options["scan"]:
            self._scan()
            return
        if options["merge_into"]:
            self._handle_merge(options)
            return
        raw_ids = options["song"] or []
        song_ids: list[int] = []
        for value in raw_ids:
            for item in value if isinstance(value, (list, tuple)) else [value]:
                try:
                    song_ids.append(int(item))
                except (TypeError, ValueError) as exc:
                    raise CommandError(f"invalid --song id: {item!r}") from exc
        if not song_ids:
            raise CommandError("pass at least one --song <id> (or --scan)")
        if options["apply"] and not options["audit_file"]:
            raise CommandError("--apply requires --audit-file")

        plans = [self._build_plan(song_id) for song_id in song_ids]

        if not options["apply"]:
            self.stdout.write("DRY RUN — no changes made")
            for plan in plans:
                self._print_plan(plan)
            self._simulate(plans)
            self.stdout.write("Constraint simulation passed (writes rolled back)")
            return

        audit_path = Path(options["audit_file"])
        if audit_path.exists():
            raise CommandError(f"audit file already exists: {audit_path}")
        self._write_audit(audit_path, self._audit_records(plans))
        self.stdout.write(f"Audit written and fsynced: {audit_path}")
        for plan in plans:
            self._print_plan(plan)

        applied = 0
        queued = 0
        with transaction.atomic():
            locked = {
                s.id: s
                for s in Song.objects.select_for_update().filter(
                    id__in=[plan.song.id for plan in plans]
                )
            }
            for plan in plans:
                self._apply_plan(locked[plan.song.id], plan)
                applied += 1

        for plan in plans:
            if not plan.has_changes:
                continue
            if plan.queue_by_gid:
                published = helpers.enqueue_download_track_by_spotify_gid(
                    plan.song.gid, priority=TaskPriority.TRACK_DOWNLOAD
                )
            else:
                published = helpers.enqueue_download_deezer_track(
                    plan.song.id, priority=TaskPriority.TRACK_DOWNLOAD
                )
            if published:
                queued += 1
            else:
                self.stdout.write(
                    f"song {plan.song.id}: re-queue skipped (already active)"
                )
        self.stdout.write(f"Applied {applied} repair(s); queued {queued} download(s)")

    def _build_plan(self, song_id: int) -> RepairPlan:
        try:
            song = Song.objects.select_related(
                "primary_artist", "album__artist", "file_path_ref"
            ).get(pk=song_id)
        except Song.DoesNotExist as exc:
            raise CommandError(f"song {song_id} does not exist") from exc
        truth = fetch_truth(song)
        song_updates: dict[str, Any] = {}
        album_updates: dict[str, Any] = {}
        reason = truth.reason

        final_deezer_id: int | None = song.deezer_id
        recommend_merge = False
        if reason:
            if song.deezer_id is not None:
                song_updates["deezer_id"] = None
                final_deezer_id = None
        elif truth.different_release:
            duplicate = None
            if truth.deezer_album_id:
                duplicate = (
                    Song.objects.filter(
                        isrc=song.isrc, album__deezer_id=truth.deezer_album_id
                    )
                    .exclude(id=song.id)
                    .first()
                )
            if duplicate:
                reason = (
                    f"song is on the wrong album row; release {truth.sp_album_upc} "
                    f"already has song {duplicate.id} with the same recording. "
                    f"Use --merge-into {song.id}:{duplicate.id} to merge them"
                )
                # No field changes: this row needs the explicit merge command.
                song_updates.clear()
                final_deezer_id = song.deezer_id
                recommend_merge = True
            else:
                reason = (
                    "song's Spotify album is a different release from its album row "
                    f"(UPC {truth.sp_album_upc}); clearing the wrong deezer_id and "
                    "leaving the album's own identifiers intact"
                )
                if song.deezer_id is not None:
                    song_updates["deezer_id"] = None
                    final_deezer_id = None
        elif truth.local_album_ok:
            if song.deezer_id != truth.deezer_track_id:
                song_updates["deezer_id"] = truth.deezer_track_id
                final_deezer_id = truth.deezer_track_id
            if (
                song.album
                and truth.deezer_album_id
                and song.album.deezer_id != truth.deezer_album_id
            ):
                album_updates["deezer_id"] = truth.deezer_album_id
        else:
            target_album = None
            if truth.deezer_album_id:
                target_album = Album.objects.filter(
                    deezer_id=truth.deezer_album_id
                ).first()
            if not target_album and truth.sp_album_id:
                target_album = Album.objects.filter(
                    spotify_uri=f"spotify:album:{truth.sp_album_id}"
                ).first()
            if target_album and truth.deezer_track_id:
                duplicate = (
                    Song.objects.filter(
                        album=target_album, deezer_id=truth.deezer_track_id
                    )
                    .exclude(id=song.id)
                    .first()
                )
                if duplicate:
                    reason = (
                        f"album {target_album.id} already has song {duplicate.id} "
                        f"with deezer_id {truth.deezer_track_id}; possible "
                        "duplicate — not moving or borrowing this id"
                    )
                    target_album = None
            if target_album and target_album.id != song.album_id:
                song_updates["album_id"] = target_album.id
            if target_album:
                if song.deezer_id != truth.deezer_track_id:
                    song_updates["deezer_id"] = truth.deezer_track_id
                    final_deezer_id = truth.deezer_track_id
            else:
                if not reason:
                    reason = (
                        f"correct album (Deezer {truth.deezer_album_id}) is not in the "
                        "library; leaving deezer_id NULL rather than borrowing a "
                        "different album's track id"
                    )
                if song.deezer_id is not None:
                    song_updates["deezer_id"] = None
                    final_deezer_id = None

        target_artist = None
        if not reason and truth.artist_deezer_id:
            target_artist = Artist.objects.filter(
                deezer_id=truth.artist_deezer_id
            ).first()
        if not reason and not target_artist and truth.artist_name:
            target_artist = Artist.objects.filter(
                name__iexact=truth.artist_name
            ).first()
        if (
            target_artist
            and song.primary_artist_id != target_artist.id
            and any(
                _norm(name) == _norm(truth.artist_name)
                for name in truth.all_artist_names
            )
        ):
            song_updates["primary_artist_id"] = target_artist.id

        contributor_names: list[str] = []
        if not reason:
            existing = set(
                ContributingArtist.objects.filter(song=song).values_list(
                    "artist_id", flat=True
                )
            )
            for name in truth.all_artist_names:
                if _norm(name) == _norm(truth.artist_name):
                    continue
                artist = Artist.objects.filter(name__iexact=name).first()
                if artist and artist.id not in existing:
                    contributor_names.append(name)

        file_to_remove = None
        if not recommend_merge:
            if song.file_path_ref:
                path = Path(song.file_path_ref.path)
                root = Path(
                    getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")
                ).resolve()
                if (
                    path.resolve().is_relative_to(root)
                    and not Song.objects.filter(file_path_ref=song.file_path_ref)
                    .exclude(id=song.id)
                    .exists()
                ):
                    file_to_remove = path

            if song.downloaded:
                song_updates["downloaded"] = False
            if song.bitrate:
                song_updates["bitrate"] = 0
            for field in (
                "matched_provider",
                "matched_provider_track_id",
                "matched_title",
                "matched_artist",
                "matched_duration_ms",
                "matched_isrc",
                "match_confidence",
                "matched_at",
            ):
                if getattr(song, field) is not None:
                    song_updates[field] = None
            if file_to_remove and song.file_path_ref:
                song_updates["file_path_ref"] = None

        return RepairPlan(
            song=song,
            truth=truth,
            song_updates=song_updates,
            album_updates=album_updates,
            contributor_names=contributor_names,
            target_artist_name=truth.artist_name or None,
            target_artist_deezer_id=truth.artist_deezer_id,
            file_to_remove=file_to_remove,
            reason=reason,
            queue_by_gid=final_deezer_id is None,
        )

    def _print_plan(self, plan: RepairPlan) -> None:
        self.stdout.write(f"song {plan.song.id} ({plan.song.name}):")
        if plan.reason:
            self.stdout.write(f"  reason: {plan.reason}")
        for field, value in plan.song_updates.items():
            self.stdout.write(f"  song.{field}: {getattr(plan.song, field)} -> {value}")
        for field, value in plan.album_updates.items():
            self.stdout.write(
                f"  album.{field}: {getattr(plan.song.album, field)} -> {value}"
            )
        for name in plan.contributor_names:
            self.stdout.write(f"  contributing artist +: {name}")
        if plan.file_to_remove:
            self.stdout.write(f"  remove file: {plan.file_to_remove}")
        if plan.queue_by_gid:
            self.stdout.write("  re-queue: by Spotify gid (deezer_id is NULL)")

    def _audit_records(self, plans: list[RepairPlan]) -> list[dict[str, Any]]:
        records = []
        for plan in plans:
            records.append(
                {
                    "id": plan.song.id,
                    "name": plan.song.name,
                    "changes": plan.changes,
                    "reason": plan.reason,
                    "queue_by_gid": plan.queue_by_gid,
                    "rollback": {
                        "deezer_id": plan.song.deezer_id,
                        "album_id": plan.song.album_id,
                        "album_deezer_id": (
                            plan.song.album.deezer_id if plan.song.album else None
                        ),
                        "primary_artist_id": plan.song.primary_artist_id,
                        "downloaded": plan.song.downloaded,
                        "bitrate": plan.song.bitrate,
                        "file_path_ref_id": plan.song.file_path_ref_id,
                        "file_path": plan.song.file_path,
                        "matched_title": plan.song.matched_title,
                        "contributing_artist_ids": list(
                            ContributingArtist.objects.filter(
                                song=plan.song
                            ).values_list("artist_id", flat=True)
                        ),
                    },
                }
            )
        return records

    def _write_audit(self, path: Path, records: list[dict[str, Any]]) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, cls=DjangoJSONEncoder, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    def _simulate(self, plans: list[RepairPlan]) -> None:
        """Apply every planned write inside a transaction that is always rolled back."""
        try:
            with transaction.atomic():
                locked = {
                    s.id: s
                    for s in Song.objects.select_for_update().filter(
                        id__in=[plan.song.id for plan in plans]
                    )
                }
                for plan in plans:
                    self._apply_plan(locked[plan.song.id], plan, simulate=True)
                transaction.set_rollback(True)
        except Exception as exc:  # pylint: disable=broad-except
            raise CommandError(f"dry-run simulation would fail: {exc}") from exc

    def _simulate_merge(self, plan: MergePlan) -> None:
        try:
            with transaction.atomic():
                list(
                    Song.objects.select_for_update()
                    .filter(id__in=[plan.keep.id, plan.drop.id])
                    .order_by("id")
                )
                self._apply_merge(plan, simulate=True)
                transaction.set_rollback(True)
        except Exception as exc:  # pylint: disable=broad-except
            raise CommandError(f"dry-run simulation would fail: {exc}") from exc

    def _apply_plan(self, song: Song, plan: RepairPlan, simulate: bool = False) -> None:
        if plan.album_updates and song.album:
            for field, value in plan.album_updates.items():
                setattr(song.album, field, value)
            song.album.save(update_fields=list(plan.album_updates))
        if plan.song_updates:
            for field, value in plan.song_updates.items():
                setattr(song, field, value)
            song.save(update_fields=list(plan.song_updates))
        for name in plan.contributor_names:
            artist = Artist.objects.filter(name__iexact=name).first()
            if artist:
                ContributingArtist.objects.get_or_create(song=song, artist=artist)
        if not simulate and plan.file_to_remove and plan.file_to_remove.is_file():
            plan.file_to_remove.unlink()

    def _handle_merge(self, options: dict[str, Any]) -> None:
        from library_manager import helpers

        raw = options["merge_into"]
        try:
            keep_id, drop_id = (int(part) for part in str(raw).split(":"))
        except (TypeError, ValueError) as exc:
            raise CommandError("--merge-into must be KEEP:DROP (numeric ids)") from exc
        if keep_id == drop_id:
            raise CommandError("--merge-into KEEP and DROP must differ")
        if not options["apply"] and options["audit_file"]:
            raise CommandError("--audit-file only applies with --apply")
        if options["apply"] and not options["audit_file"]:
            raise CommandError("--apply requires --audit-file")

        plan = self._build_merge_plan(keep_id, drop_id)
        if not options["apply"]:
            self.stdout.write("DRY RUN — no changes made")
            self._print_merge_plan(plan)
            self._simulate_merge(plan)
            self.stdout.write("Constraint simulation passed (writes rolled back)")
            return

        audit_path = Path(options["audit_file"])
        if audit_path.exists():
            raise CommandError(f"audit file already exists: {audit_path}")
        self._write_audit(audit_path, [self._merge_audit(plan)])
        self.stdout.write(f"Audit written and fsynced: {audit_path}")
        self.stdout.write("Applying merge atomically...")

        with transaction.atomic():
            list(
                Song.objects.select_for_update()
                .filter(id__in=[keep_id, drop_id])
                .order_by("id")
            )
            self._apply_merge(plan)

        if helpers.enqueue_download_deezer_track(
            keep_id, priority=TaskPriority.TRACK_DOWNLOAD
        ):
            self.stdout.write(f"Queued fresh download for song {keep_id}")
        else:
            self.stdout.write(f"song {keep_id}: re-queue skipped (already active)")

    def _build_merge_plan(self, keep_id: int, drop_id: int) -> MergePlan:
        try:
            keep = Song.objects.select_related(
                "primary_artist", "album__artist", "file_path_ref"
            ).get(pk=keep_id)
            drop = Song.objects.select_related(
                "primary_artist", "album__artist", "file_path_ref"
            ).get(pk=drop_id)
        except Song.DoesNotExist as exc:
            raise CommandError(f"--merge-into songs must exist: {exc}") from exc
        truth = fetch_truth(keep)
        if truth.reason or not truth.deezer_track_id:
            raise CommandError(
                f"cannot merge: per-album resolution failed: {truth.reason}"
            )
        # DROP is deleted, so it must be a duplicate of the same recording.
        if (
            truth.isrc
            and drop.isrc
            and drop.isrc != truth.isrc
            and drop.isrc not in (keep.alternate_isrcs or [])
            and truth.isrc not in (drop.alternate_isrcs or [])
        ):
            raise CommandError(
                f"refusing merge: song {drop_id} (ISRC {drop.isrc}) is a "
                f"different recording than song {keep_id} (ISRC {truth.isrc})"
            )
        # Compare the KEEP song's *true* release (from its gid) with the DROP
        # song's album — not KEEP's current album row, which may be wrong.
        if drop.album:
            drop_release = fetch_album_identity(drop.album)
            if (
                truth.sp_album_upc
                and drop_release.upc
                and truth.sp_album_upc != drop_release.upc
            ):
                raise CommandError(
                    f"refusing merge: song {keep_id}'s release "
                    f"(UPC {truth.sp_album_upc}) is not the release of "
                    f"song {drop_id}'s album (UPC {drop_release.upc})"
                )

        song_updates: dict[str, Any] = {"deezer_id": truth.deezer_track_id}
        album_updates: dict[str, Any] = {}
        if drop.album_id and drop.album_id != keep.album_id:
            song_updates["album_id"] = drop.album_id

        target_artist = None
        if truth.artist_deezer_id:
            target_artist = Artist.objects.filter(
                deezer_id=truth.artist_deezer_id
            ).first()
        if not target_artist and truth.artist_name:
            target_artist = Artist.objects.filter(
                name__iexact=truth.artist_name
            ).first()
        if target_artist and keep.primary_artist_id != target_artist.id:
            song_updates["primary_artist_id"] = target_artist.id

        relations: list[dict[str, Any]] = []
        ct = ContentType.objects.get_for_model(Song)
        for model, relation in _song_relations():
            for row in model.objects.filter(**{relation.name + "_id": drop_id}):
                duplicate = _duplicate_on_keep(model, relation, row, keep_id)
                relations.append(
                    {
                        "model": model._meta.label,
                        "field": relation.name,
                        "row_id": row.id,
                        "action": "delete_duplicate" if duplicate else "repoint",
                    }
                )
        for row in PendingMetadataUpdate.objects.filter(
            content_type=ct, object_id=drop_id
        ):
            duplicate = PendingMetadataUpdate.objects.filter(
                content_type=ct, object_id=keep_id, field_name=row.field_name
            ).exists()
            relations.append(
                {
                    "model": "library_manager.PendingMetadataUpdate",
                    "field": "object_id",
                    "row_id": row.id,
                    "action": "delete_duplicate" if duplicate else "repoint",
                }
            )

        for song in (keep, drop):
            for field in (
                "matched_provider",
                "matched_provider_track_id",
                "matched_title",
                "matched_artist",
                "matched_duration_ms",
                "matched_isrc",
                "match_confidence",
                "matched_at",
            ):
                if getattr(song, field) is not None:
                    if song.id == keep_id:
                        song_updates[field] = None
        if keep.downloaded:
            song_updates["downloaded"] = False
        if keep.bitrate:
            song_updates["bitrate"] = 0

        files: list[str] = []
        root = Path(getattr(settings, "OUTPUT_PATH", "/mnt/music_spotify")).resolve()
        for song in (keep, drop):
            if not song.file_path_ref:
                continue
            path = Path(song.file_path_ref.path)
            if not path.resolve().is_relative_to(root):
                continue
            others = (
                Song.objects.filter(file_path_ref=song.file_path_ref)
                .exclude(id__in=[keep_id, drop_id])
                .exists()
            )
            if not others:
                files.append(str(path))
                if song.id == keep_id:
                    song_updates["file_path_ref"] = None

        return MergePlan(
            keep=keep,
            drop=drop,
            truth=truth,
            song_updates=song_updates,
            album_updates=album_updates,
            leftover_album=(
                {
                    "id": keep.album_id,
                    "name": keep.album.name if keep.album else None,
                    "deezer_id": keep.album.deezer_id if keep.album else None,
                    "remaining_songs": list(
                        Song.objects.filter(album_id=keep.album_id)
                        .exclude(id__in=[keep_id, drop_id])
                        .values_list("id", flat=True)
                    ),
                    "action": "left untouched",
                }
                if keep.album_id and keep.album_id != drop.album_id
                else None
            ),
            relations=relations,
            files_to_remove=files,
        )

    def _print_merge_plan(self, plan: MergePlan) -> None:
        self.stdout.write(
            f"merge {plan.drop.id} -> {plan.keep.id} "
            f"({plan.drop.name} into {plan.keep.name})"
        )
        for field, value in plan.song_updates.items():
            self.stdout.write(
                f"  keep.song.{field}: {getattr(plan.keep, field)} -> {value}"
            )
        for field, value in plan.album_updates.items():
            self.stdout.write(
                f"  keep.album.{field}: {getattr(plan.keep.album, field)} -> {value}"
            )
        if plan.leftover_album:
            self.stdout.write(
                f"  leftover album {plan.leftover_album['id']} "
                f"(deezer_id={plan.leftover_album['deezer_id']}) left untouched; "
                f"other songs: {plan.leftover_album['remaining_songs']}"
            )
        for item in plan.relations:
            self.stdout.write(
                f"  {item['action']}: {item['model']}.{item['field']} "
                f"row {item['row_id']} -> keep {plan.keep.id}"
            )
        for path in plan.files_to_remove:
            self.stdout.write(f"  remove file: {path}")
        self.stdout.write(f"  delete song {plan.drop.id}")

    def _merge_audit(self, plan: MergePlan) -> dict[str, Any]:
        return {
            "action": "merge",
            "merge": {
                "keep_id": plan.keep.id,
                "drop_id": plan.drop.id,
                "album_merge": plan.album_merge,
                "leftover_album": plan.leftover_album,
                "relations": plan.relations,
                "files_to_remove": plan.files_to_remove,
            },
            "changes": {
                "song": plan.song_updates,
                "album": plan.album_updates,
            },
            "rollback": {
                "keep": {
                    "id": plan.keep.id,
                    "name": plan.keep.name,
                    "deezer_id": plan.keep.deezer_id,
                    "album_id": plan.keep.album_id,
                    "album_deezer_id": (
                        plan.keep.album.deezer_id if plan.keep.album else None
                    ),
                    "primary_artist_id": plan.keep.primary_artist_id,
                    "downloaded": plan.keep.downloaded,
                    "bitrate": plan.keep.bitrate,
                    "file_path_ref_id": plan.keep.file_path_ref_id,
                    "file_path": plan.keep.file_path,
                    "matched_title": plan.keep.matched_title,
                },
                "drop": {
                    "id": plan.drop.id,
                    "name": plan.drop.name,
                    "gid": plan.drop.gid,
                    "deezer_id": plan.drop.deezer_id,
                    "isrc": plan.drop.isrc,
                    "album_id": plan.drop.album_id,
                    "album_deezer_id": (
                        plan.drop.album.deezer_id if plan.drop.album else None
                    ),
                    "primary_artist_id": plan.drop.primary_artist_id,
                    "downloaded": plan.drop.downloaded,
                    "bitrate": plan.drop.bitrate,
                    "file_path_ref_id": plan.drop.file_path_ref_id,
                    "file_path": plan.drop.file_path,
                    "contributing_artist_ids": list(
                        ContributingArtist.objects.filter(song=plan.drop).values_list(
                            "artist_id", flat=True
                        )
                    ),
                },
                "relations": plan.relations,
                "files_to_remove": plan.files_to_remove,
            },
        }

    def _apply_merge(self, plan: MergePlan, simulate: bool = False) -> None:
        keep_id, drop_id = plan.keep.id, plan.drop.id
        ct = ContentType.objects.get_for_model(Song)
        for model, relation in _song_relations():
            rows = list(model.objects.filter(**{relation.name + "_id": drop_id}))
            for row in rows:
                if _duplicate_on_keep(model, relation, row, keep_id):
                    row.delete()
                else:
                    setattr(row, relation.attname, keep_id)
                    row.save(update_fields=[relation.name])
        for row in PendingMetadataUpdate.objects.filter(
            content_type=ct, object_id=drop_id
        ):
            if PendingMetadataUpdate.objects.filter(
                content_type=ct, object_id=keep_id, field_name=row.field_name
            ).exists():
                row.delete()
            else:
                row.object_id = keep_id
                row.save(update_fields=["object_id"])

        # Album rows are never deleted or renamed here: the old album row may
        # belong to another release, and Album.deezer_id is unique.
        # Delete DROP first: (deezer_id, album_id) is unique per album, so KEEP
        # cannot take the id until DROP's row (and its claim) is gone.
        Song.objects.filter(pk=drop_id).delete()
        for field, value in plan.song_updates.items():
            setattr(plan.keep, field, value)
        plan.keep.save(update_fields=list(plan.song_updates))
        if not simulate:
            for path in plan.files_to_remove:
                candidate = Path(path)
                if candidate.is_file():
                    candidate.unlink()

    def _scan(self) -> None:
        """Report rows whose deezer_id disagrees with their per-album truth."""
        candidates = Song.objects.filter(deezer_id__isnull=False)
        found = 0
        for song in candidates.iterator(chunk_size=500):
            try:
                truth = fetch_truth(song)
            except CommandError:
                continue
            if truth.reason or truth.deezer_track_id is None:
                continue
            if truth.deezer_track_id != song.deezer_id:
                found += 1
                self.stdout.write(
                    f"song {song.id}: deezer_id={song.deezer_id}, per-album "
                    f"Deezer track={truth.deezer_track_id} "
                    f"(album {truth.deezer_album_id})"
                )
        self.stdout.write(f"Scan complete: {found} candidate(s)")
