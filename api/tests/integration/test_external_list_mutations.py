"""Integration tests for external list GraphQL mutations.

These tests exercise the full GraphQL → mutation → service → ORM chain,
catching type mismatches and wiring bugs at the untyped API boundary.
"""

from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from asgiref.sync import sync_to_async

from library_manager.models import (
    ExternalList,
    ExternalListSource,
    ExternalListStatus,
    ExternalListType,
)
from src.schema import schema


async def _create_list(**overrides):
    """Helper to create an ExternalList with sensible defaults."""
    defaults = {
        "name": "Last.fm Loved Tracks - testuser",
        "source": ExternalListSource.LASTFM,
        "list_type": ExternalListType.LOVED_TRACKS,
        "username": "testuser",
        "status": ExternalListStatus.ACTIVE,
    }
    defaults.update(overrides)
    return await sync_to_async(ExternalList.objects.create)(**defaults)


UPDATE_MUTATION = """
mutation UpdateExternalList(
    $listId: Int!
    $name: String
    $username: String
    $period: String
    $listIdentifier: String
) {
    updateExternalList(
        listId: $listId
        name: $name
        username: $username
        period: $period
        listIdentifier: $listIdentifier
    ) {
        success
        message
    }
}
"""

DELETE_MUTATION = """
mutation DeleteExternalList($listId: Int!) {
    deleteExternalList(listId: $listId) {
        success
        message
    }
}
"""

TOGGLE_MUTATION = """
mutation ToggleExternalList($listId: Int!) {
    toggleExternalList(listId: $listId) {
        success
        message
    }
}
"""

SYNC_MUTATION = """
mutation SyncExternalList($listId: Int!, $force: Boolean) {
    syncExternalList(listId: $listId, force: $force) {
        success
        message
    }
}
"""

CREATE_MUTATION = """
mutation CreateExternalList(
    $source: String!
    $listType: String!
    $username: String!
    $period: String
    $listIdentifier: String
    $autoTrackArtists: Boolean
) {
    createExternalList(
        source: $source
        listType: $listType
        username: $username
        period: $period
        listIdentifier: $listIdentifier
        autoTrackArtists: $autoTrackArtists
    ) {
        id
        name
        source
        listType
        username
        status
    }
}
"""


