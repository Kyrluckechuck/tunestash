"""Persistent logging must retain records across rotation and worker startup."""

import gzip
import logging
import multiprocessing
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import portalocker
import pytest
from lib.logging_handlers import RetainedFileHandler


def _write_records(path, prefix, count):
    handler = RetainedFileHandler(path, maxBytes=300, max_total_bytes=100_000)
    for index in range(count):
        handler.emit(logging.makeLogRecord({"msg": f"{prefix}:{index}"}))
    handler.close()


def _read_logs(directory):
    contents = []
    for path in directory.iterdir():
        if path.name.endswith(".gz"):
            with gzip.open(path, "rt") as stream:
                contents.append(stream.read())
        elif path.suffix == ".log":
            contents.append(path.read_text())
    return "".join(contents)


def test_repeated_size_rotation_keeps_gzip_records(tmp_path):
    _write_records(str(tmp_path / "worker.log"), "record", 200)
    contents = _read_logs(tmp_path)
    assert len(list(tmp_path.glob("*.gz"))) > 1
    assert set(contents.splitlines()) == {f"record:{i}" for i in range(200)}


@pytest.mark.parametrize(
    "start_method",
    [
        method
        for method in ("spawn", "fork")
        if method in multiprocessing.get_all_start_methods()
    ],
)
def test_concurrent_writers_keep_every_record(tmp_path, start_method):
    context = multiprocessing.get_context(start_method)
    processes = [
        context.Process(
            target=_write_records, args=(str(tmp_path / "worker.log"), str(i), 80)
        )
        for i in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert not process.is_alive()
        assert process.exitcode == 0
    contents = _read_logs(tmp_path).splitlines()
    assert len(contents) == 240
    assert set(contents) == {f"{i}:{j}" for i in range(3) for j in range(80)}


def test_shared_budget_counts_active_files_and_other_services(tmp_path):
    (tmp_path / "web.log").write_bytes(b"x" * 100)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    today = datetime.now(timezone.utc).date()
    oldest = tmp_path / f"worker.log.{yesterday}.gz"
    oldest.write_bytes(b"x" * 300)
    (tmp_path / f"web.log.{today}.gz").write_bytes(b"x" * 300)
    handler = RetainedFileHandler(
        str(tmp_path / "worker.log"), maxBytes=200, max_total_bytes=500
    )
    handler.emit(logging.makeLogRecord({"msg": "hello"}))
    handler.close()
    assert sum(p.stat().st_size for p in tmp_path.glob("*.log*")) <= 500
    assert not oldest.exists()
    assert (tmp_path / "web.log").read_bytes() == b"x" * 100


def test_age_expiry_leaves_active_unrelated_and_symlink_files(tmp_path):
    expired = tmp_path / "worker.log.2000-01-01.gz"
    expired.write_bytes(b"old")
    unrelated = tmp_path / "credentials.txt"
    unrelated.write_text("keep")
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    handler.emit(logging.makeLogRecord({"msg": "retained"}))
    handler.close()
    assert not expired.exists()
    assert unrelated.read_text() == "keep"
    assert (tmp_path / "worker.log").read_text().strip() == "retained"


def test_daily_rotation(tmp_path):
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    handler.emit(logging.makeLogRecord({"msg": "yesterday"}))
    # The library shares the next rollover timestamp across processes.
    handler.clh._do_lock()
    try:
        handler.rolloverAt = int(
            (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
        )
        handler.write_rollover_time()
    finally:
        handler.clh._do_unlock()
    handler.emit(logging.makeLogRecord({"msg": "today"}))
    handler.close()
    assert list(tmp_path.glob("*.gz"))
    assert set(_read_logs(tmp_path).splitlines()) == {"yesterday", "today"}


def test_celery_startup_keeps_provider_file_handler(tmp_path):
    logfile = tmp_path / "worker.log"
    code = """
import logging
from celery_app import app
handler = logging.FileHandler(%r)
logging.getLogger().addHandler(handler)
app.log.setup_logging_subsystem(loglevel="INFO")
logging.getLogger("downloader.providers.fallback").warning("provider outcome retained")
handler.close()
""" % str(
        logfile
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
    assert "provider outcome retained" in logfile.read_text()


def test_oversized_record_is_bounded(tmp_path):
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    handler.emit(logging.makeLogRecord({"msg": "x" * 100_000}))
    handler.close()
    data = (tmp_path / "worker.log").read_text()
    assert len(data) < 17_000
    assert "[truncated]" in data


def test_retention_keeps_complete_thirtieth_day(tmp_path):
    today = datetime.now(timezone.utc).date()
    keep = tmp_path / f"worker.log.{today - timedelta(days=30)}.gz"
    expire = tmp_path / f"worker.log.{today - timedelta(days=31)}.gz"
    keep.write_bytes(b"recent")
    expire.write_bytes(b"old")
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    handler.emit(logging.makeLogRecord({"msg": "now"}))
    handler.close()
    assert keep.exists()
    assert not expire.exists()


def test_directory_scan_is_not_per_record(tmp_path):
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    with patch.object(handler, "_prune", wraps=handler._prune) as prune:
        for _ in range(3):
            handler.emit(logging.makeLogRecord({"msg": "routine"}))
        assert prune.call_count == 1
    handler.close()


def test_prune_failure_backs_off_without_losing_records(tmp_path):
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    with (
        patch.object(handler, "_prune", side_effect=PermissionError) as prune,
        patch.object(handler, "handleError") as error,
    ):
        handler.emit(logging.makeLogRecord({"msg": "first"}))
        handler.emit(logging.makeLogRecord({"msg": "second"}))
        assert prune.call_count == 1
        assert error.call_count == 1
    handler.close()
    assert (tmp_path / "worker.log").read_text().splitlines() == ["first", "second"]


def test_busy_maintenance_lock_does_not_block_or_drop_record(tmp_path):
    handler = RetainedFileHandler(str(tmp_path / "worker.log"))
    with (
        portalocker.Lock(str(tmp_path / ".retention.lock"), timeout=0),
        patch.object(handler, "_prune") as prune,
    ):
        handler.emit(logging.makeLogRecord({"msg": "retained while janitor busy"}))
        prune.assert_not_called()
    handler.close()
    assert (
        tmp_path / "worker.log"
    ).read_text().strip() == "retained while janitor busy"
