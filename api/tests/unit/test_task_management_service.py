"""Unit tests for task management service."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.services.task_management import MutationResult, TaskManagementService


@pytest.fixture
def task_management_service():
    return TaskManagementService()


@pytest.fixture
def mock_celery_app():
    """Mock Celery app instance for testing."""
    return Mock()


@pytest.fixture
def mock_celery_task():
    """Mock a Celery task result."""
    return {
        "id": "task_123",
        "name": "test_task",
        "args": ["arg1", "arg2"],
        "kwargs": {"key1": "value1"},
    }


class TestTaskManagementService:
    """Test TaskManagementService functionality."""

    def test_task_management_service_initialization(self, task_management_service):
        """Test TaskManagementService can be initialized."""
        assert task_management_service is not None
        assert hasattr(task_management_service, "get_pending_tasks")
        assert hasattr(task_management_service, "get_task_count_by_name")
        assert hasattr(task_management_service, "cancel_all_pending_tasks")
        assert hasattr(task_management_service, "cancel_tasks_by_name")
        assert hasattr(task_management_service, "get_queue_status")

    @patch("src.services.task_management.TaskResult")
    def test_get_pending_tasks_success(
        self, mock_task_result, task_management_service, mock_celery_task
    ):
        """Test getting pending tasks successfully."""
        mock_queryset = Mock()
        mock_queryset.values.return_value = [
            {
                "task_id": "task_123",
                "task_name": "test_task",
                "task_args": ["arg1", "arg2"],
                "task_kwargs": {"key1": "value1"},
            }
        ]
        mock_task_result.objects.filter.return_value = mock_queryset

        result = task_management_service.get_pending_tasks()

        assert len(result) == 1
        assert result[0]["id"] == "task_123"
        assert result[0]["name"] == "test_task"
        assert result[0]["args"] == ["arg1", "arg2"]
        assert result[0]["kwargs"] == {"key1": "value1"}

    @patch("src.services.task_management.TaskResult")
    def test_get_pending_tasks_empty(self, mock_task_result, task_management_service):
        """Test getting pending tasks when queue is empty."""
        mock_queryset = Mock()
        mock_queryset.values.return_value = []
        mock_task_result.objects.filter.return_value = mock_queryset

        result = task_management_service.get_pending_tasks()

        assert result == []

    @patch("src.services.task_management.TaskResult")
    def test_get_pending_tasks_exception(
        self, mock_task_result, task_management_service
    ):
        """Test getting pending tasks when database raises an exception."""
        mock_task_result.objects.filter.side_effect = Exception(
            "Database connection error"
        )

        # The actual implementation doesn't handle exceptions, so this should raise
        with pytest.raises(Exception, match="Database connection error"):
            task_management_service.get_pending_tasks()

    @pytest.mark.asyncio
    async def test_get_task_count_by_name(self, task_management_service):
        """Test getting task count by name."""
        # Mock the TaskResult model and its query
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock the filter and values chain
            mock_queryset = Mock()
            mock_values = Mock()
            mock_values.__iter__ = Mock(
                return_value=iter(
                    [
                        {"task_name": "test_task"},
                        {"task_name": "test_task"},
                        {"task_name": "other_task"},
                    ]
                )
            )
            mock_queryset.values.return_value = mock_values
            mock_task_result.objects.filter.return_value = mock_queryset

            result = await task_management_service.get_task_count_by_name()

            assert result["test_task"] == 2
            assert result["other_task"] == 1

    @pytest.mark.asyncio
    async def test_get_task_count_by_name_not_found(self, task_management_service):
        """Test getting task count for non-existent task name."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            mock_queryset = Mock()
            mock_values = Mock()
            mock_values.__iter__ = Mock(return_value=iter([]))
            mock_queryset.values.return_value = mock_values
            mock_task_result.objects.filter.return_value = mock_queryset

            result = await task_management_service.get_task_count_by_name()

            assert result == {}

    @pytest.mark.asyncio
    async def test_cancel_all_pending_tasks_success(
        self, task_management_service, mock_celery_task
    ):
        """Test cancelling all pending tasks successfully."""
        with (
            patch("src.services.task_management.TaskResult") as mock_task_result,
            patch("src.services.task_management.celery_app"),
            patch("src.services.task_management.sync_to_async") as mock_sync,
            patch("library_manager.models.TaskHistory") as mock_task_history,
        ):
            # Mock database update to return 1 updated row
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=1)
            mock_task_result.objects.filter.return_value = mock_queryset

            # Mock TaskHistory update
            mock_th_queryset = Mock()
            mock_th_queryset.aupdate = AsyncMock(return_value=2)
            mock_task_history.objects.filter.return_value = mock_th_queryset

            # Mock purge to return 3
            mock_sync.return_value = AsyncMock(return_value=3)

            result = await task_management_service.cancel_all_pending_tasks()

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_all_pending_tasks_empty_queue(self, task_management_service):
        """Test cancelling all pending tasks when queue is empty."""
        with (
            patch("src.services.task_management.TaskResult") as mock_task_result,
            patch("src.services.task_management.celery_app"),
            patch("src.services.task_management.sync_to_async") as mock_sync,
            patch("library_manager.models.TaskHistory") as mock_task_history,
        ):
            # Mock database update to return 0 updated rows
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=0)
            mock_task_result.objects.filter.return_value = mock_queryset

            # Mock TaskHistory update
            mock_th_queryset = Mock()
            mock_th_queryset.aupdate = AsyncMock(return_value=0)
            mock_task_history.objects.filter.return_value = mock_th_queryset

            # Mock purge to return 0
            mock_sync.return_value = AsyncMock(return_value=0)

            result = await task_management_service.cancel_all_pending_tasks()

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_all_pending_tasks_multiple_tasks(
        self, task_management_service
    ):
        """Test cancelling multiple pending tasks."""
        with (
            patch("src.services.task_management.TaskResult") as mock_task_result,
            patch("src.services.task_management.celery_app"),
            patch("src.services.task_management.sync_to_async") as mock_sync,
            patch("library_manager.models.TaskHistory") as mock_task_history,
        ):
            # Mock database update to return 5 updated rows
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=5)
            mock_task_result.objects.filter.return_value = mock_queryset

            # Mock TaskHistory update
            mock_th_queryset = Mock()
            mock_th_queryset.aupdate = AsyncMock(return_value=3)
            mock_task_history.objects.filter.return_value = mock_th_queryset

            # Mock purge to return 10
            mock_sync.return_value = AsyncMock(return_value=10)

            result = await task_management_service.cancel_all_pending_tasks()

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_all_pending_tasks_celery_exception(
        self, task_management_service
    ):
        """Test cancelling all pending tasks when database raises an exception."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            mock_task_result.objects.filter.side_effect = Exception(
                "Database connection error"
            )

            result = await task_management_service.cancel_all_pending_tasks()

            assert isinstance(result, MutationResult)
            assert result.success is False
            assert "Failed to cancel tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_tasks_by_name_success(self, task_management_service):
        """Test cancelling tasks by name successfully."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock database update to return 2 updated rows
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=2)
            mock_task_result.objects.filter.return_value = mock_queryset

            result = await task_management_service.cancel_tasks_by_name("test_task")

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled 2 tasks" in result.message
            # Verify aupdate was called with REVOKED status
            mock_queryset.aupdate.assert_called_once_with(status="REVOKED")

    @pytest.mark.asyncio
    async def test_cancel_tasks_by_name_not_found(self, task_management_service):
        """Test cancelling tasks by name when no matching tasks exist."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock database update to return 0 updated rows
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=0)
            mock_task_result.objects.filter.return_value = mock_queryset

            result = await task_management_service.cancel_tasks_by_name(
                "non_existent_task"
            )

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled 0 tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_tasks_by_name_multiple_tasks(self, task_management_service):
        """Test cancelling multiple tasks with the same name."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock database update to return 3 updated rows
            mock_queryset = Mock()
            mock_queryset.aupdate = AsyncMock(return_value=3)
            mock_task_result.objects.filter.return_value = mock_queryset

            result = await task_management_service.cancel_tasks_by_name(
                "download_playlist"
            )

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled 3 tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_running_tasks_by_name_success(self, task_management_service):
        """Test cancelling running tasks by name successfully."""
        with (
            patch("library_manager.models.TaskHistory"),
            patch("src.services.task_management.sync_to_async") as mock_sync_to_async,
        ):
            # Mock running tasks
            mock_task1 = Mock()
            mock_task1.task_id = "task_1"
            mock_task1.status = "RUNNING"
            mock_task1.asave = AsyncMock()

            mock_task2 = Mock()
            mock_task2.task_id = "task_2"
            mock_task2.status = "RUNNING"
            mock_task2.asave = AsyncMock()

            # Mock sync_to_async to return the list of running tasks
            mock_sync_to_async.return_value = AsyncMock(
                return_value=[mock_task1, mock_task2]
            )

            result = await task_management_service.cancel_running_tasks_by_name(
                "download_playlist"
            )

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled 2 running tasks" in result.message

    @pytest.mark.asyncio
    async def test_cancel_all_tasks_success(self, task_management_service):
        """Test cancelling all tasks (pending and running) successfully."""
        with (
            patch("src.services.task_management.TaskResult") as mock_task_result,
            patch("src.services.task_management.celery_app"),
            patch("src.services.task_management.sync_to_async") as mock_sync_to_async,
            patch("library_manager.models.TaskHistory") as mock_task_history,
        ):
            # Mock pending tasks update to return 1 updated row
            mock_pending_queryset = Mock()
            mock_pending_queryset.aupdate = AsyncMock(return_value=1)

            # Mock TaskResult.objects.filter for running task updates
            mock_running_queryset = Mock()
            mock_running_queryset.aupdate = AsyncMock(return_value=1)

            # Configure mock_task_result to return different querysets for different calls
            mock_task_result.objects.filter.side_effect = [
                mock_pending_queryset,  # First call for pending tasks
                mock_running_queryset,  # Second call for running task
            ]

            # Mock TaskHistory updates
            mock_th_queryset = Mock()
            mock_th_queryset.aupdate = AsyncMock(return_value=2)
            mock_task_history.objects.filter.return_value = mock_th_queryset

            # Mock running tasks (for cancel_all_tasks second part)
            mock_running_task = Mock()
            mock_running_task.task_id = "task_2"
            mock_running_task.status = "RUNNING"
            mock_running_task.asave = AsyncMock()

            # Mock sync_to_async - first call for purge (returns 0), second for running tasks list
            mock_sync_to_async.side_effect = [
                AsyncMock(return_value=0),  # purge_queues result
                AsyncMock(return_value=[mock_running_task]),  # running tasks list
            ]

            result = await task_management_service.cancel_all_tasks()

            assert isinstance(result, MutationResult)
            assert result.success is True
            assert "Successfully cancelled" in result.message

    @pytest.mark.asyncio
    async def test_get_queue_status_success(self, task_management_service):
        """Test getting queue status successfully."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock database query to return count of 3 pending tasks
            mock_queryset = Mock()
            mock_queryset.acount = AsyncMock(return_value=3)
            mock_task_result.objects.filter.return_value = mock_queryset

            # Mock the async get_task_count_by_name method
            with patch.object(
                task_management_service,
                "get_task_count_by_name",
                new_callable=AsyncMock,
                return_value={"task_a": 2, "task_b": 1},
            ):
                result = await task_management_service.get_queue_status()

            assert result["total_pending_tasks"] == 3
            assert result["task_counts"]["task_a"] == 2
            assert result["task_counts"]["task_b"] == 1

    @pytest.mark.asyncio
    async def test_get_queue_status_empty(self, task_management_service):
        """Test getting queue status when queue is empty."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            # Mock database query to return count of 0
            mock_queryset = Mock()
            mock_queryset.acount = AsyncMock(return_value=0)
            mock_task_result.objects.filter.return_value = mock_queryset

            # Mock the async get_task_count_by_name method
            with patch.object(
                task_management_service,
                "get_task_count_by_name",
                new_callable=AsyncMock,
                return_value={},
            ):
                result = await task_management_service.get_queue_status()

            assert result["total_pending_tasks"] == 0
            assert result["task_counts"] == {}

    @pytest.mark.asyncio
    async def test_get_queue_status_exception(self, task_management_service):
        """Test getting queue status when database raises an exception."""
        with patch("src.services.task_management.TaskResult") as mock_task_result:
            mock_task_result.objects.filter.side_effect = Exception(
                "Database connection error"
            )

            # The actual implementation doesn't handle exceptions, so this should raise
            with pytest.raises(Exception, match="Database connection error"):
                await task_management_service.get_queue_status()

    def test_mutation_result_creation(self):
        """Test MutationResult creation for task management."""
        success_result = MutationResult(success=True, message="Success")
        assert success_result.success is True
        assert success_result.message == "Success"

        failure_result = MutationResult(success=False, message="Failed")
        assert failure_result.success is False
        assert failure_result.message == "Failed"


