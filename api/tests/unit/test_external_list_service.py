"""Unit tests for ExternalListService.

Tests the service layer in isolation with mocked ORM calls,
focusing on business logic: partial updates, re-sync decisions,
and edge cases. Also tests get_page against a real DB for pagination
and filter correctness.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from asgiref.sync import sync_to_async
from tests.factories import ExternalListFactory

from library_manager.models import (
    ExternalListSource,
    ExternalListStatus,
    ExternalListType,
)
from src.services.external_list import (
    ExternalListService,
    _generate_list_name,
    _parse_url,
)


@pytest.mark.django_db
class TestExternalListServiceUpdate:
    """Test update_external_list business logic."""

    @pytest.fixture
    def service(self):
        return ExternalListService()

    def _mock_list(self, **overrides):
        """Build a mock ExternalList with sensible defaults."""
        obj = Mock()
        obj.id = overrides.get("id", 1)
        obj.name = overrides.get("name", "Test List")
        obj.source = overrides.get("source", ExternalListSource.LASTFM)
        obj.list_type = overrides.get("list_type", ExternalListType.LOVED_TRACKS)
        obj.username = overrides.get("username", "testuser")
        obj.period = overrides.get("period", None)
        obj.list_identifier = overrides.get("list_identifier", None)
        obj.status = overrides.get("status", ExternalListStatus.ACTIVE)
        obj.asave = AsyncMock()
        return obj

    @pytest.mark.asyncio
    async def test_update_name_only(self, service):
        mock_obj = self._mock_list(name="Old Name")

        with patch.object(
            service.model.objects, "aget", new_callable=AsyncMock, return_value=mock_obj
        ):
            result = await service.update_external_list(1, name="New Name")

        assert result.success is True
        assert mock_obj.name == "New Name"
        assert mock_obj.username == "testuser"
        mock_obj.asave.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_username_triggers_resync(self, service):
        mock_obj = self._mock_list(username="olduser")

        with (
            patch.object(
                service.model.objects,
                "aget",
                new_callable=AsyncMock,
                return_value=mock_obj,
            ),
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_task.delay = MagicMock()

            result = await service.update_external_list(1, username="newuser")

        assert result.success is True
        assert "re-sync" in result.message
        assert mock_obj.username == "newuser"
        mock_task.delay.assert_called_once_with(1, force=True)

    @pytest.mark.asyncio
    async def test_update_same_username_no_resync(self, service):
        mock_obj = self._mock_list(username="sameuser")

        with (
            patch.object(
                service.model.objects,
                "aget",
                new_callable=AsyncMock,
                return_value=mock_obj,
            ),
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_task.delay = MagicMock()

            result = await service.update_external_list(1, username="sameuser")

        assert result.success is True
        assert "re-sync" not in result.message
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_list_identifier_triggers_resync(self, service):
        mock_obj = self._mock_list(list_identifier="old-id")

        with (
            patch.object(
                service.model.objects,
                "aget",
                new_callable=AsyncMock,
                return_value=mock_obj,
            ),
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_task.delay = MagicMock()

            result = await service.update_external_list(1, list_identifier="new-id")

        assert result.success is True
        assert "re-sync" in result.message
        mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, service):
        with patch.object(
            service.model.objects,
            "aget",
            new_callable=AsyncMock,
            side_effect=service.model.DoesNotExist,
        ):
            result = await service.update_external_list(99999, name="Ghost")

        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_update_no_fields_is_noop(self, service):
        mock_obj = self._mock_list(name="Original")

        with patch.object(
            service.model.objects, "aget", new_callable=AsyncMock, return_value=mock_obj
        ):
            result = await service.update_external_list(1)

        assert result.success is True
        assert mock_obj.name == "Original"
        mock_obj.asave.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_strips_whitespace(self, service):
        mock_obj = self._mock_list(name="Old", username="old")

        with (
            patch.object(
                service.model.objects,
                "aget",
                new_callable=AsyncMock,
                return_value=mock_obj,
            ),
            patch("library_manager.tasks.sync_external_list") as mock_task,
        ):
            mock_task.delay = MagicMock()

            result = await service.update_external_list(
                1, name="  Padded Name  ", username="  padded  "
            )

        assert result.success is True
        assert mock_obj.name == "Padded Name"
        assert mock_obj.username == "padded"

    @pytest.mark.asyncio
    async def test_update_empty_period_becomes_none(self, service):
        mock_obj = self._mock_list(period="7day")

        with patch.object(
            service.model.objects, "aget", new_callable=AsyncMock, return_value=mock_obj
        ):
            result = await service.update_external_list(1, period="")

        assert result.success is True
        assert mock_obj.period is None


class TestParseUrl:
    """Test the URL parsing helper."""

    def test_lastfm_url(self):
        username, identifier = _parse_url("lastfm", "https://www.last.fm/user/JohnDoe")
        assert username == "johndoe"
        assert identifier is None

    def test_lastfm_plain_username(self):
        username, identifier = _parse_url("lastfm", "JohnDoe")
        assert username == "johndoe"
        assert identifier is None

    def test_listenbrainz_user_url(self):
        username, identifier = _parse_url(
            "listenbrainz", "https://listenbrainz.org/user/JaneDoe"
        )
        assert username == "janedoe"
        assert identifier is None

    def test_listenbrainz_playlist_url(self):
        username, identifier = _parse_url(
            "listenbrainz", "https://listenbrainz.org/playlist/abc-123-def"
        )
        assert username == ""
        assert identifier == "abc-123-def"

    def test_listenbrainz_plain_username(self):
        username, identifier = _parse_url("listenbrainz", "SomeUser")
        assert username == "someuser"

    def test_youtube_music_playlist_url(self):
        username, identifier = _parse_url(
            "youtube_music",
            "https://music.youtube.com/playlist?list=PLxxxxxxx",
        )
        assert identifier == "PLxxxxxxx"

    def test_youtube_music_plain_id(self):
        username, identifier = _parse_url("youtube_music", "PLxxxxxxx")
        assert identifier == "PLxxxxxxx"

    def test_whitespace_stripped(self):
        username, identifier = _parse_url("lastfm", "  JohnDoe  ")
        assert username == "johndoe"


class TestGenerateListName:
    """Test human-readable name generation."""

    def test_lastfm_loved(self):
        name = _generate_list_name("lastfm", "loved", "testuser")
        assert "Last.fm" in name
        assert "testuser" in name

    def test_lastfm_top_with_period(self):
        name = _generate_list_name("lastfm", "top", "testuser", period="7day")
        assert "7day" in name

    def test_chart_with_tag(self):
        name = _generate_list_name("lastfm", "chart", "", list_identifier="rock")
        assert "Chart" in name
        assert "Rock" in name

    def test_youtube_music_playlist(self):
        name = _generate_list_name(
            "youtube_music", "playlist", "", list_identifier="PLxxxxxxx"
        )
        assert "YouTube Music" in name
        assert "Playlist" in name

    def test_youtube_music_liked(self):
        name = _generate_list_name("youtube_music", "loved", "")
        assert "YouTube Music Liked Songs" == name


@pytest.mark.django_db
@pytest.mark.asyncio
class TestGetPage:
    """Test ExternalListService.get_page with a real DB."""

    @pytest.fixture(autouse=True)
    def service(self) -> ExternalListService:
        return ExternalListService()

    async def test_basic_pagination_page1_returns_correct_count(
        self, service: ExternalListService
    ) -> None:
        """Page 1 with page_size=3 returns exactly 3 items when 5 exist."""
        for _ in range(5):
            await sync_to_async(ExternalListFactory)()

        result = await service.get_page(page=1, page_size=3)

        assert len(result.items) == 3
        assert result.page == 1
        assert result.page_size == 3

    async def test_page2_returns_different_items(
        self, service: ExternalListService
    ) -> None:
        """Page 2 returns items that don't overlap with page 1."""
        for _ in range(5):
            await sync_to_async(ExternalListFactory)()

        page1 = await service.get_page(page=1, page_size=2)
        page2 = await service.get_page(page=2, page_size=2)

        ids_page1 = {item.id for item in page1.items}
        ids_page2 = {item.id for item in page2.items}
        assert ids_page1.isdisjoint(ids_page2)

    async def test_total_count_is_correct_across_pages(
        self, service: ExternalListService
    ) -> None:
        """total_count reflects total DB rows, not just the current page."""
        for _ in range(6):
            await sync_to_async(ExternalListFactory)()

        page1 = await service.get_page(page=1, page_size=4)
        page2 = await service.get_page(page=2, page_size=4)

        assert page1.total_count == page2.total_count
        assert page1.total_count >= 6

    async def test_filter_by_source(self, service: ExternalListService) -> None:
        """Only items matching the requested source are returned."""
        import uuid

        suffix = uuid.uuid4().hex[:8]
        await sync_to_async(ExternalListFactory)(
            source=ExternalListSource.LASTFM, username=f"lastfm_only_{suffix}_1"
        )
        await sync_to_async(ExternalListFactory)(
            source=ExternalListSource.LASTFM, username=f"lastfm_only_{suffix}_2"
        )
        await sync_to_async(ExternalListFactory)(
            source=ExternalListSource.LISTENBRAINZ,
            username=f"lb_only_{suffix}",
        )

        result = await service.get_page(
            page=1, page_size=50, source=ExternalListSource.LASTFM
        )

        assert all(item.source == ExternalListSource.LASTFM for item in result.items)
        assert result.total_count >= 2

    async def test_filter_by_search_matches_name(
        self, service: ExternalListService
    ) -> None:
        """Search filter matches against the list name."""
        await sync_to_async(ExternalListFactory)(name="My Favourite Shoegaze")
        await sync_to_async(ExternalListFactory)(name="Top 50 Hip-Hop")

        result = await service.get_page(page=1, page_size=50, search="Shoegaze")

        assert result.total_count == 1
        assert result.items[0].name == "My Favourite Shoegaze"

    async def test_filter_by_search_matches_username(
        self, service: ExternalListService
    ) -> None:
        """Search filter also matches against username."""
        await sync_to_async(ExternalListFactory)(username="uniqueuser99")
        await sync_to_async(ExternalListFactory)(username="anotheruser")

        result = await service.get_page(page=1, page_size=50, search="uniqueuser99")

        assert result.total_count == 1
        assert result.items[0].username == "uniqueuser99"

    async def test_empty_results_when_no_match(
        self, service: ExternalListService
    ) -> None:
        """Search that matches nothing returns empty items and zero total_count."""
        result = await service.get_page(
            page=1, page_size=50, search="xyzzy_no_such_list_should_ever_exist_abc123"
        )

        assert result.items == []
        assert result.total_count == 0

    async def test_page_beyond_last_returns_empty(
        self, service: ExternalListService
    ) -> None:
        """Requesting a page past the last one returns empty items."""
        await sync_to_async(ExternalListFactory)()

        result = await service.get_page(page=999, page_size=50)

        assert result.items == []
        assert result.total_count >= 1
