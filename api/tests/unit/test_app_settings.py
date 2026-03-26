"""Tests for the in-app settings system.

Covers: registry, get_setting(), AppSetting model, SettingsService,
type coercion, sensitive masking, and YAML migration.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from library_manager.models import AppSetting
from src.app_settings.registry import (
    SETTINGS_REGISTRY,
    get_setting,
    get_setting_with_default,
    is_sensitive,
)
from src.services.settings import SettingsService

# ── Registry tests ────────────────────────────────────────────────────────────


class TestSettingsRegistry:
    def test_all_entries_have_required_fields(self):
        required = {"default", "type", "category", "label", "description"}
        for key, entry in SETTINGS_REGISTRY.items():
            missing = required - set(entry.keys())
            assert not missing, f"Setting {key!r} missing fields: {missing}"

    def test_all_categories_are_known(self):
        from src.app_settings.registry import CATEGORY_ORDER

        for key, entry in SETTINGS_REGISTRY.items():
            assert (
                entry["category"] in CATEGORY_ORDER
            ), f"Setting {key!r} has unknown category {entry['category']!r}"

    def test_registry_has_expected_count(self):
        assert len(SETTINGS_REGISTRY) >= 35

    def test_youtube_premium_defaults_true(self):
        assert SETTINGS_REGISTRY["youtube_premium"]["default"] is True

    def test_lyrics_enabled_defaults_true(self):
        assert SETTINGS_REGISTRY["lyrics_enabled"]["default"] is True


# ── get_setting() tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetSetting:
    def test_returns_registry_default_when_no_db_row(self):
        result = get_setting("youtube_premium")
        assert result is True

    def test_returns_db_value_when_row_exists(self):
        AppSetting.objects.create(
            key="youtube_premium", value=False, category="authentication"
        )
        assert get_setting("youtube_premium") is False

    def test_raises_key_error_for_unknown_key(self):
        with pytest.raises(KeyError, match="Unknown setting"):
            get_setting("nonexistent_setting_xyz")

    def test_db_value_overrides_default(self):
        assert get_setting("log_level") == "INFO"
        AppSetting.objects.create(
            key="log_level", value="DEBUG", category="infrastructure"
        )
        assert get_setting("log_level") == "DEBUG"

    def test_get_setting_with_default_returns_default_for_unknown(self):
        result = get_setting_with_default("totally_unknown", "fallback")
        assert result == "fallback"

    def test_get_setting_with_default_returns_value_for_known(self):
        result = get_setting_with_default("youtube_premium", False)
        assert result is True

    def test_handles_list_value(self):
        AppSetting.objects.create(
            key="download_provider_order",
            value=["tidal", "youtube"],
            category="downloads",
        )
        result = get_setting("download_provider_order")
        assert result == ["tidal", "youtube"]

    def test_handles_none_default(self):
        result = get_setting("po_token")
        assert result is None


# ── is_sensitive() tests ─────────────────────────────────────────────────────


class TestIsSensitive:
    def test_secret_type_is_sensitive(self):
        assert is_sensitive("po_token") is True
        assert is_sensitive("spotipy_client_secret") is True
        assert is_sensitive("navidrome_password") is True

    def test_non_secret_is_not_sensitive(self):
        assert is_sensitive("youtube_premium") is False
        assert is_sensitive("log_level") is False

    def test_notifications_urls_is_sensitive(self):
        assert is_sensitive("notifications_urls") is True

    def test_case_insensitive(self):
        assert is_sensitive("PO_TOKEN") is True
        assert is_sensitive("YOUTUBE_PREMIUM") is False


# ── AppSetting model tests ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestAppSettingModel:
    def test_create_and_retrieve(self):
        AppSetting.objects.create(
            key="test_key", value="test_value", category="infrastructure"
        )
        row = AppSetting.objects.get(key="test_key")
        assert row.value == "test_value"
        assert row.category == "infrastructure"

    def test_unique_key_constraint(self):
        AppSetting.objects.create(key="unique_test", value=True, category="test")
        with pytest.raises(Exception):
            AppSetting.objects.create(key="unique_test", value=False, category="test")

    def test_json_field_stores_list(self):
        AppSetting.objects.create(
            key="list_test", value=["a", "b", "c"], category="test"
        )
        row = AppSetting.objects.get(key="list_test")
        assert row.value == ["a", "b", "c"]

    def test_json_field_stores_bool(self):
        AppSetting.objects.create(key="bool_test", value=False, category="test")
        row = AppSetting.objects.get(key="bool_test")
        assert row.value is False

    def test_json_field_stores_int(self):
        AppSetting.objects.create(key="int_test", value=42, category="test")
        row = AppSetting.objects.get(key="int_test")
        assert row.value == 42

    def test_str_representation(self):
        row = AppSetting.objects.create(key="str_test", value="hello", category="test")
        assert str(row) == "str_test=hello"

    def test_updated_at_auto_set(self):
        row = AppSetting.objects.create(key="time_test", value=True, category="test")
        assert row.updated_at is not None


# ── SettingsService tests ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSettingsServiceUpdate:
    def setup_method(self):
        self.service = SettingsService()

    def test_update_creates_db_row(self):
        result = self.service._update_setting_sync("log_level", "DEBUG")
        assert result["key"] == "log_level"
        assert not result["isDefault"]
        row = AppSetting.objects.get(key="log_level")
        assert row.value == "DEBUG"

    def test_update_to_default_deletes_row(self):
        AppSetting.objects.create(
            key="log_level", value="DEBUG", category="infrastructure"
        )
        self.service._update_setting_sync("log_level", "INFO")
        assert not AppSetting.objects.filter(key="log_level").exists()

    def test_update_unknown_key_raises(self):
        with pytest.raises(ValueError, match="Unknown setting"):
            self.service._update_setting_sync("nonexistent_xyz", "val")

    def test_update_skips_masked_placeholder(self):
        AppSetting.objects.create(
            key="po_token", value="real_secret", category="authentication"
        )
        result = self.service._update_setting_sync("po_token", "**configured**")
        assert AppSetting.objects.get(key="po_token").value == "real_secret"
        assert result["sensitive"] is True

    def test_update_sensitive_actually_saves_new_value(self):
        self.service._update_setting_sync("po_token", "new_token_value")
        row = AppSetting.objects.get(key="po_token")
        assert row.value == "new_token_value"


@pytest.mark.django_db
class TestSettingsServiceReset:
    def setup_method(self):
        self.service = SettingsService()

    def test_reset_deletes_db_row(self):
        AppSetting.objects.create(
            key="log_level", value="DEBUG", category="infrastructure"
        )
        result = self.service._reset_setting_sync("log_level")
        assert result["isDefault"] is True
        assert not AppSetting.objects.filter(key="log_level").exists()

    def test_reset_unknown_key_raises(self):
        with pytest.raises(ValueError, match="Unknown setting"):
            self.service._reset_setting_sync("nonexistent_xyz")

    def test_reset_when_no_row_is_noop(self):
        result = self.service._reset_setting_sync("log_level")
        assert result["isDefault"] is True


# ── Type coercion tests ──────────────────────────────────────────────────────


class TestTypeCoercion:
    def setup_method(self):
        self.service = SettingsService()

    def _coerce(self, key, value):
        entry = SETTINGS_REGISTRY[key]
        return self.service._coerce_value(key, entry, value)

    def test_bool_from_string_true(self):
        assert self._coerce("youtube_premium", "true") is True
        assert self._coerce("youtube_premium", "1") is True
        assert self._coerce("youtube_premium", "yes") is True

    def test_bool_from_string_false(self):
        assert self._coerce("youtube_premium", "false") is False
        assert self._coerce("youtube_premium", "0") is False
        assert self._coerce("youtube_premium", "no") is False

    def test_bool_from_bool(self):
        assert self._coerce("youtube_premium", True) is True
        assert self._coerce("youtube_premium", False) is False

    def test_int_from_string(self):
        assert self._coerce("notifications_cooldown_minutes", "120") == 120

    def test_int_from_int(self):
        assert self._coerce("notifications_cooldown_minutes", 120) == 120

    def test_string_from_string(self):
        assert self._coerce("log_level", "DEBUG") == "DEBUG"

    def test_secret_from_string(self):
        assert self._coerce("po_token", "abc123") == "abc123"

    def test_list_from_json_string(self):
        result = self._coerce("download_provider_order", '["tidal", "youtube"]')
        assert result == ["tidal", "youtube"]

    def test_list_from_csv_string(self):
        result = self._coerce("download_provider_order", "tidal, youtube")
        assert result == ["tidal", "youtube"]

    def test_list_from_list(self):
        result = self._coerce("download_provider_order", ["tidal"])
        assert result == ["tidal"]


# ── Sensitive masking tests ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestSensitiveMasking:
    def setup_method(self):
        self.service = SettingsService()

    def test_sensitive_value_is_masked(self):
        AppSetting.objects.create(
            key="po_token", value="real_secret", category="authentication"
        )
        settings = self.service._get_all_settings_sync()
        po_setting = next(s for s in settings if s["key"] == "po_token")
        assert po_setting["value"] == "**configured**"

    def test_unset_sensitive_shows_default(self):
        settings = self.service._get_all_settings_sync()
        po_setting = next(s for s in settings if s["key"] == "po_token")
        assert po_setting["isDefault"] is True

    def test_non_sensitive_shows_real_value(self):
        AppSetting.objects.create(
            key="log_level", value="DEBUG", category="infrastructure"
        )
        settings = self.service._get_all_settings_sync()
        log_setting = next(s for s in settings if s["key"] == "log_level")
        assert log_setting["value"] == "DEBUG"


# ── Category grouping tests ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCategoryGrouping:
    def setup_method(self):
        self.service = SettingsService()

    def test_returns_all_categories(self):
        categories = self.service._get_settings_by_category_sync()
        labels = [c["label"] for c in categories]
        assert "Authentication" in labels
        assert "Downloads" in labels
        assert "Notifications" in labels

    def test_category_order_is_consistent(self):
        categories = self.service._get_settings_by_category_sync()
        cat_ids = [c["category"] for c in categories]
        assert cat_ids.index("authentication") < cat_ids.index("downloads")
        assert cat_ids.index("downloads") < cat_ids.index("notifications")

    def test_each_category_has_settings(self):
        categories = self.service._get_settings_by_category_sync()
        for cat in categories:
            assert len(cat["settings"]) > 0, f"Category {cat['label']} is empty"


# ── YAML migration tests ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestYamlMigration:
    def setup_method(self):
        self.service = SettingsService()

    def test_migrate_nonexistent_file(self):
        result = self.service._migrate_from_yaml_sync("/nonexistent/path.yaml")
        assert result["success"] is True
        assert result["migrated"] == 0

    def test_migrate_imports_non_default_values(self):
        yaml_content = "default:\n  log_level: DEBUG\n  lyrics_enabled: false\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = f.name

        try:
            result = self.service._migrate_from_yaml_sync(path)
            assert result["success"] is True
            assert result["migrated"] == 2

            assert AppSetting.objects.get(key="log_level").value == "DEBUG"
            assert AppSetting.objects.get(key="lyrics_enabled").value is False
        finally:
            Path(path).unlink(missing_ok=True)
            Path(path + ".bak").unlink(missing_ok=True)

    def test_migrate_skips_default_values(self):
        yaml_content = "default:\n  youtube_premium: true\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = f.name

        try:
            result = self.service._migrate_from_yaml_sync(path)
            assert result["skipped"] >= 1
            assert not AppSetting.objects.filter(key="youtube_premium").exists()
        finally:
            Path(path).unlink(missing_ok=True)
            Path(path + ".bak").unlink(missing_ok=True)

    def test_migrate_skips_unknown_keys(self):
        yaml_content = "default:\n  totally_unknown_key: something\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = f.name

        try:
            result = self.service._migrate_from_yaml_sync(path)
            assert result["skipped"] >= 1
            assert not AppSetting.objects.filter(key="totally_unknown_key").exists()
        finally:
            Path(path).unlink(missing_ok=True)
            Path(path + ".bak").unlink(missing_ok=True)

    def test_migrate_creates_backup(self):
        yaml_content = "default:\n  log_level: WARNING\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = f.name

        try:
            self.service._migrate_from_yaml_sync(path)
            assert Path(path + ".bak").exists()
            assert not Path(path).exists()
        finally:
            Path(path).unlink(missing_ok=True)
            Path(path + ".bak").unlink(missing_ok=True)

    def test_migrate_is_idempotent(self):
        yaml_content = "default:\n  log_level: ERROR\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = f.name

        try:
            self.service._migrate_from_yaml_sync(path)
            # Second call should find no file
            result = self.service._migrate_from_yaml_sync(path)
            assert result["migrated"] == 0
            assert AppSetting.objects.filter(key="log_level").count() == 1
        finally:
            Path(path).unlink(missing_ok=True)
            Path(path + ".bak").unlink(missing_ok=True)


# ── youtube_premium gate integration ─────────────────────────────────────────


@pytest.mark.django_db
class TestYoutubePremiumGate:
    @patch("src.services.system_health.SystemHealthService.check_storage_status")
    def test_skips_cookie_check_when_premium_false(self, mock_storage):
        from src.services.system_health import SystemHealthService

        mock_storage.return_value = type(
            "StorageStatus",
            (),
            {"is_writable": True, "is_critically_low": False},
        )()

        AppSetting.objects.create(
            key="youtube_premium", value=False, category="authentication"
        )

        can_download, reason = SystemHealthService.is_download_capable()
        assert can_download is True
        assert reason is None

    @patch("src.services.system_health.SystemHealthService.check_storage_status")
    @patch("downloader.cookie_validator.CookieValidator.validate_file")
    def test_checks_cookies_when_premium_true(self, mock_validate, mock_storage):
        from dataclasses import dataclass

        from src.services.system_health import SystemHealthService

        @dataclass
        class FakeResult:
            valid: bool = False
            error_type: str = "missing"
            error_message: str = "Not found"

        mock_validate.return_value = FakeResult()

        can_download, reason = SystemHealthService.is_download_capable()
        assert can_download is False
        assert "Cookies" in (reason or "")