class TestUpdateExternalListMutation(TransactionTestCase):
    """Test the updateExternalList mutation end-to-end."""

    async def test_update_name_only(self):
        ext_list = await _create_list()

        variables = {"listId": ext_list.id, "name": "My Custom Name"}
        result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data["updateExternalList"]["success"] is True
        assert "re-sync" not in result.data["updateExternalList"]["message"]

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.name == "My Custom Name"
        assert refreshed.username == "testuser"

    async def test_update_username_triggers_resync(self):
        ext_list = await _create_list()

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {"listId": ext_list.id, "username": "newuser"}
            result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

            assert result.errors is None, f"GraphQL errors: {result.errors}"
            assert result.data["updateExternalList"]["success"] is True
            assert "re-sync" in result.data["updateExternalList"]["message"]

            mock_task.delay.assert_called_once_with(ext_list.id, force=True)

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.username == "newuser"

    async def test_update_list_identifier_triggers_resync(self):
        ext_list = await _create_list(
            source=ExternalListSource.LISTENBRAINZ,
            list_type=ExternalListType.PLAYLIST,
            username="lbuser",
            list_identifier="old-mbid-123",
            name="LB Playlist",
        )

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {
                "listId": ext_list.id,
                "listIdentifier": "new-mbid-456",
            }
            result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

            assert result.errors is None, f"GraphQL errors: {result.errors}"
            assert result.data["updateExternalList"]["success"] is True
            assert "re-sync" in result.data["updateExternalList"]["message"]

            mock_task.delay.assert_called_once_with(ext_list.id, force=True)

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.list_identifier == "new-mbid-456"

    async def test_update_same_username_no_resync(self):
        """Sending the same username value should not trigger a re-sync."""
        ext_list = await _create_list(username="samename")

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {"listId": ext_list.id, "username": "samename"}
            result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

            assert result.errors is None
            assert result.data["updateExternalList"]["success"] is True
            assert "re-sync" not in result.data["updateExternalList"]["message"]

            mock_task.delay.assert_not_called()

    async def test_update_multiple_fields(self):
        ext_list = await _create_list(
            source=ExternalListSource.LASTFM,
            list_type=ExternalListType.TOP_TRACKS,
            period="7day",
            username="olduser",
            name="Old Name",
        )

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {
                "listId": ext_list.id,
                "name": "New Name",
                "username": "newuser",
                "period": "overall",
            }
            result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

            assert result.errors is None
            assert result.data["updateExternalList"]["success"] is True
            # Username changed, so re-sync should fire
            mock_task.delay.assert_called_once()

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.name == "New Name"
        assert refreshed.username == "newuser"
        assert refreshed.period == "overall"

    async def test_update_no_fields_is_noop(self):
        """Passing no optional fields should succeed without changes."""
        ext_list = await _create_list(name="Original Name")

        variables = {"listId": ext_list.id}
        result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["updateExternalList"]["success"] is True

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.name == "Original Name"

    async def test_update_nonexistent_list(self):
        variables = {"listId": 99999, "name": "Ghost"}
        result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["updateExternalList"]["success"] is False
        assert "not found" in result.data["updateExternalList"]["message"].lower()

    async def test_update_whitespace_handling(self):
        """Name and username should be stripped of leading/trailing whitespace."""
        ext_list = await _create_list()

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {
                "listId": ext_list.id,
                "name": "  Trimmed Name  ",
                "username": "  trimmeduser  ",
            }
            result = await schema.execute(UPDATE_MUTATION, variable_values=variables)

            assert result.errors is None
            assert result.data["updateExternalList"]["success"] is True

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.name == "Trimmed Name"
        assert refreshed.username == "trimmeduser"


