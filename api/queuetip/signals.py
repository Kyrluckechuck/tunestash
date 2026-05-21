"""Queuetip Django signals — auto-sync triggers for PlaylistExportTarget.

When a Contribution is added/removed or a Vote is created/cleared on a
playlist, we may need to push the change to the user's Subsonic / Spotify
playlists. The push is debounced 60s in the Celery task layer
(`schedule_auto_sync_for_playlist`); this module just wires the signal
handler that calls it.

Why post-save (not pre-save) and why on Contribution AND Vote:
  * post-save runs after the row is persisted, so sync sees consistent state.
  * Contribution (add/remove) changes the track set.
  * Vote (create/clear) changes ordering when the playlist's ordering depends
    on votes — true today for the "rolled" playback selection. Even if a
    given sync target doesn't reorder by votes, a vote signals "this playlist
    is being actively used" and re-syncing keeps the remote in step.

Failures here must never propagate — signal failures would break the
underlying mutation. Wrap the auto-sync scheduling in a broad try/except.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Contribution, Vote

logger = logging.getLogger(__name__)


def _schedule_for(playlist_id: int) -> None:
    # Imported lazily so this module can load without celery (e.g. during
    # collectstatic, migrations, or tests that don't exercise tasks).
    try:
        from .tasks import schedule_auto_sync_for_playlist
    except ImportError as exc:
        logger.debug("[signals] tasks unavailable: %s", exc)
        return
    try:
        schedule_auto_sync_for_playlist(playlist_id)
    except Exception as exc:  # pylint: disable=broad-except
        # Auto-sync is best-effort. Never break the originating mutation.
        logger.warning(
            "[signals] auto-sync schedule failed for playlist %s: %s",
            playlist_id,
            exc,
        )


@receiver(post_save, sender=Contribution, dispatch_uid="queuetip_autosync_contrib_save")
def _on_contribution_saved(sender: Any, instance: Contribution, **kwargs: Any) -> None:
    _schedule_for(instance.playlist_id)


@receiver(
    post_delete, sender=Contribution, dispatch_uid="queuetip_autosync_contrib_delete"
)
def _on_contribution_deleted(
    sender: Any, instance: Contribution, **kwargs: Any
) -> None:
    _schedule_for(instance.playlist_id)


@receiver(post_save, sender=Vote, dispatch_uid="queuetip_autosync_vote_save")
def _on_vote_saved(sender: Any, instance: Vote, **kwargs: Any) -> None:
    # Vote.playlist isn't stored directly — it goes via the contribution.
    # Fetch the playlist_id on the contribution row; one extra query per vote
    # is acceptable for auto-sync wiring.
    try:
        playlist_id = instance.contribution.playlist_id  # type: ignore[union-attr]
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("[signals] vote without resolvable playlist: %s", exc)
        return
    _schedule_for(playlist_id)


@receiver(post_delete, sender=Vote, dispatch_uid="queuetip_autosync_vote_delete")
def _on_vote_deleted(sender: Any, instance: Vote, **kwargs: Any) -> None:
    try:
        playlist_id = instance.contribution.playlist_id  # type: ignore[union-attr]
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("[signals] vote-delete without resolvable playlist: %s", exc)
        return
    _schedule_for(playlist_id)
