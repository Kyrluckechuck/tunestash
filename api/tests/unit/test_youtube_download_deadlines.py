# pylint: disable=protected-access

"""Regression tests for YouTube download deadlines, cancellation and atomic publish."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from downloader.providers import youtube
from downloader.providers.base import QualityPreference, TrackMatch
from downloader.providers.youtube import (
    DownloadCancelled,
    DownloadChildError,
    DownloadTimeoutError,
    YouTubeMusicProvider,
    _child_main,
    _run_yt_dlp_child,
)


def _match() -> TrackMatch:
    return TrackMatch(
        provider="youtube",
        provider_track_id="abc123",
        title="Song",
        artist="Artist",
        album="Album",
        duration_ms=200_000,
    )


class _FakeProcess:
    """Minimal Popen stand-in driven by the config file the parent wrote."""

    def __init__(self, args, **kwargs):
        del kwargs
        self.config = json.loads(Path(args[-1]).read_text(encoding="utf-8"))
        self.pid = 424242
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def finish(self, *, ok=True, error=None, write_output=True):
        """Simulate the child completing normally."""
        result_path = Path(self.config["result_file"])
        payload = {"ok": ok, "value": None} if ok else {"ok": False, "error": error}
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        if write_output:
            outtmpl = self.config["opts"]["outtmpl"]
            output = Path(outtmpl.replace("%(ext)s", "m4a"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"audio")
        self.returncode = 0

    def finish_after_kill(self):
        """Simulate a late child that writes files just as it is killed."""
        self.finish(write_output=True)
        self.returncode = -9


def _install_fake_popen(monkeypatch, process_holder):
    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, **kwargs)
        process_holder.append(process)
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)

    def fake_kill(process):
        process.killed = True
        process.returncode = -9

    monkeypatch.setattr(youtube, "_kill_child", fake_kill)


def test_child_config_is_private_and_preserves_options(monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    seen = {}

    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, **kwargs)
        holders.append(process)
        seen["mode"] = process.config["mode"]
        seen["opts"] = process.config["opts"]
        seen["config_mode"] = os.stat(args[-1]).st_mode & 0o777
        process.finish(write_output=False)
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)

    with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1):
        _run_yt_dlp_child(
            opts={
                "format": "bestaudio/best",
                "cookiefile": "/config/cookies.txt",
                "extractor_args": {"youtube": {"po_token": ["mweb.gvs+SECRET"]}},
                "outtmpl": "/tmp/out.%(ext)s",
            },
            url="https://music.youtube.com/watch?v=abc",
            mode="probe",
            timeout=1,
        )

    assert seen["mode"] == "probe"
    assert seen["opts"]["cookiefile"] == "/config/cookies.txt"
    assert seen["opts"]["extractor_args"]["youtube"]["po_token"] == ["mweb.gvs+SECRET"]
    assert "progress_hooks" not in seen["opts"]
    assert seen["config_mode"] == 0o600


def test_child_environment_excludes_secrets(monkeypatch):
    seen = {}

    def fake_popen(args, **kwargs):
        seen["env"] = kwargs["env"]
        process = _FakeProcess(args, **kwargs)
        process.finish(write_output=False)
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("TUNESTASH_SUPER_SECRET", "s3cr3t-value")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "django-secret")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "spotify-secret")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")

    _run_yt_dlp_child(
        opts={"outtmpl": "/tmp/out.%(ext)s"},
        url="https://music.youtube.com/watch?v=abc",
        mode="probe",
        timeout=1,
    )

    env = seen["env"]
    for secret_name in (
        "TUNESTASH_SUPER_SECRET",
        "DJANGO_SECRET_KEY",
        "SPOTIFY_CLIENT_SECRET",
    ):
        assert secret_name not in env
        assert "s3cr3t-value" not in env.values()
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HTTPS_PROXY"] == "http://proxy.example:8080"


def test_popen_failure_removes_secret_config(monkeypatch, tmp_path):
    work_dir = tmp_path / "childwork"
    work_dir.mkdir()

    def mkdtemp(*args, **kwargs):
        del args, kwargs
        return str(work_dir)

    monkeypatch.setattr(youtube.tempfile, "mkdtemp", mkdtemp)

    def failing_popen(*args, **kwargs):
        del args, kwargs
        raise OSError("fork failed")

    monkeypatch.setattr(youtube.subprocess, "Popen", failing_popen)

    with pytest.raises(OSError, match="fork failed"):
        _run_yt_dlp_child(
            opts={"outtmpl": str(tmp_path / "out.%(ext)s")},
            url="https://music.youtube.com/watch?v=abc",
            mode="download",
            timeout=1,
        )

    assert not work_dir.exists()


def test_successful_download_publishes_atomically(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    original = youtube.subprocess.Popen

    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, **kwargs)
        holders.append(process)
        process.finish()
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    final_path = tmp_path / "Artist - Song.m4a"

    try:
        with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1):
            result = YouTubeMusicProvider()._download_track_sync(_match(), final_path)
    finally:
        monkeypatch.setattr(youtube.subprocess, "Popen", original)

    assert result.success is True
    assert result.file_path == final_path
    assert final_path.read_bytes() == b"audio"
    assert not list(tmp_path.glob("*.part*"))


def test_failed_child_leaves_no_partial_final_file(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"
    final_path.write_bytes(b"stale")

    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, **kwargs)
        holders.append(process)
        process.finish(ok=False, error="RuntimeError: boom", write_output=False)
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)

    with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1):
        result = YouTubeMusicProvider()._download_track_sync(_match(), final_path)

    assert result.success is False
    assert "boom" in result.error
    assert final_path.read_bytes() == b"stale"
    assert not list(tmp_path.glob("*.part*"))


def test_timeout_kills_child_and_leaves_no_files(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"

    with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 0.1):
        result = YouTubeMusicProvider()._download_track_sync(_match(), final_path)

    assert result.success is False
    assert "timed out" in result.error.lower()
    assert holders and holders[0].killed
    assert not final_path.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_late_completion_after_timeout_never_publishes(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"

    def fake_kill(process):
        process.finish_after_kill()

    monkeypatch.setattr(youtube, "_kill_child", fake_kill)

    with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 0.1):
        result = YouTubeMusicProvider()._download_track_sync(_match(), final_path)

    assert result.success is False
    assert "timed out" in result.error.lower()
    assert not final_path.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_cancellation_stops_child_and_cleans_up(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"
    provider = YouTubeMusicProvider()
    calls = []

    def cancel_check():
        calls.append(1)
        raise DownloadCancelled("cancelled by test")

    provider.set_cancellation_check(cancel_check)

    with (
        patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1),
        pytest.raises(DownloadCancelled),
    ):
        provider._download_track_sync(_match(), final_path)

    assert calls
    assert holders and holders[0].killed
    assert not final_path.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_contextvar_cancellation_check_is_honoured(tmp_path, monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"

    def cancel_check():
        raise ValueError("stop")

    with (
        youtube.cancellation_scope(cancel_check),
        patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1),
        pytest.raises(ValueError),
    ):
        YouTubeMusicProvider()._download_track_sync(_match(), final_path)

    assert holders and holders[0].killed
    assert not final_path.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_child_progress_hook_aborts_on_cancel_flag(tmp_path):
    """The child's own hook stops yt-dlp before the hard kill is needed."""
    cancel_flag = tmp_path / "cancel"
    cancel_flag.touch()
    config_path = tmp_path / "opts.json"
    config_path.write_text(
        json.dumps(
            {
                "opts": {"quiet": True},
                "url": "https://music.youtube.com/watch?v=abc",
                "mode": "download",
                "cancel_flag": str(cancel_flag),
                "result_file": str(tmp_path / "result.json"),
            }
        ),
        encoding="utf-8",
    )
    hooked = {}

    class HookedYDL:
        def __init__(self, opts):
            hooked["hooks"] = opts["progress_hooks"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            for hook in hooked["hooks"]:
                hook({"status": "downloading"})

    with patch("yt_dlp.YoutubeDL", HookedYDL):
        _child_main(str(config_path))

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "cancelled" in result["error"]


def test_child_reports_errors(monkeypatch):
    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)

    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, **kwargs)
        holders.append(process)
        process.finish(ok=False, error="DownloadError: nope", write_output=False)
        return process

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(DownloadChildError, match="nope"):
        _run_yt_dlp_child(
            opts={"outtmpl": "/tmp/out.%(ext)s"},
            url="https://music.youtube.com/watch?v=abc",
            mode="download",
            timeout=1,
        )


