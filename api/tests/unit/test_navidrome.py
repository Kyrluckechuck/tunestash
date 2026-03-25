"""Tests for Navidrome integration service."""

import hashlib
from unittest.mock import MagicMock, patch

from src.services.navidrome import NavidromeService


class TestNavidromeAuth:
    """Test Subsonic MD5 token authentication."""

    def test_auth_params_contain_required_fields(self):
        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://navidrome:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "secret"

            service = NavidromeService()
            params = service._build_auth_params()

            assert params["u"] == "admin"
            assert params["c"] == "tunestash"
            assert params["f"] == "json"
            assert params["v"] == "1.16.1"
            assert "t" in params
            assert "s" in params

    def test_token_is_md5_of_password_plus_salt(self):
        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://navidrome:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "secret"

            service = NavidromeService()
            params = service._build_auth_params()

            expected = hashlib.md5(("secret" + params["s"]).encode("utf-8")).hexdigest()
            assert params["t"] == expected

    def test_salt_is_random_between_calls(self):
        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://navidrome:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "secret"

            service = NavidromeService()
            params1 = service._build_auth_params()
            params2 = service._build_auth_params()

            assert params1["s"] != params2["s"]


class TestNavidromeRescan:
    """Test rescan trigger logic."""

    @patch("src.services.navidrome.requests.get")
    def test_successful_rescan(self, mock_get):
        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://navidrome:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "secret"

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "subsonic-response": {
                    "status": "ok",
                    "scanStatus": {"scanning": True, "count": 100},
                }
            }
            mock_get.return_value = mock_response

            service = NavidromeService()
            assert service.trigger_rescan() is True

    @patch("src.services.navidrome.requests.get")
    def test_failed_rescan_auth_error(self, mock_get):
        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://navidrome:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "wrong"

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "subsonic-response": {
                    "status": "failed",
                    "error": {"code": 40, "message": "Wrong credentials"},
                }
            }
            mock_get.return_value = mock_response

            service = NavidromeService()
            assert service.trigger_rescan() is False

    @patch("src.services.navidrome.requests.get")
    def test_handles_connection_error(self, mock_get):
        import requests

        with patch("src.services.navidrome.django_settings") as mock_settings:
            mock_settings.NAVIDROME_URL = "http://unreachable:4533"
            mock_settings.NAVIDROME_USER = "admin"
            mock_settings.NAVIDROME_PASSWORD = "secret"

            mock_get.side_effect = requests.ConnectionError("refused")

            service = NavidromeService()
            assert service.trigger_rescan() is False
