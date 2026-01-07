"""Tests for the TidalEndpointManager."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests
from downloader.providers.tidal_endpoints import (
    CONFIG_CACHE_TTL,
    DEFAULT_CONFIG_URL,
    ENDPOINT_COOLDOWN,
    FALLBACK_ENDPOINTS,
    TidalEndpoint,
    TidalEndpointManager,
)


class TestTidalEndpoint:
    """Tests for the TidalEndpoint dataclass."""

    @pytest.mark.unit
    def test_endpoint_creation(self):
        """Test creating an endpoint."""
        endpoint = TidalEndpoint(
            name="test",
            base_url="https://test.example.com",
            weight=10,
        )
        assert endpoint.name == "test"
        assert endpoint.base_url == "https://test.example.com"
        assert endpoint.weight == 10
        assert endpoint.last_failure is None
        assert endpoint.consecutive_failures == 0

    @pytest.mark.unit
    def test_is_healthy_no_failures(self):
        """Test endpoint is healthy when no failures."""
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        assert endpoint.is_healthy is True

    @pytest.mark.unit
    def test_is_healthy_after_cooldown(self):
        """Test endpoint becomes healthy after cooldown."""
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        # Set failure in the past, beyond cooldown
        endpoint.last_failure = (
            datetime.now() - ENDPOINT_COOLDOWN - timedelta(seconds=1)
        )
        assert endpoint.is_healthy is True

    @pytest.mark.unit
    def test_is_unhealthy_within_cooldown(self):
        """Test endpoint is unhealthy within cooldown period."""
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        endpoint.last_failure = datetime.now()
        assert endpoint.is_healthy is False

    @pytest.mark.unit
    def test_mark_failure(self):
        """Test marking an endpoint as failed."""
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        assert endpoint.consecutive_failures == 0

        endpoint.mark_failure()
        assert endpoint.last_failure is not None
        assert endpoint.consecutive_failures == 1

        endpoint.mark_failure()
        assert endpoint.consecutive_failures == 2

    @pytest.mark.unit
    def test_mark_success(self):
        """Test marking an endpoint as successful."""
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        endpoint.mark_failure()
        endpoint.mark_failure()
        assert endpoint.consecutive_failures == 2

        endpoint.mark_success()
        assert endpoint.last_failure is None
        assert endpoint.consecutive_failures == 0


class TestTidalEndpointManager:
    """Tests for the TidalEndpointManager class."""

    @pytest.fixture
    def sample_config_text(self):
        """Sample TypeScript config file content."""
        return """
