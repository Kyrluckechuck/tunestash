"""Detect and remove placeholder genre tags from downloaded audio files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from django.core.management.base import BaseCommand, CommandParser

from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from library_manager.models import Song

MISSING_GENRE_MARKERS = {"[missing genre]"}
GENRE_KEYS_BY_SUFFIX = {
    ".m4a": ("\xa9gen",),
    ".mp4": ("\xa9gen",),
    ".aac": ("\xa9gen",),
    ".flac": ("GENRE",),
}


@dataclass(frozen=True)
class TagCleanupResult:
    """Result of checking or cleaning one audio file's genre tags."""

    affected: bool
    changed: bool
    removed_keys: tuple[str, ...]
    replacement_genres: tuple[str, ...] = ()


class Command(BaseCommand):
    """Clean downloaded files that were tagged with placeholder genres."""

    help = (
        "Detect downloaded songs with '[Missing Genre]' audio tags. "
        "Use --apply to remove those genre tags."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Remove matching placeholder genre tags. Defaults to dry-run.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of downloaded songs scanned.",
        )
        parser.add_argument(
            "--song-id",
            type=int,
            action="append",
            dest="song_ids",
            help="Only scan the given song ID. Can be supplied multiple times.",
        )

    def handle(self, *args: object, **options: object) -> None:
        apply_changes = bool(options["apply"])
        limit = cast(int | None, options.get("limit"))
        song_ids = cast(list[int] | None, options.get("song_ids"))

        queryset = (
            Song.objects.filter(downloaded=True, file_path_ref__isnull=False)
            .select_related("album", "primary_artist", "file_path_ref")
            .order_by("id")
        )
        if song_ids:
            queryset = queryset.filter(id__in=song_ids)
        if limit:
            queryset = queryset[:limit]

        scanned = 0
        affected = 0
        changed = 0
        missing_files = 0
        unsupported = 0
        errors = 0

        for song in queryset.iterator():
            scanned += 1
            file_path = song.file_path
            if not file_path:
                continue

            path = Path(file_path)
            if path.suffix.lower() not in GENRE_KEYS_BY_SUFFIX:
                unsupported += 1
                continue
            if not path.exists():
                missing_files += 1
                self.stderr.write(f"MISSING FILE song={song.id} path={path}")
                continue

            try:
                audio = self._load_audio(path)
                initial_result = self.clean_audio_tags(
                    audio,
                    path.suffix,
                    apply=False,
                )
                if not initial_result.affected:
                    continue

                replacement_genres = self.resolve_song_genres(song)
                result = self.clean_audio_tags(
                    audio,
                    path.suffix,
                    apply=apply_changes,
                    replacement_genres=replacement_genres,
                )
            except Exception as exc:  # pylint: disable=broad-except
                errors += 1
                self.stderr.write(f"ERROR song={song.id} path={path}: {exc}")
                continue

            affected += 1
            if result.changed:
                changed += 1

            artist_name = song.primary_artist.name if song.primary_artist_id else ""
            action = "UPDATED" if result.changed else "WOULD_UPDATE"
            keys = ",".join(result.removed_keys)
            genre_msg = (
                f" replacement_genres={list(result.replacement_genres)!r}"
                if result.replacement_genres
                else " replacement_genres=[]"
            )
            self.stdout.write(
                f"{action} song={song.id} keys={keys} "
                f"title={song.name!r} artist={artist_name!r}{genre_msg} path={path}"
            )

        mode = "apply" if apply_changes else "dry-run"
        self.stdout.write(
            f"Done mode={mode} scanned={scanned} affected={affected} "
            f"changed={changed} missing_files={missing_files} "
            f"unsupported={unsupported} errors={errors}"
        )

    @staticmethod
    def _load_audio(path: Path) -> MP4 | FLAC:
        suffix = path.suffix.lower()
        if suffix in (".m4a", ".mp4", ".aac"):
            return MP4(str(path))
        if suffix == ".flac":
            return FLAC(str(path))
        raise ValueError(f"Unsupported audio format: {suffix}")

    def clean_audio_tags(
        self,
        audio: MP4 | FLAC,
        suffix: str,
        *,
        apply: bool,
        replacement_genres: tuple[str, ...] = (),
    ) -> TagCleanupResult:
        """Remove or replace placeholder genre tags on an already-loaded file."""
        removed_keys: list[str] = []
        for key in GENRE_KEYS_BY_SUFFIX.get(suffix.lower(), ()):
            if key not in audio:
                continue
            if self._contains_missing_genre(audio[key]):
                removed_keys.append(key)

        if not removed_keys:
            return TagCleanupResult(affected=False, changed=False, removed_keys=())

        if apply:
            for key in removed_keys:
                if replacement_genres:
                    audio[key] = self._format_genres_for_tag(suffix, replacement_genres)
                else:
                    del audio[key]
            audio.save()

        return TagCleanupResult(
            affected=True,
            changed=apply,
            removed_keys=tuple(removed_keys),
            replacement_genres=replacement_genres,
        )

    def resolve_song_genres(self, song: Song) -> tuple[str, ...]:
        """Resolve best available genres for a song from Deezer album metadata."""
        album_deezer_id = song.album.deezer_id if song.album else None
        try:
            from src.providers.deezer import DeezerMetadataProvider

            provider = DeezerMetadataProvider()
            if not album_deezer_id and song.deezer_id:
                track = provider.get_track(song.deezer_id)
                album_deezer_id = track.album_deezer_id if track else None
            if not album_deezer_id:
                return ()

            album = provider.get_album(album_deezer_id)
            if not album or not album.genres:
                return ()
            return tuple(album.genres)
        except Exception:  # pylint: disable=broad-except
            return ()

    @staticmethod
    def _format_genres_for_tag(suffix: str, genres: tuple[str, ...]) -> list[str]:
        if suffix.lower() in (".m4a", ".mp4", ".aac"):
            return [", ".join(genres)]
        return list(genres)

    @staticmethod
    def _contains_missing_genre(values: object) -> bool:
        if isinstance(values, str):
            value_list = [values]
        elif isinstance(values, Iterable):
            value_list = list(values)
        else:
            value_list = [values]
        return any(
            str(value).strip().lower() in MISSING_GENRE_MARKERS for value in value_list
        )
