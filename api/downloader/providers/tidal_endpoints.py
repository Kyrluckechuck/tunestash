"""
Tidal endpoint manager for dynamic API discovery.

This module handles fetching and managing Tidal API endpoints from the upstream
tidal-ui configuration. It supports weighted endpoint selection and health checking.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

# Default config URL - points to the tidal-ui repo's config file
DEFAULT_CONFIG_URL = "https://raw.githubusercontent.com/uimaxbai/tidal-ui/refs/heads/main/src/lib/config.ts"

# Fallback endpoints if config fetch fails
FALLBACK_ENDPOINTS = [
    {"name": "squid-api", "baseUrl": "https://triton.squid.wtf", "weight": 30},
    {"name": "hund", "baseUrl": "https://hund.qqdl.site", "weight": 15},
    {"name": "katze", "baseUrl": "https://katze.qqdl.site", "weight": 15},
]

# How long to cache the endpoint configuration
CONFIG_CACHE_TTL = timedelta(hours=1)

# How long before an endpoint is considered unhealthy after a failure
ENDPOINT_COOLDOWN = timedelta(minutes=5)


@dataclass
class TidalEndpoint:
    """Represents a Tidal API endpoint."""

    name: str
    base_url: str
    weight: int
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        """Check if endpoint is currently considered healthy."""
        if self.last_failure is None:
            return True
        cooldown_end = self.last_failure + ENDPOINT_COOLDOWN
        return datetime.now() >= cooldown_end

    def mark_failure(self) -> None:
        """Mark this endpoint as having failed."""
        self.last_failure = datetime.now()
        self.consecutive_failures += 1

    def mark_success(self) -> None:
        """Mark this endpoint as having succeeded."""
        self.last_failure = None
        self.consecutive_failures = 0


class TidalEndpointManager:
    """
    Manages Tidal API endpoints with dynamic discovery and health tracking.

    Features:
    - Fetches endpoint configuration from upstream GitHub repo
    - Weighted random selection respecting endpoint capacities
    - Health tracking with automatic cooldown for failed endpoints
    - Fallback endpoints if config fetch fails
    """

    def __init__(
        self,
        config_url: str = DEFAULT_CONFIG_URL,
        cache_ttl: timedelta = CONFIG_CACHE_TTL,
    ) -> None:
        """
        Initialize the endpoint manager.

        Args:
            config_url: URL to fetch endpoint configuration from
            cache_ttl: How long to cache the configuration
        """
        self._config_url = config_url
        self._cache_ttl = cache_ttl
        self._endpoints: list[TidalEndpoint] = []
        self._last_fetch: Optional[datetime] = None
        self._lock = asyncio.Lock()

    @property
    def endpoints(self) -> list[TidalEndpoint]:
        """Get the current list of endpoints (may be stale)."""
        return self._endpoints.copy()

    async def get_endpoint(self) -> Optional[TidalEndpoint]:
        """
        Get a healthy endpoint using weighted random selection.

        Returns:
            A healthy endpoint, or None if no healthy endpoints are available.
        """
        await self._ensure_endpoints_loaded()

        healthy = [e for e in self._endpoints if e.is_healthy]
        if not healthy:
            logger.warning("No healthy Tidal endpoints available")
            return None

        return self._weighted_random_choice(healthy)

    async def get_all_healthy_endpoints(self) -> list[TidalEndpoint]:
        """
        Get all currently healthy endpoints, ordered by weight (highest first).

        Returns:
            List of healthy endpoints sorted by weight descending.
        """
        await self._ensure_endpoints_loaded()
        healthy = [e for e in self._endpoints if e.is_healthy]
        return sorted(healthy, key=lambda e: e.weight, reverse=True)

    def mark_endpoint_failure(self, endpoint: TidalEndpoint) -> None:
        """Mark an endpoint as having failed."""
        endpoint.mark_failure()
        logger.warning(
            f"Tidal endpoint {endpoint.name} failed "
            f"(consecutive failures: {endpoint.consecutive_failures})"
        )

    def mark_endpoint_success(self, endpoint: TidalEndpoint) -> None:
        """Mark an endpoint as having succeeded."""
        if endpoint.consecutive_failures > 0:
            logger.info(
                f"Tidal endpoint {endpoint.name} recovered after "
                f"{endpoint.consecutive_failures} failures"
            )
        endpoint.mark_success()

    async def refresh_endpoints(self) -> None:
        """Force refresh the endpoint configuration."""
        async with self._lock:
            await self._fetch_config()

    async def _ensure_endpoints_loaded(self) -> None:
        """Ensure endpoints are loaded and not stale."""
        if self._should_refresh():
            async with self._lock:
                # Double-check after acquiring lock
                if self._should_refresh():
                    await self._fetch_config()

    def _should_refresh(self) -> bool:
        """Check if we should refresh the endpoint configuration."""
        if not self._endpoints:
            return True
        if self._last_fetch is None:
            return True
        return datetime.now() >= self._last_fetch + self._cache_ttl

    def _fetch_config_sync(self) -> Optional[str]:
        """Synchronous config fetch (called via sync_to_async)."""
        try:
            response = requests.get(self._config_url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Tidal endpoint config: {e}")
            return None

    async def _fetch_config(self) -> None:
        """Fetch and parse the endpoint configuration."""
        config_text = await sync_to_async(self._fetch_config_sync)()

        if config_text:
            new_endpoints = self._parse_config(config_text)
            if new_endpoints:
                self._merge_endpoints(new_endpoints)
                self._last_fetch = datetime.now()
                logger.info(
                    f"Refreshed Tidal endpoints: {len(self._endpoints)} available"
                )
                return

        logger.warning("Failed to parse Tidal endpoint config, using fallbacks")
        if not self._endpoints:
            self._use_fallbacks()

    def _parse_config(self, config_text: str) -> list[TidalEndpoint]:
        """
        Parse the TypeScript config file to extract endpoints.

        The config format is:
        export const V2_API_TARGETS = [
            { name: 'squid-api', baseUrl: 'https://triton.squid.wtf', weight: 30 },
            ...
        ];
        """
        endpoints = []

        # Pattern to match endpoint objects in the array
        pattern = r"\{\s*name:\s*['\"]([^'\"]+)['\"],\s*baseUrl:\s*['\"]([^'\"]+)['\"],\s*weight:\s*(\d+)"

        for match in re.finditer(pattern, config_text):
            name, base_url, weight = match.groups()
            endpoints.append(
                TidalEndpoint(
                    name=name,
                    base_url=base_url.rstrip("/"),
                    weight=int(weight),
                )
            )

        return endpoints

    def _merge_endpoints(self, new_endpoints: list[TidalEndpoint]) -> None:
        """
        Merge new endpoints with existing ones, preserving health state.

        Endpoints that no longer exist in the config are removed.
        New endpoints are added.
        Existing endpoints preserve their health state.
        """
        existing_by_url = {e.base_url: e for e in self._endpoints}

        merged = []
        for new in new_endpoints:
            if new.base_url in existing_by_url:
                # Preserve existing endpoint's health state
                existing = existing_by_url[new.base_url]
                existing.name = new.name  # Update name in case it changed
                existing.weight = new.weight  # Update weight
                merged.append(existing)
            else:
                merged.append(new)

        self._endpoints = merged

    def _use_fallbacks(self) -> None:
        """Initialize with fallback endpoints."""
        self._endpoints = [
            TidalEndpoint(
                name=e["name"],
                base_url=e["baseUrl"],
                weight=e["weight"],
            )
            for e in FALLBACK_ENDPOINTS
        ]
        self._last_fetch = datetime.now()
        logger.info(f"Using {len(self._endpoints)} fallback Tidal endpoints")

    @staticmethod
    def _weighted_random_choice(endpoints: list[TidalEndpoint]) -> TidalEndpoint:
        """Select an endpoint using weighted random selection."""
        total_weight = sum(e.weight for e in endpoints)
        r = random.uniform(0, total_weight)

        cumulative = 0
        for endpoint in endpoints:
            cumulative += endpoint.weight
            if r <= cumulative:
                return endpoint

        # Fallback (shouldn't happen)
        return endpoints[-1]
