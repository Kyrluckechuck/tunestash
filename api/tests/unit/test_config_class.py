"""
Tests for Config class, particularly download provider ordering.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestConfigProviderOrder:
    """Tests for download_provider_order configuration."""

    @pytest.fixture
    def mock_django_settings(self):
        """Create a mock Django settings object."""
        settings = MagicMock()
        # Set default attributes that Config expects
        settings.youtube_cookies_location = "/config/cookies.txt"
        settings.spotify_user_auth_enabled = False
        settings.po_token = None
        settings.log_level = "INFO"
        settings.spotdl_log_level = "INFO"
        settings.no_lrc = False
        settings.overwrite = False
        settings.fallback_quality = "high"
        # Remove attributes to test defaults (getattr will use default value)
        del settings.download_provider_order
        del settings.qobuz_use_mp3
        return settings

    def test_default_provider_order(self, mock_django_settings):
        """Default provider order should include all providers for max success rate."""
        from lib.config_class import Config

        config = Config(download_provider_order=None)
        assert config.download_provider_order == ["youtube", "tidal", "qobuz"]

    @patch("lib.config_class.settings")
    def test_explicit_provider_order_from_settings(
        self, mock_settings, mock_django_settings
    ):
        """Provider order from settings.yaml should be respected."""
        mock_django_settings.download_provider_order = ["tidal", "youtube"]
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config()
        assert config.download_provider_order == ["tidal", "youtube"]

    @patch("lib.config_class.settings")
    def test_explicit_provider_order_constructor(
        self, mock_settings, mock_django_settings
    ):
        """Provider order passed to constructor takes precedence."""
        mock_django_settings.download_provider_order = ["youtube", "tidal"]
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(download_provider_order=["tidal"])
        assert config.download_provider_order == ["tidal"]

    @patch("lib.config_class.settings")
    def test_tidal_only_order(self, mock_settings, mock_django_settings):
        """Tidal-only configuration should work."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(download_provider_order=["tidal"])
        assert config.download_provider_order == ["tidal"]
        assert "youtube" not in config.download_provider_order

    @patch("lib.config_class.settings")
    def test_youtube_only_order(self, mock_settings, mock_django_settings):
        """YouTube-only configuration should work."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(download_provider_order=["youtube"])
        assert config.download_provider_order == ["youtube"]
        assert "tidal" not in config.download_provider_order

    @patch("lib.config_class.settings")
    def test_legacy_spotdl_mapped_to_youtube(self, mock_settings, mock_django_settings):
        """Legacy 'spotdl' in provider order should be mapped to 'youtube'."""
        mock_django_settings.download_provider_order = ["spotdl", "tidal", "qobuz"]
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config()
        assert config.download_provider_order == ["youtube", "tidal", "qobuz"]

    @patch("lib.config_class.settings")
    def test_quality_preference_default(self, mock_settings, mock_django_settings):
        """Default quality should be high (M4A/AAC)."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config()
        assert config.fallback_quality == "high"

    @patch("lib.config_class.settings")
    def test_quality_preference_explicit(self, mock_settings, mock_django_settings):
        """Explicit quality preference should override default."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(fallback_quality="high")
        assert config.fallback_quality == "high"

    @patch("lib.config_class.settings")
    def test_empty_provider_order(self, mock_settings, mock_django_settings):
        """Empty provider order should be allowed (will fail at runtime)."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(download_provider_order=[])
        assert config.download_provider_order == []

    @patch("lib.config_class.settings")
    def test_qobuz_use_mp3_default(self, mock_settings, mock_django_settings):
        """Default qobuz_use_mp3 should be False (FLAC → M4A conversion)."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config()
        assert config.qobuz_use_mp3 is False

    @patch("lib.config_class.settings")
    def test_qobuz_use_mp3_explicit_true(self, mock_settings, mock_django_settings):
        """Setting qobuz_use_mp3=True should enable direct MP3 download."""
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config(qobuz_use_mp3=True)
        assert config.qobuz_use_mp3 is True

    @patch("lib.config_class.settings")
    def test_qobuz_use_mp3_from_settings(self, mock_settings, mock_django_settings):
        """qobuz_use_mp3 from settings.yaml should be respected."""
        mock_django_settings.qobuz_use_mp3 = True
        mock_settings.configure_mock(**vars(mock_django_settings))

        from lib.config_class import Config

        config = Config()
        assert config.qobuz_use_mp3 is True
