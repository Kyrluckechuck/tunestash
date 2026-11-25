import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from library_manager.helpers import enqueue_fetch_all_albums_for_artist
from library_manager.models import Artist

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Artist)
def artist_save(sender, instance: Artist, created: bool, **kwargs) -> None:
    if created:
        # Shares the task id with the service-layer fetch, so a new artist
        # gets exactly one fetch regardless of which path queues first.
        enqueue_fetch_all_albums_for_artist(instance.id)
