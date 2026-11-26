"""
YouTube Music download provider using yt-dlp.

Downloads audio from YouTube Music without requiring Spotify URIs.
Uses yt-dlp's Python API for search and download operations.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from .base import (
    DownloadProvider,
    DownloadResult,
    ProviderCapabilities,
    ProviderType,
    QualityOption,
    QualityPreference,
    TrackMatch,
    is_duration_compatible,
    is_rejected,
)

logger = logging.getLogger(__name__)

# Minimum confidence threshold for accepting a match
MIN_MATCH_CONFIDENCE = 0.6


# Duration tolerance for matching (10 seconds)
DURATION_TOLERANCE_MS = 10000

# Request timeout for yt-dlp operations
YTDLP_TIMEOUT = 60

# Whole-operation deadline for a single yt-dlp download. ``socket_timeout``
# only bounds per-socket inactivity; a slow-but-progressing extraction can
# otherwise occupy a worker until Celery's hard limit.
YTDLP_TOTAL_TIMEOUT = 300

# Download to a temp path and publish with an atomic rename so a timeout,
# network error, or hard kill never leaves a partial file at the final path.
_PART_SUFFIX = ".part"


class DownloadCancelled(Exception):
    """Raised by a cancellation check to stop an in-flight download."""


class DownloadTimeoutError(Exception):
    """Raised when a yt-dlp operation exceeds YTDLP_TOTAL_TIMEOUT."""


# A task context (e.g. ``raise_if_cancelled(task_history, force_refresh=True)``)
# can install a synchronous check for the duration of a download. The provider
# instance can also carry one via ``set_cancellation_check``; both are invoked
# from yt-dlp's progress hooks so cancellation is honoured between stages.
_active_cancellation_check: ContextVar[Optional[Callable[[], None]]] = ContextVar(
    "youtube_download_cancellation_check", default=None
)


@contextmanager
def cancellation_scope(check: Callable[[], None]):
    """Bind a synchronous cancellation check for the current async context."""
    token = _active_cancellation_check.set(check)
    try:
        yield
    finally:
        _active_cancellation_check.reset(token)


# The child is a fresh Python process: it cannot inherit mocks, DB connections
# or a cancelled parent context. Options (including the PO token) travel in a
# 0600 JSON config file, never on the command line. A flag file gives yt-dlp's
# progress hook a cooperative abort signal before the parent kills the process
# group on deadline/cancel, which also terminates any ffmpeg child.
_CHILD_CODE = (
    "import sys;"
    "from downloader.providers.youtube import _child_main;"
    "_child_main(sys.argv[1])"
)
_POLL_INTERVAL = 0.1
_CHILD_EXIT_GRACE = 5


class DownloadChildError(Exception):
    """Raised when the yt-dlp child process reports a failure."""


def _child_main(config_path: str) -> None:
    """Entry point invoked in the child process; writes a JSON result file."""
    import yt_dlp

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    opts = config["opts"]
    cancel_flag = Path(config["cancel_flag"])
    result: dict[str, object]

    def progress_hook(info: dict) -> None:
        if cancel_flag.exists():
            raise DownloadCancelled("download cancelled in child")

    opts["progress_hooks"] = [progress_hook]
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if config["mode"] == "probe":
                info = ydl.extract_info(config["url"], download=False)
                formats = len(info.get("formats", [])) if info else 0
                result = {"ok": True, "value": {"formats": formats}}
            else:
                ydl.download([config["url"]])
                result = {"ok": True, "value": None}
    except BaseException as exc:  # pylint: disable=broad-except
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    Path(config["result_file"]).write_text(json.dumps(result), encoding="utf-8")


# The child only needs enough environment to start Python, import yt-dlp,
# choose a locale/timezone, find proxies and CA certificates, and write temp
# files. Everything else in the worker environment (Django/database/Spotify/
# QueueTip credentials) stays out of the child.
_CHILD_ENV_NAMES = (
    "PATH",
    "HOME",
    "LANG",
    "TMPDIR",
    "TZ",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONIOENCODING",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)


def _child_environment() -> dict[str, str]:
    """Build an explicit allowlisted environment for the yt-dlp child."""
    env = {
        name: value
        for name in _CHILD_ENV_NAMES
        if (value := os.environ.get(name)) is not None
    }
    env.update(
        {name: value for name, value in os.environ.items() if name.startswith("LC_")}
    )
    return env


def _kill_child(process: subprocess.Popen) -> None:
    """Kill the child's whole process group, then reap it."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()
    try:
        process.wait(timeout=_CHILD_EXIT_GRACE)
    except subprocess.TimeoutExpired:
        pass