class TestDeleteExternalListMutation(TransactionTestCase):
    """Test the deleteExternalList mutation."""

    async def test_delete_success(self):
        ext_list = await _create_list(name="Doomed List")

        variables = {"listId": ext_list.id}
        result = await schema.execute(DELETE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["deleteExternalList"]["success"] is True
        assert "Doomed List" in result.data["deleteExternalList"]["message"]

        exists = await sync_to_async(
            ExternalList.objects.filter(id=ext_list.id).exists
        )()
        assert exists is False

    async def test_delete_nonexistent(self):
        variables = {"listId": 99999}
        result = await schema.execute(DELETE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["deleteExternalList"]["success"] is False


class TestToggleExternalListMutation(TransactionTestCase):
    """Test the toggleExternalList mutation."""

    async def test_disable_active_list(self):
        ext_list = await _create_list(status=ExternalListStatus.ACTIVE)

        variables = {"listId": ext_list.id}
        result = await schema.execute(TOGGLE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["toggleExternalList"]["success"] is True

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.status == ExternalListStatus.DISABLED_BY_USER

    async def test_enable_disabled_list(self):
        ext_list = await _create_list(status=ExternalListStatus.DISABLED_BY_USER)

        variables = {"listId": ext_list.id}
        result = await schema.execute(TOGGLE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["toggleExternalList"]["success"] is True

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.status == ExternalListStatus.ACTIVE

    async def test_reset_error_status(self):
        ext_list = await _create_list(status=ExternalListStatus.AUTH_ERROR)

        variables = {"listId": ext_list.id}
        result = await schema.execute(TOGGLE_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["toggleExternalList"]["success"] is True

        refreshed = await ExternalList.objects.aget(id=ext_list.id)
        assert refreshed.status == ExternalListStatus.ACTIVE


class TestSyncExternalListMutation(TransactionTestCase):
    """Test the syncExternalList mutation."""

    async def test_sync_queues_task(self):
        ext_list = await _create_list()

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {"listId": ext_list.id}
            result = await schema.execute(SYNC_MUTATION, variable_values=variables)

            assert result.errors is None
            assert result.data["syncExternalList"]["success"] is True

            mock_task.delay.assert_called_once_with(ext_list.id, force=False)

    async def test_force_sync(self):
        ext_list = await _create_list()

        with patch("library_manager.tasks.sync_external_list") as mock_task:
            mock_task.delay = MagicMock()

            variables = {"listId": ext_list.id, "force": True}
            result = await schema.execute(SYNC_MUTATION, variable_values=variables)

            assert result.errors is None
            assert result.data["syncExternalList"]["success"] is True

            mock_task.delay.assert_called_once_with(ext_list.id, force=True)

    async def test_sync_nonexistent(self):
        variables = {"listId": 99999}
        result = await schema.execute(SYNC_MUTATION, variable_values=variables)

        assert result.errors is None
        assert result.data["syncExternalList"]["success"] is False


class TestCreateExternalListMutation(TransactionTestCase):
    """Test the createExternalList mutation."""

    async def test_create_lastfm_loved(self):
        with (
            patch("src.providers.get_provider") as mock_get_provider,
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_provider = MagicMock()
            mock_provider.validate_user.return_value = (True, None)
            mock_get_provider.return_value = mock_provider
            mock_task.delay = MagicMock()

            variables = {
                "source": "lastfm",
                "listType": "loved",
                "username": "testuser",
            }
            result = await schema.execute(CREATE_MUTATION, variable_values=variables)

            assert result.errors is None, f"GraphQL errors: {result.errors}"
            data = result.data["createExternalList"]
            assert data["source"] == "lastfm"
            assert data["listType"] == "loved"
            assert data["username"] == "testuser"
            assert data["status"] == "active"

            mock_task.delay.assert_called_once()

    async def test_create_returns_existing_on_duplicate(self):
        """Creating a list with the same source/type/username should return existing."""
        existing = await _create_list(
            source=ExternalListSource.LASTFM,
            list_type=ExternalListType.LOVED_TRACKS,
            username="dupeuser",
        )

        with (
            patch("src.providers.get_provider") as mock_get_provider,
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_provider = MagicMock()
            mock_provider.validate_user.return_value = (True, None)
            mock_get_provider.return_value = mock_provider
            mock_task.delay = MagicMock()

            variables = {
                "source": "lastfm",
                "listType": "loved",
                "username": "dupeuser",
            }
            result = await schema.execute(CREATE_MUTATION, variable_values=variables)

            assert result.errors is None
            data = result.data["createExternalList"]
            assert int(data["id"]) == existing.id

            # Should NOT queue a new sync for existing list
            mock_task.delay.assert_not_called()

    async def test_create_listenbrainz_top_with_period(self):
        with (
            patch("src.providers.get_provider") as mock_get_provider,
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_provider = MagicMock()
            mock_provider.validate_user.return_value = (True, None)
            mock_get_provider.return_value = mock_provider
            mock_task.delay = MagicMock()

            variables = {
                "source": "listenbrainz",
                "listType": "top",
                "username": "lbuser",
                "period": "this_month",
            }
            result = await schema.execute(CREATE_MUTATION, variable_values=variables)

            assert result.errors is None
            data = result.data["createExternalList"]
            assert data["source"] == "listenbrainz"
            assert data["listType"] == "top"

    async def test_create_validation_failure(self):
        """Provider validation failure should raise."""
        with patch("src.providers.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.validate_user.return_value = (False, "User not found")
            mock_get_provider.return_value = mock_provider

            variables = {
                "source": "lastfm",
                "listType": "loved",
                "username": "nonexistent",
            }
            result = await schema.execute(CREATE_MUTATION, variable_values=variables)

            # Strawberry wraps ValueError as a GraphQL error
            assert result.errors is not None
            assert "not found" in str(result.errors[0]).lower()
