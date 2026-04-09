# mypy: disable-error-code=attr-defined
from typing import Any, List, Optional

from asgiref.sync import sync_to_async

from library_manager.models import DownloadHistory as DjangoDownloadHistory

from ..graphql_types.models import DownloadHistory, DownloadStatus
from .base import BaseService, PageResult


class DownloadHistoryService(BaseService[DownloadHistory]):
    def __init__(self) -> None:
        super().__init__()
        self.model = DjangoDownloadHistory

    async def get_by_id(self, id: str) -> Optional[DownloadHistory]:
        return None

    async def get_page(
        self,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> PageResult[DownloadHistory]:
        entity_type: Optional[str] = filters.get("entity_type")
        status: Optional[str] = filters.get("status")
        page, page_size = self.validate_page_params(page, page_size)
        queryset = self.model.objects.all()

        if entity_type:
            queryset = queryset.filter(url__contains=entity_type)

        if status:
            if status == "COMPLETED":
                queryset = queryset.filter(completed_at__isnull=False)
            elif status == "IN_PROGRESS":
                queryset = queryset.filter(completed_at__isnull=True, progress__gt=0)
            elif status == "PENDING":
                queryset = queryset.filter(completed_at__isnull=True, progress=0)

        total_count = await queryset.acount()
        offset = (page - 1) * page_size

        def fetch_items() -> List[DjangoDownloadHistory]:
            return list(queryset.order_by("-added_at")[offset : offset + page_size])

        items = await sync_to_async(fetch_items)()

        return PageResult(
            items=[self._to_graphql_type(item) for item in items],
            page=page,
            page_size=page_size,
            total_count=total_count,
        )

    def _to_graphql_type(
        self, django_history: DjangoDownloadHistory
    ) -> DownloadHistory:
        # Extract entity type and ID from URL
        url_parts = django_history.url.split(":")
        entity_type = url_parts[1].upper() if len(url_parts) > 1 else "UNKNOWN"
        entity_id = url_parts[2] if len(url_parts) > 2 else django_history.url

        # Determine status
        if django_history.completed_at:
            status = DownloadStatus.COMPLETED
        elif django_history.progress > 0:
            status = DownloadStatus.IN_PROGRESS
        else:
            status = DownloadStatus.PENDING

        return DownloadHistory(
            id=str(django_history.id),
            entity_id=entity_id,
            entity_type=entity_type,
            status=status,
            started_at=django_history.added_at,
            completed_at=django_history.completed_at,
            error_message=(
                getattr(django_history, "error_message", None)
                if hasattr(django_history, "error_message")
                else None
            ),
        )
