"""Process-safe application logs with a budget shared by all services."""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import portalocker
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

# Only application log files are eligible; never touch locks or unrelated files.
_LOG_PREFIX = r"^[a-zA-Z0-9_-]+\.log"
_LOG_NAME = re.compile(
    _LOG_PREFIX + r"(?:\.(?P<date>\d{4}-\d{2}-\d{2})(?:\.\d+)?(?:\.gz)?)?$"
)


class RetainedFileHandler(ConcurrentTimedRotatingFileHandler):
    """Coordinate archive rotation and retention across /config/logs.

    The underlying handler owns per-file locking, fork handling, stale file
    descriptors, unique size-rollover names, and compression. A directory lock
    prevents one service's retention sweep from racing another's rotation.
    Active logs are never deleted. The normal shared budget is deliberately far
    below the 1 GiB emergency ceiling; oldest archives are sacrificed first.
    """

    def __init__(
        self,
        filename: str,
        maxBytes: int = 5 * 1024 * 1024,
        max_total_bytes: int = 128 * 1024 * 1024,
        retention_days: int = 30,
        encoding: str = "utf-8",
    ) -> None:
        if not 0 < max_total_bytes <= 1024**3:
            raise ValueError("Log budget must be between 1 byte and 1 GiB")
        if not 0 < maxBytes < max_total_bytes or retention_days < 1:
            raise ValueError("Invalid rotation size or retention age")
        self.directory = Path(filename).absolute().parent
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_total_bytes = max_total_bytes
        self.retention_days = retention_days
        self._next_prune = 0.0
        super().__init__(
            filename,
            when="midnight",
            utc=True,
            backupCount=0,
            maxBytes=maxBytes,
            use_gzip=True,
            encoding=encoding,
        )

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        if time.monotonic() < self._next_prune:
            return
        try:
            # Routine writes use only the library's per-service lock. A busy
            # janitor must not block requests or drop their diagnostic record.
            with portalocker.Lock(str(self.directory / ".retention.lock"), timeout=0):
                self._prune()
                self._next_prune = time.monotonic() + 60
        except portalocker.exceptions.LockException:
            self._next_prune = time.monotonic() + 60
        except Exception:  # pylint: disable=broad-except
            self._next_prune = time.monotonic() + 60
            self.handleError(record)

    def doRollover(self) -> None:
        # The library holds this service's file lock here. Other rotations and
        # retention sweeps share the directory lock, but routine writes do not.
        with portalocker.Lock(str(self.directory / ".retention.lock"), timeout=10):
            super().doRollover()
            self._prune()
            self._next_prune = time.monotonic() + 60

    def format(self, record: logging.LogRecord) -> str:
        # One enormous upstream response must not defeat the shared budget.
        message = super().format(record)
        return message[:16384] + (" [truncated]" if len(message) > 16384 else "")

    def _prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        archives: list[tuple[float, Path, int]] = []
        total = 0
        for path in self.directory.iterdir():
            match = _LOG_NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            if match["date"]:
                try:
                    archive_day = datetime.strptime(match["date"], "%Y-%m-%d")
                except ValueError:
                    continue
                archive_end = archive_day.replace(tzinfo=timezone.utc) + timedelta(
                    days=1
                )
                if archive_end.timestamp() < cutoff:
                    path.unlink()
                    continue
            total += stat.st_size
            if match["date"]:
                archives.append((stat.st_mtime, path, stat.st_size))
        for _, path, size in sorted(archives):
            if total <= self.max_total_bytes:
                break
            path.unlink()
            total -= size