export const V2_API_TARGETS = [
    { name: 'squid-api', baseUrl: 'https://triton.squid.wtf', weight: 30 },
    { name: 'hund', baseUrl: 'https://hund.qqdl.site', weight: 15 },
    { name: 'katze', baseUrl: 'https://katze.qqdl.site', weight: 15 },
];
"""

    @pytest.mark.unit
    def test_manager_creation(self):
        """Test creating an endpoint manager."""
        manager = TidalEndpointManager()
        assert manager._config_url == DEFAULT_CONFIG_URL
        assert manager._cache_ttl == CONFIG_CACHE_TTL
        assert manager._endpoints == []

    @pytest.mark.unit
    def test_manager_custom_config_url(self):
        """Test manager with custom config URL."""
        custom_url = "https://custom.example.com/config.ts"
        manager = TidalEndpointManager(config_url=custom_url)
        assert manager._config_url == custom_url

    @pytest.mark.unit
    def test_parse_config(self, sample_config_text):
        """Test parsing TypeScript config file."""
        manager = TidalEndpointManager()
        endpoints = manager._parse_config(sample_config_text)

        assert len(endpoints) == 3
        assert endpoints[0].name == "squid-api"
        assert endpoints[0].base_url == "https://triton.squid.wtf"
        assert endpoints[0].weight == 30
        assert endpoints[1].name == "hund"
        assert endpoints[2].name == "katze"

    @pytest.mark.unit
    def test_parse_config_strips_trailing_slash(self):
        """Test that trailing slashes are stripped from URLs."""
        config = "{ name: 'test', baseUrl: 'https://test.com/', weight: 10 }"
        manager = TidalEndpointManager()
        endpoints = manager._parse_config(config)

        assert len(endpoints) == 1
        assert endpoints[0].base_url == "https://test.com"

    @pytest.mark.unit
    def test_parse_config_empty(self):
        """Test parsing empty config."""
        manager = TidalEndpointManager()
        endpoints = manager._parse_config("const X = {};")
        assert endpoints == []

    @pytest.mark.unit
    def test_parse_config_malformed(self):
        """Test parsing malformed config."""
        manager = TidalEndpointManager()
        endpoints = manager._parse_config("not valid typescript at all")
        assert endpoints == []

    @pytest.mark.unit
    def test_use_fallbacks(self):
        """Test fallback endpoint initialization."""
        manager = TidalEndpointManager()
        manager._use_fallbacks()

        assert len(manager._endpoints) == len(FALLBACK_ENDPOINTS)
        assert manager._endpoints[0].name == FALLBACK_ENDPOINTS[0]["name"]
        assert manager._last_fetch is not None

    @pytest.mark.unit
    def test_weighted_random_choice(self):
        """Test weighted random selection."""
        endpoints = [
            TidalEndpoint(name="heavy", base_url="https://heavy.com", weight=100),
            TidalEndpoint(name="light", base_url="https://light.com", weight=1),
        ]

        # With such extreme weights, heavy should be selected most of the time
        manager = TidalEndpointManager()
        heavy_count = 0
        iterations = 1000

        for _ in range(iterations):
            selected = manager._weighted_random_choice(endpoints)
            if selected.name == "heavy":
                heavy_count += 1

        # Heavy should be selected ~99% of the time (weight 100 / 101 total)
        assert heavy_count > iterations * 0.95

    @pytest.mark.unit
    def test_weighted_random_choice_single_endpoint(self):
        """Test weighted selection with single endpoint."""
        endpoint = TidalEndpoint(name="only", base_url="https://only.com", weight=10)
        manager = TidalEndpointManager()
        selected = manager._weighted_random_choice([endpoint])
        assert selected.name == "only"

    @pytest.mark.unit
    def test_merge_endpoints_preserves_health(self, sample_config_text):
        """Test that merging preserves existing endpoint health state."""
        manager = TidalEndpointManager()

        # Create initial endpoint and mark it as failed
        initial = manager._parse_config(sample_config_text)
        manager._endpoints = initial
        manager._endpoints[0].mark_failure()
        manager._endpoints[0].mark_failure()
        assert manager._endpoints[0].consecutive_failures == 2

        # Merge same endpoints (simulating a refresh)
        new_endpoints = manager._parse_config(sample_config_text)
        manager._merge_endpoints(new_endpoints)

        # Health state should be preserved
        assert manager._endpoints[0].consecutive_failures == 2

    @pytest.mark.unit
    def test_merge_endpoints_adds_new(self, sample_config_text):
        """Test that merging adds new endpoints."""
        manager = TidalEndpointManager()

        # Start with just one endpoint
        manager._endpoints = [
            TidalEndpoint(name="original", base_url="https://original.com", weight=5)
        ]

        # Merge in new endpoints
        new_endpoints = manager._parse_config(sample_config_text)
        manager._merge_endpoints(new_endpoints)

        # Should now have the new endpoints (original is gone, new ones added)
        assert len(manager._endpoints) == 3
        urls = {e.base_url for e in manager._endpoints}
        assert "https://triton.squid.wtf" in urls

    @pytest.mark.unit
    def test_should_refresh_empty_endpoints(self):
        """Test refresh needed when endpoints empty."""
        manager = TidalEndpointManager()
        assert manager._should_refresh() is True

    @pytest.mark.unit
    def test_should_refresh_stale_cache(self):
        """Test refresh needed when cache is stale."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="t", base_url="https://t.com", weight=1)
        ]
        manager._last_fetch = datetime.now() - CONFIG_CACHE_TTL - timedelta(seconds=1)
        assert manager._should_refresh() is True

    @pytest.mark.unit
    def test_should_not_refresh_fresh_cache(self):
        """Test no refresh needed when cache is fresh."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="t", base_url="https://t.com", weight=1)
        ]
        manager._last_fetch = datetime.now()
        assert manager._should_refresh() is False

    @pytest.mark.unit
    def test_endpoints_property_returns_copy(self):
        """Test that endpoints property returns a copy."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="t", base_url="https://t.com", weight=1)
        ]

        endpoints = manager.endpoints
        endpoints.append(TidalEndpoint(name="x", base_url="https://x.com", weight=1))

        # Original should be unchanged
        assert len(manager._endpoints) == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_endpoint_fetches_on_first_call(self, sample_config_text):
        """Test that get_endpoint fetches config on first call."""
        manager = TidalEndpointManager()

        mock_response = MagicMock()
        mock_response.text = sample_config_text
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.return_value = mock_response

            endpoint = await manager.get_endpoint()

        assert endpoint is not None
        assert len(manager._endpoints) == 3
        mock_get.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_endpoint_uses_cache(self, sample_config_text):
        """Test that get_endpoint uses cached endpoints."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="cached", base_url="https://cached.com", weight=10)
        ]
        manager._last_fetch = datetime.now()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            endpoint = await manager.get_endpoint()

        # Should not have called the client (used cache)
        mock_get.assert_not_called()
        assert endpoint.name == "cached"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_endpoint_filters_unhealthy(self):
        """Test that get_endpoint filters out unhealthy endpoints."""
        manager = TidalEndpointManager()
        healthy = TidalEndpoint(
            name="healthy", base_url="https://healthy.com", weight=10
        )
        unhealthy = TidalEndpoint(
            name="unhealthy", base_url="https://unhealthy.com", weight=10
        )
        unhealthy.mark_failure()  # Mark as unhealthy

        manager._endpoints = [healthy, unhealthy]
        manager._last_fetch = datetime.now()

        # Should always return the healthy one
        for _ in range(10):
            endpoint = await manager.get_endpoint()
            assert endpoint.name == "healthy"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_endpoint_returns_none_when_all_unhealthy(self):
        """Test get_endpoint returns None when all endpoints are unhealthy."""
        manager = TidalEndpointManager()
        unhealthy = TidalEndpoint(
            name="unhealthy", base_url="https://unhealthy.com", weight=10
        )
        unhealthy.mark_failure()

        manager._endpoints = [unhealthy]
        manager._last_fetch = datetime.now()

        endpoint = await manager.get_endpoint()
        assert endpoint is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_all_healthy_endpoints_sorted(self):
        """Test get_all_healthy_endpoints returns sorted by weight."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="light", base_url="https://light.com", weight=5),
            TidalEndpoint(name="heavy", base_url="https://heavy.com", weight=30),
            TidalEndpoint(name="medium", base_url="https://medium.com", weight=15),
        ]
        manager._last_fetch = datetime.now()

        healthy = await manager.get_all_healthy_endpoints()

        assert len(healthy) == 3
        assert healthy[0].name == "heavy"
        assert healthy[1].name == "medium"
        assert healthy[2].name == "light"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fetch_config_uses_fallbacks_on_error(self):
        """Test that fetch errors result in fallback endpoints."""
        manager = TidalEndpointManager()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection failed")

            await manager._fetch_config()

        assert len(manager._endpoints) == len(FALLBACK_ENDPOINTS)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fetch_config_uses_fallbacks_on_parse_failure(self):
        """Test that parse failures result in fallback endpoints."""
        manager = TidalEndpointManager()

        mock_response = MagicMock()
        mock_response.text = "invalid content with no endpoints"
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.return_value = mock_response

            await manager._fetch_config()

        assert len(manager._endpoints) == len(FALLBACK_ENDPOINTS)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_refresh_endpoints(self, sample_config_text):
        """Test force refresh of endpoints."""
        manager = TidalEndpointManager()
        manager._endpoints = [
            TidalEndpoint(name="old", base_url="https://old.com", weight=1)
        ]
        manager._last_fetch = datetime.now()

        mock_response = MagicMock()
        mock_response.text = sample_config_text
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.return_value = mock_response

            await manager.refresh_endpoints()

        # Should have the new endpoints
        assert len(manager._endpoints) == 3
        mock_get.assert_called_once()

    @pytest.mark.unit
    def test_mark_endpoint_failure_logs_warning(self, caplog):
        """Test that marking failure logs appropriately."""
        manager = TidalEndpointManager()
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)

        with caplog.at_level("WARNING"):
            manager.mark_endpoint_failure(endpoint)

        assert "test" in caplog.text
        assert "failed" in caplog.text.lower()

    @pytest.mark.unit
    def test_mark_endpoint_success_logs_recovery(self, caplog):
        """Test that marking success logs recovery."""
        manager = TidalEndpointManager()
        endpoint = TidalEndpoint(name="test", base_url="https://test.com", weight=10)
        endpoint.mark_failure()
        endpoint.mark_failure()

        with caplog.at_level("INFO"):
            manager.mark_endpoint_success(endpoint)

        assert "recovered" in caplog.text.lower()

    @pytest.mark.unit
    def test_fetch_config_sync_success(self, sample_config_text):
        """Test synchronous config fetch returns text on success."""
        manager = TidalEndpointManager()

        mock_response = MagicMock()
        mock_response.text = sample_config_text
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.return_value = mock_response

            result = manager._fetch_config_sync()

        assert result == sample_config_text

    @pytest.mark.unit
    def test_fetch_config_sync_returns_none_on_error(self):
        """Test synchronous config fetch returns None on error."""
        manager = TidalEndpointManager()

        with patch("downloader.providers.tidal_endpoints.requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection failed")

            result = manager._fetch_config_sync()

        assert result is None
