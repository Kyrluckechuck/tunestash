from math import ceil
from typing import Any, Generic, List, Optional, Tuple, TypeVar, Union

from ..types.typing import SupportsId
from ..utils.cursor import decode_cursor as decode_cursor_value
from ..utils.cursor import encode_cursor as encode_cursor_value

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

    async def get_connection(
        self, first: int = 20, after: Optional[str] = None, **filters: Any
    ) -> Union[Tuple[List[T], bool, int], Any]:
        """
        Returns a tuple of (items, has_next_page, total_count)
        or a specialized result type for complex pagination needs.
        """
        raise NotImplementedError

    @staticmethod
    def validate_page_params(page: int, page_size: int) -> Tuple[int, int]:
        """Validate and clamp pagination parameters."""
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        return page, page_size

    def create_cursor(self, item: SupportsId | T) -> str:
        """
        Creates a cursor for pagination based on the item
        """
        # Many GraphQL/DTO types guarantee an `id` field
        if hasattr(item, "id"):
            return encode_cursor_value(getattr(item, "id"))
        raise NotImplementedError("Item lacks an 'id' for cursor generation")

    def create_cursor_from_offset(self, offset: int) -> str:
        """
        Creates a cursor for offset-based pagination.
        Used when sorting by non-ID fields where cursor-based pagination won't work.
        """
        return encode_cursor_value(offset)

    def decode_cursor(self, cursor: str) -> Union[int, str]:
        """
        Decodes an opaque cursor into a value that can be used for filtering
        """
        return decode_cursor_value(cursor)
