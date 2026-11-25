"""QueueTip export-sync enqueue helpers.

One deterministic task id per export target is the logical lock. Each enqueue
also carries a unique nonce, stored on the PENDING TaskHistory claim and in the
broker payload, so stale redeliveries cannot adopt a newer generation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from library_manager.models import TaskHistory
    from queuetip.models import PlaylistExportTarget

EXPORT_SYNC_TASK_NAME = "queuetip.tasks.sync_export_target"
NONCE_KEY = "export_sync_nonce"
RECREATE_KEY = "export_sync_recreate"


def export_sync_task_id(target_id: int) -> str:
    """Return the single task id shared by every sync trigger for a target."""
    from library_manager.helpers import generate_task_id

    return generate_task_id(EXPORT_SYNC_TASK_NAME, int(target_id))


def generate_export_nonce() -> str:
    return uuid.uuid4().hex


def claim_marker(nonce: str, *, recreate: bool = False) -> dict[str, Any]:
    marker: dict[str, Any] = {NONCE_KEY: nonce}
    if recreate:
        marker[RECREATE_KEY] = True
    return marker


def is_export_sync_active(target_id: int) -> bool:
    """Return True while the target's logical export task is active."""
    from library_manager.models import TaskHistory

    return TaskHistory.objects.filter(
        task_id=export_sync_task_id(target_id),
        status__in=TaskHistory.ACTIVE_STATUSES,
    ).exists()


def get_claim(target_id: int) -> "TaskHistory | None":
    from library_manager.models import TaskHistory

    return TaskHistory.objects.filter(task_id=export_sync_task_id(target_id)).first()


def claim_has_nonce(claim: "TaskHistory | None", nonce: str) -> bool:
    """Check the nonce embedded in a claim's existing JSON log metadata."""
    if claim is None:
        return False
    return any(
        isinstance(entry, dict) and entry.get(NONCE_KEY) == nonce
        for entry in (claim.log_messages or [])
    )


def claim_is_recreate(claim: "TaskHistory | None", nonce: str) -> bool:
    """Recreate intent must be on the same marker as the matched nonce."""
    if claim is None:
        return False
    return any(
        isinstance(entry, dict)
        and entry.get(NONCE_KEY) == nonce
        and entry.get(RECREATE_KEY) is True
        for entry in (claim.log_messages or [])
    )


def enqueue_export_sync(
    target: "PlaylistExportTarget", *, recreate: bool = False
) -> bool:
    """Publish a sync attempt unless the logical target lock is held.

    The broker payload contains only target id and nonce. Credentials and the
    account remain in the database; the worker reloads them.
    """
    from library_manager.helpers import enqueue_deduped
    from queuetip.tasks import sync_export_target

    nonce = generate_export_nonce()
    task_id = export_sync_task_id(target.id)

    # The marker is written by enqueue_deduped in the same INSERT as the
    # PENDING claim; no post-insert UPDATE by task id is allowed.
    return enqueue_deduped(
        sync_export_target,
        task_id=task_id,
        args=[int(target.id), nonce],
        task_type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(target.playlist_id),
        claim_nonce=nonce,
        nonce_key=NONCE_KEY,
        initial_metadata=claim_marker(nonce, recreate=recreate),
    )
