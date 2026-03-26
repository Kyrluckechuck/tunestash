"""Tests for Navidrome integration service."""

import hashlib
from unittest.mock import MagicMock, patch

from src.services.navidrome import NavidromeService

NAVIDROME_DEFAULTS = {
    "navidrome_url": "http://navidrome:4533",
    "navidrome_user": "admin",
    "navidrome_password": "secret",
}


def _mock_get_setting(overrides=None):
    vals = {**NAVIDROME_DEFAULTS, **(overrides or {})}
    return lambda key: vals.get(key, "")


class TestNavidromeAuth:
    """Test Subsonic MD5 token authentication."""

    @patch("src.services.navidrome.get_setting", side_effect=_mock_get_setting())
    def test_auth_params_contain_required_fields(self, _mock):
        service = NavidromeService()
        params = service._build_auth_params()

        assert params["u"] == "admin"
        assert params["c"] == "tunestash"
        assert params["f"] == "json"
        assert params["v"] == "1.16.1"
        assert "t" in params
        assert "s" in params

    @patch("src.services.navidrome.get_setting", side_effect=_mock_get_setting())
    def test_token_is_md5_of_password_plus_salt(self, _mock):
        service = NavidromeService()
        params = service._build_auth_params()

        expected = hashlib.md5(("secret" + params["s"]).encode("utf-8")).hexdigest()
        assert params["t"] == expected

    @patch("src.services.navidrome.get_setting", side_effect=_mock_get_setting())
    def test_salt_is_random_between_calls(self, _mock):
        service = NavidromeService()
        params1 = service._build_auth_params()
        params2 = service._build_auth_params()

        assert params1["s"] != params2["s"]


class TestNavidromeRescan:
    """Test rescan trigger logic."""

    @patch("src.services.navidrome.requests.get")
    @patch("src.services.navidrome.get_setting", side_effect=_mock_get_setting())
    def test_successful_rescan(self, _mock_setting, mock_get):
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
    @patch(
        "src.services.navidrome.get_setting",
        side_effect=_mock_get_setting({"navidrome_password": "wrong"}),
    )
    def test_failed_rescan_auth_error(self, _mock_setting, mock_get):
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
    @patch(
        "src.services.navidrome.get_setting",
        side_effect=_mock_get_setting({"navidrome_url": "http://unreachable:4533"}),
    )
    def test_handles_connection_error(self, _mock_setting, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("refused")

        service = NavidromeService()
        assert service.trigger_rescan() is False