class TestExtractEntityId:
    """Test _extract_entity_id helper function."""

    def test_extract_entity_id_from_list_args(self):
        """Test extracting entity ID from list args."""
        from src.services.task_management import _extract_entity_id

        result = _extract_entity_id("some_task", [123], {})
        assert result == 123

    def test_extract_entity_id_from_tuple_args(self):
        """Test extracting entity ID from tuple args (Celery stores args as tuples)."""
        from src.services.task_management import _extract_entity_id

        # Celery stores args as tuples like (123,)
        result = _extract_entity_id("some_task", (456,), {})
        assert result == 456

    def test_extract_entity_id_from_kwargs(self):
        """Test extracting entity ID from kwargs takes precedence."""
        from src.services.task_management import _extract_entity_id

        result = _extract_entity_id("download_artist", [999], {"artist_id": 123})
        assert result == 123

    def test_extract_entity_id_from_kwargs_playlist_url(self):
        """Test extracting playlist URL from kwargs."""
        from src.services.task_management import _extract_entity_id

        result = _extract_entity_id(
            "sync_playlist",
            [],
            {"playlist_url": "spotify:playlist:abc123"},
        )
        assert result == "spotify:playlist:abc123"

    def test_extract_entity_id_empty_args(self):
        """Test extracting entity ID with empty args returns None."""
        from src.services.task_management import _extract_entity_id

        result = _extract_entity_id("some_task", [], {})
        assert result is None

    def test_extract_entity_id_empty_tuple(self):
        """Test extracting entity ID with empty tuple returns None."""
        from src.services.task_management import _extract_entity_id

        result = _extract_entity_id("some_task", (), {})
        assert result is None

    def test_extract_entity_id_string_args_fallback(self):
        """Test that string args (unparseable) returns None."""
        from src.services.task_management import _extract_entity_id

        # If JSON parsing failed, args might be a raw string
        result = _extract_entity_id("some_task", "unparsed_string", {})
        assert result is None


