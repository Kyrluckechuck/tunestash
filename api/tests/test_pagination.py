import pytest

from src.services.base import BaseService, PageResult


class TestPageResult:
    """Test PageResult pagination calculations."""

    def test_page_one(self) -> None:
        result = PageResult(
            items=list(range(10)), page=1, page_size=10, total_count=100
        )
        assert result.page == 1
        assert result.page_size == 10
        assert len(result.items) == 10

    def test_total_pages_exact_division(self) -> None:
        result = PageResult(items=[], page=1, page_size=10, total_count=100)
        assert result.total_pages == 10

    def test_total_pages_remainder(self) -> None:
        result = PageResult(items=[], page=1, page_size=10, total_count=101)
        assert result.total_pages == 11

    def test_total_pages_zero_items(self) -> None:
        result = PageResult(items=[], page=1, page_size=50, total_count=0)
        assert result.total_pages == 0

    def test_page_beyond_total(self) -> None:
        result = PageResult(items=[], page=100, page_size=10, total_count=50)
        assert result.total_pages == 5
        assert result.page == 100
        assert len(result.items) == 0

    def test_rejects_zero_page_size(self) -> None:
        with pytest.raises(ValueError, match="page_size must be >= 1"):
            PageResult(items=[], page=1, page_size=0, total_count=10)


class TestValidatePageParams:
    """Test BaseService.validate_page_params."""

    def test_clamps_page_minimum(self) -> None:
        page, page_size = BaseService.validate_page_params(0, 50)
        assert page == 1

    def test_clamps_page_size_minimum(self) -> None:
        page, page_size = BaseService.validate_page_params(1, 0)
        assert page_size == 1

    def test_clamps_page_size_maximum(self) -> None:
        page, page_size = BaseService.validate_page_params(1, 500)
        assert page_size == 200

    def test_valid_params_unchanged(self) -> None:
        page, page_size = BaseService.validate_page_params(5, 50)
        assert page == 5
        assert page_size == 50
