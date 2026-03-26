"""
Tests for Config class, particularly download provider ordering.
"""

from unittest.mock import patch

# Default values that get_setting returns for Config's dependencies
_SETTING_DEFAULTS = {
    "spotify_user_auth_enabled": False,
    "po_token": None,
    "log_level": "INFO",
    "lyrics_enabled": True,
    "overwrite": False,
    "fallback_quality": "high",
    "download_provider_order": ["youtube", "tidal", "qobuz"],
    "qobuz_use_mp3": False,
}


def _mock_get_setting(overrides=None):
    """Return a side_effect function for get_setting with optional overrides."""
    defaults = {**_SETTING_DEFAULTS, **(overrides or {})}

    def _side_effect(key):
        if key in defaults:
            return defaults[key]
        raise KeyError(f"Unknown setting: {key!r}")

    return _side_effect


class TestConfigProviderOrder:
    """Tests for download_provider_order configuration."""

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_default_provider_order(self, mock_get_setting):
        """Default provider order should include all providers for max success rate."""
        from lib.config_class import Config

        config = Config(download_provider_order=None)
        assert config.download_provider_order == ["youtube", "tidal", "qobuz"]

    @patch("lib.config_class.get_setting")
    def test_explicit_provider_order_from_settings(self, mock_get_setting):
        """Provider order from settings.yaml should be respected."""
        mock_get_setting.side_effect = _mock_get_setting(
            {"download_provider_order": ["tidal", "youtube"]}
        )

        from lib.config_class import Config

        config = Config()
        assert config.download_provider_order == ["tidal", "youtube"]

    @patch("lib.config_class.get_setting")
    def test_explicit_provider_order_constructor(self, mock_get_setting):
        """Provider order passed to constructor takes precedence."""
        mock_get_setting.side_effect = _mock_get_setting(
            {"download_provider_order": ["youtube", "tidal"]}
        )

        from lib.config_class import Config

        config = Config(download_provider_order=["tidal"])
        assert config.download_provider_order == ["tidal"]

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_tidal_only_order(self, mock_get_setting):
        """Tidal-only configuration should work."""
        from lib.config_class import Config

        config = Config(download_provider_order=["tidal"])
        assert config.download_provider_order == ["tidal"]
        assert "youtube" not in config.download_provider_order

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_youtube_only_order(self, mock_get_setting):
        """YouTube-only configuration should work."""
        from lib.config_class import Config

        config = Config(download_provider_order=["youtube"])
        assert config.download_provider_order == ["youtube"]
        assert "tidal" not in config.download_provider_order

    @patch("lib.config_class.get_setting")
    def test_legacy_spotdl_mapped_to_youtube(self, mock_get_setting):
        """Legacy 'spotdl' in provider order should be mapped to 'youtube'."""
        mock_get_setting.side_effect = _mock_get_setting(
            {"download_provider_order": ["spotdl", "tidal", "qobuz"]}
        )

        from lib.config_class import Config

        config = Config()
        assert config.download_provider_order == ["youtube", "tidal", "qobuz"]

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_quality_preference_default(self, mock_get_setting):
        """Default quality should be high (M4A/AAC)."""
        from lib.config_class import Config

        config = Config()
        assert config.fallback_quality == "high"

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_quality_preference_explicit(self, mock_get_setting):
        """Explicit quality preference should override default."""
        from lib.config_class import Config

        config = Config(fallback_quality="high")
        assert config.fallback_quality == "high"

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_empty_provider_order(self, mock_get_setting):
        """Empty provider order should be allowed (will fail at runtime)."""
        from lib.config_class import Config

        config = Config(download_provider_order=[])
        assert config.download_provider_order == []

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_qobuz_use_mp3_default(self, mock_get_setting):
        """Default qobuz_use_mp3 should be False (FLAC -> M4A conversion)."""
        from lib.config_class import Config

        config = Config()
        assert config.qobuz_use_mp3 is False

    @patch("lib.config_class.get_setting", side_effect=_mock_get_setting())
    def test_qobuz_use_mp3_explicit_true(self, mock_get_setting):
        """Setting qobuz_use_mp3=True should enable direct MP3 download."""
        from lib.config_class import Config

        config = Config(qobuz_use_mp3=True)
        assert config.qobuz_use_mp3 is True

    @patch("lib.config_class.get_setting")
    def test_qobuz_use_mp3_from_settings(self, mock_get_setting):
        """qobuz_use_mp3 from settings.yaml should be respected."""
        mock_get_setting.side_effect = _mock_get_setting({"qobuz_use_mp3": True})

        from lib.config_class import Config

        config = Config()
        assert config.qobuz_use_mp3 is True