def _run_yt_dlp_child(
    *,
    opts: dict,
    url: str,
    mode: str,
    timeout: float,
    cancellation_check: Optional[Callable[[], None]] = None,
) -> object:
    """Run yt-dlp in a child process bounded by ``timeout``.

    On deadline or cancellation the process group is killed before any cleanup,
    so no yt-dlp/ffmpeg work or temp file can outlive the attempt. Returns the
    child's result value; raises DownloadTimeoutError, DownloadCancelled, the
    cancellation check's exception, or DownloadChildError on failure.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="tunestash-ytdlp-"))
    config_path = work_dir / "opts.json"
    cancel_flag = work_dir / "cancel"
    result_file = work_dir / "result.json"
    child_opts = {key: value for key, value in opts.items() if key != "progress_hooks"}
    config = {
        "opts": child_opts,
        "url": url,
        "mode": mode,
        "cancel_flag": str(cancel_flag),
        "result_file": str(result_file),
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    os.chmod(config_path, 0o600)

    process: Optional[subprocess.Popen] = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-c", _CHILD_CODE, str(config_path)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_child_environment(),
        )
        while process.poll() is None:
            if cancellation_check is not None:
                # Runs in the parent: the task context is not picklable. The
                # flag file lets the child abort cooperatively too.
                cancellation_check()
            if time.monotonic() >= deadline:
                cancel_flag.touch()
                _kill_child(process)
                raise DownloadTimeoutError(
                    f"yt-dlp operation timed out after {timeout}s"
                )
            time.sleep(_POLL_INTERVAL)

        if not result_file.exists():
            raise DownloadChildError("yt-dlp child produced no result")
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise DownloadChildError(str(payload.get("error", "unknown error")))
        return payload.get("value")
    finally:
        if process is not None and process.poll() is None:
            cancel_flag.touch()
            _kill_child(process)
        shutil.rmtree(work_dir, ignore_errors=True)


# Fixed, ultra-stable video used by probe_auth() to validate that cookies + PO
# token still authenticate the watch-page download path. "Never Gonna Give You
# Up" — 1.5B+ views, actively maintained by the rights holder, not age- or
# region-restricted. A fixed target keeps the probe deterministic: a probe
# failure has one plausible cause (auth), no confounding per-video variables.
PROBE_VIDEO_ID = "dQw4w9WgXcQ"

YOUTUBE_CAPABILITIES = ProviderCapabilities(
    provider_type=ProviderType.REST_API,
    supports_search=True,
    supports_isrc_lookup=False,
    embeds_metadata=False,
    available_qualities=(
        QualityOption(
            quality=QualityPreference.HIGH,
            bitrate_kbps=256,
            format="m4a",
            lossless=False,
        ),
    ),
    formats=("m4a",),
)


def _get_cookies_path() -> Optional[str]:
    """Get the YouTube cookies path (hardcoded, managed via UI)."""
    default_path = Path("/config/youtube_music_cookies.txt")
    if default_path.exists():
        return str(default_path)
    return None


def _get_po_token() -> Optional[str]:
    """Read the PO token from app settings.

    Returns the bare token string (no client prefix). _build_ydl_opts handles
    the yt-dlp `<client>.<context>+<token>` formatting.
    """
    try:
        from lib.config_class import Config

        token = Config().po_token
        if token and token.strip():
            return token.strip()
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(f"[youtube] Failed to load PO token from config: {e}")
    return None


def _build_ydl_opts(
    cookies_path: Optional[str] = None,
    po_token: Optional[str] = None,
) -> dict:
    """Build base yt-dlp options.

    When po_token is provided we forward it via extractor_args under both
    mweb.gvs and web.gvs client signatures — yt-dlp picks whichever the
    extractor needs per request. Cookies-only auth (no po_token) is the
    fallback path; it still works but is heavily throttled by YouTube's
    anti-abuse for non-POT clients.
    """
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": YTDLP_TIMEOUT,
        "retries": 2,
        # 10MB HTTP read buffer; default leaves TCP windows small and a
        # ~10MB audio stream takes ~7s instead of ~3s.
        "http_chunk_size": 10 * 1024 * 1024,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    if po_token:
        # Expand the POT client coverage. yt-dlp falls back through multiple
        # clients (web → mweb → tv → tv_embedded) for different operations,
        # and search calls in particular have been observed to use clients
        # the original two formats didn't cover, producing 403s. Adding the
        # tv/tv_embedded clients and the `player` context (vs only `gvs`)
        # makes the POT usable across more of yt-dlp's fallback chain.
        # The token was minted for browser context; entries for clients it
        # doesn't apply to are silently ignored by yt-dlp.
        opts["extractor_args"] = {
            "youtube": {
                "po_token": [
                    f"mweb.gvs+{po_token}",
                    f"web.gvs+{po_token}",
                    f"tv.gvs+{po_token}",
                    f"tv_embedded.gvs+{po_token}",
                    f"mweb.player+{po_token}",
                    f"web.player+{po_token}",
                ]
            }
        }
    return opts


class YouTubeMusicProvider(DownloadProvider):
    """Download provider using yt-dlp for YouTube Music."""

    # Class-level flag so the no-POT warning fires once per process, not on
    # every provider instantiation (which happens per task call).
    _warned_no_po_token: bool = False

    def __init__(self) -> None:
        self._cookies_path = _get_cookies_path()
        self._cancellation_check: Optional[Callable[[], None]] = None

    def set_cancellation_check(self, check: Optional[Callable[[], None]]) -> None:
        """Install a synchronous callback invoked between yt-dlp stages.

        A caller with a task context should pass a check built from the
        existing helper, e.g.
        ``lambda: raise_if_cancelled(task_history, force_refresh=True)``.
        The callback may raise to abort the download; its exception is
        re-raised after temp files are removed.
        """
        self._cancellation_check = check

    @property
    def _po_token(self) -> Optional[str]:
        """Read the PO token lazily on each access.

        Avoids two failure modes of caching the token at __init__:
        1) During the brief boot window when the DB-backed AppSetting isn't
           yet readable, a cached `None` would persist for the lifetime of
           the provider instance — running that task in cookies-only mode.
        2) UI-driven POT updates take effect on the next task without
           requiring a worker restart.
        """
        token = _get_po_token()
        if not token and not YouTubeMusicProvider._warned_no_po_token:
            YouTubeMusicProvider._warned_no_po_token = True
            logger.warning(
                "[youtube] No PO token configured — operating in cookies-only "
                "mode, which YouTube heavily throttles. Set 'po_token' in "
                "app settings to authenticate downloads."
            )
        return token

    @property
    def name(self) -> str:
        return "youtube"

    @property
    def display_name(self) -> str:
        return "YouTube Music"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return YOUTUBE_CAPABILITIES

    async def is_available(self) -> bool:
        """Check if yt-dlp is importable."""
        try:
            import yt_dlp  # noqa: F401

            return True
        except ImportError:
            logger.warning("yt-dlp is not installed")
            return False

    async def search_track(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
        search_alternate_isrcs: Optional[Iterable[str]] = None,
        excluded_track_ids: Optional[Iterable[str]] = None,
    ) -> Optional[TrackMatch]:
        """Search YouTube Music for a track."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self._search_track_sync,
                title=title,
                artist=artist,
                album=album,
                isrc=isrc,
                duration_ms=duration_ms,
                search_alternate_isrcs=search_alternate_isrcs,
                excluded_track_ids=excluded_track_ids,
            ),
        )

    def _search_track_sync(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None,
        isrc: Optional[str] = None,
        duration_ms: Optional[int] = None,
        search_alternate_isrcs: Optional[Iterable[str]] = None,
        excluded_track_ids: Optional[Iterable[str]] = None,
    ) -> Optional[TrackMatch]:
        """Search YouTube Music's song catalog, excluding ordinary videos."""
        from downloader.track_matcher import score_track_match
        from ytmusicapi import YTMusic

        try:
            entries = YTMusic().search(f"{artist} {title}", filter="songs", limit=10)
            if not entries:
                return None

            search_duration_s = duration_ms / 1000.0 if duration_ms else None
            best_match: Optional[TrackMatch] = None
            best_confidence = 0.0

            for entry in entries:
                video_id = entry.get("videoId")
                if not video_id:
                    continue
                if is_rejected("youtube", str(video_id), excluded_track_ids):
                    continue

                result_title = entry.get("title", "")
                result_artist = " • ".join(
                    str(item.get("name", "")).strip()
                    for item in entry.get("artists", [])
                    if item.get("name")
                )
                result_duration_ms = int(entry.get("duration_seconds") or 0) * 1000
                result_duration_s = result_duration_ms / 1000.0

                if not is_duration_compatible(duration_ms, result_duration_ms):
                    duration_diff = (
                        abs(duration_ms - result_duration_ms)
                        if duration_ms and result_duration_ms
                        else 0
                    )
                    logger.debug(
                        f"[youtube] Duration mismatch for '{title}': "
                        f"expected {duration_ms}ms, got {result_duration_ms}ms "
                        f"(diff: {duration_diff}ms)"
                    )
                    continue

                confidence = score_track_match(
                    search_title=title,
                    search_artist=artist,
                    result_title=result_title,
                    result_artist=result_artist,
                    search_duration_s=search_duration_s,
                    result_duration_s=result_duration_s,
                    duration_tolerance_s=DURATION_TOLERANCE_MS / 1000.0,
                )

                if confidence > best_confidence:
                    best_confidence = confidence
                    # Construct thumbnail URL from video_id rather than relying
                    # on entry["thumbnail"]; extract_flat search results omit
                    # the thumbnail field, and this URL pattern is stable.
                    # Only used as a fallback when the source metadata
                    # (Deezer/Spotify) lacks cover art.
                    best_match = TrackMatch(
                        provider="youtube",
                        provider_track_id=video_id,
                        title=result_title,
                        artist=result_artist,
                        album=(entry.get("album") or {}).get("name") or album or "",
                        duration_ms=result_duration_ms,
                        confidence=confidence,
                        cover_url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                    )

            if best_match and best_confidence >= MIN_MATCH_CONFIDENCE:
                return best_match

            if best_confidence > 0:
                logger.debug(
                    f"[youtube] Best confidence ({best_confidence:.2f}) below "
                    f"threshold for '{artist} - {title}'"
                )
            return None

        except Exception as e:
            logger.error(
                f"[youtube] YouTube Music search failed for '{artist} - {title}': {e}"
            )
            return None

    async def download_track(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """Download a track from YouTube."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self._download_track_sync,
                track_match=track_match,
                output_path=output_path,
                quality=quality,
            ),
        )

    def _download_track_sync(
        self,
        track_match: TrackMatch,
        output_path: Path,
        quality: QualityPreference = QualityPreference.HIGH,
    ) -> DownloadResult:
        """Synchronous download implementation with deadline and atomic publish."""
        url = f"https://music.youtube.com/watch?v={track_match.provider_track_id}"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # A unique temp base means a failed attempt can never mistake a stale
        # file for its own output, and cleanup cannot race another download.
        temp_base = output_path.with_name(
            f"{output_path.stem}.{uuid.uuid4().hex}{_PART_SUFFIX}"
        )

        opts = _build_ydl_opts(self._cookies_path, self._po_token)
        opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": str(temp_base) + ".%(ext)s",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                        "preferredquality": "256",
                    }
                ],
            }
        )

        def cancellation_check() -> None:
            check = self._cancellation_check or _active_cancellation_check.get()
            if check is not None:
                check()

        try:
            _run_yt_dlp_child(
                opts=opts,
                url=url,
                mode="download",
                timeout=YTDLP_TOTAL_TIMEOUT,
                cancellation_check=cancellation_check,
            )

            produced = sorted(temp_base.parent.glob(f"{temp_base.name}.*"))
            if not produced:
                return DownloadResult(
                    success=False,
                    provider="youtube",
                    error="Downloaded file not found",
                )
            # Prefer the post-processed m4a; fall back to yt-dlp's raw output.
            temp_file = next(
                (p for p in produced if p.suffix.lower() == ".m4a"), produced[0]
            )
            if temp_file.stat().st_size == 0:
                return DownloadResult(
                    success=False,
                    provider="youtube",
                    error="Downloaded file is empty",
                )

            os.replace(temp_file, output_path)
            return DownloadResult(
                success=True,
                provider="youtube",
                file_path=output_path,
                bitrate_kbps=256,
                format="m4a",
                duration_ms=track_match.duration_ms,
            )

        except DownloadTimeoutError as exc:
            logger.warning(
                "[youtube] Download timed out for %s: %s",
                track_match.provider_track_id,
                exc,
            )
            return DownloadResult(
                success=False,
                provider="youtube",
                error=str(exc),
                error_retryable=False,
            )
        except DownloadChildError as e:
            logger.error(
                "[youtube] Download failed for %s: %s",
                track_match.provider_track_id,
                e,
            )
            return DownloadResult(
                success=False,
                provider="youtube",
                error=str(e),
            )
        finally:
            for leftover in temp_base.parent.glob(f"{temp_base.name}.*"):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    logger.warning("[youtube] Could not remove temp file %s", leftover)

    def probe_auth(self) -> tuple[bool, Optional[str]]:
        """Probe YouTube auth by resolving stream info for a known-stable video.

        Runs a metadata-only yt-dlp extraction (download=False) of PROBE_VIDEO_ID
        using the same cookies + PO token a real download uses. This exercises
        the watch-page player API in the GVS (get-video-stream) context — the
        exact auth path downloads depend on — so a pass/fail genuinely reflects
        download capability rather than acting as a proxy.

        Returns:
            (ok, detail) — detail is a short success note or the error string.
        """
        if not self._po_token:
            return False, "PO token not configured"

        opts = _build_ydl_opts(self._cookies_path, self._po_token)
        url = f"https://www.youtube.com/watch?v={PROBE_VIDEO_ID}"

        try:
            info = _run_yt_dlp_child(
                opts=opts,
                url=url,
                mode="probe",
                timeout=YTDLP_TOTAL_TIMEOUT,
            )
            if info and info.get("formats"):
                return True, f"Resolved {len(info['formats'])} formats for probe video"
            return False, "Probe returned no playable formats"
        except DownloadTimeoutError as exc:
            return False, f"Probe timed out: {exc}"
        except Exception as e:  # pylint: disable=broad-except
            return False, str(e)
