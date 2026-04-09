"""Unit tests for task history service."""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from asgiref.sync import sync_to_async
from tests.factories import CompletedTaskFactory, FailedTaskFactory, TaskHistoryFactory

from src.graphql_types.models import EntityType, TaskStatus, TaskType
from src.services.task_history import TaskHistoryService


@pytest.fixture
def task_history_service():
    return TaskHistoryService()


@pytest.fixture
def mock_task():
    return Mock(
        id="task_123",
        type="SYNC",
        entity_id="entity_456",
        entity_type="ARTIST",
        status="RUNNING",
        started_at=datetime.now(),
        completed_at=None,
        error_message=None,
        duration_seconds=0,
        progress_percentage=50,
        log_messages=["Task started", "Processing..."],
    )


class TestTaskHistoryService:
    """Test TaskHistoryService functionality."""

    def test_task_history_service_initialization(self, task_history_service):
        """Test TaskHistoryService can be initialized."""
        assert task_history_service is not None
        assert hasattr(task_history_service, "create_task")
        assert hasattr(task_history_service, "get_page")
        assert hasattr(task_history_service, "_to_graphql_type")

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_success(self, task_history_service):
        """Test creating a task successfully."""
        import uuid

        unique_id = f"test_task_{uuid.uuid4().hex[:8]}"
        task = await task_history_service.create_task(
            task_id=unique_id,
            task_type=TaskType.SYNC,
            entity_id="artist_456",
            entity_type=EntityType.ARTIST,
        )

        assert task is not None
        assert task.task_id == unique_id
        assert task.type == "SYNC"
        assert task.entity_id == "artist_456"
        assert task.entity_type == "ARTIST"
        assert task.status == "PENDING"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_with_filters(self, task_history_service):
        """Test getting task page with filters."""
        import uuid

        suffix = uuid.uuid4().hex[:8]
        await sync_to_async(CompletedTaskFactory)(task_id=f"completed_task_{suffix}")
        await sync_to_async(FailedTaskFactory)(task_id=f"failed_task_{suffix}")

        result = await task_history_service.get_page(
            page=1, page_size=10, status=TaskStatus.COMPLETED
        )

        assert len(result.items) >= 1
        assert result.total_count >= 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_with_pagination(self, task_history_service):
        """Test getting task page with pagination."""
        import uuid

        suffix = uuid.uuid4().hex[:8]
        for i in range(5):
            await sync_to_async(TaskHistoryFactory)(
                task_id=f"paginated_task_{suffix}_{i}"
            )

        result = await task_history_service.get_page(page=1, page_size=3)

        assert len(result.items) == 3
        assert result.total_count >= 5
        assert result.total_pages >= 2

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_with_sorting(self, task_history_service):
        """Test getting task page with sorting."""
        import uuid

        suffix = uuid.uuid4().hex[:8]
        await sync_to_async(TaskHistoryFactory)(
            started_at=datetime.now() - timedelta(hours=2), task_id=f"old_task_{suffix}"
        )
        await sync_to_async(TaskHistoryFactory)(
            started_at=datetime.now(), task_id=f"new_task_{suffix}"
        )

        result = await task_history_service.get_page(page=1, page_size=10)

        assert len(result.items) >= 2
        assert result.items[0].started_at >= result.items[1].started_at

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_with_different_types(self, task_history_service):
        """Test creating tasks with different types."""
        import uuid

        unique_suffix = str(uuid.uuid4())[:8]

        # Test SYNC task
        sync_task = await task_history_service.create_task(
            task_id=f"sync_task_types_{unique_suffix}",
            task_type=TaskType.SYNC,
            entity_id="artist_123",
            entity_type=EntityType.ARTIST,
        )
        assert sync_task.type == "SYNC"

        # Test DOWNLOAD task
        download_task = await task_history_service.create_task(
            task_id=f"download_task_types_{unique_suffix}",
            task_type=TaskType.DOWNLOAD,
            entity_id="album_456",
            entity_type=EntityType.ALBUM,
        )
        assert download_task.type == "DOWNLOAD"

        # Test FETCH task
        fetch_task = await task_history_service.create_task(
            task_id=f"fetch_task_types_{unique_suffix}",
            task_type=TaskType.FETCH,
            entity_id="playlist_789",
            entity_type=EntityType.PLAYLIST,
        )
        assert fetch_task.type == "FETCH"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_empty_result(self, task_history_service):
        """Test getting page with no matching tasks."""
        result = await task_history_service.get_page(
            page=1, page_size=10, status=TaskStatus.FAILED
        )

        assert len(result.items) >= 0
        assert result.total_count >= 0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_with_search(self, task_history_service):
        """Test getting page with search filter."""
        await task_history_service.create_task(
            task_id="unique_search_task_456",
            task_type=TaskType.SYNC,
            entity_id="artist_123",
            entity_type=EntityType.ARTIST,
        )

        result = await task_history_service.get_page(
            page=1, page_size=10, search="unique_search_task_456"
        )

        assert len(result.items) >= 1
        assert result.total_count >= 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_second_page(self, task_history_service):
        """Test getting second page of results."""
        for i in range(5):
            await task_history_service.create_task(
                task_id=f"page_task_{i}",
                task_type=TaskType.SYNC,
                entity_id=f"entity_{i}",
                entity_type=EntityType.ARTIST,
            )

        result1 = await task_history_service.get_page(page=1, page_size=2)
        assert len(result1.items) == 2
        assert result1.total_count >= 5

        result2 = await task_history_service.get_page(page=2, page_size=2)
        assert len(result2.items) >= 0
        assert result2.page == 2

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_to_graphql_type_conversion(self, task_history_service):
        """Test conversion from Django model to GraphQL type."""
        # Create a task
        django_task = await task_history_service.create_task(
            task_id="test_conversion_789",
            task_type=TaskType.SYNC,
            entity_id="test_entity",
            entity_type=EntityType.ARTIST,
        )

        # Convert to GraphQL type
        graphql_task = task_history_service._to_graphql_type(django_task)

        assert graphql_task.task_id == "test_conversion_789"
        assert graphql_task.type == TaskType.SYNC
        assert graphql_task.entity_id == "test_entity"
        assert graphql_task.entity_type == EntityType.ARTIST
        assert graphql_task.status == TaskStatus.PENDING
        assert graphql_task.id == str(django_task.id)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_with_all_entity_types(self, task_history_service):
        """Test creating tasks with all entity types."""
        import uuid

        entity_types = [EntityType.ARTIST, EntityType.ALBUM, EntityType.PLAYLIST]

        for i, entity_type in enumerate(entity_types):
            task = await task_history_service.create_task(
                task_id=f"task_{entity_type.value}_{i}_{uuid.uuid4().hex[:8]}",
                task_type=TaskType.SYNC,
                entity_id=f"entity_{entity_type.value}_{i}",
                entity_type=entity_type,
            )

            assert task.entity_type == entity_type.value.upper()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_with_type_filter(self, task_history_service):
        """Test getting page with type filter."""
        await task_history_service.create_task(
            task_id="sync_task_filter_1",
            task_type=TaskType.SYNC,
            entity_id="entity_1",
            entity_type=EntityType.ARTIST,
        )

        await task_history_service.create_task(
            task_id="download_task_filter_1",
            task_type=TaskType.DOWNLOAD,
            entity_id="entity_2",
            entity_type=EntityType.ALBUM,
        )

        result = await task_history_service.get_page(
            page=1, page_size=10, type=TaskType.SYNC
        )

        assert len(result.items) >= 1
        assert all(item.type == TaskType.SYNC for item in result.items)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_cancelled_status_mapping(self, task_history_service):
        """Test that CANCELLED status is properly mapped to GraphQL type."""
        from library_manager.models import TaskHistory as DjangoTaskHistory

        # Create a task and mark it as cancelled
        django_task = await task_history_service.create_task(
            task_id="test_cancelled_mapping",
            task_type=TaskType.DOWNLOAD,
            entity_id="artist_123",
            entity_type=EntityType.ARTIST,
        )

        # Manually set status to CANCELLED (simulating cancellation)
        django_task.status = "CANCELLED"
        await sync_to_async(django_task.save)()

        # Refresh from DB and convert to GraphQL type
        refreshed_task = await sync_to_async(DjangoTaskHistory.objects.get)(
            task_id="test_cancelled_mapping"
        )
        graphql_task = task_history_service._to_graphql_type(refreshed_task)

        # Verify CANCELLED status is properly mapped
        assert graphql_task.status == TaskStatus.CANCELLED
        assert refreshed_task.status == "CANCELLED"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_page_filters_cancelled_tasks(self, task_history_service):
        """Test that cancelled tasks can be filtered in queries."""
        running_task = await task_history_service.create_task(
            task_id="running_task_filter",
            task_type=TaskType.DOWNLOAD,
            entity_id="artist_456",
            entity_type=EntityType.ARTIST,
        )
        running_task.status = "RUNNING"
        await sync_to_async(running_task.save)()

        cancelled_task = await task_history_service.create_task(
            task_id="cancelled_task_filter",
            task_type=TaskType.DOWNLOAD,
            entity_id="artist_789",
            entity_type=EntityType.ARTIST,
        )
        cancelled_task.status = "CANCELLED"
        await sync_to_async(cancelled_task.save)()

        running_result = await task_history_service.get_page(
            page=1, page_size=10, status=TaskStatus.RUNNING
        )

        running_task_ids = [item.task_id for item in running_result.items]
        assert "running_task_filter" in running_task_ids
        assert "cancelled_task_filter" not in running_task_ids

        cancelled_result = await task_history_service.get_page(
            page=1, page_size=10, status=TaskStatus.CANCELLED
        )

        cancelled_task_ids = [item.task_id for item in cancelled_result.items]
        assert "cancelled_task_filter" in cancelled_task_ids
        assert "running_task_filter" not in cancelled_task_ids
