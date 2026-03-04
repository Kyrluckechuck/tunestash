import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from api.library_manager import tasks
from library_manager.helpers import generate_task_id, is_task_pending_or_running
from library_manager.models import Artist

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Artist)
def artist_save(sender, instance: Artist, created: bool, **kwargs) -> None:
    if created:
        # Use deduplication to avoid queuing duplicate tasks
        task_id = generate_task_id(
            "library_manager.tasks.fetch_all_albums_for_artist", instance.id
        )
        is_pending, reason = is_task_pending_or_running(task_id)
        if is_pending:
            logger.info(
                f"[DEDUP] Skipping auto-fetch for new artist {instance.id}: "
                f"task already queued ({reason})"
            )
            return

        tasks.fetch_all_albums_for_artist.apply_async(
            args=[instance.id], task_id=task_id
        )
