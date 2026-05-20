"""Async service for queueing + fetching bulk-import jobs."""

from __future__ import annotations

from typing import cast

from asgiref.sync import sync_to_async

from queuetip.models import Account, BulkImportJob, Playlist
from queuetip.permissions import require_member

from ..errors import NotFoundError


class BulkImportService:
    """Stateless namespace for bulk-import operations."""

    @staticmethod
    async def start(
        account: Account, playlist_id: int, source_url: str
    ) -> BulkImportJob:
        """Create a BulkImportJob row and queue the Celery task."""

        def _create() -> BulkImportJob:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            return BulkImportJob.objects.create(
                playlist=playlist,
                requested_by=account,
                source_url=source_url,
            )

        job = await sync_to_async(_create)()

        def _queue() -> None:
            from queuetip.tasks import bulk_import_playlist

            bulk_import_playlist.delay(job.id)

        await sync_to_async(_queue)()
        return job

    @staticmethod
    async def get(account: Account, job_id: int) -> BulkImportJob:
        """Fetch a job; requires the caller be a member of its playlist."""

        def _get() -> BulkImportJob:
            job = (
                BulkImportJob.objects.select_related("playlist", "requested_by")
                .filter(id=job_id)
                .first()
            )
            if job is None:
                raise NotFoundError(f"No bulk-import job with id={job_id}")
            require_member(account, cast(Playlist, job.playlist))
            return job

        return await sync_to_async(_get)()
