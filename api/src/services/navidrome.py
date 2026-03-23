"""Navidrome integration service.

Triggers library rescans via the Subsonic API when new music is downloaded.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from django.conf import settings as django_settings

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


class NavidromeService:
    """Service for interacting with Navidrome via the Subsonic API."""

    def __init__(self) -> None:
        self._url = getattr(
            django_settings, "NAVIDROME_URL", "http://navidrome:4533"
        ).rstrip("/")
        self._user = getattr(django_settings, "NAVIDROME_USER", "admin")
        self._password = getattr(django_settings, "NAVIDROME_PASSWORD", "")

    def _build_auth_params(self) -> dict[str, str]:
        """Build Subsonic token auth parameters (MD5 challenge-response)."""
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode("utf-8")).hexdigest()
        return {
            "u": self._user,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "tunestash",
            "f": "json",
        }

    def trigger_rescan(self) -> bool:
        """Trigger a Navidrome library rescan.

        Returns True if the rescan was triggered successfully.
        """
        try:
            params = self._build_auth_params()
            response = requests.get(
                f"{self._url}/rest/startScan.view",
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            data = response.json()
            subsonic_response = data.get("subsonic-response", {})
            status = subsonic_response.get("status")

            if status == "ok":
                scan_status = subsonic_response.get("scanStatus", {})
                logger.info(
                    "Navidrome rescan triggered: scanning=%s, count=%s",
                    scan_status.get("scanning"),
                    scan_status.get("count"),
                )
                return True

            error = subsonic_response.get("error", {})
            logger.error(
                "Navidrome rescan failed: code=%s, message=%s",
                error.get("code"),
                error.get("message"),
            )
            return False

        except requests.RequestException as e:
            logger.error(f"Navidrome API request failed: {e}")
            return False