def test_real_child_process_is_killed_on_deadline(tmp_path, monkeypatch):
    """A genuine subprocess is spawned and killed before it can finish."""
    work_dir = tmp_path / "childwork"
    work_dir.mkdir()

    def mkdtemp(*args, **kwargs):
        del args, kwargs
        return str(work_dir)

    monkeypatch.setattr(youtube.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(
        youtube,
        "_CHILD_CODE",
        (
            "import sys, json, time;"
            "cfg=json.load(open(sys.argv[1]));"
            "time.sleep(30);"
            "open(cfg['result_file'],'w').write(json.dumps({'ok':True,'value':None}))"
        ),
    )

    with pytest.raises(DownloadTimeoutError):
        _run_yt_dlp_child(
            opts={},
            url="https://music.youtube.com/watch?v=abc",
            mode="download",
            timeout=0.3,
        )

    assert not (work_dir / "result.json").exists()
    assert not work_dir.exists()


def test_download_track_async_honours_cancellation(tmp_path, monkeypatch):
    import asyncio

    holders: list[_FakeProcess] = []
    _install_fake_popen(monkeypatch, holders)
    final_path = tmp_path / "Artist - Song.m4a"
    provider = YouTubeMusicProvider()
    provider.set_cancellation_check(lambda: (_ for _ in ()).throw(DownloadCancelled()))

    async def run():
        with patch.object(youtube, "YTDLP_TOTAL_TIMEOUT", 1):
            return await provider.download_track(
                _match(), final_path, quality=QualityPreference.HIGH
            )

    with pytest.raises(DownloadCancelled):
        asyncio.run(run())

    assert holders and holders[0].killed
    assert not final_path.exists()
    assert not list(tmp_path.glob("*.part*"))
