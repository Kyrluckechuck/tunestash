"""Shared filesystem safety helpers for download and metadata file placement.

All writes into the music library go through :func:`safe_join` so a provider
filename or a renamed artist cannot escape the configured output root via
``..`` components or a symlinked directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Keep the historical replacement map so ordinary artist/album names do not
# change on disk. The security addition is the dot-only component rejection.
_REPLACEMENTS = {
    "/": "-",
    "\\": "-",
    ":": "-",
    "*": "",
    "?": "",
    '"': "'",
    "<": "",
    ">": "",
    "|": "-",
}


class UnsafePathError(ValueError):
    """Raised when a requested path would leave the configured library root."""


def sanitize_component(name: str) -> str:
    """Return a single safe path component for ``name``.

    Replaces characters that are illegal on common filesystems, then strips
    leading/trailing dots and whitespace so ``"."``, ``".."`` and Windows-style
    dot-only names can never become traversal components or device names.
    Normal artist names are left untouched.
    """
    result = name or ""
    for old, new in _REPLACEMENTS.items():
        result = result.replace(old, new)
    result = result.strip().strip(".").strip()
    if not result:
        return ""
    return result[:100]


def is_within(path: Path, root: Path) -> bool:
    """Return whether ``path`` resolves to a location inside ``root``.

    ``Path.resolve()`` follows symlinks, so a symlinked directory pointing
    outside the library is correctly reported as outside.
    """
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return resolved_path.is_relative_to(resolved_root)


def safe_join(root: Path, *components: str, fallback: str = "Unknown") -> Path:
    """Join ``components`` under ``root`` and assert the result stays inside.

    Raises:
        UnsafePathError: if a component resolves outside ``root`` (for example
            a ``..`` segment or a symlink to an external directory).
    """
    resolved_root = root.resolve()
    safe_parts: list[str] = []
    for part in components:
        # A dot-only component is a traversal attempt, never a usable name.
        if part and set(part.strip()) <= {"."}:
            raise UnsafePathError(f"Refusing dot-only path component: {part!r}")
        safe = sanitize_component(part)
        if not safe:
            if fallback:
                safe = sanitize_component(fallback) or "Unknown"
            else:
                raise UnsafePathError(f"Refusing empty path component: {part!r}")
        safe_parts.append(safe)
    candidate = resolved_root.joinpath(*safe_parts)
    if not is_within(candidate, resolved_root):
        raise UnsafePathError(
            f"Refusing path outside library root: {candidate} (root {resolved_root})"
        )
    return candidate


def assert_within(root: Path, *components: str) -> Path:
    """Join already-sanitized ``components`` under ``root`` and assert containment.

    Unlike :func:`safe_join`, this does not re-sanitize or truncate components:
    callers use it for composed filenames whose length limits were applied to
    the semantic parts before composition (so extensions are preserved). It
    still rejects separators and dot-only components and verifies the resolved
    destination stays inside ``root``.
    """
    resolved_root = root.resolve()
    parts: list[str] = []
    for part in components:
        if not part or "/" in part or "\\" in part or set(part.strip()) <= {"."}:
            raise UnsafePathError(f"Refusing unsafe path component: {part!r}")
        parts.append(part)
    candidate = resolved_root.joinpath(*parts)
    if not is_within(candidate, resolved_root):
        raise UnsafePathError(
            f"Refusing path outside library root: {candidate} (root {resolved_root})"
        )
    return candidate


def secure_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically with a private temp file.

    ``mkstemp`` (random name, mode 0600) prevents pre-created symlink attacks.
    The final mode preserves an existing target's permissions, or uses 0644 for
    a new file so media servers running as another UID can read the playlist.
    """
    fd = -1
    temp: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.ts-")
        temp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        os.chmod(temp, mode)
        os.replace(temp, path)
        temp = None
    finally:
        if fd >= 0:
            os.close(fd)
        if temp is not None:
            temp.unlink(missing_ok=True)
