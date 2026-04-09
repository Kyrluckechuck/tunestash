from math import ceil
from typing import Any, Generic, List, Optional, Tuple, TypeVar

T = TypeVar("T")


class PageResult(Generic[T]):
    """Result of a paginated query."""

    __slots__ = ("items", "page", "page_size", "total_pages", "total_count")

    def __init__(
        self,
        items: List[T],
        page: int,
        page_size: int,
        total_count: int,
    ) -> None:
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")
        self.items = items
        self.page = page
        self.page_size = page_size
        self.total_count = total_count
        self.total_pages = ceil(total_count / page_size) if total_count > 0 else 0


class BaseService(Generic[T]):
    def __init__(self) -> None:
        # Django model type is dynamic; keep typing flexible to avoid false-positives
        self.model: Any = None

    async def get_by_id(self, id: str) -> Optional[T]:
        raise NotImplementedError

    @staticmethod
    def validate_page_params(page: int, page_size: int) -> Tuple[int, int]:
        """Validate and clamp pagination parameters."""
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        return page, page_size
