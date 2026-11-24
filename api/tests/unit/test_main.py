"""Unit tests for main application module."""

from unittest.mock import Mock, patch

import pytest

from src.main import Settings, create_app, get_settings


class TestStartupTokenConfiguration:
    @pytest.mark.parametrize("token, warns", [("A" * 120, False), (None, True)])
    def test_uses_runtime_token_source(self, caplog, token, warns):
        from src.main import _validate_runtime_configuration

        with patch("lib.config_class.Config") as config:
            config.return_value.po_token = token
            _validate_runtime_configuration()

        messages = [record.getMessage() for record in caplog.records]
        assert any("PO token validation failed" in msg for msg in messages) is warns

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize("token,warns", [("A" * 120, False), (None, True)])
    async def test_uvicorn_startup_reads_database_token(self, caplog, token, warns):
        from django.db import connections

        from asgiref.sync import sync_to_async

        from library_manager.models import AppSetting

        try:
            if token is not None:
                await sync_to_async(AppSetting.objects.update_or_create)(
                    key="po_token", defaults={"value": token}
                )
            else:
                await sync_to_async(AppSetting.objects.filter(key="po_token").delete)()
            Settings.reset()
            with patch("downloader.spotipy_tasks.OAuthSpotifyClient") as spotify:
                spotify.return_value.sp = None
                app = create_app()
                await app.router.startup()
                await app.router.shutdown()
        finally:
            await sync_to_async(connections.close_all)()

        messages = [record.getMessage() for record in caplog.records]
        assert any("PO token validation failed" in msg for msg in messages) is warns


class TestMainApplication:
    """Test main application functionality."""

    def test_get_settings_default(self):
        """Test getting default settings."""
        Settings.reset()
        settings = get_settings()

        assert settings is not None
        assert hasattr(settings, "debug")
        assert hasattr(settings, "title")
        assert hasattr(settings, "version")

    def test_get_settings_with_env_vars(self):
        """Test getting settings with environment variables."""
        Settings.reset()
        with patch.dict(
            "os.environ",
            {"DEBUG": "true", "HOST": "0.0.0.0", "PORT": "8001", "RELOAD": "true"},
        ):
            settings = get_settings()

            assert settings.debug is True
            assert settings.host == "0.0.0.0"
            assert settings.port == 8001
            assert settings.reload is True

    def test_get_settings_invalid_port(self):
        """Test getting settings with invalid port."""
        Settings.reset()
        with patch.dict("os.environ", {"PORT": "invalid"}):
            # Should handle invalid port gracefully
            try:
                settings = get_settings()
                # If it doesn't raise an exception, should use default
                assert settings.port == 8000
            except ValueError:
                # If it raises ValueError, that's also acceptable
                pass

    def test_get_settings_invalid_boolean(self):
        """Test getting settings with invalid boolean values."""
        Settings.reset()
        with patch.dict("os.environ", {"DEBUG": "invalid", "RELOAD": "invalid"}):
            settings = get_settings()

            # Should use default values
            assert settings.debug is False
            assert settings.reload is False

    @patch("src.main.FastAPI")
    def test_create_app_success(self, mock_fastapi):
        """Test creating FastAPI app successfully."""
        mock_app = Mock()
        mock_fastapi.return_value = mock_app

        app = create_app()

        assert app is not None
        mock_fastapi.assert_called_once()

    @patch("src.main.FastAPI")
    @patch("src.main.get_settings")
    def test_create_app_with_settings(self, mock_get_settings, mock_fastapi):
        """Test creating app with custom settings."""
        mock_settings = Mock()
        mock_settings.title = "Test API"
        mock_settings.version = "1.0.0"
        mock_settings.debug = True
        mock_get_settings.return_value = mock_settings

        mock_app = Mock()
        mock_fastapi.return_value = mock_app

        app = create_app()

        assert app is not None
        mock_get_settings.assert_called_once()

    def test_main_module_imports(self):
        """Test that main module can be imported without errors."""
        try:
            from src.main import create_app, get_settings

            assert create_app is not None
            assert get_settings is not None
        except ImportError as e:
            pytest.fail(f"Failed to import main module: {e}")

    def test_settings_validation(self):
        """Test that settings validation works correctly."""
        Settings.reset()
        settings = get_settings()
        assert isinstance(settings.debug, bool)
        assert isinstance(settings.host, str)
        assert isinstance(settings.port, int)
        assert isinstance(settings.reload, bool)
        assert 1 <= settings.port <= 65535

    def test_settings_immutability(self):
        """Test that settings are immutable after creation."""
        Settings.reset()
        settings1 = get_settings()
        settings2 = get_settings()

        # Settings should be the same instance (singleton-like behavior)
        assert settings1 is settings2

    @patch("src.main.FastAPI")
    def test_create_app_multiple_calls(self, mock_fastapi):
        """Test creating app multiple times."""
        mock_app1 = Mock()
        mock_app2 = Mock()
        mock_fastapi.side_effect = [mock_app1, mock_app2]

        app1 = create_app()
        app2 = create_app()

        assert app1 is not None
        assert app2 is not None
        # Should create new instances each time
        assert app1 is not app2