class TestParseJsonField:
    """Test _parse_json_field helper function."""

    def test_parse_json_string(self):
        """Test parsing JSON string."""
        from src.services.task_management import _parse_json_field

        result = _parse_json_field('["arg1", "arg2"]')
        assert result == ["arg1", "arg2"]

    def test_parse_python_repr_tuple(self):
        """Test parsing Python repr tuple string."""
        from src.services.task_management import _parse_json_field

        # Celery stores args as Python repr: "(123,)"
        result = _parse_json_field("(123,)")
        assert result == (123,)

    def test_parse_python_repr_with_booleans(self):
        """Test parsing Python repr with True/False."""
        from src.services.task_management import _parse_json_field

        result = _parse_json_field("{'flag': True, 'count': 5}")
        assert result == {"flag": True, "count": 5}

    def test_parse_already_parsed_value(self):
        """Test that already parsed values are returned as-is."""
        from src.services.task_management import _parse_json_field

        result = _parse_json_field([1, 2, 3])
        assert result == [1, 2, 3]

    def test_parse_double_encoded_string(self):
        """Test parsing double-encoded JSON (JSON containing Python repr)."""
        from src.services.task_management import _parse_json_field

        # JSON string containing Python repr
        result = _parse_json_field('"(123,)"')
        assert result == (123,)
